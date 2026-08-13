from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "raw" / "sec_filings"
MANIFEST_PATH = DATA_DIR / "manifest.csv"
OUTPUT_DIR = BASE_DIR / "data" / "processed" / "sec_filings"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CHUNKS_PATH = OUTPUT_DIR / "chunks.jsonl"
SUMMARY_PATH = OUTPUT_DIR / "filings_summary.json"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@dataclass
class FilingRecord:
    company: str
    filing_type: str
    filing_year: str
    filing_date: str
    period_end_date: str
    source_url: str
    local_file: str


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag in {"p", "br", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self.parts.append(text + " ")

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n\s*\n\s*\n+", "\n\n", raw)
        return raw.strip()


SECTION_DEFINITIONS: list[tuple[str, str]] = [
    ("ITEM 1. BUSINESS", r"ITEM\s+1\.\s+BUSINESS"),
    ("ITEM 1A. RISK FACTORS", r"ITEM\s+1A\.\s+RISK\s+FACTORS"),
    ("ITEM 1B. UNRESOLVED STAFF COMMENTS", r"ITEM\s+1B\.\s+UNRESOLVED\s+STAFF\s+COMMENTS"),
    ("ITEM 2. PROPERTIES", r"ITEM\s+2\.\s+PROPERTIES"),
    ("ITEM 3. LEGAL PROCEEDINGS", r"ITEM\s+3\.\s+LEGAL\s+PROCEEDINGS"),
    ("ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS", r"ITEM\s+7\.\s+MANAGEMENT['’]S\s+DISCUSSION\s+AND\s+ANALYSIS"),
    ("ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK", r"ITEM\s+7A\.\s+QUANTITATIVE\s+AND\s+QUALITATIVE\s+DISCLOSURES\s+ABOUT\s+MARKET\s+RISK"),
    ("ITEM 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA", r"ITEM\s+8\.\s+FINANCIAL\s+STATEMENTS\s+AND\s+SUPPLEMENTARY\s+DATA"),
    ("ITEM 9A. CONTROLS AND PROCEDURES", r"ITEM\s+9A\.\s+CONTROLS\s+AND\s+PROCEDURES"),
]

SECTION_REGEX = re.compile("|".join(f"(?P<S{i}>{pattern})" for i, (_, pattern) in enumerate(SECTION_DEFINITIONS)), re.IGNORECASE)


def load_manifest(path: Path) -> list[FilingRecord]:
    filings: list[FilingRecord] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filings.append(FilingRecord(**row))
    return filings


def extract_text(html_path: Path) -> str:
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    parser = TextExtractor()
    parser.feed(html)
    return clean_text(parser.text())


def clean_text(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "http://fasb.org/" in stripped:
            continue
        if stripped.startswith("http://") or stripped.startswith("https://"):
            continue
        if stripped.lower() in {"true", "false"}:
            continue
        if re.fullmatch(r"[A-Za-z0-9._:-]{20,}", stripped):
            continue
        lines.append(stripped)

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r" +", " ", cleaned)
    return cleaned.strip()


def trim_to_first_major_section(text: str) -> str:
    match = SECTION_REGEX.search(text)
    if not match:
        return text
    return text[match.start() :].strip()


def split_into_sections(text: str) -> list[tuple[str, str]]:
    trimmed = trim_to_first_major_section(text)
    matches = list(SECTION_REGEX.finditer(trimmed))
    if not matches:
        return [("FULL_TEXT", trimmed)]

    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        section_name = canonical_section_name(match.group(0))
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(trimmed)
        section_text = trimmed[start:end].strip()
        sections.append((section_name, section_text))
    return sections


def canonical_section_name(raw_heading: str) -> str:
    normalized = re.sub(r"\s+", " ", raw_heading.upper()).strip()
    for name, pattern in SECTION_DEFINITIONS:
        if re.fullmatch(pattern, normalized, flags=re.IGNORECASE):
            return name
    return normalized


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]


def chunk_paragraphs(items: Iterable[str], chunk_size: int = 2600) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for paragraph in items:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        paragraph_len = len(paragraph)
        separator_len = 2 if current else 0

        if current and current_len + separator_len + paragraph_len > chunk_size:
            chunks.append("\n\n".join(current).strip())
            current = current[-1:] if len(current) > 1 else current
            current_len = sum(len(p) for p in current) + max(0, len(current) - 1) * 2

        if paragraph_len > chunk_size:
            if current:
                chunks.append("\n\n".join(current).strip())
                current = []
                current_len = 0

            for start in range(0, paragraph_len, chunk_size):
                piece = paragraph[start : start + chunk_size].strip()
                if piece:
                    chunks.append(piece)
            continue

        current.append(paragraph)
        current_len += separator_len + paragraph_len

    if current:
        chunks.append("\n\n".join(current).strip())

    return [chunk for chunk in chunks if chunk]


def chunk_sections(sections: list[tuple[str, str]]) -> list[dict[str, str]]:
    chunk_records: list[dict[str, str]] = []
    chunk_index = 0

    for section_name, section_text in sections:
        section_paragraphs = paragraphs(section_text)
        section_chunks = chunk_paragraphs(section_paragraphs)

        for section_chunk_index, chunk_text in enumerate(section_chunks, start=1):
            chunk_records.append(
                {
                    "section_name": section_name,
                    "section_chunk_index": section_chunk_index,
                    "chunk_index": chunk_index,
                    "text": chunk_text,
                }
            )
            chunk_index += 1

    return chunk_records


def make_chunk_id(company: str, filing_year: str, chunk_index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")
    return f"{slug}-{filing_year}-{chunk_index:04d}"


def process_filing(filing: FilingRecord) -> list[dict[str, object]]:
    html_path = DATA_DIR / filing.local_file
    text = extract_text(html_path)
    sections = split_into_sections(text)
    chunk_records = chunk_sections(sections)

    output_rows: list[dict[str, object]] = []
    for item in chunk_records:
        chunk_id = make_chunk_id(filing.company, filing.filing_year, int(item["chunk_index"]))
        output_rows.append(
            {
                "chunk_id": chunk_id,
                "company": filing.company,
                "filing_type": filing.filing_type,
                "filing_year": filing.filing_year,
                "filing_date": filing.filing_date,
                "period_end_date": filing.period_end_date,
                "source_url": filing.source_url,
                "local_file": filing.local_file,
                "section_name": item["section_name"],
                "section_chunk_index": item["section_chunk_index"],
                "chunk_index": item["chunk_index"],
                "text": item["text"],
                "char_count": len(item["text"]),
            }
        )

    return output_rows


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    filings = load_manifest(MANIFEST_PATH)
    all_chunks: list[dict[str, object]] = []
    summary: list[dict[str, object]] = []

    print(f"Loaded {len(filings)} filings from manifest.csv")

    for filing in filings:
        html_path = DATA_DIR / filing.local_file
        if not html_path.exists():
            print(f"[missing] {html_path.name}")
            continue

        chunks = process_filing(filing)
        all_chunks.extend(chunks)
        summary.append(
            {
                "company": filing.company,
                "filing_year": filing.filing_year,
                "filing_type": filing.filing_type,
                "file": filing.local_file,
                "chunk_count": len(chunks),
            }
        )

        first_preview = chunks[0]["text"].replace("\n", " ")[:300] if chunks else ""
        print(f"\n[{filing.filing_year}] {filing.local_file}")
        print(f"  chunks: {len(chunks)}")
        print(f"  first section: {chunks[0]['section_name'] if chunks else 'n/a'}")
        print(f"  preview: {first_preview}")

    write_jsonl(CHUNKS_PATH, all_chunks)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\nWrote {len(all_chunks)} chunk records to {CHUNKS_PATH.relative_to(BASE_DIR)}")
    print(f"Wrote summary to {SUMMARY_PATH.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
