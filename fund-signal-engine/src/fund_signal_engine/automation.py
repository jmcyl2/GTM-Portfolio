"""Build the n8n daily-signal workflow, and backtest how often it would fire.

  fse-automation build      write the n8n workflows: private (importable, with the
                            matching list) and public (same logic, list removed)
  fse-automation backtest   replay the last year of Form D data through the same
                            matching rules and write outputs/automation.md

Universe: active US advisers with private fund assets <= $1B that run at least
one PE/RE fund without an outside administrator. Matches on the adviser's legal
name, its Schedule A entity owners (GPs, holding companies) and known fund names.
Tier A/B advisers are flagged as priority, with their v2 score and drafted opener.
"""

import argparse
import json
import os
import re
import uuid
from pathlib import Path

import duckdb
import pandas as pd

from . import sec
from .build import OUT, PRIVATE, pct, table
from .ingest import DB, ROOT
from .openers import firm_name

AUTOMATION = ROOT / "automation"
SUFFIX = re.compile(r"\b(LLC|L L C|LP|L P|LLLP|INC|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|THE)\b")
UNIVERSE = """
    SELECT crd FROM adviser_profile
    WHERE active_now AND country = 'United States' AND n_pe_re_self_admin > 0 AND private_fund_assets <= 1e9"""
FUND_FILTER = """INVESTMENTFUNDTYPE IN ('Private Equity Fund', 'Other Investment Fund')
       OR INDUSTRYGROUPTYPE IN ('Other Real Estate', 'Commercial', 'Residential', 'REITS and Finance')"""


def norm(s) -> str:
    """Same normalisation as automation/match.js; keep the two in sync."""
    s = re.sub(r"[^A-Z0-9 ]", " ", str(s or "").upper())
    return " ".join(SUFFIX.sub(" ", s).split())


def lookup(con) -> pd.DataFrame:
    con.create_function("norm", norm, ["VARCHAR"], "VARCHAR")
    df = con.execute(f"""
        WITH t AS ({UNIVERSE}),
        o AS (SELECT 'ERA' AS regime, * FROM raw_era_owners UNION ALL BY NAME SELECT 'IA' AS regime, * FROM raw_ia_owners),
        owners AS (SELECT fl.crd, o."Full Legal Name" AS nm FROM o
                   JOIN filings fl ON fl.filing_id = try_cast(o.FilingID AS BIGINT) AND fl.regime = o.regime
                   WHERE o."DE/FE/I" = 'DE' AND fl.crd IN (SELECT crd FROM t)),
        funds AS (SELECT DISTINCT crd, fund_name AS nm FROM fund_obs WHERE crd IN (SELECT crd FROM t)),
        names AS (SELECT crd, adviser_name AS nm FROM latest_filing WHERE crd IN (SELECT crd FROM t))
        SELECT DISTINCT crd, norm(nm) AS k FROM (SELECT * FROM names UNION ALL SELECT * FROM owners UNION ALL SELECT * FROM funds)
        WHERE length(norm(nm)) >= 6""").df()
    # a name shared by two advisers can't say which one filed, so drop it
    shared = df.groupby("k").crd.nunique()
    return df[df.k.isin(shared[shared == 1].index)].sort_values(["k", "crd"])


def managers(con) -> dict:
    base = con.execute(f"""
        SELECT a.crd, a.adviser_name, t.tier FROM adviser_profile a
        LEFT JOIN targets t USING (crd) WHERE a.crd IN ({UNIVERSE})""").df()
    v2 = pd.read_csv(PRIVATE / "targets_v2.csv", dtype={"crd": str})[["crd", "p_switch"]]
    short = set(pd.read_csv(PRIVATE / "shortlist.csv", dtype={"crd": str}).crd)
    openers = pd.read_csv(PRIVATE / "openers.csv", dtype={"crd": str}) if (PRIVATE / "openers.csv").exists() else pd.DataFrame(columns=["crd"])
    base = base.merge(v2, on="crd", how="left").merge(openers, on="crd", how="left")
    out = {}
    for r in base.itertuples():
        out[r.crd] = {
            "manager": firm_name(r.adviser_name),
            "tier": r.tier if isinstance(r.tier, str) else None,
            "score": None if pd.isna(r.p_switch) else round(float(r.p_switch), 4),
            "shortlist": r.crd in short,
            "contact": r.contact if isinstance(getattr(r, "contact", None), str) else None,
            "title": r.title if isinstance(getattr(r, "title", None), str) else None,
            "opener": r.opener if isinstance(getattr(r, "opener", None), str) else None,
        }
    return out


def node(name, type_, version, position, parameters, **extra):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, name)), "name": name, "type": type_,
            "typeVersion": version, "position": position, "parameters": parameters, **extra}


def workflows(list_js: str, match_js: str, format_js: str, user_agent: str, slack_url: str) -> tuple[dict, dict]:
    slack_post = lambda name, pos: node(name, "n8n-nodes-base.httpRequest", 4.2, pos, {
        "method": "POST", "url": slack_url, "sendBody": True, "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($json.slack) }}", "options": {}},
        retryOnFail=True, maxTries=3, waitBetweenTries=3000)
    flow = ["Weekdays 07:30", "List new Form D filings", "Fetch Form D", "Match against self-administered managers",
            "Format Slack messages", "Post to Slack"]
    main = {
        "name": "Fund signals: daily SEC Form D scan",
        "nodes": [
            node(flow[0], "n8n-nodes-base.scheduleTrigger", 1.2, [0, 0],
                 {"rule": {"interval": [{"field": "cronExpression", "expression": "30 7 * * 1-5"}]}}),
            # Always Output Data: an empty item on a quiet day keeps the summary flowing
            node(flow[1], "n8n-nodes-base.code", 2, [240, 0], {"jsCode": list_js}, alwaysOutputData=True),
            # Fetching lives in an HTTP node, not a Code node: no 60s Code limit, built-in batching and retries
            node(flow[2], "n8n-nodes-base.httpRequest", 4.2, [480, 0], {
                "url": "={{ $json.xmlUrl }}", "sendHeaders": True,
                "headerParameters": {"parameters": [{"name": "User-Agent", "value": user_agent}]},
                "options": {"batching": {"batch": {"batchSize": 5, "batchInterval": 1000}},
                            "response": {"response": {"responseFormat": "text", "outputPropertyName": "xml"}},
                            "timeout": 20000}},
                retryOnFail=True, maxTries=3, waitBetweenTries=2000, onError="continueRegularOutput"),
            node(flow[3], "n8n-nodes-base.code", 2, [720, 0], {"jsCode": match_js}),
            node(flow[4], "n8n-nodes-base.code", 2, [960, 0], {"jsCode": format_js}),
            slack_post(flow[5], [1200, 0]),
        ],
        "connections": {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(flow, flow[1:])},
        "settings": {"executionOrder": "v1", "timezone": "America/New_York", "saveManualExecutions": True},
    }
    error_js = ("const e = $input.first().json;\n"
                "return [{ json: { slack: { text: `:x: Fund signals workflow failed: ${e.execution?.error?.message || 'unknown error'}"
                " (node: ${e.execution?.lastNodeExecuted || '?'}). ${e.execution?.url || ''}` } } }];")
    errors = {
        "name": "Fund signals: error alerts",
        "nodes": [
            node("On workflow error", "n8n-nodes-base.errorTrigger", 1, [0, 0], {}),
            node("Format error", "n8n-nodes-base.code", 2, [240, 0], {"jsCode": error_js}),
            slack_post("Post error to Slack", [480, 0]),
        ],
        "connections": {
            "On workflow error": {"main": [[{"node": "Format error", "type": "main", "index": 0}]]},
            "Format error": {"main": [[{"node": "Post error to Slack", "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1"},
    }
    return main, errors


def build():
    sec._load_dotenv()
    with duckdb.connect(str(DB), read_only=True) as con:
        lk, mgr = lookup(con), managers(con)
    list_js = (AUTOMATION / "list.js").read_text()
    match_js = (AUTOMATION / "match.js").read_text()
    fmt = (AUTOMATION / "format.js").read_text()
    private_match = (match_js.replace("__LOOKUP__", json.dumps(dict(zip(lk.k, lk.crd)), separators=(",", ":")))
                             .replace("__MANAGERS__", json.dumps({c: mgr[c] for c in sorted(set(lk.crd))}, separators=(",", ":"))))
    public_match = (match_js.replace("__LOOKUP__", "{} /* removed from the public copy */")
                            .replace("__MANAGERS__", "{} /* removed from the public copy */"))
    slack = os.environ.get("SLACK_WEBHOOK_URL", "").strip() or "https://hooks.slack.com/services/REPLACE_ME"
    builds = ((private_match, sec.user_agent(), slack, PRIVATE / "n8n"),
              (public_match, "Your Name you@example.com", "https://hooks.slack.com/services/REPLACE_ME", AUTOMATION / "n8n"))
    for match, ua, slack_url, folder in builds:
        folder.mkdir(parents=True, exist_ok=True)
        main, errors = workflows(list_js.replace("__USER_AGENT__", ua), match, fmt, ua, slack_url)
        (folder / "fund-signals-daily.json").write_text(json.dumps(main, indent=2))
        (folder / "fund-signals-errors.json").write_text(json.dumps(errors, indent=2))
    print(f"lookup: {len(lk)} names for {lk.crd.nunique()} advisers")
    print(f"private (importable): {(PRIVATE / 'n8n').relative_to(ROOT)}/  public: automation/n8n/")
    if "REPLACE_ME" in slack:
        print("note: SLACK_WEBHOOK_URL not set in .env; the private copy has a placeholder Slack URL")


def backtest():
    with duckdb.connect(str(DB), read_only=True) as con:
        lk = lookup(con)
        con.register("lk", lk)
        tiers = con.execute("SELECT crd, tier FROM targets").df()
        hits = con.execute(f"""
            WITH s AS (SELECT ACCESSIONNUMBER, strptime(FILING_DATE, '%d-%b-%Y')::DATE AS d
                       FROM raw_formd_formdsubmission WHERE SUBMISSIONTYPE = 'D'),
            f AS (SELECT ACCESSIONNUMBER FROM raw_formd_offering WHERE {FUND_FILTER}),
            nm AS (SELECT ACCESSIONNUMBER, norm(LASTNAME) AS k FROM raw_formd_relatedpersons
                   WHERE upper(trim(FIRSTNAME)) IN ('N/A', 'NA', '')
                   UNION ALL SELECT ACCESSIONNUMBER, norm(ENTITYNAME) FROM raw_formd_issuers)
            SELECT DISTINCT s.ACCESSIONNUMBER, s.d, lk.crd
            FROM s JOIN f USING (ACCESSIONNUMBER) JOIN nm USING (ACCESSIONNUMBER) JOIN lk USING (k)""").df()
        scanned = con.execute(f"""
            SELECT count(*) AS n, min(strptime(FILING_DATE, '%d-%b-%Y')::DATE) AS d0, max(strptime(FILING_DATE, '%d-%b-%Y')::DATE) AS d1
            FROM raw_formd_formdsubmission s JOIN raw_formd_offering o USING (ACCESSIONNUMBER)
            WHERE s.SUBMISSIONTYPE = 'D' AND ({FUND_FILTER})""").fetchone()
    hits = hits.merge(tiers, on="crd", how="left")
    alerts = hits.drop_duplicates(["d", "crd"])
    biz_days = len(pd.bdate_range(scanned[1], scanned[2]))
    priority = alerts[alerts.tier.isin(["A", "B"])]
    md = ["[← Findings](findings.md)", "", "# Daily automation: new fund launches by self-administered managers", "",
          "An n8n workflow checks the SEC every weekday for new private-fund offerings (Form D) and alerts Slack when the "
          "general partner, manager or fund belongs to a manager that runs its funds without an outside administrator. "
          "A launch is when a manager decides how the new fund will be administered, so that's the moment to reach out. "
          "Workflow files: [`automation/n8n/`](../automation/n8n/) (the matching list is removed from the public copy). "
          "Logic: [`list.js`](../automation/list.js) → n8n HTTP Request (batched, retried) → [`match.js`](../automation/match.js) → [`format.js`](../automation/format.js).", "",
          "## How often it would have fired", "",
          f"The same matching rules, replayed over the Form D data sets ({scanned[1]:%b %Y} to {scanned[2]:%b %Y}):", "",
          table(["", ""], [
              ("Managers watched (US, under $1B, at least one self-administered PE/RE fund)", f"{lk.crd.nunique():,}"),
              ("New fund offerings scanned", f"{scanned[0]:,}"),
              ("Alerts (one per manager per day)", f"{len(alerts):,} from {alerts.crd.nunique()} managers"),
              ("Priority alerts (Tier A/B, with score and drafted opener)", f"{len(priority)} from {priority.crd.nunique()} managers"),
              ("Business days with at least one alert", f"{alerts.d.nunique()} of {biz_days} ({pct(alerts.d.nunique(), biz_days)})"),
          ]), "",
          "## Reliability built in", "",
          "- Weekends and holidays have no index file and are skipped.",
          "- Every SEC request is retried with backoff. A filing that still fails counts as an error and is retried next run.",
          "- Processed filings are remembered between runs, so a rerun never alerts twice.",
          "- Filings are downloaded by n8n's HTTP Request step (5 per second, retried), not inside a Code step, so the job stays within n8n Cloud's 60-second Code limit. Each run is capped, and a backlog after an outage drains over the next runs.",
          "- A daily summary posts even when there are no matches, so silence can't hide a broken job. "
          "A separate error workflow posts any failure to Slack.", ""]
    (OUT / "automation.md").write_text("\n".join(md) + "\n")
    print(f"{len(alerts)} alerts ({len(priority)} priority) over {biz_days} business days; "
          f"{alerts.d.nunique()} days with an alert")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cmd", choices=["build", "backtest"])
    {"build": build, "backtest": backtest}[parser.parse_args().cmd]()


if __name__ == "__main__":
    main()
