"""Relabel `section_name` on the existing chunks after expanding SECTION_DEFINITIONS.

Why not just re-run prepare_sec_filings.py: new section boundaries change how paragraphs
pack into chunks, which renumbers every `chunk_id` after the first new boundary - that
would break alignment with extractions.jsonl, Neo4j, pgvector and the eval set. This
migration keeps chunk_id / text / embeddings untouched and only corrects the
`section_name` field, in all three places it is stored.

Each existing chunk's text is a contiguous slice of exactly one section, so we re-split
each filing with the new (complete) section list and match every chunk to the section
whose text contains it.

    python scripts/fix_chunk_sections.py            # dry run - report only
    APPLY=1 python scripts/fix_chunk_sections.py     # write chunks.jsonl + pgvector + Neo4j
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prepare_sec_filings import (  # noqa: E402
    CHUNKS_PATH,
    DATA_DIR,
    MANIFEST_PATH,
    SECTION_REGEX,
    canonical_section_name,
    extract_text,
    load_manifest,
    trim_to_first_major_section,
)

APPLY = os.getenv("APPLY", "0") == "1"


def load_chunks() -> list[dict]:
    return [
        json.loads(line)
        for line in CHUNKS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def section_ranges(html_text: str) -> tuple[str, list[tuple[str, int, int]]]:
    """Whitespace-normalised body text + (section_name, start, end) char ranges over it."""
    norm = " ".join(trim_to_first_major_section(html_text).split())
    matches = list(SECTION_REGEX.finditer(norm))
    ranges: list[tuple[str, int, int]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(norm)
        ranges.append((canonical_section_name(m.group(0)), m.start(), end))
    return norm, ranges


def _all_starts(hay: str, needle: str) -> list[int]:
    out: list[int] = []
    i = hay.find(needle)
    while i != -1:
        out.append(i)
        i = hay.find(needle, i + 1)
    return out


def _section_at(pos: int, ranges: list[tuple[str, int, int]]) -> str | None:
    for name, s, e in ranges:
        if s <= pos < e:
            return name
    return None


def locate_section(chunk_text: str, norm: str, ranges: list[tuple[str, int, int]]) -> str | None:
    """Map a chunk to its section. First anchor the chunk in the body text by widening a
    prefix probe until it matches uniquely, then vote across ~8 evenly-spaced slices of
    the chunk so a chunk that straddles a boundary is labelled by its *majority* content,
    not its first line."""
    needle = " ".join(chunk_text.split())
    anchor: int | None = None
    for width in (250, 500, 1000, 2000):
        starts = _all_starts(norm, needle[: min(width, len(needle))])
        if len(starts) == 1:
            anchor = starts[0]
            break
        if not starts:
            return None
    if anchor is None:
        return None

    votes: dict[str, int] = {}
    step = max(1, len(needle) // 8)
    for off in range(0, len(needle), step):
        probe = needle[off : off + 60]
        hits = _all_starts(norm, probe)
        # prefer the occurrence nearest the anchor (handles repeated boilerplate)
        near = min(hits, key=lambda h: abs(h - (anchor + off)), default=None)
        name = _section_at(near, ranges) if near is not None else None
        if name:
            votes[name] = votes.get(name, 0) + 1

    if not votes:
        return _section_at(anchor, ranges)
    return max(votes, key=votes.get)


def main() -> None:
    filings = load_manifest(MANIFEST_PATH)
    chunks = load_chunks()
    by_file: dict[str, list[dict]] = defaultdict(list)
    for c in chunks:
        by_file[c["local_file"]].append(c)

    changes: list[tuple[str, str, str]] = []
    unmatched = 0
    for filing in filings:
        html = DATA_DIR / filing.local_file
        if not html.exists():
            print(f"[missing] {filing.local_file}")
            continue
        norm, ranges = section_ranges(extract_text(html))
        for c in by_file.get(filing.local_file, []):
            new = locate_section(c["text"], norm, ranges)
            if new is None:
                unmatched += 1
                continue
            if new != c["section_name"]:
                changes.append((c["chunk_id"], c["section_name"], new))
                c["section_name"] = new

    print(f"{len(chunks)} chunks, {len(changes)} section_name changes, {unmatched} unmatched (kept as-is)\n")
    tally: dict[tuple[str, str], int] = defaultdict(int)
    for _, old, new in changes:
        tally[(old, new)] += 1
    for (old, new), n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3}  {old}  ->  {new}")

    if not APPLY:
        print("\ndry run - set APPLY=1 to write chunks.jsonl + pgvector + Neo4j")
        return

    with CHUNKS_PATH.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\nwrote {CHUNKS_PATH.name}")

    changed = {cid: new for cid, _, new in changes}
    groups: dict[str, list[str]] = defaultdict(list)
    for cid, new in changed.items():
        groups[new].append(cid)

    from kgrag.db import VECTOR_TABLE, connect

    conn = connect()
    total = 0
    with conn.cursor() as cur:
        for new, ids in groups.items():
            cur.execute(
                f"UPDATE {VECTOR_TABLE} SET section_name = %s, updated_at = NOW() WHERE chunk_id = ANY(%s)",
                (new, ids),
            )
            total += cur.rowcount
    conn.commit()
    conn.close()
    print(f"pgvector: {total} row(s) updated")

    try:
        from kgrag.db import NEO4J_DATABASE, neo4j_driver

        driver = neo4j_driver()
        with driver.session(database=NEO4J_DATABASE) as session:
            n = session.run(
                "UNWIND $rows AS r MATCH (c:Chunk {chunk_id: r.id}) "
                "SET c.section_name = r.section RETURN count(c) AS n",
                rows=[{"id": cid, "section": new} for cid, new in changed.items()],
            ).single()["n"]
        driver.close()
        print(f"neo4j: {n} Chunk node(s) updated")
    except SystemExit as exc:
        print(f"neo4j: skipped ({exc})")


if __name__ == "__main__":
    main()
