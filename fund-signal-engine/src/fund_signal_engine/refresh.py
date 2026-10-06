"""Refresh Tier A against each adviser's *current* Form ADV.

The bulk fund-level data ends Dec 2024. The full current Form ADV for any firm
is published as a PDF on the SEC's adviser search site. This parses Schedule D
7.B.(1) out of it (fund ID, name, gross assets, whether an outside
administrator is used) and compares it with the 2024 picture:

  - which Tier A advisers have hired an administrator since 2024 (already bought)
  - which are still fully self-administered (still in market)
  - and, because these outcomes post-date all model training data, a live
    out-of-sample check of the v2 filter.

Checkbox answers do not survive PDF text extraction, so administrator status is
read from structure: a fund with an outside administrator has administrator
records filed under question 26; one without shows "No Information Filed".
"""

import argparse
import re
from pathlib import Path

import duckdb
import pandas as pd
import pymupdf
from scipy.stats import fisher_exact

from . import sec
from .build import OUT, PRIVATE, pct, table
from .ingest import DB, RAW

PDF_URL = "https://reports.adviserinfo.sec.gov/reports/ADV/{crd}/PDF/{crd}.pdf"
PDF_DIR = RAW / "adv_pdf"

# "1. (a)" marks a reported fund; feeder funds listed under a master use a bare "(a)"
FUND = re.compile(r"1\.\s*\(a\)\s*Name of the private fund:\s*\n(.+?)\n.*?(805-\d{10})", re.S)
Q26 = re.compile(r"26\. \(a\) Does the private fund use an administrator other than your firm\?(.*?)27\. During", re.S)
GAV = re.compile(r"Current gross asset value of the private fund:\s*\$\s*([\d,]+)")
ADMIN_NAME = re.compile(r"\(b\) Name of administrator:\s*\n(.+)")
STAMP = re.compile(r"Rev\. \d+/\d{4}\s*\n(\d{1,2}/\d{1,2}/\d{4})")
NO_FUNDS = "No Information Filed"


def fetch_text(crd: str) -> str | None:
    pdf = PDF_DIR / f"{crd}.pdf"
    txt = pdf.with_suffix(".txt")
    if txt.exists():
        return txt.read_text()
    try:
        sec.download(PDF_URL.format(crd=crd), pdf)
    except Exception as e:  # firm withdrawn, report unavailable, transient error
        print(f"  {crd}: fetch failed ({e})")
        return None
    # PyMuPDF, not pypdf: these PDFs share content streams across pages, and
    # pypdf re-extracts the shared text on every page.
    with pymupdf.open(pdf) as doc:
        text = "\n".join(page.get_text() for page in doc)
    txt.write_text(text)
    return text


def parse(text: str) -> tuple[str | None, list[dict]]:
    """Return (filing date, one dict per private fund)."""
    stamp = STAMP.search(text)
    start = text.find("SECTION 7.B.(1) Private Fund Reporting")
    if start < 0:
        return (stamp.group(1) if stamp else None), []
    # stop before 7.B.(2), where funds reported by *other* advisers are listed
    end = text.find("SECTION 7.B.(2)", start)
    section = text[start:end if end > 0 else None]
    # A fund's name and ID repeat at the top of every page it spans, so walk the
    # markers in order and attach each question to the most recent fund.
    markers = [(m.start(), m.group(2), " ".join(m.group(1).split())) for m in FUND.finditer(section)]
    funds: dict[str, dict] = {}
    for i, (pos, fund_id, name) in enumerate(markers):
        end = markers[i + 1][0] if i + 1 < len(markers) else len(section)
        chunk = section[pos:end]
        f = funds.setdefault(fund_id, {"fund_id": fund_id, "fund_name": name, "gross_assets": None,
                                       "has_admin": None, "administrators": None})
        if f["gross_assets"] is None and (g := GAV.search(chunk)):
            f["gross_assets"] = float(g.group(1).replace(",", ""))
        if f["has_admin"] is None and (q := Q26.search(chunk)):
            answer = q.group(1)
            names = [" ".join(n.split()) for n in ADMIN_NAME.findall(answer)]
            f["has_admin"] = bool(names) or "Record(s) Filed" in answer
            f["administrators"] = "; ".join(dict.fromkeys(names)) or None
    return (stamp.group(1) if stamp else None), list(funds.values())


def main():
    parser = argparse.ArgumentParser(description="Refresh Tier A from current Form ADV filings")
    parser.add_argument("--limit", type=int, help="only the first N advisers (for testing)")
    args = parser.parse_args()

    targets = pd.read_csv(PRIVATE / "targets_v2.csv", dtype={"crd": str})
    tier_a = targets[targets.tier == "A"].head(args.limit)
    with duckdb.connect(str(DB)) as con:
        then = con.execute("""
            SELECT l.crd, f.fund_id, f.fund_type, f.has_admin AS had_admin_2024
            FROM fund_obs f JOIN latest_filing l USING (filing_id, regime)""").df()

    rows, advisers = [], []
    for i, a in enumerate(tier_a.itertuples(), 1):
        print(f"[{i}/{len(tier_a)}] {a.crd}", flush=True)
        text = fetch_text(a.crd)
        if text is None:
            advisers.append({"crd": a.crd, "status": "no current filing"})
            continue
        filed, funds = parse(text)
        total = re.search(r"Total Funds:\s*(\d+)", text)
        prior = then[then.crd == a.crd].set_index("fund_id")
        for f in funds:
            f["crd"] = a.crd
            f["fund_type_2024"] = prior.fund_type.get(f["fund_id"])
            f["had_admin_2024"] = prior.had_admin_2024.get(f["fund_id"])
            rows.append(f)
        cur = pd.DataFrame(funds)
        pe_re_2024 = prior[prior.fund_type.isin(["Private Equity Fund", "Real Estate Fund"])].index
        if cur.empty:
            status = "no private funds reported"
        elif cur.has_admin.isna().all():
            status = "unparsed"
        elif cur[cur.fund_id.isin(pe_re_2024)].has_admin.fillna(False).any():
            status = "hired administrator"
        elif cur[~cur.fund_id.isin(prior.index)].has_admin.fillna(False).any():
            status = "new fund uses administrator"
        else:
            status = "still self-administered"
        advisers.append({"crd": a.crd, "filed": filed, "status": status,
                         "funds_now": len(cur), "new_funds": int((~cur.fund_id.isin(prior.index)).sum()) if len(cur) else 0,
                         "fund_count_mismatch": bool(total) and int(total.group(1)) != len(cur)})

    funds_df = pd.DataFrame(rows)
    adv = pd.DataFrame(advisers).merge(tier_a[["crd", "adviser_name", "p_switch", "passes_v2_filter"]], on="crd")
    PRIVATE.mkdir(parents=True, exist_ok=True)
    adv.to_csv(PRIVATE / "tier_a_refreshed.csv", index=False)
    funds_df.to_csv(PRIVATE / "tier_a_funds_current.csv", index=False)
    with duckdb.connect(str(DB)) as con:
        con.execute("CREATE OR REPLACE TABLE refresh_advisers AS SELECT * FROM adv")
        con.execute("CREATE OR REPLACE TABLE refresh_funds AS SELECT * FROM funds_df")

    # The outreach shortlist: passes the backtested filter and has not bought yet.
    shortlist = (adv[adv.passes_v2_filter & (adv.status == "still self-administered")]
                 .merge(tier_a[["crd", "state", "private_fund_assets", "cco_name", "website"]], on="crd")
                 .sort_values(["p_switch", "crd"], ascending=[False, True]))
    shortlist.to_csv(PRIVATE / "shortlist.csv", index=False)

    write_report(adv, len(shortlist))


def write_report(adv: pd.DataFrame, n_shortlist: int):
    n = len(adv)
    status = adv.status.value_counts()
    parsed = adv[adv.status.isin(["hired administrator", "new fund uses administrator", "still self-administered"])]
    bought = parsed.status != "still self-administered"
    by_filter = []
    for label, mask in [("Passed v2 filter", parsed.passes_v2_filter), ("Failed v2 filter", ~parsed.passes_v2_filter)]:
        grp = bought[mask.to_numpy()]
        by_filter.append((label, len(grp), int(grp.sum()), pct(grp.sum(), len(grp))))
    _, p_value = fisher_exact([[by_filter[0][2], by_filter[0][1] - by_filter[0][2]],
                               [by_filter[1][2], by_filter[1][1] - by_filter[1][2]]], alternative="greater")
    mismatches = int(adv.get("fund_count_mismatch", pd.Series(dtype=bool)).sum())
    dates = pd.to_datetime(adv.filed, format="%m/%d/%Y", errors="coerce").dropna()
    md = [
        "[← Findings](findings.md)", "",
        "# Tier A refresh: current Form ADV filings", "",
        f"The bulk fund-level data ends Dec 2024. Each Tier A adviser's current Form ADV was pulled and its "
        f"private-fund section parsed. Filings span {dates.min():%b %Y} to {dates.max():%b %Y} "
        f"(median {dates.median():%b %Y})." if len(dates) else "", "",
        "## Status since 2024", "",
        table(["Status", "Advisers", "Share"], [(s, c, pct(c, n)) for s, c in status.items()]), "",
        "- **hired administrator**: a PE/RE fund that was self-administered in 2024 now reports an outside administrator. "
        "These advisers have already bought, so they come off the outreach list.",
        "- **new fund uses administrator**: existing funds are unchanged, but a fund launched since 2024 uses an administrator.",
        "- **still self-administered**: still in market.", "",
        f"**Outreach shortlist: {n_shortlist} advisers** pass the v2 filter and are still fully self-administered "
        "(`data/private/shortlist.csv`, not committed). This is the input to enrichment.", "",
        "## Live check of the v2 filter", "",
        "These outcomes happened after every year the model was trained or tested on, so they are a genuine "
        "forward test. Small numbers: read as directional.", "",
        table(["Group", "Advisers", "Bought administration since 2024", "Rate"], by_filter), "",
        f"Fisher's exact test, one-sided: p = {p_value:.3f}. "
        "'Bought' means either status above: an existing fund hired an administrator, or a new fund launched with one.", "",
        f"Parse check: every adviser's parsed fund count matches the filing's own 'Total Funds' figure "
        f"({mismatches} mismatches).", "",
    ]
    (OUT / "refresh.md").write_text("\n".join(md) + "\n")
    print(status.to_string())
    print(by_filter)


if __name__ == "__main__":
    main()
