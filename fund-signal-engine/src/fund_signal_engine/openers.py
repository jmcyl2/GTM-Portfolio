"""Draft one outreach opener per enriched adviser, from its own filing data.

Rule-based, not free-form generation: every observation in an opener is a fact
read from the adviser's Form ADV (fund count, audit status, administrator use,
investor count, new funds), so nothing about a real firm can be invented. The
rules pick the strongest hook per firm; the template keeps the tone consistent.

Nothing is sent. Full openers (names, firms, emails) are written to
data/private/; the public output is the method, aggregates, and anonymized
examples.
"""

import re

import duckdb
import pandas as pd

from .build import OUT, PRIVATE, pct, table
from .clay import EXPORT, FREE_MAIL, name_plausible
from .contacts import rank_title
from .ingest import DB

SIGN_OFF = "Best wishes,\nJoseph Leung"
LEGAL_SUFFIX = re.compile(r",?\s+(LLC|L\.L\.C\.|LP|L\.P\.|LLLP|INC\.?|CORP\.?|CO\.?,?\.?LTD\.?|LTD\.?|CO\.?)$", re.I)
KEEP_UPPER = {"II", "III", "IV", "SF", "FS", "MCM", "NRDC", "TRM", "BHC", "CEFI", "ESCP", "CW"}
NUMBERS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}

ROLE_LINES = {
    "finance": "I imagine a good part of the quarter-end close sits with you.",
    "operations": "I imagine the quarter-end close runs through your team.",
    "compliance": "I imagine you see much of the quarter-end process from where you sit.",
    "executive": "At a firm of your size, I imagine the quarter-end close still runs close to the partners.",
    "other": "At a firm of your size, I imagine the quarter-end close still runs close to the partners.",
}
BODY = (
    "I have a background in fund audit and financial reporting and am researching how managers of "
    "your size run the quarterly close: where the time goes and what tends to break before investor "
    "reports go out.\n\n"
    "Would you be open to a 15-minute conversation? I would value your perspective."
)


def firm_name(legal: str) -> str:
    name, prev = legal.strip(), None
    while name != prev:  # "CO., L.L.C." needs two passes
        prev, name = name, LEGAL_SUFFIX.sub("", name).strip(" ,")
    words = []
    for w in name.split():
        core = w.strip(".,")
        words.append(w.upper() if core.upper() in KEEP_UPPER else "-".join(p.capitalize() for p in w.split("-")))
    return " ".join(words)


def count_word(n: int) -> str:
    return NUMBERS.get(n, str(n))


def hook(f) -> tuple[str, str]:
    """(hook id, observation) from the firm's filing facts: one main clause, then at most one short sentence."""
    n, self_admin = int(f.funds_now), int(f.self_admin_now)
    all_n = "both" if n == 2 else f"all {count_word(n)}"
    if n >= 2 and f.all_audited and self_admin == n:
        kind, text = "audited_multi", f"{all_n} of your funds are audited and none use an outside administrator."
    elif n >= 2 and self_admin == n:
        kind, text = "self_admin_multi", f"none of your {count_word(n)} funds use an outside administrator."
    elif n >= 2:
        kind, text = "partly_in_house", f"{count_word(self_admin)} of your {count_word(n)} funds are administered in-house."
    elif f.all_audited:
        kind, text = "audited_single", "your fund is audited annually and administered in-house."
    else:
        kind, text = "self_admin_single", "your fund is administered in-house rather than by an outside administrator."
    extras = []
    if f.investors and f.investors >= 25:
        extras.append(f"{'between them they report' if n >= 2 else 'it reports'} more than "
                      f"{int(f.investors // 10 * 10)} investors")
    if f.new_funds and f.new_funds > 0:
        extras.append("one was launched in the past year" if n >= 2 else "it was launched in the past year")
    if extras:
        text += " " + (" and ".join(extras)).capitalize() + "."
    return kind, text


def facts(con) -> pd.DataFrame:
    return con.execute("""
        WITH now AS (
            SELECT crd, count(*) AS funds_now, count(*) FILTER (NOT has_admin) AS self_admin_now
            FROM refresh_funds GROUP BY crd),
        inv AS (
            SELECT l.crd, sum(f.owners) AS investors
            FROM fund_obs f JOIN latest_filing l USING (filing_id, regime)
            WHERE f.fund_type IN ('Private Equity Fund', 'Real Estate Fund') GROUP BY l.crd)
        SELECT t.crd, t.all_audited, t.n_pe, t.n_re, t.private_fund_assets,
               now.funds_now, now.self_admin_now, ra.new_funds, inv.investors
        FROM targets t
        JOIN now USING (crd)
        JOIN refresh_advisers ra USING (crd)
        LEFT JOIN inv USING (crd)""").df()


def size_bucket(assets: float) -> str:
    for hi, label in ((50e6, "under $50M"), (100e6, "$50-100M"), (250e6, "$100-250M"), (500e6, "$250-500M")):
        if assets < hi:
            return label
    return "over $500M"


def main():
    df = pd.read_csv(EXPORT, dtype=str).replace({"undefined": None, "None found": None})
    df.columns = [re.sub(r"\W+", "_", c.strip().lower()).strip("_") for c in df.columns]
    email = df.work_email.fillna("").str.lower()
    usable = email.ne("") & ~email.str.split("@").str[-1].isin(FREE_MAIL) & pd.Series(
        [name_plausible(e, n) if e else False for e, n in zip(email, df.contact_full_name.fillna(""))], index=df.index)
    df = df[usable].copy()
    with duckdb.connect(str(DB), read_only=True) as con:
        df = df.merge(facts(con), on="crd", how="left")

    rows = []
    for f in df.itertuples():
        kind, observation = hook(f)
        function = rank_title(f.contact_title or "")[1]
        firm = firm_name(f.company_name)
        first = f.contact_full_name.split()[0]
        opener = (f"Dear {first},\n\n"
                  f"I was reviewing {firm}'s Form ADV and noticed that {observation} {ROLE_LINES[function]}\n\n"
                  f"{BODY}\n\n{SIGN_OFF}")
        rows.append({"crd": f.crd, "firm": firm, "contact": f.contact_full_name, "title": f.contact_title,
                     "function": function, "email": f.work_email, "hook": kind,
                     "subject": f"Quarter-end close at {firm}", "opener": opener,
                     "words": len(opener.split()), "size_bucket": size_bucket(f.private_fund_assets or 0),
                     "fund_mix": "PE" if not f.n_re else ("RE" if not f.n_pe else "PE and RE"),
                     "funds_now": int(f.funds_now)})
    out = pd.DataFrame(rows)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    out.to_csv(PRIVATE / "openers.csv", index=False)
    (PRIVATE / "openers.md").write_text("\n\n---\n\n".join(
        f"**To:** {r.contact} ({r.title}) <{r.email}>\n**Subject:** {r.subject}\n\n{r.opener}" for r in out.itertuples()))
    write_public(out)
    print(f"{len(out)} openers -> data/private/openers.csv / openers.md (not committed)")


def anonymize(r) -> str:
    text = r.opener.replace(r.firm, "[Firm]").replace(r.contact.split()[0], "[First name]", 1)
    return re.sub(r"more than \d+ investors", "more than [N] investors", text)


def write_public(out: pd.DataFrame):
    n = len(out)
    # one example per hook, then extra contact functions not yet shown, up to six
    examples = out.drop_duplicates("hook")
    extra = out[~out.function.isin(examples.function) & ~out.index.isin(examples.index)].drop_duplicates("function")
    examples = pd.concat([examples, extra]).head(6)
    md = ["[← Findings](findings.md)", "", "# Outreach openers (drafted, never sent)", "",
          f"One opener per adviser with a usable email: **{n} drafts**, generated by "
          "[`openers.py`](../src/fund_signal_engine/openers.py). This is a portfolio showcase: nothing was sent. "
          "Full drafts stay in `data/private/`; examples below are anonymized, with firm and person replaced by "
          "placeholders, sizes bucketed and locations removed.", "",
          "## How an opener is built", "",
          "Rules, not free-form generation. Every observation is a fact from the adviser's own Form ADV, "
          "so nothing about a real firm can be invented.", "",
          table(["Part", "Source", "Rule"], [
              ("Hook", "Schedule D 7.B.(1), current filing", "All funds audited and self-administered > none administered > some in-house > single-fund variants"),
              ("Investor clause", "Fund owner counts (Schedule D)", "Added when the funds report 25+ investors, rounded down to tens"),
              ("New-fund clause", "Current vs 2024 fund list", "Added when a fund launched since 2024 is also run in-house"),
              ("Role line", "Contact title (Schedule A)", "Finance / operations / compliance / executive wording"),
              ("Ask", "Fixed", "15-minute research conversation; one ask, no pitch"),
          ]), "",
          "## Mix", "",
          table(["Hook", "Openers"], [(h, f"{c} ({pct(c, n)})") for h, c in out.hook.value_counts().items()]), "",
          table(["Contact function", "Openers"], [(h, f"{c} ({pct(c, n)})") for h, c in out.function.value_counts().items()]), "",
          f"Median length: {int(out.words.median())} words.", "",
          "## Examples (anonymized)", ""]
    for r in examples.itertuples():
        md += [f"**{r.fund_mix} manager, {r.funds_now} fund{'s' if r.funds_now > 1 else ''}, {r.size_bucket}; "
               f"contact: {r.function}; hook: `{r.hook}`**", "",
               "> **Subject:** Quarter-end close at [Firm]", ">",
               *[f"> {line}" if line else ">" for line in anonymize(r).splitlines()], ""]
    (OUT / "openers.md").write_text("\n".join(md) + "\n")


if __name__ == "__main__":
    main()
