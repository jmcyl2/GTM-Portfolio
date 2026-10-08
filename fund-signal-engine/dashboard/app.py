"""Fund Signal Engine: public dashboard.

Reads only the aggregate tables in outputs/dashboard/ (written by
`fse-dashboard-data`), never the private data folder.
Run locally:  uv run streamlit run dashboard/app.py
"""

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

DATA = Path(__file__).resolve().parents[1] / "outputs" / "dashboard"
REPO = "https://github.com/jmcyl2/GTM-Portfolio/tree/main/fund-signal-engine"

st.set_page_config(page_title="Fund Signal Engine", page_icon="📊", layout="wide")


# --- Palette (validated: scripts/validate_palette.js, light and dark) ---------
def theme() -> str:
    try:
        return st.context.theme.type or "light"
    except Exception:
        return "light"


DARK = theme() == "dark"
C = {
    "blue": "#3987e5" if DARK else "#2a78d6",     # slot 1: the series / the emphasis
    "orange": "#d95926" if DARK else "#eb6834",   # slot 2: second series
    "red": "#e66767" if DARK else "#e34948",      # diverging pole (negative)
    "muted": "#55544f" if DARK else "#c3c2b7",    # de-emphasis gray
    "ink": "#ffffff" if DARK else "#0b0b0b",
    "ink2": "#c3c2b7" if DARK else "#52514e",
    "axis": "#898781",
    "grid": "#2c2c2a" if DARK else "#e1e0d9",
    "page": "#0e1117" if DARK else "#ffffff",     # Streamlit page background: the 2px gap between stacked fills
}


def style(chart: alt.Chart, height: int) -> alt.Chart:
    return (chart.properties(height=height)
            .configure(background="transparent")  # must come first: configure() replaces earlier configure_* calls
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor=C["axis"], titleColor=C["ink2"], gridColor=C["grid"], domainColor=C["grid"],
                            tickColor=C["grid"], labelFontSize=12, titleFontSize=12, titleFontWeight="normal")
            .configure_legend(labelColor=C["ink2"], titleColor=C["ink2"], orient="top", title=None))


def hbar(df, y, x, *, emphasis=None, fmt=".0%", x_title="", label=True, sort=None, height=None, scale=None):
    """Horizontal bars: thin, 4px rounded ends, tooltip on every bar, emphasis optional."""
    color = (alt.condition(emphasis, alt.value(C["blue"]), alt.value(C["muted"])) if emphasis is not None
             else alt.value(C["blue"]))
    base = alt.Chart(df).encode(y=alt.Y(f"{y}:N", sort=sort or "-x", title=None, axis=alt.Axis(labelLimit=320)),
                                x=alt.X(f"{x}:Q", title=x_title, axis=alt.Axis(format=fmt, tickCount=4),
                                        scale=alt.Scale(type=scale) if scale else alt.Undefined))
    bars = base.mark_bar(cornerRadiusEnd=4, height=14).encode(
        color=color, tooltip=[alt.Tooltip(f"{y}:N", title=""), alt.Tooltip(f"{x}:Q", format=fmt, title=x_title or x)])
    layers = bars
    if label:
        layers = bars + base.mark_text(align="left", dx=6, color=C["ink2"], fontSize=12).encode(text=alt.Text(f"{x}:Q", format=fmt))
    return style(layers, height or 30 * len(df))


def table_view(label: str, df: pd.DataFrame):
    with st.expander(f"Data: {label}"):
        st.dataframe(df, hide_index=True, use_container_width=True)


k = json.loads((DATA / "kpis.json").read_text())
read = lambda name: pd.read_csv(DATA / f"{name}.csv")

# --- Header ------------------------------------------------------------------
st.title("Fund Signal Engine")
st.markdown(
    "Which small private equity and real estate funds still do their own books, and which are likely to pay for help? "
    "Built entirely from public SEC filings, and tested against what those funds actually did next. "
    f"[Case study]({REPO}/CASE_STUDY.md) · [Code and methodology]({REPO})")

c = st.columns(5)
c[0].metric("Fund records screened", f"{k['fund_records'] / 1e6:.1f}M")
c[1].metric("Tier A managers", f"{k['tier_a']}", help="Small, active US managers where every PE/RE fund is self-administered")
c[2].metric("Outreach shortlist", f"{k['shortlist']}", help="Pass the backtested filter and still self-administered in 2026")
c[3].metric("Verified work emails", f"{k['usable_emails']} of {k['enriched']}", help="After Clay's waterfall and a name/domain QA pass")
c[4].metric("Forward test: bought outside help", f"{k['forward_pass']:.0%} vs {k['forward_fail']:.0%}",
            help="2025–26 outcomes: firms that passed the filter vs those that failed (p = 0.011)")

st.divider()

# --- 1. The market -------------------------------------------------------------
st.header("Who still does their own books")
left, right = st.columns(2)
with left:
    st.subheader("No outside administrator, by fund type")
    by_type = read("self_admin_by_type").rename(columns={"fund_type": "Fund type", "share_self_admin": "No outside administrator"})
    st.altair_chart(hbar(by_type, "Fund type", "No outside administrator",
                         emphasis=alt.FieldOneOfPredicate("Fund type", ["Real Estate Fund", "Private Equity Fund"])),
                    use_container_width=True)
    st.caption("Real estate and private equity funds run their own books far more often than hedge or VC funds. "
               "Latest Form ADV per adviser.")
    table_view("by fund type", by_type)
with right:
    st.subheader("PE/RE funds: no outside administrator, by size")
    by_size = read("self_admin_by_size").rename(columns={"fund_size": "Fund size", "share_self_admin": "No outside administrator"})
    st.altair_chart(hbar(by_size, "Fund size", "No outside administrator", sort=list(by_size["Fund size"]),
                         emphasis=alt.datum["Fund size"] == "Under $10M"), use_container_width=True)
    st.caption("The smallest funds are the most likely to self-administer, but even above $1B more than a third still do.")
    table_view("by fund size", by_size)

st.divider()

# --- 2. The administrator market --------------------------------------------------
st.header("The fund-administration market")
left, right = st.columns(2)
with left:
    st.subheader("Largest administrators of US PE/RE funds")
    share = read("admin_share").rename(columns={"administrator": "Administrator", "pe_re_funds": "PE/RE funds"})
    other = share[share.Administrator.str.startswith("All other")].iloc[0]
    top10 = share[~share.Administrator.str.startswith("All other")]
    st.altair_chart(hbar(top10, "Administrator", "PE/RE funds", fmt=",.0f", sort=list(top10["Administrator"])),
                    use_container_width=True)
    st.caption(f"The other {k['admins_total'] - 10} administrators serve {other['PE/RE funds']:,} funds between them; "
               f"{k['boutique_admins']} are boutiques serving 10–50 funds each. The long tail is a channel partner, not just a competitor.")
    table_view("administrator share", share)
with right:
    st.subheader("Who wins the funds that switch")
    won = read("switch_winners").rename(columns={"administrator": "Administrator", "funds_won": "Funds won"})
    st.altair_chart(hbar(won, "Administrator", "Funds won", fmt=",.0f", sort=list(won["Administrator"])),
                    use_container_width=True)
    st.caption("Self-administered funds that hired an administrator within 3 years (2014–2021 base years).")
    table_view("switch winners", won)

st.divider()

# --- 3. Does the targeting work? ---------------------------------------------------
st.header("Does the targeting actually work?")
st.markdown("A fund that later reports an outside administrator has *bought* the service, so the public record provides "
            "closed-won data. The first model failed and is published as it was; the second was graded on years it never saw.")
c = st.columns(3)
c[0].metric("v1 rules (set in advance), AUC", f"{k['auc_v1']:.3f}", help="0.5 is a coin flip")
c[1].metric("v2 learned model, AUC on 2018–21", f"{k['auc_v2']:.3f}", delta=f"{k['auc_v2'] - k['auc_v1']:+.3f} vs v1")
c[2].metric("Forward test p-value", "0.011", help="One-sided Fisher's exact test, 2025–26 outcomes")

left, right = st.columns(2)
with left:
    st.subheader("v2 test set: switch rate by score")
    qn = read("v2_quintiles").rename(columns={"quintile": "Score quintile", "switch_rate": "Hired an administrator"})
    st.altair_chart(hbar(qn, "Score quintile", "Hired an administrator", sort=list(qn["Score quintile"]),
                         emphasis=alt.FieldOneOfPredicate("Score quintile", list(qn["Score quintile"][:3]))),
                    use_container_width=True)
    st.caption("An exclusion filter, not a winner-picker: the bottom 40% (gray) buy at less than half the rate of the rest.")
    table_view("quintiles", qn)
with right:
    st.subheader("Forward test, 2025–26")
    ft = read("forward_test").rename(columns={"group": "Filter result", "bought_rate": "Bought administration"})
    a, b = st.columns(2)
    passed, failed = ft.iloc[0], ft.iloc[1]
    a.metric(f"Passed the filter ({passed['advisers']} firms)", f"{passed['Bought administration']:.0%}", help="Bought fund administration after 2024")
    b.metric(f"Failed the filter ({failed['advisers']} firms)", f"{failed['Bought administration']:.0%}", help="Bought fund administration after 2024")
    st.caption("Share that went on to buy fund administration in 2025–26, outcomes that happened after every year the "
               "model saw. Twice the rate, p = 0.011.")
    table_view("forward test", ft)
st.subheader("What predicts a switch")
w = read("v2_weights").head(10).rename(columns={"signal": "Signal", "weight": "Weight"})
w["Direction"] = w.Weight.map(lambda v: "More likely" if v > 0 else "Less likely")
chart = alt.Chart(w).mark_bar(cornerRadiusEnd=4, height=12).encode(
    y=alt.Y("Signal:N", sort=list(w.Signal), title=None, axis=alt.Axis(labelLimit=420, labelOverlap=False)),
    x=alt.X("Weight:Q", title="Standardized weight", axis=alt.Axis(tickCount=5)),
    color=alt.Color("Direction:N", scale=alt.Scale(domain=["More likely", "Less likely"], range=[C["blue"], C["red"]])),
    tooltip=["Signal", alt.Tooltip("Weight:Q", format="+.2f"), "Direction"])
st.altair_chart(style(chart, 34 * len(w)), use_container_width=True)
st.caption("Top 10 of 20 signals. Number of investors, the strongest prior, barely mattered.")
table_view("weights", w)

st.divider()

# --- 4. Funnel ------------------------------------------------------------------------
st.header("From 2 million fund records to a verified inbox")
fn = read("funnel").rename(columns={"step": "Step", "n": "Managers"})
st.altair_chart(hbar(fn, "Step", "Managers", fmt=",.0f", sort=list(fn["Step"]), x_title="Managers (square-root scale, so the last steps stay visible)", scale="sqrt"),
                use_container_width=True)
st.caption("Contacts and domains came free from SEC filings (49 of 50 firms got a named person, 4 dead mail domains caught). "
           "Clay ran only the email waterfall: 54 credits, about 1.3 per usable email.")
table_view("funnel", fn)

st.divider()

# --- 5. Automation -------------------------------------------------------------------------
st.header("Daily automation: new fund launches by self-administered managers")
am = read("automation_monthly")
am["month"] = pd.to_datetime(am.month)
am = am.rename(columns={"month": "Month", "kind": "Alert type", "alerts": "Alerts"})
chart = alt.Chart(am).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, stroke=C["page"], strokeWidth=2).encode(
    x=alt.X("yearmonth(Month):O", title=None, axis=alt.Axis(format="%b %y", labelAngle=0)),
    y=alt.Y("Alerts:Q", title="Alerts per month", axis=alt.Axis(tickCount=4)),
    color=alt.Color("Alert type:N", scale=alt.Scale(domain=["Priority (Tier A/B)", "Watchlist"], range=[C["blue"], C["orange"]])),
    order=alt.Order("Alert type:N", sort="ascending"),
    tooltip=[alt.Tooltip("yearmonth(Month):O", title="Month", format="%B %Y"), "Alert type", "Alerts"])
st.altair_chart(style(chart, 260), use_container_width=True)
st.caption(f"An n8n workflow checks the SEC each weekday and posts matches to Slack. Replayed over the past year, the same rules "
           f"watch {k['watched_managers']} managers and would have raised {k['backtest_alerts']} alerts. "
           "A launch is when a manager decides how the new fund will be run, so that's the moment to reach out.")
table_view("alerts per month", am)

st.divider()
st.caption("All data is from public SEC filings (Form ADV, Form D). This dashboard shows aggregates only: no prospect firm, "
           f"person or email appears here. Nothing in this project sends email. [Source]({REPO})")
