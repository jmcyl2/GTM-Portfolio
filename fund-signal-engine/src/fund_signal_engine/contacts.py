"""Resolve each shortlisted adviser's company domain and best finance contact
from public data, before any paid enrichment.

Contact sources, in order:
  1. Schedule A of the adviser's *current* Form ADV (PDF fetched by refresh.py):
     executive officers and owners with their titles.
  2. Schedule A from the bulk data (latest filing that has one, <= 2024).
  3. The Chief Compliance Officer named in Item 1.J of the bulk data.
Within a source, the person is picked by title: finance first, because the
buyer of a fund-close product is whoever owns the books.

Domains come from the ADV website field, else from a manually verified list
(data/private/domains_manual.csv: each domain checked against the filing's
address or named people).
"""

import re
from functools import cache

import dns.resolver
import duckdb
import pandas as pd

from .build import PRIVATE
from .ingest import DB
from .refresh import PDF_DIR

# Title keyword -> priority (higher is better). First match wins, so order matters.
TITLE_PRIORITY = [
    # "finance" only as a role ("VP, Finance"), not inside an entity name ("Social Finance GP")
    (r"\bCFO\b|CHIEF FINANCIAL|(VP|VICE PRESIDENT|HEAD|DIRECTOR)\W+(OF\W+)?FINANCE|CONTROLLER|TREASURER|\bCAO\b|CHIEF ACCOUNTING",
     5, "finance"),
    (r"\bCOO\b|CHIEF OPERAT|OPERATIONS", 4, "operations"),
    (r"\bCCO\b|COMPLIANCE", 3, "compliance"),
    (r"\bCEO\b|CHIEF EXECUTIVE|PRESIDENT|MANAGING (MEMBER|PARTNER|DIRECTOR)|FOUNDER|PRINCIPAL|\bCIO\b|CHIEF INVESTMENT", 2, "executive"),
    (r"PARTNER|MEMBER|MANAGER|DIRECTOR|OFFICER", 1, "other"),
]
NAME = r"[A-Z][A-Z'\-\. ]*?, [A-Z][A-Z'\-\. ]*?(?:, [A-Z][A-Z'\-\. ]*?)?"
SCHED_A_ROW = re.compile(rf"({NAME}) I ((?:(?!\d{{2}}/\d{{4}}).)+?) (\d{{2}}/\d{{4}})")
ROW_TAIL = re.compile(r"^(?:(?:NA|[A-E]) )?(?:[YN] ){1,2}(?:\d+ )?")  # previous row's code/flags/CRD


def rank_title(title: str) -> tuple[int, str]:
    for pattern, score, label in TITLE_PRIORITY:
        if re.search(pattern, title.upper()):
            return score, label
    return 0, "other"


def split_legal_name(name: str) -> tuple[str, str]:
    """'LAST, FIRST, MIDDLE' or 'LAST, FIRST MIDDLE' -> ('First', 'Last')."""
    last, _, rest = name.partition(",")
    first = rest.replace(",", " ").split()[0] if rest.strip() else ""
    return first.title(), last.strip().title()


def schedule_a_from_pdf(crd: str) -> list[dict]:
    path = PDF_DIR / f"{crd}.txt"
    if not path.exists():
        return []
    text = path.read_text()
    start = text.find("Direct Owners and Executive Officers")
    head = text.find("If None: S.S. No. and Date of", start)
    if start < 0 or head < 0:
        return []
    flat = " ".join(text[head:text.find("Schedule B", head)].split()[8:])
    people = []
    for m in SCHED_A_ROW.finditer(flat):
        name = ROW_TAIL.sub("", m.group(1)).strip()
        if "," in name:
            people.append({"name": name, "title": m.group(2).strip()})
    return people


def schedule_a_from_bulk(con, crd: str) -> list[dict]:
    rows = con.execute("""
        WITH o AS (SELECT 'ERA' AS regime, * FROM raw_era_owners
                   UNION ALL BY NAME SELECT 'IA' AS regime, * FROM raw_ia_owners),
        f AS (SELECT fl.filed_on, fl.filing_id, o."Full Legal Name" AS name, o."Title or Status" AS title
              FROM o JOIN filings fl ON fl.filing_id = try_cast(o.FilingID AS BIGINT) AND fl.regime = o.regime
              WHERE fl.crd = ? AND o.Schedule = 'A' AND o."DE/FE/I" = 'I')
        SELECT name, title FROM f
        WHERE filing_id = (SELECT filing_id FROM f ORDER BY filed_on DESC, filing_id DESC LIMIT 1)
        ORDER BY name""", [crd]).fetchall()
    return [{"name": n, "title": t or ""} for n, t in rows]


@cache
def accepts_mail(domain: str) -> bool:
    """A domain with no MX record bounces every address, so it is useless for email."""
    try:
        return bool(dns.resolver.resolve(domain, "MX", lifetime=10))
    except Exception:
        return False


def best_person(people: list[dict]) -> dict | None:
    if not people:
        return None
    scored = sorted(people, key=lambda p: (-rank_title(p["title"])[0], p["name"]))
    return scored[0]


def resolve(rows: list[dict]) -> list[dict]:
    manual = PRIVATE / "domains_manual.csv"
    verified = {}
    if manual.exists():
        m = pd.read_csv(manual, dtype=str).fillna("")
        verified = {r.crd: r.domain.strip().lower() for r in m.itertuples()
                    if r.domain.strip() and r.confidence in ("high", "medium")}
    with duckdb.connect(str(DB), read_only=True) as con:
        for row in rows:
            crd = row["crd"]
            if row["domain"]:
                row["domain_final"], row["domain_source"] = row["domain"], "SEC Form ADV website"
            elif crd in verified:
                row["domain_final"], row["domain_source"] = verified[crd], "Manually verified against filing"
            else:
                row["domain_final"], row["domain_source"] = None, None
            row["domain_accepts_mail"] = bool(row["domain_final"]) and accepts_mail(row["domain_final"])
            if row["domain_final"] and not row["domain_accepts_mail"]:
                row["domain_source"] = f"{row['domain_source']} (no MX record: not used for email)"
                row["domain_final"] = None

            for source, people in (("SEC Form ADV Schedule A (current)", schedule_a_from_pdf(crd)),
                                   ("SEC Form ADV Schedule A (2024 bulk)", schedule_a_from_bulk(con, crd))):
                if (p := best_person(people)) is not None:
                    first, last = split_legal_name(p["name"])
                    row.update(contact_first_name=first, contact_last_name=last,
                               contact_full_name=f"{first} {last}", contact_title=p["title"].title(),
                               contact_function=rank_title(p["title"])[1], contact_source=source)
                    break
            else:
                if row["adv_contact_first_name"]:
                    row.update(contact_first_name=row["adv_contact_first_name"],
                               contact_last_name=row["adv_contact_last_name"],
                               contact_full_name=row["adv_contact_full_name"],
                               contact_title="Chief Compliance Officer", contact_function="compliance",
                               contact_source="SEC Form ADV Item 1.J (2024 bulk)")
                else:
                    row.update(contact_first_name=None, contact_last_name=None, contact_full_name=None,
                               contact_title=None, contact_function=None, contact_source=None)
    return rows
