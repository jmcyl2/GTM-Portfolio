// n8n Code node: "List new Form D filings" (mode: Run Once for All Items).
//
// Reads the SEC daily index for every weekday since the last completed scan and
// lists the new Form D filings (type "D", not amendments) not yet processed.
// Only the index files are fetched here (1-4 requests), so this node stays far
// inside n8n Cloud's 60-second Code limit; the filings themselves are fetched by
// the HTTP Request node that follows, which handles batching and retries.
//
// The node has "Always Output Data" on: on a day with nothing to fetch it emits
// one empty item, so the rest of the flow still runs and posts the daily summary.

const UA = '__USER_AGENT__';
const MAX_DAYS_BACK = 4;          // a Monday run covers Friday, plus a holiday
const MAX_FILINGS_PER_RUN = 450;  // a backlog after an outage drains over later runs

const state = $getWorkflowStaticData('global');
state.seen = state.seen || {};
const ymd = d => d.toISOString().slice(0, 10).replace(/-/g, '');
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function index(day) {
  const q = Math.floor((Number(day.slice(4, 6)) - 1) / 3) + 1;
  const url = `https://www.sec.gov/Archives/edgar/daily-index/${day.slice(0, 4)}/QTR${q}/form.${day}.idx`;
  for (let i = 1; i <= 3; i++) {
    try {
      return await this.helpers.httpRequest({ url, headers: { 'User-Agent': UA }, json: false });
    } catch (e) {
      const code = String(e.httpCode || e.statusCode || (e.response && e.response.status) || '');
      if (code === '403' || code === '404') return null;  // the SEC answers 403 for a missing index (holiday)
      if (i === 3) throw e;
      await sleep(2000 * i);
    }
  }
}

const now = new Date();
const due = [];
for (let back = MAX_DAYS_BACK; back >= 1; back--) {
  const d = new Date(now); d.setUTCDate(d.getUTCDate() - back);
  if ([0, 6].includes(d.getUTCDay())) continue;  // no filings at weekends
  if (!state.lastScanned || ymd(d) > state.lastScanned) due.push(ymd(d));
}

const run = { at: now.toISOString(), daysChecked: [], noIndexDays: [], indexErrors: 0, listed: 0, deferredDays: [] };
const filings = [];
for (const day of due) {
  let idx;
  try { idx = await index.call(this, day); } catch (e) { run.indexErrors++; break; }  // retry from here next run
  run.daysChecked.push(day);
  if (!idx) { run.noIndexDays.push(day); continue; }
  for (const line of idx.split('\n')) {
    if (!/^D\s{2,}/.test(line)) continue;
    const m = line.match(/edgar\/data\/(\d+)\/(\S+)\.txt/);
    if (!m || state.seen[m[2]]) continue;
    filings.push({ day, cik: m[1], accession: m[2],
                   xmlUrl: `https://www.sec.gov/Archives/edgar/data/${m[1]}/${m[2].replace(/-/g, '')}/primary_doc.xml` });
  }
}

const work = filings.slice(0, MAX_FILINGS_PER_RUN);
run.listed = work.length;
run.deferredDays = [...new Set(filings.slice(MAX_FILINGS_PER_RUN).map(f => f.day))];
state.pendingRun = run;  // picked up by the match node

return work.map(f => ({ json: f }));
