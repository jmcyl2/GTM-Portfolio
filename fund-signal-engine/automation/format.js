// n8n Code node: "Format Slack messages" (mode: Run Once for All Items).
// One message per matched filing, plus a daily summary so quiet days still
// prove the job ran.

const money = v => (/^\d+$/.test(v || '') ? '$' + (Number(v) / 1e6).toFixed(1) + 'M' : 'amount not stated');
const day = d => `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}`;
const items = $input.all().map(i => i.json);
const out = [];

// One message per manager per filing day, listing every new fund it filed.
const groups = {};
for (const a of items.filter(a => a.type === 'alert')) (groups[`${a.crd}|${a.filed}`] ||= []).push(a);

for (const group of Object.values(groups)) {
  const a = group[0];
  const priority = a.tier === 'A' || a.tier === 'B';
  const funds = group.map(g => `• ${g.issuer} (${g.fundType}, ${money(g.amount)}) <${g.filingUrl}|filing>`);
  const lines = [
    `${priority ? ':rotating_light: *Priority*' : ':eyes: *Watchlist*'}: *${a.manager || a.matchedOn}* filed `
      + `${group.length === 1 ? 'a new fund' : `${group.length} new funds`} on ${day(a.filed)}`,
    ...funds,
    `*Why it matters:* this manager runs its existing PE/RE funds without an outside administrator`
      + (priority ? `. Tier ${a.tier}${a.score != null ? `, v2 score ${(a.score * 100).toFixed(1)}%` : ''}`
                    + `${a.shortlist ? ', on the outreach shortlist' : ''}.` : '.'),
  ];
  if (a.contact) lines.push(`*Contact:* ${a.contact}${a.title ? ` (${a.title})` : ''}`);
  if (a.opener) lines.push(`*Draft opener:*\n>${a.opener.replace(/\n/g, '\n>')}`);
  lines.push(`<${a.adviserUrl}|SEC adviser profile> · matched on "${a.matchedOn}"`);
  out.push({ json: { slack: { text: lines.join('\n') } } });
}

for (const a of items.filter(a => a.type === 'summary')) {
  const days = a.daysChecked.length ? a.daysChecked.map(day).join(', ') : 'none due';
  out.push({ json: { slack: { text:
    `:white_check_mark: Daily scan done. Days: ${days}. Form D filings checked: ${a.formD}, `
    + `fund offerings: ${a.funds}, matches: *${a.matched}* (${Object.keys(groups).length} alert${Object.keys(groups).length === 1 ? '' : 's'}), errors: ${a.errors}`
    + (a.deferred ? `, deferred to next run: ${a.deferred}` : '')
    + (a.noIndexDays.length ? `, no SEC index (holiday?): ${a.noIndexDays.map(day).join(', ')}` : '')
    + `. Run #${a.runsSoFar}: ${a.matchesSoFar} matches and ${a.errorsSoFar} errors so far.` } } });
}
return out;
