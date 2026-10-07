[← Findings](findings.md)

# Daily automation: new fund launches by self-administered managers

An n8n workflow checks the SEC every weekday for new private-fund offerings (Form D) and alerts Slack when the general partner, manager or fund belongs to a manager that runs its funds without an outside administrator. A launch is when a manager decides how the new fund will be administered, so that's the moment to reach out. Workflow files: [`automation/n8n/`](../automation/n8n/) (the matching list is removed from the public copy). Logic: [`scan.js`](../automation/scan.js), [`format.js`](../automation/format.js).

## How often it would have fired

The same matching rules, replayed over the Form D data sets (Jul 2025 to Jun 2026):

|  |  |
|---|---|
| Managers watched (US, under $1B, at least one self-administered PE/RE fund) | 879 |
| New fund offerings scanned | 15,356 |
| Alerts (one per manager per day) | 131 from 62 managers |
| Priority alerts (Tier A/B, with score and drafted opener) | 32 from 21 managers |
| Business days with at least one alert | 102 of 261 (39%) |

## Reliability built in

- Weekends and holidays have no index file and are skipped.
- Every SEC request is retried with backoff. A filing that still fails counts as an error and is retried next run.
- Processed filings are remembered between runs, so a rerun never alerts twice.
- Each run is capped. A backlog after an outage drains over the next runs and stays within n8n's time limit.
- A daily summary posts even when there are no matches, so silence can't hide a broken job. A separate error workflow posts any failure to Slack.

