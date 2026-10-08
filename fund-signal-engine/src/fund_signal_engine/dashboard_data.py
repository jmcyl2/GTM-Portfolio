"""Export the aggregate tables the public dashboard reads (outputs/dashboard/).

Counts, rates and model results only: nothing that names a firm's prospects
or a person. Fund administrators appear by name: they are the market being
mapped, not targets. The dashboard (dashboard/app.py) reads only these files,
so it can never see data/private/.
"""

import json

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .build import OUT, PRIVATE
from .clay import EXPORT, FREE_MAIL, name_plausible
from .ingest import DB
from .openers import firm_name
from .score_v2 import FEATURES, TEST_YEARS, TRAIN_YEARS, matrix

DASH = OUT / "dashboard"
SIZE_BUCKETS = [(0, 10e6, "Under $10M"), (10e6, 50e6, "$10–50M"), (50e6, 250e6, "$50–250M"),
                (250e6, 1e9, "$250M–1B"), (1e9, float("inf"), "Over $1B")]


ACRONYMS = {"II", "III", "IV", "SS&C", "SEI", "MUFG", "NAV", "U.S.", "CSC", "IQ-EQ", "BNY", "JPMORGAN", "CLA", "RSM", "LLP"}


def admin_name(raw: str) -> str:
    """Readable administrator name: legal suffix dropped, acronyms kept upper case."""
    words = []
    for w in firm_name(raw).split():
        core = w.strip("(),").upper()
        fixed = core if core in ACRONYMS else core.capitalize()
        words.append(w.upper().replace(core, fixed) if core else w)
    words = [w.lower() if i and w in ("And", "Of", "The", "For") else w for i, w in enumerate(words)]
    return " ".join(words).replace("Jpmorgan", "JPMorgan")


def write(name: str, df: pd.DataFrame):
    df.to_csv(DASH / f"{name}.csv", index=False)


def main():
    DASH.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(DB), read_only=True) as con:
        q = lambda sql: con.execute(sql).df()

        # Who runs their own books, by fund type and by fund size (latest filing per adviser)
        latest = """FROM fund_obs JOIN latest_filing USING (filing_id, regime)"""
        write("self_admin_by_type", q(f"""
            SELECT fund_type, count(*) AS funds, avg((NOT has_admin)::INT) AS share_self_admin
            {latest} WHERE fund_type IS NOT NULL GROUP BY 1 ORDER BY share_self_admin DESC"""))
        size = q(f"""SELECT gross_assets, NOT has_admin AS self_admin {latest}
                     WHERE fund_type IN ('Private Equity Fund', 'Real Estate Fund') AND gross_assets IS NOT NULL""")
        rows = []
        for i, (lo, hi, label) in enumerate(SIZE_BUCKETS):
            b = size[(size.gross_assets >= lo) & (size.gross_assets < hi)]
            rows.append({"order": i, "fund_size": label, "funds": len(b), "share_self_admin": b.self_admin.mean()})
        write("self_admin_by_size", pd.DataFrame(rows))

        # Targeting funnel (advisers), then the outreach steps
        funnel = q("""
            SELECT 'Advisers with a PE/RE fund' AS step, count(*) FILTER (n_pe_re > 0) AS n FROM adviser_profile
            UNION ALL SELECT 'Active today, US', count(*) FILTER (n_pe_re > 0 AND active_now AND country = 'United States') FROM adviser_profile
            UNION ALL SELECT '$20M–$500M, 1–5 funds', count(*) FROM targets
            UNION ALL SELECT 'Tier A: every PE/RE fund in-house', count(*) FILTER (tier = 'A') FROM targets""")
        refresh = q("SELECT * FROM refresh_advisers")
        shortlist_n = len(pd.read_csv(PRIVATE / "shortlist.csv"))
        df = pd.read_csv(EXPORT, dtype=str).replace({"undefined": None, "None found": None})
        email = df["Work Email"].fillna("").str.lower()
        usable = int((email.ne("") & ~email.str.split("@").str[-1].isin(FREE_MAIL)
                      & pd.Series([name_plausible(e, n) if e else False
                                   for e, n in zip(email, df["Contact Full Name"].fillna(""))])).sum())
        funnel = pd.concat([funnel, pd.DataFrame([
            {"step": "Pass the backtested filter", "n": int(refresh.passes_v2_filter.sum())},
            {"step": "…and still in-house in 2026", "n": shortlist_n},
            {"step": "Enriched (Clay trial cap)", "n": len(df)},
            {"step": "Usable work email after QA", "n": usable},
        ])], ignore_index=True)
        funnel["order"] = range(len(funnel))
        write("funnel", funnel)

        # The administrator market (PE/RE funds of active US advisers) and who wins switchers
        admins = q("SELECT admin_key, administrator, pe_re_funds FROM administrators ORDER BY pe_re_funds DESC, administrator")
        admins["administrator"] = admins.administrator.map(admin_name)
        top = admins.head(10)[["administrator", "pe_re_funds"]]
        rest = admins.iloc[10:]
        boutique = int(((admins.pe_re_funds >= 10) & (admins.pe_re_funds <= 50)).sum())
        write("admin_share", pd.concat([top, pd.DataFrame([{"administrator": f"All other ({len(rest)})",
                                                             "pe_re_funds": int(rest.pe_re_funds.sum())}])]))
        winners = q("SELECT administrator, funds_won FROM switch_winners ORDER BY funds_won DESC, administrator LIMIT 10")
        winners["administrator"] = winners.administrator.map(admin_name)
        write("switch_winners", winners)

        # Model: v1 vs v2 on held-out years; v2 quintiles and weights
        bt = q("SELECT * FROM backtest")
    train, test = bt[bt.base_year.between(*TRAIN_YEARS)], bt[bt.base_year.between(*TEST_YEARS)]
    model = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=5000))
    model.fit(matrix(train), train.switched.astype(int))
    p = model.predict_proba(matrix(test))[:, 1]
    y = test.switched.astype(int).to_numpy()
    ranks = pd.qcut(pd.Series(p).rank(method="first"), 5, labels=False)
    write("v2_quintiles", pd.DataFrame([{"order": q_, "quintile": f"Q{5 - q_}" + (" (highest)" if q_ == 4 else " (lowest)" if q_ == 0 else ""),
                                         "funds": int((ranks == q_).sum()), "switch_rate": y[(ranks == q_).to_numpy()].mean()}
                                        for q_ in range(4, -1, -1)]))
    write("v2_weights", pd.DataFrame({"signal": list(FEATURES), "weight": model[-1].coef_[0]})
          .sort_values("weight", key=abs, ascending=False))
    model_json = json.loads((OUT / "score_v2_model.json").read_text())

    # Forward test (2025–26 outcomes)
    parsed = refresh[refresh.status.isin(["hired administrator", "new fund uses administrator", "still self-administered"])]
    bought = parsed.status.ne("still self-administered")
    write("forward_test", pd.DataFrame([
        {"group": "Passed v2 filter", "advisers": int(parsed.passes_v2_filter.sum()), "bought_rate": bought[parsed.passes_v2_filter].mean()},
        {"group": "Failed v2 filter", "advisers": int((~parsed.passes_v2_filter).sum()), "bought_rate": bought[~parsed.passes_v2_filter].mean()},
    ]))

    # Automation backtest: alerts per month
    from .automation import FUND_FILTER, lookup
    with duckdb.connect(str(DB), read_only=True) as con:
        lk = lookup(con)
        con.register("lk", lk)
        hits = con.execute(f"""
            WITH s AS (SELECT ACCESSIONNUMBER, strptime(FILING_DATE, '%d-%b-%Y')::DATE AS d
                       FROM raw_formd_formdsubmission WHERE SUBMISSIONTYPE = 'D'),
            f AS (SELECT ACCESSIONNUMBER FROM raw_formd_offering WHERE {FUND_FILTER}),
            nm AS (SELECT ACCESSIONNUMBER, norm(LASTNAME) AS k FROM raw_formd_relatedpersons
                   WHERE upper(trim(FIRSTNAME)) IN ('N/A', 'NA', '')
                   UNION ALL SELECT ACCESSIONNUMBER, norm(ENTITYNAME) FROM raw_formd_issuers)
            SELECT DISTINCT s.d, lk.crd, t.tier FROM s JOIN f USING (ACCESSIONNUMBER) JOIN nm USING (ACCESSIONNUMBER)
            JOIN lk USING (k) LEFT JOIN targets t USING (crd)""").df()
    hits["month"] = pd.to_datetime(hits.d).dt.to_period("M").dt.to_timestamp()
    hits["kind"] = np.where(hits.tier.isin(["A", "B"]), "Priority (Tier A/B)", "Watchlist")
    write("automation_monthly", hits.groupby(["month", "kind"]).size().rename("alerts").reset_index())

    kpis = {
        "fund_records": int(con_count()),
        "tier_a": int(funnel.loc[funnel.step.str.startswith("Tier A"), "n"].iloc[0]),
        "shortlist": shortlist_n, "usable_emails": usable, "enriched": len(df),
        "auc_v1": model_json["test_auc_v1"], "auc_v2": model_json["test_auc_v2"],
        "forward_pass": float(bought[parsed.passes_v2_filter].mean()), "forward_fail": float(bought[~parsed.passes_v2_filter].mean()),
        "boutique_admins": boutique, "admins_total": len(admins),
        "watched_managers": int(lk.crd.nunique()), "backtest_alerts": int(len(hits)),
    }
    (DASH / "kpis.json").write_text(json.dumps(kpis, indent=2))
    print(f"wrote {len(list(DASH.glob('*')))} files to outputs/dashboard/")


def con_count() -> int:
    with duckdb.connect(str(DB), read_only=True) as con:
        return con.execute("SELECT count(*) FROM fund_obs").fetchone()[0]


if __name__ == "__main__":
    main()
