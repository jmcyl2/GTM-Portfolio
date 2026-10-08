// n8n Code node: "Match against self-administered managers" (mode: Run Once for All Items).
//
// Input: one item per filing from the HTTP Request node (the Form D XML in
// `xml`, or an error item if the fetch failed after its retries). Keeps fund
// offerings whose general partner, manager or fund name matches a known
// self-administered manager, marks filings as seen, advances the scan cursor,
// and emits the alerts plus one summary item. The matching list is injected
// when the private workflow is generated; the public copy ships it empty.

const LOOKUP = __LOOKUP__;      // { normalisedName: crd }
const MANAGERS = __MANAGERS__;  // { crd: { manager, tier, score, shortlist, contact, title, opener } }

const state = $getWorkflowStaticData('global');
state.seen = state.seen || {};
state.runs = state.runs || [];
const run = state.pendingRun || { daysChecked: [], noIndexDays: [], indexErrors: 0, listed: 0, deferredDays: [] };
delete state.pendingRun;

const SUFFIX = /\b(LLC|L L C|LP|L P|LLLP|INC|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|THE)\b/g;
const norm = s => String(s || '').toUpperCase().replace(/[^A-Z0-9 ]/g, ' ').replace(SUFFIX, ' ').split(/\s+/).filter(Boolean).join(' ');
const tag = (xml, name) => { const m = xml.match(new RegExp(`<${name}>([\\s\\S]*?)</${name}>`)); return m ? m[1].trim() : ''; };
const FUND_TYPES = ['Private Equity Fund', 'Other Investment Fund'];
const RE_GROUPS = ['Other Real Estate', 'Commercial', 'Residential', 'REITS and Finance'];

const listed = $('List new Form D filings').all();
const results = $input.all();
const failedDays = new Set(run.deferredDays);
const alerts = [];
Object.assign(run, { formD: 0, funds: 0, matched: 0, errors: run.indexErrors });

results.forEach((item, i) => {
  const f = listed[item.pairedItem?.item ?? i]?.json;
  if (!f || !f.accession) return;  // the empty item on a day with nothing to fetch
  run.formD++;
  const xml = typeof item.json.xml === 'string' ? item.json.xml : '';
  if (!xml.includes('<edgarSubmission')) { run.errors++; failedDays.add(f.day); return; }
  state.seen[f.accession] = f.day;

  const fundType = tag(xml, 'investmentFundType');
  const industry = tag(xml, 'industryGroupType');
  if (!FUND_TYPES.includes(fundType) && !RE_GROUPS.includes(industry)) return;
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
  const folder = `https://www.sec.gov/Archives/edgar/data/${f.cik}/${f.accession.replace(/-/g, '')}/`;
  alerts.push({ type: 'alert', filed: f.day, accession: f.accession, issuer, matchedOn,
                fundType: fundType || industry, amount: tag(xml, 'totalOfferingAmount'),
                crd, ...(MANAGERS[crd] || {}), filingUrl: folder,
                adviserUrl: `https://adviserinfo.sec.gov/firm/summary/${crd}` });
});

// Advance the cursor past every checked day whose filings were all processed.
for (const day of [...run.daysChecked].sort()) {
  if (failedDays.has(day)) break;
  state.lastScanned = day;
}
const cutoff = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10).replace(/-/g, '');
for (const [acc, day] of Object.entries(state.seen)) if (day < cutoff) delete state.seen[acc];
state.runs.push(run);
state.runs = state.runs.slice(-200);

return [
  ...alerts.map(a => ({ json: a })),
  { json: { type: 'summary', ...run, deferred: run.deferredDays.length,
            runsSoFar: state.runs.length,
            matchesSoFar: state.runs.reduce((s, r) => s + (r.matched || 0), 0),
            errorsSoFar: state.runs.reduce((s, r) => s + (r.errors || 0), 0) } },
];
