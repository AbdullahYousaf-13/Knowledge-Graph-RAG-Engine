from __future__ import annotations

import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CSV_PATH = BASE_DIR / "data" / "processed" / "sec_filings" / "entity_merge_candidates.csv"

# Keyed by frozenset({entity_key_a, entity_key_b}) -> (recommendation, reason)
DECISIONS: dict[frozenset, tuple[str, str]] = {
    frozenset({"eu-digital-markets-act", "european-union-digital-markets-act"}): ("MERGE", "Same act, full name vs abbreviated name"),
    frozenset({"deferred-tax-assets", "deferred-tax-asset"}): ("MERGE", "Same concept, plural vs singular"),
    frozenset({"u-s-securities-and-exchange-commission", "securities-and-exchange-commission"}): ("MERGE", "Same regulator, with/without U.S. prefix"),
    frozenset({"u-s-department-of-justice", "department-of-justice"}): ("MERGE", "Same agency, with/without U.S. prefix"),
    frozenset({"internal-revenue-service", "u-s-internal-revenue-service"}): ("MERGE", "Same agency, with/without U.S. prefix"),
    frozenset({"asu-2023-07", "asu-no-2023-07"}): ("MERGE", "Same ASU number, with/without 'No.' prefix"),
    frozenset({"wearables-home-and-accessories", "wearables-and-accessories"}): ("MERGE", "Same Apple reporting segment, shortened name"),
    frozenset({"u-s", "united-states"}): ("MERGE", "Same country, abbreviation vs full name"),
    frozenset({"apple-inc-non-employee-director-stock-plan", "non-employee-director-stock-plan"}): ("MERGE", "Same plan, with/without company prefix"),
    frozenset({"covid-19-pandemic", "covid-19"}): ("MERGE", "Same event, with/without 'pandemic' suffix"),
    frozenset({"apple-inc-2014-employee-stock-plan", "2014-employee-stock-plan"}): ("MERGE", "Same plan, with/without company prefix"),
    frozenset({"eu-digital-markets-act", "digital-markets-act"}): ("MERGE", "Same act; only one Digital Markets Act discussed in this corpus, no competing sibling entity"),
    frozenset({"european-union-digital-markets-act", "digital-markets-act"}): ("MERGE", "Same act; only one Digital Markets Act discussed in this corpus, no competing sibling entity"),
    frozenset({"apple-inc-2022-employee-stock-plan", "2022-employee-stock-plan"}): ("MERGE", "Same plan, with/without company prefix"),
    frozenset({"rule-10b5-1", "rule-10b5-1-c"}): ("MERGE (moderate confidence)", "Likely the same underlying SEC rule cited with/without subsection (c) - flagging for your own sanity check since subsection references can matter"),
}

# Everything else defaults to DON'T MERGE with a category-based reason.
DEFAULT_REASON_RULES = [
    (lambda a, b: "asu-" in a and "asu-" in b, "Different ASU (Accounting Standards Update) numbers - these are distinct FASB documents despite similar naming"),
    (lambda a, b: any(x in a for x in ["iphone", "ipad", "macbook", "airpods", "watch", "mac-pro", "mac"]) and any(x in b for x in ["iphone", "ipad", "macbook", "airpods", "watch", "mac-pro", "mac"]), "Different product / product version - shared product-family vocabulary caused a high similarity score, but these are distinct products"),
    (lambda a, b: any(x in a for x in ["ios-", "ipados-", "tvos", "watchos", "visionos"]) and any(x in b for x in ["ios-", "ipados-", "tvos", "watchos", "visionos"]), "Different OS version, or generic OS name vs a specific version - kept separate for consistency with other OS-version entities that are deliberately not merged"),
    (lambda a, b: "net-income" in a and "net-income" in b, "Different fiscal year - distinct metric values, not the same fact"),
    (lambda a, b: "net-sales" in a and "net-sales" in b, "Different net-sales breakdown (products vs services vs total, or different year) - distinct line items"),
    (lambda a, b: "employee-stock-plan" in a and "employee-stock-plan" in b, "Different stock plan (different year or different plan type) - distinct plans"),
]


def default_decision(entity_key_a: str, entity_key_b: str) -> tuple[str, str]:
    for predicate, reason in DEFAULT_REASON_RULES:
        if predicate(entity_key_a, entity_key_b):
            return "DON'T MERGE", reason
    return "DON'T MERGE", "Textually similar but appear to be distinct entities on inspection (different scope, subset/superset, or unrelated concept sharing vocabulary)"


def main() -> None:
    with CSV_PATH.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        key = frozenset({row["entity_key_a"], row["entity_key_b"]})
        if key in DECISIONS:
            recommendation, reason = DECISIONS[key]
        else:
            recommendation, reason = default_decision(row["entity_key_a"], row["entity_key_b"])
        row["recommendation"] = recommendation
        row["reason"] = reason

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    merge_count = sum(1 for r in rows if r["recommendation"].startswith("MERGE"))
    print(f"Wrote recommendations for {len(rows)} pairs: {merge_count} recommended to merge, {len(rows) - merge_count} recommended to leave separate.")


if __name__ == "__main__":
    main()
