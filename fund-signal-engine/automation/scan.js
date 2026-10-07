// n8n Code node: "Scan SEC Form D filings" (mode: Run Once for All Items).
//
// Finds new private-fund launches (Form D, type "D") filed since the last run,
// and keeps those whose general partner, manager or fund name matches a known
// self-administered manager. The matching list (LOOKUP/MANAGERS) is injected
// when the private workflow is generated; the public copy ships it empty.
//
// Reliability:
// - weekends are skipped; a weekday with no index file (a holiday) is noted, not an error
// - each SEC request is retried with backoff; a filing that still fails is
//   counted as an error, not fatal, and is retried on the next run
// - filings already processed are remembered in workflow static data, so reruns
//   never alert twice
// - work per run is capped; a backlog (e.g. after an outage) drains over the
//   next runs, so the node stays inside n8n's execution time limit

const LOOKUP = __LOOKUP__;      // { normalisedName: crd }
const MANAGERS = __MANAGERS__;  // { crd: { manager, tier, score, shortlist, contact, title, opener } }
const UA = '__USER_AGENT__';
const MAX_DAYS_BACK = 4;        // covers a Monday run after Friday plus a holiday
const MAX_FILINGS_PER_RUN = 450;
const BATCH = 5;                // SEC fair access is 10 requests/second; stay at ~5

const state = $getWorkflowStaticData('global');
state.seen = state.seen || {};
state.runs = state.runs || [];

const SUFFIX = /\b(LLC|L L C|LP|L P|LLLP|INC|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|THE)\b/g;
const norm = s => String(s || '').toUpperCase().replace(/[^A-Z0-9 ]/g, ' ').replace(SUFFIX, ' ').split(/\s+/).filter(Boolean).join(' ');
const tag = (xml, name) => { const m = xml.match(new RegExp(`<${name}>([\\s\\S]*?)</${name}>`)); return m ? m[1].trim() : ''; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ymd = d => d.toISOString().slice(0, 10).replace(/-/g, '');
const http = this.helpers.httpRequest.bind(this.helpers);

async function get(url, { missingOk = false, tries = 3 } = {}) {
  for (let i = 1; i <= tries; i++) {
    try {
      return await http({ url, headers: { 'User-Agent': UA }, json: false });
    } catch (e) {
      const code = String(e.httpCode || e.statusCode || (e.response && e.response.status) || '');
      if (code === '404' || (missingOk && code === '403')) return null;  // SEC answers 403 for a missing index file
      if (i === tries) throw e;
      await sleep(2000 * i);
    }
  }
}

// 1. Which days are due: after the last fully scanned day, up to yesterday.
const now = new Date();
const due = [];
for (let back = MAX_DAYS_BACK; back >= 1; back--) {
  const d = new Date(now); d.setUTCDate(d.getUTCDate() - back);
  if ([0, 6].includes(d.getUTCDay())) continue;  // no filings at weekends
  if (!state.lastScanned || ymd(d) > state.lastScanned) due.push(ymd(d));
}

const run = { at: now.toISOString(), daysChecked: due, indexDays: 0, noIndexDays: [], formD: 0, funds: 0, matched: 0, errors: 0, deferred: 0 };

// 2. Read each day's index; collect new Form D filings not yet processed.
const queue = [];   // { day, cik, accession }
const perDay = {};  // day -> number of filings queued
for (const day of due) {
  const q = Math.floor((Number(day.slice(4, 6)) - 1) / 3) + 1;
  let idx;
  try {
    idx = await get(`https://www.sec.gov/Archives/edgar/daily-index/${day.slice(0, 4)}/QTR${q}/form.${day}.idx`, { missingOk: true });
  } catch (e) { run.errors++; break; }  // can't read this day: stop here, retry next run
  perDay[day] = 0;
  if (!idx) { run.noIndexDays.push(day); continue; }  // market holiday
  run.indexDays++;
  for (const line of idx.split('\n')) {
    if (!/^D\s{2,}/.test(line)) continue;  // new offerings only, not D/A amendments
    const m = line.match(/edgar\/data\/(\d+)\/(\S+)\.txt/);
    if (!m || state.seen[m[2]]) continue;
    queue.push({ day, cik: m[1], accession: m[2] });
    perDay[day]++;
  }
}

// 3. Fetch and match, five filings at a time.
const work = queue.slice(0, MAX_FILINGS_PER_RUN);
run.deferred = queue.length - work.length;
const alerts = [];
const failedDays = new Set(queue.slice(MAX_FILINGS_PER_RUN).map(f => f.day));

for (let i = 0; i < work.length; i += BATCH) {
  const batch = work.slice(i, i + BATCH);
  const started = Date.now();
  await Promise.all(batch.map(async f => {
    run.formD++;
    let xml;
    try {
      xml = await get(`https://www.sec.gov/Archives/edgar/data/${f.cik}/${f.accession.replace(/-/g, '')}/primary_doc.xml`);
    } catch (e) { xml = undefined; }
    if (!xml) { run.errors++; failedDays.add(f.day); return; }
    state.seen[f.accession] = f.day;

    const fundType = tag(xml, 'investmentFundType');
    const industry = tag(xml, 'industryGroupType');
    const isFund = ['Private Equity Fund', 'Other Investment Fund'].includes(fundType)
      || ['Other Real Estate', 'Commercial', 'Residential', 'REITS and Finance'].includes(industry);
    if (!isFund) return;
    run.funds++;

    const issuer = tag(xml, 'entityName');
    const entities = [...xml.matchAll(/<relatedPersonName>([\s\S]*?)<\/relatedPersonName>/g)]
      .map(m => ({ first: tag(m[1], 'firstName'), last: tag(m[1], 'lastName') }))
      .filter(p => ['N/A', 'NA', ''].includes(p.first.toUpperCase()))
      .map(p => p.last);
    const matchedOn = [issuer, ...entities].find(n => LOOKUP[norm(n)]);
    if (!matchedOn) return;
    run.matched++;
    const crd = LOOKUP[norm(matchedOn)];
    alerts.push({
      type: 'alert', filed: f.day, accession: f.accession, issuer, matchedOn,
      fundType: fundType || industry, amount: tag(xml, 'totalOfferingAmount'),
      crd, ...(MANAGERS[crd] || {}),
      filingUrl: `https://www.sec.gov/Archives/edgar/data/${f.cik}/${f.accession.replace(/-/g, '')}/`,
      adviserUrl: `https://adviserinfo.sec.gov/firm/summary/${crd}`,
    });
  }));
  const wait = 1000 - (Date.now() - started);
  if (wait > 0) await sleep(wait);
}

// 4. Advance the cursor past every due day that is now fully processed.
for (const day of Object.keys(perDay).sort()) {
  if (failedDays.has(day)) break;
  state.lastScanned = day;
}
const cutoff = ymd(new Date(now - 30 * 864e5));
for (const [acc, day] of Object.entries(state.seen)) if (day < cutoff) delete state.seen[acc];
state.runs.push(run);
state.runs = state.runs.slice(-200);

return [
  ...alerts.map(a => ({ json: a })),
  { json: { type: 'summary', ...run, runsSoFar: state.runs.length,
            matchesSoFar: state.runs.reduce((s, r) => s + r.matched, 0),
            errorsSoFar: state.runs.reduce((s, r) => s + r.errors, 0) } },
];
