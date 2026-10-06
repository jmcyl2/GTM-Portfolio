"""Hand the shortlist to Clay for enrichment, and score what comes back.

  fse-clay push      send each shortlisted adviser to a Clay table via its webhook
  fse-clay report    read the Clay CSV export and write the enrichment funnel

Domains and contacts are resolved from public SEC data first (contacts.py), so
Clay only does what it is best at: LinkedIn matching and the work-email
waterfall with verification. Build steps: docs/clay-enrichment.md. This module
owns the hand-off in and the measurement out, so the funnel numbers are
reproducible from the export.
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

TABLE_CAP = 50  # Clay trial tables hold 50 rows
PAYLOAD = ["shortlist_rank", "crd", "company_name", "state", "domain_final", "domain_source", "domain_accepts_mail",
           "linkedin_company_url", "contact_first_name", "contact_last_name", "contact_full_name",
           "contact_title", "contact_function", "contact_source", "private_fund_assets_musd",
           "pe_funds", "re_funds", "all_funds_audited", "p_buy_admin_3yr", "sec_profile_url"]

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
    from .contacts import resolve
    rows = resolve(shortlist_rows()[:limit or TABLE_CAP])
    # one log per destination table, so a new webhook gets a full push
    log = PRIVATE / f"clay_pushed_{url.rstrip('/').rsplit('-', 1)[-1] if url else 'dry'}.jsonl"
    done = {json.loads(l)["crd"] for l in log.read_text().splitlines()} if log.exists() else set()
    sent = 0
    for row in rows:
        if row["crd"] in done:
            continue
        payload = {k: row[k] for k in PAYLOAD}
        if dry_run:
            print(json.dumps(payload))
            continue
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status >= 300:
                raise SystemExit(f"Clay returned {resp.status} on crd {row['crd']}")
        with open(log, "a") as f:
            f.write(json.dumps({"crd": row["crd"], "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        sent += 1
        time.sleep(0.25)
    print(f"pushed {sent} rows ({len(done)} already sent earlier, {len(rows)} on the shortlist)")


# Clay title-cases headers on export ("domain_final" -> "Domain Final"), so columns
# are matched after normalising to snake_case.
COLS = {
    "domain_found": "domain_final",
    "person_name": "contact_full_name",
    "person_source": "contact_source",
    "linkedin": "contact_linkedin",
    "email": "work_email",
    "email_status": "email_status",
    "email_provider": "email_provider",
}
FREE_MAIL = ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "proton.me")


def name_plausible(email: str, full_name: str) -> bool:
    """Does the mailbox look like it belongs to this person (name, surname or initials)?"""
    local = re.sub(r"[^a-z]", "", email.split("@")[0].lower())
    parts = [re.sub(r"[^a-z]", "", p) for p in str(full_name).lower().split()]
    parts = [p for p in parts if p]
    if not parts or not local:
        return False
    return (any(len(p) > 2 and p in local for p in parts)            # a name or surname
            or (len(local) >= 3 and parts[0].startswith(local))       # short first name: wes = wesley
            or (2 <= len(local) <= 4 and local[0] == parts[0][0]      # initials, with optional middle or
                and local[-1] == parts[-1][0]))                       # second surname: amn, ogn


def report(credits_used: float | None, actions_used: float | None):
    df = pd.read_csv(EXPORT, dtype=str).replace({"undefined": None, "": None, "None found": None})
    df.columns = [re.sub(r"\W+", "_", c.strip().lower()).strip("_") for c in df.columns]
    missing = [COLS[c] for c in ("domain_found", "person_name", "email") if COLS[c] not in df.columns]
    if missing:
        raise SystemExit(f"Export is missing columns {missing}; see docs/clay-enrichment.md.")
    for optional in ("linkedin", "email_provider", "person_source", "email_status"):
        if COLS[optional] not in df.columns:
            df[COLS[optional]] = None
    col = lambda c: df[COLS[c]].fillna("").str.strip()
    has = lambda c: col(c).ne("")
    n = len(df)

    email, domain = col("email").str.lower(), col("domain_found").str.lower()
    email_domain = email.str.split("@").str[-1]
    found = has("email")
    free = found & email_domain.isin(FREE_MAIL)
    named = pd.Series([name_plausible(e, nm) if e else False for e, nm in zip(email, col("person_name"))], index=df.index)
    on_domain = found & ~free & domain.ne("") & email_domain.eq(domain)
    other_domain = found & ~free & domain.ne("") & email_domain.ne(domain)
    no_domain = found & ~free & domain.eq("")
    usable = found & ~free & named
    from_adv = df.get("domain_source", pd.Series("", index=df.index)).fillna("").eq("SEC Form ADV website")

    funnel = [
        ("Advisers enriched", n),
        ("Company domain that can receive email (from the filing or found by research, MX record checked)", int(has("domain_found").sum())),
        ("Named contact from SEC filings (Form ADV Schedule A or Item 1.J)", int(has("person_name").sum())),
        ("Email found by Clay's waterfall (Conservative setting)", int(found.sum())),
        ("**Usable after my checks**", int(usable.sum())),
    ]
    qa = [
        ("On the verified company domain", int(on_domain.sum())),
        ("On a different domain (the firm's separate mail domain, or an affiliate's)", int(other_domain.sum())),
        ("Firm had no verified domain; Clay matched it from the company name", int(no_domain.sum())),
        ("Rejected: personal address (Gmail, Yahoo, etc.)", int(free.sum())),
        ("Rejected: mailbox doesn't match the contact's name", int((found & ~free & ~named).sum())),
    ]
    provider = df.loc[found & ~free, COLS["email_provider"]].fillna("unknown").value_counts()
    source = df.loc[has("person_name"), COLS["person_source"]].fillna("unknown").value_counts()
    finance = df.get("contact_title", pd.Series("", index=df.index)).fillna("").str.upper().str.contains(
        r"\bCFO\b|CHIEF FINANCIAL|FINANCE|CONTROLLER|TREASURER|\bCAO\b")
    shortlist_n = len(pd.read_csv(PRIVATE / "shortlist.csv"))

    md = ["[← Findings](findings.md)", "", "# Finding contacts and emails", "",
          f"The top {n} of the {shortlist_n} advisers on the contact list, by v2 score (Clay's free trial limits a "
          "table to 50 rows). Company domains and contact names come from SEC filings first, at no cost. Clay is only "
          "used to find work emails, with its waterfall: it tries one email provider after another until one finds a "
          "verified address. Method: [`docs/clay-enrichment.md`](../docs/clay-enrichment.md). "
          "Summary stats only; names and emails stay in `data/private/`.", "",
          table(["Step", "Advisers", "Coverage"], [(s, v, pct(v, n)) for s, v in funnel]), "",
          f"**{int((usable & finance).sum())} of the {int(usable.sum())} usable emails belong to a finance-titled "
          "contact** (CFO, controller, treasurer, VP finance).", "",
          "## Checking the emails Clay returned", "",
          "Clay's validation confirms an address accepts mail, not that it belongs to the right person. "
          "So every email is also checked against the contact's name and the firm's verified domain.", "",
          table(["Check", "Emails"], qa), "",
          "**Which provider found each email (the first one in the waterfall to find it):**", "",
          table(["Provider", "Emails"], list(provider.items())), "",
          "**Where the contact came from:**", "", table(["Source", "Advisers"], list(source.items())), ""]
    if credits_used:
        md += ["## Cost", "",
               f"- **{credits_used:g} Clay data credits** in total: {credits_used / n:.2f} per adviser, "
               f"**{credits_used / max(int(usable.sum()), 1):.2f} per usable email**."
               + (f" Plus {actions_used:g} Clay actions, which Clay counts separately from credits." if actions_used else ""),
               "- Domains and contacts cost nothing. They come from SEC filings, research checked by hand, and a DNS check "
               "that each domain can receive email.", ""]
    (OUT / "enrichment.md").write_text("\n".join(md) + "\n")
    for s_, v in funnel + qa:
        print(f"{s_}: {v}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("push")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int)
    r = sub.add_parser("report")
    r.add_argument("--credits", type=float, help="Clay data credits the enrichment used")
    r.add_argument("--actions", type=float, help="Clay actions the enrichment used")
    args = parser.parse_args()
    if args.cmd == "push":
        push(args.dry_run, args.limit)
    else:
        report(args.credits, args.actions)


if __name__ == "__main__":
    main()
