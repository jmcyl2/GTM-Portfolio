"""Hand the shortlist to Clay for enrichment, and score what comes back.

  fse-clay push      send each shortlisted adviser to a Clay table via its webhook
  fse-clay report    read the Clay CSV export and write the enrichment funnel

Clay does the waterfall (domain -> person -> email -> verification); the build
steps are in docs/clay-enrichment.md. This module owns the hand-off in and the
measurement out, so the funnel numbers are reproducible from the export.
"""

import argparse
import json
import os
import re
import time
import urllib.request
from urllib.parse import urlparse

import duckdb
import pandas as pd

from . import sec
from .build import OUT, PRIVATE, pct, table
from .ingest import DB

EXPORT = PRIVATE / "clay_export.csv"
SUFFIXES = {"JR", "SR", "II", "III", "IV", "CPA", "CFA", "ESQ"}
SOCIAL = ("tiktok.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com")


def split_site(url: str | None) -> tuple[str | None, str | None]:
    """Return (company domain, LinkedIn company URL) from an ADV website field."""
    if not isinstance(url, str) or not url.strip():
        return None, None
    url = url.strip().lower()
    if "linkedin.com" in url:
        return None, url if url.startswith("http") else "https://" + url
    host = urlparse(url if "://" in url else "http://" + url).netloc.removeprefix("www.")
    if not host or host.endswith(SOCIAL):
        return None, None  # a social profile is not a company domain; let Clay find the real one
    return host, None


def split_name(full: str | None) -> tuple[str | None, str | None]:
    if not isinstance(full, str) or not full.strip():
        return None, None
    parts = [p for p in re.split(r"\s+", full.strip().title()) if p.upper().strip(".") not in SUFFIXES]
    return (parts[0], parts[-1]) if len(parts) > 1 else (parts[0], None)


def shortlist_rows() -> list[dict]:
    short = pd.read_csv(PRIVATE / "shortlist.csv", dtype={"crd": str})
    with duckdb.connect(str(DB), read_only=True) as con:
        mix = con.execute("SELECT crd, n_pe, n_re, all_audited FROM targets").df()
    short = short.merge(mix, on="crd", how="left")
    rows = []
    for rank, r in enumerate(short.itertuples(), 1):
        domain, linkedin = split_site(r.website)
        first, last = split_name(r.cco_name)
        rows.append({
            "shortlist_rank": rank,
            "crd": r.crd,
            "company_name": r.adviser_name,
            "state": r.state,
            "domain": domain,
            "linkedin_company_url": linkedin,
            "adv_contact_full_name": r.cco_name.title() if isinstance(r.cco_name, str) else None,
            "adv_contact_first_name": first,
            "adv_contact_last_name": last,
            "adv_contact_role": "Chief Compliance Officer (Form ADV Item 1.J)" if first else None,
            "private_fund_assets_musd": round(r.private_fund_assets / 1e6, 1),
            "pe_funds": int(r.n_pe), "re_funds": int(r.n_re),
            "all_funds_audited": bool(r.all_audited),
            "p_buy_admin_3yr": round(r.p_switch, 4),
            "sec_profile_url": f"https://adviserinfo.sec.gov/firm/summary/{r.crd}",
        })
    return rows


def push(dry_run: bool, limit: int | None):
    sec._load_dotenv()
    url = os.environ.get("CLAY_WEBHOOK_URL", "").strip()
    if not url and not dry_run:
        raise SystemExit("Set CLAY_WEBHOOK_URL in .env (Clay table -> Import -> Webhook).")
    rows = shortlist_rows()[:limit]
    log = PRIVATE / "clay_pushed.jsonl"
    done = {json.loads(l)["crd"] for l in log.read_text().splitlines()} if log.exists() else set()
    sent = 0
    for row in rows:
        if row["crd"] in done:
            continue
        if dry_run:
            print(json.dumps(row))
            continue
        req = urllib.request.Request(url, data=json.dumps(row).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status >= 300:
                raise SystemExit(f"Clay returned {resp.status} on crd {row['crd']}")
        with open(log, "a") as f:
            f.write(json.dumps({"crd": row["crd"], "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        sent += 1
        time.sleep(0.25)
    print(f"pushed {sent} rows ({len(done)} already sent earlier, {len(rows)} on the shortlist)")


# Column names the Clay table is asked to use (docs/clay-enrichment.md).
COLS = {
    "domain_found": "Domain (final)",
    "person_name": "Contact name (final)",
    "person_title": "Contact title",
    "person_source": "Contact source",
    "linkedin": "Contact LinkedIn",
    "email": "Work email",
    "email_status": "Email status",
    "email_provider": "Email provider",
}


def report(credits_used: float | None):
    df = pd.read_csv(EXPORT, dtype=str)
    missing = [c for c in COLS.values() if c not in df.columns]
    if missing:
        raise SystemExit(f"Export is missing columns {missing}; rename them in Clay to match docs/clay-enrichment.md.")
    has = lambda c: df[COLS[c]].fillna("").str.strip().ne("")
    n = len(df)
    domain_in = df["domain"].fillna("").str.strip().ne("")
    status = df[COLS["email_status"]].fillna("").str.lower()
    verified = has("email") & status.str.contains("valid|verified|deliverable") & ~status.str.contains("invalid|undeliverable")
    risky = has("email") & status.str.contains("catch|risky|accept")
    steps = [
        ("Advisers on the shortlist", n),
        ("Company domain known (from ADV)", int(domain_in.sum())),
        ("Company domain known (after Clay)", int(has("domain_found").sum())),
        ("Named contact", int(has("person_name").sum())),
        ("...with LinkedIn profile", int((has("person_name") & has("linkedin")).sum())),
        ("Work email found", int(has("email").sum())),
        ("...verified deliverable", int(verified.sum())),
        ("...catch-all / risky", int(risky.sum())),
    ]
    source = df.loc[has("person_name"), COLS["person_source"]].fillna("unknown").value_counts()
    provider = df.loc[has("email"), COLS["email_provider"]].fillna("unknown").value_counts()
    md = ["[← Findings](findings.md)", "", "# Enrichment funnel (Clay waterfall)", "",
          f"{n} of the {len(pd.read_csv(PRIVATE / 'shortlist.csv'))} shortlisted advisers (the top {n} by v2 score; "
          "the Clay trial caps a table at 50 rows), enriched in Clay following "
          "[`docs/clay-enrichment.md`](../docs/clay-enrichment.md). "
          "Aggregates only; contact-level output stays in `data/private/`.", "",
          table(["Step", "Advisers", "Coverage"], [(s, v, pct(v, n)) for s, v in steps]), "",
          "**Where the contact came from:**", "", table(["Source", "Advisers"], list(source.items())), "",
          "**Which provider found the email (first hit in the waterfall):**", "",
          table(["Provider", "Emails"], list(provider.items())), ""]
    if credits_used:
        md += [f"**Cost:** {credits_used:g} Clay credits in total, "
               f"{credits_used / n:.1f} per adviser and "
               f"{credits_used / max(int(verified.sum()), 1):.1f} per verified email.", ""]
    (OUT / "enrichment.md").write_text("\n".join(md) + "\n")
    print("\n".join(f"{s}: {v} ({pct(v, n)})" for s, v in steps))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("push")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int)
    r = sub.add_parser("report")
    r.add_argument("--credits", type=float, help="total Clay credits the enrichment used")
    args = parser.parse_args()
    if args.cmd == "push":
        push(args.dry_run, args.limit)
    else:
        report(args.credits)


if __name__ == "__main__":
    main()
