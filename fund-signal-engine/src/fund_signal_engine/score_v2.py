"""Score v2: learn which signals predict a self-administered fund hiring an
outside administrator, on an out-of-time split.

  train: funds whose base year is 2014-2017
  test:  funds whose base year is 2018-2021 (never seen during fitting)

v1 (pre-registered) is evaluated on the same test set for comparison. The
fitted model is then applied to today's Tier A/B funds to rank advisers.
"""

import csv
import json

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .build import OUT, PRIVATE, table
from .ingest import DB

TRAIN_YEARS, TEST_YEARS = (2014, 2017), (2018, 2021)

# Every candidate signal, fixed before the test set was scored. Label -> how to compute it.
FEATURES = {
    "Audited": lambda d: d.audited,
    "Financials prepared under GAAP": lambda d: d.gaap,
    "Audited financials sent to investors": lambda d: d.fs_distributed,
    "Fund of funds": lambda d: d.fund_of_funds,
    "Master/feeder structure": lambda d: d.master_feeder,
    "Qualified purchasers only (3(c)(7))": lambda d: d.qualified_purchasers_only,
    "Uses placement agent": lambda d: d.uses_placement_agent,
    "Real estate (vs PE)": lambda d: d.is_real_estate,
    "SEC-registered adviser (vs exempt)": lambda d: d.sec_registered,
    "Adviser already uses an administrator elsewhere": lambda d: d.adviser_uses_admin_elsewhere,
    "Number of investors (log)": lambda d: np.log1p(d.owners.fillna(0)),
    "Fund assets (log)": lambda d: np.log1p(d.gross_assets.fillna(0)),
    "Adviser private fund assets (log)": lambda d: np.log1p(d.adviser_assets.fillna(0)),
    "Adviser fund count (log)": lambda d: np.log1p(d.adviser_funds.fillna(0)),
    "Minimum investment (log)": lambda d: np.log1p(d.min_investment.fillna(0)),
    "% owned by non-US investors": lambda d: d.pct_non_us.fillna(0) / 100,
    "% owned by adviser/related": lambda d: d.pct_owned_related.fillna(0) / 100,
    "% assets valued by third party": lambda d: d.pct_third_party_valued.fillna(0) / 100,
    "Fund age (years, capped at 10)": lambda d: d.fund_age.clip(upper=10),
    "Asset growth YoY (clipped)": lambda d: d.asset_growth.fillna(0).clip(-1, 3),
}


def matrix(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({name: fn(df).astype(float).fillna(0) for name, fn in FEATURES.items()})


def lift_table(y, scores, buckets=5):
    ranks = pd.qcut(pd.Series(scores).rank(method="first"), buckets, labels=False)
    base = y.mean()
    rows = []
    for q in range(buckets - 1, -1, -1):
        mask = (ranks == q).to_numpy()
        rate = y[mask].mean()
        rows.append((f"Q{buckets - q}" + (" (highest)" if q == buckets - 1 else " (lowest)" if q == 0 else ""),
                     f"{mask.sum():,}", f"{100 * rate:.1f}%", f"{rate / base:.2f}x"))
    return rows


def main():
    with duckdb.connect(str(DB)) as con:
        bt = con.execute("SELECT * FROM backtest").df()
        current = con.execute("SELECT * FROM current_fund_features").df()
        names = con.execute("SELECT crd, tier, adviser_name, state, private_fund_assets, cco_name, website FROM targets").df()

    train = bt[bt.base_year.between(*TRAIN_YEARS)]
    test = bt[bt.base_year.between(*TEST_YEARS)]
    y_train, y_test = train.switched.astype(int).to_numpy(), test.switched.astype(int).to_numpy()

    model = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=5000))
    model.fit(matrix(train), y_train)
    p_test = model.predict_proba(matrix(test))[:, 1]

    auc_v2 = roc_auc_score(y_test, p_test)
    auc_v1 = roc_auc_score(y_test, test.score)
    auc_train = roc_auc_score(y_train, model.predict_proba(matrix(train))[:, 1])

    coefs = pd.Series(model[-1].coef_[0], index=list(FEATURES)).sort_values(key=abs, ascending=False)
    top_q = lift_table(y_test, p_test)[0]
    upper = pd.Series(p_test).rank(pct=True).to_numpy() > 0.4
    upper_rate, bottom_rate = y_test[upper].mean(), y_test[~upper].mean()

    # --- apply to today's targets: an adviser's score is its highest-scoring self-administered fund
    current["p_switch"] = model.predict_proba(matrix(current))[:, 1]
    by_adviser = (current.groupby("crd")
                  .agg(p_switch=("p_switch", "max"), n_self_admin_funds=("fund_id", "nunique"))
                  .reset_index().merge(names, on="crd")
                  .sort_values(["p_switch", "crd"], ascending=[False, True]))
    by_adviser["v2_rank"] = range(1, len(by_adviser) + 1)
    # the exclusion cutoff is the test set's 40th percentile, not the target list's own
    cutoff = float(np.quantile(p_test, 0.4))
    by_adviser["passes_v2_filter"] = by_adviser.p_switch > cutoff
    tier_a = by_adviser[by_adviser.tier == "A"]

    PRIVATE.mkdir(parents=True, exist_ok=True)
    cols = ["v2_rank", "tier", "adviser_name", "crd", "state", "private_fund_assets", "n_self_admin_funds",
            "p_switch", "passes_v2_filter", "cco_name", "website"]
    by_adviser[cols].round({"p_switch": 4, "private_fund_assets": 0}).to_csv(PRIVATE / "targets_v2.csv", index=False,
                                                                           quoting=csv.QUOTE_MINIMAL)

    (OUT / "score_v2_model.json").write_text(json.dumps({
        "train_years": TRAIN_YEARS, "test_years": TEST_YEARS,
        "features": list(FEATURES),
        "scaler_mean": model[0].mean_.round(6).tolist(), "scaler_scale": model[0].scale_.round(6).tolist(),
        "coef": model[-1].coef_[0].round(6).tolist(), "intercept": round(float(model[-1].intercept_[0]), 6),
        "test_auc_v2": round(auc_v2, 4), "test_auc_v1": round(auc_v1, 4),
        "exclusion_cutoff": round(cutoff, 6),
    }, indent=2))

    md = [
        "[← Findings](findings.md)", "",
        "# Score v2: learned on 2014-2017, tested on 2018-2021", "",
        "The pre-registered v1 score barely beat random. v2 asks which signals actually predict a self-administered "
        "PE/RE fund hiring an outside administrator within 3 years. To keep the test honest, it learns only from funds "
        f"whose base year is {TRAIN_YEARS[0]}-{TRAIN_YEARS[1]} and is graded on funds from "
        f"{TEST_YEARS[0]}-{TEST_YEARS[1]} that it never saw. v1 is graded on the same test set.", "",
        "## Results on the held-out test set", "",
        table(["", "v1 (pre-registered)", "v2 (learned)"], [
            ("AUC (0.5 = random, 1.0 = perfect)", f"{auc_v1:.3f}", f"{auc_v2:.3f}"),
        ]), "",
        f"Train: {len(train):,} funds ({100 * y_train.mean():.1f}% switched). "
        f"Test: {len(test):,} funds ({100 * y_test.mean():.1f}% switched). "
        f"Train AUC is {auc_train:.3f} against {auc_v2:.3f} on test: part of what the model learned from the earlier "
        "years did not carry over to the later ones. The test figure is the one to trust.", "",
        "**v2 test-set switch rate by score quintile:**", "",
        table(["Quintile", "Funds", "Switched within 3 yrs", "vs average"], lift_table(y_test, p_test)), "",
        f"**v2 works as an exclusion filter, not a winner-picker.** The bottom 40% of funds by score switched at "
        f"{100 * bottom_rate:.1f}%, against {100 * upper_rate:.1f}% for the top 60% ({upper_rate / bottom_rate:.1f}x). "
        "Within the top 60% the score barely separates funds, so ranking inside it adds little; "
        "dropping the bottom 40% does.", "",
        "## What predicts a switch", "",
        "Standardized logistic-regression weights (positive = more likely to hire an administrator; "
        "magnitude = effect of a one-standard-deviation change, holding the others fixed):", "",
        table(["Signal", "Weight", "Direction"],
              [(n, f"{w:+.2f}", "more likely" if w > 0 else "less likely") for n, w in coefs.items()]), "",
        "## Applied to today's targets", "",
        f"Each Tier A/B adviser is scored by its highest-scoring self-administered fund (fund detail as of "
        f"its latest bulk filing). Tier A's {len(tier_a)} advisers range from "
        f"{100 * tier_a.p_switch.min():.1f}% to {100 * tier_a.p_switch.max():.1f}% predicted 3-year switch probability "
        f"(median {100 * tier_a.p_switch.median():.1f}%). Applying the test-set exclusion cutoff "
        f"({100 * cutoff:.1f}%) keeps **{int(tier_a.passes_v2_filter.sum())} of {len(tier_a)}** Tier A advisers. "
        "The ranked list is written to `data/private/targets_v2.csv` (not committed).", "",
        "Caveats: the outcome is *hiring an administrator*, which is evidence of willingness to pay for the close, "
        "but not of demand for any specific product. Funds that stopped reporting are excluded. Probabilities are "
        "calibrated to the training period's base rate, which is lower than the test period's.",
    ]
    (OUT / "score_v2.md").write_text("\n".join(md) + "\n")
    print(f"v1 test AUC {auc_v1:.3f} | v2 test AUC {auc_v2:.3f} (train {auc_train:.3f})")
    print(f"top 60% {100 * upper_rate:.1f}% vs bottom 40% {100 * bottom_rate:.1f}%")
    print(coefs.round(2).to_string())


if __name__ == "__main__":
    main()
