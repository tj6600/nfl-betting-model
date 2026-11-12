const D = JSON.parse(document.getElementById('td-data').textContent);
const TD = D.players.map((p) => ({ ...p, opps: p.carries + p.targets, edge: p.book == null ? null : p.model - p.book }));
const YD = D.yards || [];
const headStep = (p) => {
  const v = p.steps.filter((x) => x.cat === 'Value'); if (v.length) return v.reduce((a, b) => (b.ev > a.ev ? b : a));
  const l = p.steps.filter((x) => x.cat === 'Likely hit'); if (l.length) return l[l.length - 1];
  return p.steps.reduce((a, b) => (Math.abs(b.p - 0.5) < Math.abs(a.p - 0.5) ? b : a));
};
const MS = (D.milestones || []).map((p) => { const h = headStep(p); return { ...p, head: h, p: h.p, ev: Math.max(...p.steps.map((x) => x.ev)) }; });
const state = { tab: 'td', cat: 'all', game: 'all', win: 'all', pos: 'all', q: '', sort: null, small: true, open: null };
const TABS = [['td', 'Touchdowns'], ['rush', 'Rushing yards'], ['rec', 'Receiving yards']].concat(MS.length ? [['ms', 'Milestones']] : []).concat(D.legs ? [['parlay', 'Parlay builder']] : []).concat(D.blind ? [['test', `Week ${D.blind.week} test`]] : []);
const PILL = { 'TD value': 'value', 'Value': 'value', 'Most likely': 'likely', 'Check role': 'check', 'Likely hit': 'likely' };
const fmtOdds = (o) => o == null ? '—' : (o > 0 ? '+' : '') + o;
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const DAY = { Thursday: 'Thu', Sunday: 'Sun', Monday: 'Mon', Saturday: 'Sat', Friday: 'Fri' };
const clock = (t) => { const [h, m] = t.split(':').map(Number); return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${h >= 12 ? 'PM' : 'AM'}`; };
const pct = (v) => (v * 100).toFixed(0) + '%';
const games = [...new Map(TD.map((p) => [p.game, p])).values()].sort((a, b) => (a.day + a.time).localeCompare(b.day + b.time));
const impOf = Object.fromEntries(TD.map((p) => [p.team, p.imp]));

const CONF = {
  td: {
    lede: 'Each player\'s chance to score a rushing or receiving touchdown, set against sportsbook odds. Pick a game, filter by position, or open a player to see why.',
    cats: [['all', 'All players'], ['TD value', 'TD value'], ['Most likely', 'Most likely'], ['Check role', 'Check role']],
    pos: ['all', 'RB', 'WR', 'TE', 'QB'],
    sorts: [['model', 'Sort: chance to score'], ['edge', 'Sort: model minus book'], ['ev', 'Sort: expected value'], ['odds', 'Sort: longest odds']],
    legend: '<span><i style="width:22px;height:8px;border-radius:4px;background:var(--turf)"></i>Model chance</span><span><i style="width:2px;height:14px;background:var(--tick)"></i>Book chance (includes their margin)</span><span><span class="pill value">TD value</span></span><span><span class="pill likely">Most likely</span></span><span><span class="pill check">Check role</span></span>',
    foot: 'The touchdown model learns from each player\'s recent red-zone and goal-line work, carries and targets, his share among teammates at his position, games he missed, the opponent\'s touchdowns allowed to his position, and his team\'s expected points. It was well calibrated on 2024 and 2025 games, but there are no past touchdown odds to test it against. "Small roles" means fewer than 3 carries plus targets a game; long odds there produce big but unrealistic EV numbers. The depth chart is shown and flags Check role when it has moved a player down.',
  },
  rush: {
    lede: 'Each player\'s projected rushing yards against the over/under lines. The bar shows the model\'s likely range, its median and the line. Open a player to see every book\'s line.',
    cats: [['all', 'All players'], ['Value', 'Value'], ['Check role', 'Check role']],
    pos: ['all', 'RB', 'WR'],
    sorts: [['ev', 'Sort: expected value'], ['chance', 'Sort: chance of lean'], ['gap', 'Sort: projection vs line'], ['line', 'Sort: line']],
  },
  rec: {
    lede: 'Each player\'s projected receiving yards against the over/under lines. The bar shows the model\'s likely range, its median and the line. Open a player to see every book\'s line.',
    cats: [['all', 'All players'], ['Value', 'Value'], ['Check role', 'Check role']],
    pos: ['all', 'WR', 'TE', 'RB'],
    sorts: [['ev', 'Sort: expected value'], ['chance', 'Sort: chance of lean'], ['gap', 'Sort: projection vs line'], ['line', 'Sort: line']],
  },
  ms: {
    lede: 'Chances to reach yardage milestones, like 40+ receiving or 50+ rushing, priced against the books\' alternate lines. Each chip is one milestone and its chance. Open a player for every milestone with its best price.',
    cats: [['all', 'All players'], ['Likely hit', 'Likely hit'], ['Value', 'Value']],
    pos: ['all', 'rush', 'rec'],
    sorts: [['sure', 'Sort: surest hit'], ['ev', 'Sort: best EV'], ['median', 'Sort: projected yards']],
  },
};
const SEG = { all: 'All', rush: 'Rushing', rec: 'Receiving' };
const MS_LEGEND = '<span><i style="width:22px;height:12px;border-radius:4px;background:color-mix(in srgb, var(--turf) 70%, transparent)"></i>Darker chip = likelier</span><span><span class="pill likely">Likely hit</span> 80%+ chance</span><span><span class="pill value">Value</span> 5%+ EV at the best price</span>';
const MS_FOOT = 'Each chance blends the yards model 50/50 with the books\' own chance (their alternate-line price with an estimated 6% margin taken out). Likely hit means 80%+ for a regular with no role flags. Expect most likely hits to show a small negative EV: books price heavy favorites like -400 to -1800 with extra margin, so a likely hit is safe for a parlay leg but rarely value on its own. Value needs 5%+ EV and at least two books offering the milestone.';
const YARDS_LEGEND = '<span><i style="width:26px;height:8px;border-radius:3px;background:var(--bar)"></i>Middle half of outcomes</span><span><i style="width:3px;height:14px;background:var(--turf)"></i>Model median</span><span><i style="width:2px;height:14px;background:var(--tick)"></i>Book line</span><span><span class="pill value">Value</span></span><span><span class="pill check">Check role</span></span>';
const YARDS_FOOT = 'The yards model projects each player from his recent yards and usage, his recent role, his team\'s expected points and margin (teams that lead run more), and the opponent\'s yards allowed to his position. It beat each player\'s recent average on 2024 and 2025 games, and its over/under chances were well calibrated there. Yards are lopsided: a few big games pull the average up, so the median is usually below the average and unders win a bit more often than averages suggest. There are no past prop lines to test against, so the chance shown blends the model 50/50 with the books\' no-vig chance. Value needs 57%+ and 5%+ EV at the best line. Check role means he missed his last game, the depth chart moved him down, or the model and line are more than 25% apart (the books likely know something). "Small roles" means under 8 carries or 3 targets a game.';

function renderTabs() {
  const box = document.getElementById('tabs'); box.replaceChildren();
  for (const [k, label] of TABS) {
    const b = el('button', 'tab', label); b.type = 'button'; b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', state.tab === k);
    b.onclick = () => { if (state.tab === k) return; state.tab = k; state.cat = 'all'; state.pos = 'all'; state.sort = null; state.open = null; render(); };
    box.append(b);
  }
}
function renderGames() {
  const box = document.getElementById('games'); box.replaceChildren();
  const all = el('button', 'game'); all.type = 'button'; all.append(el('span', 'm', 'All games'), el('span', 't', `${games.length} games`));
  all.setAttribute('aria-pressed', state.game === 'all'); all.onclick = () => { state.game = 'all'; state.win = 'all'; state.open = null; render(); };
  box.append(all);
  for (const g of games) {
    const b = el('button', 'game'); b.type = 'button';
    b.append(el('span', 'm', `${g.away} @ ${g.home}`), el('span', 't', `${DAY[g.weekday] || g.weekday} ${clock(g.time)} ET`));
    b.setAttribute('aria-pressed', state.game === g.game);
    b.onclick = () => { state.game = state.game === g.game ? 'all' : g.game; state.win = 'all'; state.open = null; render(); };
    box.append(b);
  }
}
function renderCats(base) {
  const box = document.getElementById('cats'); box.replaceChildren();
  for (const [k, label] of CONF[state.tab].cats) {
    const n = k === 'all' ? base.length : base.filter((p) => p.cat === k).length;
    const b = el('button', 'chip'); b.type = 'button'; b.append(el('span', null, label), el('b', null, String(n)));
    b.setAttribute('aria-pressed', state.cat === k); b.onclick = () => { state.cat = k; state.open = null; render(); };
    box.append(b);
  }
}
function renderPos() {
  const box = document.getElementById('pos'); box.replaceChildren();
  for (const k of CONF[state.tab].pos) {
    const b = el('button', null, SEG[k] && (state.tab === 'ms' || k === 'all') ? SEG[k] : k); b.type = 'button';
    b.setAttribute('aria-pressed', state.pos === k); b.onclick = () => { state.pos = k; state.open = null; render(); };
    box.append(b);
  }
}
function renderSort() {
  const sel = document.getElementById('sort'); const opts = CONF[state.tab].sorts;
  if (!state.sort) state.sort = opts[0][0];
  sel.replaceChildren(...opts.map(([v, l]) => { const o = el('option', null, l); o.value = v; return o; }));
  sel.value = state.sort;
}
const SORTS = {
  model: (a, b) => b.model - a.model,
  edge: (a, b) => (b.edge ?? -999) - (a.edge ?? -999),
  ev: (a, b) => (b.ev ?? -999) - (a.ev ?? -999),
  odds: (a, b) => (b.best ?? -1e9) - (a.best ?? -1e9),
  chance: (a, b) => b.p - a.p,
  gap: (a, b) => Math.abs(b.gap) - Math.abs(a.gap),
  line: (a, b) => b.line - a.line,
  sure: (a, b) => (b.cat === 'Likely hit') - (a.cat === 'Likely hit') || b.head.m * (b.cat ? 1 : 0) - a.head.m * (a.cat ? 1 : 0) || b.p - a.p,
  median: (a, b) => b.median - a.median,
};
function filtered() {
  const q = state.q.trim().toLowerCase();
  const src = state.tab === 'td' ? TD : state.tab === 'ms' ? MS : YD.filter((p) => p.market === state.tab);
  const base = src.filter((p) => (state.game === 'all' || p.game === state.game)
    && (state.pos === 'all' || (state.tab === 'ms' ? p.market : p.pos) === state.pos)
    && (!state.small || p.cat || (state.tab === 'td' ? p.opps >= 3 : p.regular))
    && (!q || p.name.toLowerCase().includes(q) || p.team.toLowerCase() === q || p.opp.toLowerCase() === q));
  return { base, list: base.filter((p) => state.cat === 'all' || p.cat === state.cat).sort(SORTS[state.sort] || SORTS.ev) };
}
function who(p) {
  const w = el('div', 'who');
  const dc = p.depth == null ? '' : ` · ${p.pos}${p.depth} on depth chart${p.depthPrev != null && p.depthPrev !== p.depth ? ` (was ${p.pos}${p.depthPrev})` : ''}`;
  w.append(el('span', 'n', p.name), el('span', 's', `${p.pos} · ${p.team} vs ${p.opp}${dc}${p.missed ? ` · missed last ${p.missed}` : ''}`));
  if (p.cat) { const pill = el('span', `pill ${PILL[p.cat]}`, p.cat); pill.style.alignSelf = 'flex-start'; pill.style.marginTop = '3px'; w.append(pill); }
  return w;
}
function rowShell(p, parts, detailFn) {
  const frag = document.createDocumentFragment();
  const r = el('button', 'row'); r.type = 'button'; r.setAttribute('aria-expanded', state.open === p.id);
  r.append(...parts);
  r.onclick = () => { state.open = state.open === p.id ? null : p.id; render(); };
  frag.append(r);
  if (state.open === p.id) frag.append(detailFn(p));
  return frag;
}
function stats(pairs) {
  const st = el('div', 'stats');
  for (const [v, k] of pairs) { const x = el('div', 'stat'); x.append(el('b', null, v), el('span', null, k)); st.append(x); }
  return st;
}
// ---- touchdowns ----
function tdRow(p) {
  const m = el('div', 'meter'); const tr = el('div', 'track'); const f = el('div', 'fill'); f.style.width = Math.min(100, p.model) + '%'; tr.append(f);
  if (p.book != null) { const t = el('div', 'tick'); t.style.left = `calc(${Math.min(100, p.book)}% - 1px)`; tr.append(t); }
  const l = el('div', 'l'); const lm = el('span'); lm.append(el('b', null, p.model.toFixed(0) + '%'), document.createTextNode(' model'));
  l.append(lm, el('span', null, p.book == null ? 'no line' : `books ${p.book.toFixed(0)}%`)); m.append(tr, l);
  const pr = el('div', 'price'); pr.append(el('span', 'o', fmtOdds(p.best)));
  const small = p.opps < 3;
  pr.append(el('span', 'e ' + (p.ev == null || small ? 'dim' : p.ev >= 0 ? 'pos' : 'neg'), p.ev == null ? '' : small ? 'small role' : `EV ${p.ev > 0 ? '+' : ''}${p.ev.toFixed(0)}%`));
  return rowShell(p, [who(p), m, pr], tdDetail);
}
// ---- season game log (opens from any player) ----
const LOGS = D.logs || {};
function logButton(pid, ctx) {
  if (!LOGS[pid]) return null;
  const b = el('button', 'logbtn', 'Season game log'); b.type = 'button';
  b.onclick = (e) => { e.stopPropagation(); showLog(pid, ctx); }; return b;
}
function movePanel(L) {
  const m = L.move; const box = el('div', 'move ' + (m.verdict === 'benefits' ? 'up' : m.verdict === 'falls' ? 'down' : 'flat'));
  const posName = { WR: 'receivers', TE: 'tight ends', RB: 'running backs' }[m.pos] || m.pos;
  const pc = (o, n) => (o > 0 ? `${n >= o ? '+' : ''}${Math.round((n / o - 1) * 100)}%` : '');
  box.append(el('b', null, `New team: ${m.frm} → ${m.to} (${m.season} week ${m.week})`));
  const main = m.pos === 'RB' ? `${m.ctx.carries[1] + m.ctx.targets[1] > 0 ? (m.ctx.carries[1] + m.ctx.targets[1]).toFixed(1) : '0'} carries + targets a game to ${posName} vs ${(m.ctx.carries[0] + m.ctx.targets[0]).toFixed(1)} in ${m.frm}`
    : `${m.ctx.targets[1].toFixed(1)} targets a game to ${posName} vs ${m.ctx.targets[0].toFixed(1)} in ${m.frm}`;
  box.append(el('span', null, `Scheme fit: ${m.verdict === 'benefits' ? 'the new offense feeds his position more' : m.verdict === 'falls' ? 'the new offense feeds his position less' : 'the new offense uses his position about the same'} (${main}, ${m.chg >= 0 ? '+' : ''}${Math.round(m.chg * 100)}%).`));
  const k = m.pos === 'RB' ? 'carries' : 'targets'; const yk = m.pos === 'RB' ? 'rush_yds' : 'rec_yds';
  const own = (m.his[k][0] > 0 ? m.his[k][1] / m.his[k][0] - 1 : 0);
  box.append(el('span', null, `His own ${k}: ${m.his[k][0]} a game in his last ${m.n_old} with ${m.frm} → ${m.his[k][1]} in ${m.n_new} with ${m.to} (${m.his[yk][0]} → ${m.his[yk][1]} ${m.pos === 'RB' ? 'rush' : 'rec'} yds).`));
  if (Math.abs(own - m.chg) > 0.3) box.append(el('span', 'dim', own > m.chg ? 'He is getting far more than the offense change explains, so his role in it has grown. The model still counts his old games, so it may underrate him.' : 'He is getting far less than the offense change explains, so his role in it has shrunk. The model still counts his old games, so it may overrate him.'));
  return box;
}
function showLog(pid, ctx) {
  const L = LOGS[pid]; const prev = document.activeElement;
  const ov = el('div', 'overlay'); const pn = el('div', 'logpanel'); pn.setAttribute('role', 'dialog'); pn.setAttribute('aria-modal', 'true'); pn.setAttribute('aria-label', `${L.name} game log`);
  const close = () => { ov.remove(); document.removeEventListener('keydown', esc); if (prev) prev.focus(); };
  const esc = (e) => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', esc); ov.onclick = (e) => { if (e.target === ov) close(); };
  const hd = el('div', 'loghead'); const t = el('div'); t.append(el('h2', null, L.name), el('span', 'dim', `${L.pos} · ${L.team} · ${D.season} regular season`));
  const x = el('button', 'x', '×'); x.type = 'button'; x.setAttribute('aria-label', 'Close'); x.onclick = close; hd.append(t, x); pn.append(hd);
  if (L.move) pn.append(movePanel(L));
  const played = L.g.filter((r) => r[3] != null); const n = played.length || 1;
  const sum = (i) => played.reduce((a, r) => a + r[i], 0);
  const st = stats([[String(played.length), `games played${L.g.length > played.length ? ` (${L.g.length - played.length} missed)` : ''}`], [(sum(3) / n).toFixed(1), 'carries a game'], [(sum(4) / n).toFixed(0), 'rush yds a game'],
    [(sum(5) / n).toFixed(1), 'targets a game'], [(sum(7) / n).toFixed(0), 'rec yds a game'], [String(sum(8)), `TDs (${(sum(8) / n).toFixed(2)} a game)`]]);
  st.classList.add('pad'); pn.append(st);
  // how this bet would have done in each game this season
  let hitFn = null; let hitLabel = '';
  if (ctx && ctx.kind === 'td') { hitFn = (r) => r[8] > 0; hitLabel = 'Scored'; }
  else if (ctx && ctx.line != null) {
    const i = ctx.kind === 'rush' ? 4 : 7; const over = ctx.side !== 'Under';
    hitFn = (r) => (over ? r[i] > ctx.line : r[i] < ctx.line); hitLabel = `${over ? 'Over' : 'Under'} ${ctx.line}`;
  }
  if (hitFn) {
    const h = played.filter(hitFn).length;
    pn.append(el('p', 'loghit', `${ctx.kind === 'td' ? 'Scored a TD' : `${hitLabel} ${ctx.kind === 'rush' ? 'rushing' : 'receiving'} yds hit`} in ${h} of ${played.length} games this season (${played.length ? Math.round(100 * h / played.length) : 0}%).`));
  }
  const wrap = el('div', 'tablewrap'); const tb = el('table', 'res');
  const th = el('thead'); const hr = el('tr');
  for (const [tx, c] of [['Wk'], ['Opp'], ['Car', 'num'], ['Rush yds', 'num'], ['Tgt', 'num'], ['Rec', 'num'], ['Rec yds', 'num'], ['TD', 'num']].concat(hitFn ? [[hitLabel]] : [])) hr.append(el('th', c || null, tx));
  th.append(hr); tb.append(th); const tbody = el('tbody');
  for (const r of L.g) {
    const tr = el('tr'); tr.append(el('td', null, String(r[0])), el('td', null, `${r[2] ? '@' : 'vs'} ${r[1]}`));
    if (r[3] == null) { const td = el('td', 'dim', 'Did not play'); td.colSpan = 6 + (hitFn ? 1 : 0); tr.append(td); }
    else {
      for (const i of [3, 4, 5, 6, 7, 8]) tr.append(el('td', 'num', String(r[i])));
      if (hitFn) { const ok = hitFn(r); tr.append(el('td', ok ? 'pos' : 'neg', ok ? 'Hit' : 'Miss')); }
    }
    tbody.append(tr);
  }
  tb.append(tbody); wrap.append(tb); pn.append(wrap);
  pn.append(el('p', 'note logfoot', `${L.move ? 'Scheme fit compares how many targets and carries each offense has given his position lately (recency-weighted, nudged toward league average). As a model input it did not improve 2024-25 backtests, so it is shown for judgment only. ' : ''}From play-by-play data. Past games show his range, not a forecast: role changes, injuries and the opponent matter, and the model weighs his recent games more.`));
  ov.append(pn); document.body.append(ov); x.focus();
}
function tdDetail(p) {
  const d = el('div', 'detail');
  const a = el('div'); a.append(el('h3', null, 'Recent usage'), stats([[p.carries.toFixed(1), 'carries a game'], [p.targets.toFixed(1), 'targets a game'], [p.tdpg.toFixed(2), 'TDs a game'],
    [p.gl + '%', 'goal-line share'], [p.rz + '%', 'red-zone share'], [p.room + '%', 'share at his position']]));
  const b = el('div'); b.append(el('h3', null, 'Why'), el('p', 'why', p.why));
  const ctx = el('p', 'note', `${p.opp} allows ${Math.abs(p.deftd).toFixed(2)} ${p.deftd >= 0 ? 'more' : 'fewer'} TDs a game than average to ${p.pos}s. Last game he had ${p.last}% of his team's touches.`);
  ctx.style.marginTop = '8px'; b.append(ctx);
  const c = el('div'); c.append(el('h3', null, 'Prices by book'));
  const bk = el('div', 'books');
  if (!p.books.length) bk.append(el('span', 'dim', 'No book is offering this player yet.'));
  p.books.forEach((x, i) => { const r = el('div', i === 0 ? 'best' : null); r.append(el('span', null, x.b), el('span', null, fmtOdds(x.p))); bk.append(r); });
  c.append(bk);
  if (p.books.length) {
    const fair = p.model / 100; const need = fair >= .5 ? -Math.round(100 * fair / (1 - fair)) : Math.round(100 * (1 - fair) / fair);
    const t = el('p', 'note', `The model's fair price is ${fmtOdds(need)}. Any price longer than that is value if the model is right.`); t.style.marginTop = '8px'; c.append(t);
  }
  const lb = logButton(p.id, { kind: 'td' }); if (lb) a.append(lb);
  d.append(a, b, c); return d;
}
// ---- yards ----
function ydRow(p) {
  const m = el('div', 'meter'); const tr = el('div', 'track');
  const max = Math.max(p.q75, p.line, p.projection) * 1.15; const x = (v) => Math.max(0, Math.min(100, (v / max) * 100));
  const rg = el('div', 'range'); rg.style.left = x(p.q25) + '%'; rg.style.width = (x(p.q75) - x(p.q25)) + '%';
  const mk = el('div', 'mark'); mk.style.left = `calc(${x(p.median)}% - 1.5px)`;
  const ln = el('div', 'line'); ln.style.left = `calc(${x(p.line)}% - 1px)`;
  tr.append(rg, mk, ln);
  const l = el('div', 'l'); const lm = el('span'); lm.append(el('b', null, p.median.toFixed(0)), document.createTextNode(` median · ${p.projection.toFixed(0)} avg`));
  l.append(lm, el('span', null, `line ${p.line}`)); m.append(tr, l);
  const pr = el('div', 'price'); const s = p.sides[p.lean];
  const sd = el('span', 'side ' + p.lean.toLowerCase(), `${p.lean} ${s.line}`);
  pr.append(sd, el('span', 'e', `${fmtOdds(s.price)} · ${pct(s.p)}`),
    el('span', 'e ' + (s.ev >= 0 ? 'pos' : 'neg'), `EV ${s.ev > 0 ? '+' : ''}${(s.ev * 100).toFixed(0)}%`));
  return rowShell(p, [who(p), m, pr], ydDetail);
}
function ydDetail(p) {
  const d = el('div', 'detail'); const rush = p.market === 'rush';
  const a = el('div'); a.append(el('h3', null, 'Recent form'), stats([[p.recent.toFixed(0), `${rush ? 'rushing' : 'receiving'} yds a game`],
    [(rush ? p.carries : p.targets).toFixed(1), rush ? 'carries a game' : 'targets a game'], [`${p.q25.toFixed(0)}–${p.q75.toFixed(0)}`, 'likely range'],
    [p.imp.toFixed(1), 'team expected pts'], [(p.margin > 0 ? '+' : '') + p.margin.toFixed(1), 'expected margin'], [(p.defyds > 0 ? '+' : '') + p.defyds.toFixed(0), `yds vs avg allowed to ${p.pos}s`]]));
  const b = el('div'); b.append(el('h3', null, 'Chances'));
  const ch = el('div', 'books');
  for (const side of ['Over', 'Under']) {
    const s = p.sides[side]; if (!s) continue;
    const r = el('div', side === p.lean ? 'best' : null);
    r.append(el('span', null, `${side} ${s.line} (${s.book})`), el('span', null, `model ${pct(s.model)} · books ${pct(s.mkt)} · used ${pct(s.p)}`));
    ch.append(r);
  }
  b.append(ch);
  if (p.note) { const n = el('p', 'note', p.note); n.style.marginTop = '8px'; b.append(n); }
  const c = el('div'); c.append(el('h3', null, 'Lines by book'));
  const bk = el('div', 'books');
  for (const x of p.books) {
    const r = el('div'); r.append(el('span', null, x.b), el('span', null, `${x.o ? `O ${x.o.pt} ${fmtOdds(x.o.pr)}` : ''}${x.o && x.u ? '  ·  ' : ''}${x.u ? `U ${x.u.pt} ${fmtOdds(x.u.pr)}` : ''}`));
    bk.append(r);
  }
  c.append(bk);
  const lb = logButton(p.pid, { kind: p.market, line: p.line, side: p.lean }); if (lb) a.append(lb);
  d.append(a, b, c); return d;
}
// ---- milestones ----
const mlabel = (p, x) => `${x.m}+ ${p.market === 'rush' ? 'rush' : 'rec'}`;
function chip(x, hot) {
  const c = el('span', 'step' + (hot ? ' hot' : '')); c.style.setProperty('--a', Math.round(12 + x.p * 70) + '%');
  c.append(el('b', null, `${x.m}+`), document.createTextNode(' ' + pct(x.p))); return c;
}
function msRow(p) {
  const lad = el('div', 'ladder');
  let pts = p.steps.filter((x) => x.p >= 0.08 && x.p <= 0.97);
  if (pts.length > 7) { const k = (pts.length - 1) / 6; pts = [...new Set([0, 1, 2, 3, 4, 5, 6].map((i) => Math.round(i * k)))].map((i) => pts[i]); }
  if (!pts.includes(p.head)) pts = [...pts, p.head].sort((a, b) => a.m - b.m);
  pts.forEach((x) => lad.append(chip(x, x === p.head)));
  const m = el('div', 'meter'); m.append(lad, el('div', 'l', `median ${p.median.toFixed(0)} yds${p.line != null ? ` · main line ${p.line}` : ''}`));
  const pr = el('div', 'price'); const h = p.head;
  pr.append(el('span', 'side over', mlabel(p, h)), el('span', 'e', `${fmtOdds(h.price)} · ${pct(h.p)}`),
    el('span', 'e ' + (h.ev >= 0 ? 'pos' : 'neg'), `EV ${h.ev > 0 ? '+' : ''}${(h.ev * 100).toFixed(0)}%`));
  return rowShell(p, [who(p), m, pr], msDetail);
}
function msDetail(p) {
  const d = el('div', 'detail one');
  const wrap = el('div', 'tablewrap'); const tb = el('table', 'res');
  const th = el('thead'); const hr = el('tr');
  for (const [t, c] of [['Milestone'], ['Chance', 'num'], ['Model', 'num'], ['Books', 'num'], ['Fair price', 'num'], ['Best price', 'num'], ['Book'], ['EV', 'num'], ['']]) hr.append(el('th', c || null, t));
  th.append(hr); tb.append(th);
  const tbody = el('tbody');
  for (const x of p.steps) {
    const tr = el('tr', x === p.head ? 'hl' : null);
    const fair = x.p >= .5 ? -Math.round(100 * x.p / (1 - x.p)) : Math.round(100 * (1 - x.p) / x.p);
    const cells = [[mlabel(p, x)], [pct(x.p), 'num'], [pct(x.model), 'num dim'], [pct(x.book), 'num dim'], [fmtOdds(fair), 'num dim'], [fmtOdds(x.price), 'num'], [`${x.bk}${x.n > 1 ? ` +${x.n - 1}` : ''}`, 'dim'],
      [`${x.ev > 0 ? '+' : ''}${(x.ev * 100).toFixed(0)}%`, 'num ' + (x.ev >= 0 ? 'pos' : 'neg')]];
    for (const [v, c] of cells) tr.append(el('td', c || null, v));
    const td = el('td'); if (x.cat) td.append(el('span', `pill ${PILL[x.cat]}`, x.cat)); tr.append(td);
    tbody.append(tr);
  }
  tb.append(tbody); wrap.append(tb);
  const n = el('p', 'note', `Model projects ${p.projection.toFixed(0)} yards on average and ${p.median.toFixed(0)} at the median. "Model" is the yards model alone, "Books" is their chance with the margin removed, and "Chance" is the blend used. Fair price is what the blended chance is worth; a best price longer than it is value.${p.risky ? ' Role flag: he missed his last game, moved down the depth chart, or the model and books disagree a lot, so he is kept out of Likely hit and Value.' : ''}`);
  n.style.marginTop = '8px';
  const lb = logButton(p.pid, { kind: p.market, line: p.head.m - 0.5, side: 'Over' });
  d.append(wrap, n); if (lb) d.append(lb); return d;
}
function column(title, sub, list) {
  const c = el('section', 'col'); const h = el('div', 'colhead'); h.append(el('h2', null, title), el('span', null, sub)); c.append(h);
  if (!list.length) c.append(el('div', 'empty', 'No players match these filters. Try All players or turn off Hide small roles.'));
  list.forEach((p) => c.append(state.tab === 'td' ? tdRow(p) : state.tab === 'ms' ? msRow(p) : ydRow(p)));
  return c;
}
function renderTest() {
  const B = D.blind;
  document.getElementById('lede').textContent = `Blind test on week ${B.week}: both models were fit only on games before week ${B.week}, priced the players that week, and were then checked against what happened. Players who didn't play are left out, since books void those bets.`;
  for (const id of ['cats', 'games', 'legend']) document.getElementById(id).replaceChildren();
  document.querySelector('.bar').style.display = 'none';
  const board = document.getElementById('board'); board.replaceChildren(); board.className = 'cols';
  const tiles = el('div', 'tiles');
  for (const r of B.summary) {
    const t = el('div', 'tile');
    t.append(el('span', 'k', `${r.test} · ${r.group}`), el('span', 'big', `${r.right}–${r.wrong}`),
      el('span', 's', `${(r.hit * 100).toFixed(0)}% right · model expected ${r.expected} of ${r.picks}`));
    tiles.append(t);
  }
  board.append(tiles);
  const mk = (title, sub, rows, cells) => {
    const c = el('section', 'col'); const h = el('div', 'colhead'); h.append(el('h2', null, title), el('span', null, sub)); c.append(h);
    const wrap = el('div', 'tablewrap'); const tb = el('table', 'res'); const tbody = el('tbody');
    for (const r of rows) { const tr = el('tr'); for (const [v, cls] of cells(r)) tr.append(el('td', cls || null, v)); tbody.append(tr); }
    tb.append(tbody); wrap.append(tb); c.append(wrap); return c;
  };
  board.append(mk('Touchdowns', 'players given 35%+', B.td, (r) => [[r.name], [`${r.pos} · ${r.team}`, 'dim'], [pct(r.p), 'num'], [r.right ? 'Scored' : 'No TD', r.right ? 'pos' : 'neg']]));
  board.append(mk('Yards leans', 'confident leans (57%+) vs stand-in line', B.yards, (r) => [[r.name], [`${r.market.split(' ')[0]} · ${r.team}`, 'dim'],
    [`${r.lean} ${r.line}`], [`proj ${r.proj.toFixed(0)}`, 'num dim'], [`actual ${r.actual.toFixed(0)}`, 'num'], [r.right ? 'Right' : 'Wrong', r.right ? 'pos' : 'neg']]));
  document.getElementById('foot').textContent = `There are no saved prop lines for week ${B.week}, so touchdowns are graded on whether the player scored, and yards are graded against a stand-in line: his season average before week ${B.week}, rounded to .5. Real books set yards lines a little below the average, because a few big games pull the average up, so the Under results here look better than they would against real lines. Treat this as a check that the chances are sensible. The real test is this week's picks, graded against real lines after the games.`;
}
// ---- parlay builder ----
const LEGS = D.legs || []; const LEG = Object.fromEntries(LEGS.map((l) => [l.id, l]));
const dec = (a) => (a > 0 ? 1 + a / 100 : 1 + 100 / -a);
const amer = (d) => (d >= 2 ? Math.round((d - 1) * 100) : -Math.round(100 / (d - 1)));
const PK = 'props-parlay-v2';
const PBOOKS = ['DraftKings'];
const ABBR = { DraftKings: 'DK', FanDuel: 'FD' };
const PS = { kind: 'all', mode: 'value', q: '', plus: true, clean: true, price: '', sort: 'edge', minp: 0.25, note: '', sel: {} };
try { PS.mode = localStorage.getItem('props-mode') === 'likely' ? 'likely' : 'value'; } catch (e) {}
// market of a leg, for the filter: game lines split into moneyline / spread / total
const mkt = (l) => (l.kind !== 'Game' ? l.kind : /moneyline/i.test(l.label) ? 'ML' : /^(Over|Under)/.test(l.label) ? 'Total' : 'Spread');
const MKTS = [['all', 'All'], ['ML', 'Moneyline'], ['Spread', 'Spread'], ['Total', 'Game total'], ['TD', 'TDs'], ['Rush', 'Rush yds'], ['Rec', 'Rec yds'], ['Milestone', 'Milestones']];
// one row per bet: both sides of an over/under or spread together, so either side can be picked
const GROUPS = Object.values(LEGS.reduce((acc, l) => { (acc[l.grp] = acc[l.grp] || { grp: l.grp, title: l.gt, kind: l.kind, sides: [] }).sides.push(l); return acc; }, {}))
  .map((g) => { g.sides.sort((a, b) => (a.sl === 'Over' ? -1 : b.sl === 'Over' ? 1 : 0)); g.flag = g.sides.map((x) => x.flag).find((f) => f && f !== 'season disagrees') || '';
    g.mkt = mkt(g.sides[0]); g.text = (g.title + ' ' + g.sides[0].game + ' ' + (g.sides[0].team || '')).toLowerCase(); return g; });
const pts = (e) => `${e > 0 ? '+' : ''}${(e * 100).toFixed(1)} pts`;
const pct1 = (v) => (v < 0.1 ? (v * 100).toFixed(1) : (v * 100).toFixed(0)) + '%';
let slip = []; try { slip = (JSON.parse(localStorage.getItem(PK) || '[]')).filter((id) => LEG[id]); } catch (e) { slip = []; }
const saveSlip = () => { try { localStorage.setItem(PK, JSON.stringify(slip)); } catch (e) { /* storage unavailable */ } };
const legName = (l) => (l.kind === 'Game' ? (/^(Over|Under)/.test(l.label) ? `${l.game} ${l.label}` : l.label) : `${l.who} ${l.label}`);
// a parlay sits at one book: price it at DraftKings and at FanDuel, keep the better payout (DraftKings on a tie)
function parlayMath(ids, priceOverride) {
  const ls = ids.map((i) => LEG[i]);
  const p = ls.reduce((a, l) => a * l.p, 1);
  const at = PBOOKS.filter((b) => ls.every((l) => l.offers[b] != null)).map((b) => ({ b, d: ls.reduce((a, l) => a * dec(l.offers[b]), 1) }));
  at.sort((x, y) => y.d - x.d || (x.b === 'DraftKings' ? -1 : 1));
  const book = at.length ? at[0].b : null; const other = at[1] || null;
  const dBook = at.length ? at[0].d : ls.reduce((a, l) => a * dec(l.price), 1);
  const d = priceOverride ? dec(priceOverride) : dBook;
  return { ls, p, d, dBook, book, other, ev: p * d - 1, be: 1 / d };
}
function warnings(ids) {
  const ls = ids.map((i) => LEG[i]); const w = [];
  const byGame = {}; ls.forEach((l) => { (byGame[l.game] = byGame[l.game] || []).push(l); });
  for (const [g, xs] of Object.entries(byGame)) if (xs.length > 1) w.push(['warn', `${xs.length} legs from ${g}. Same-game legs move together, and this math treats them as independent. Books also price same-game parlays differently.`]);
  const byKey = {}; ls.forEach((l) => { (byKey[l.key] = byKey[l.key] || []).push(l); });
  for (const xs of Object.values(byKey)) if (xs.length > 1) w.push(['bad', `${xs.map(legName).join(' and ')} are the same bet market twice. Most books won't allow it, and the chances aren't independent.`]);
  ls.filter((l) => l.ev < 0).forEach((l) => w.push(['bad', `${legName(l)} is negative EV on its own (${(l.ev * 100).toFixed(0)}%). It drags the whole parlay down.`]));
  ls.filter((l) => l.flag).forEach((l) => w.push(['warn', `${legName(l)}: ${l.flag === 'Check role' ? 'role flag (missed time, moved down the depth chart, or the model and books disagree a lot)' : l.flag === 'season disagrees' ? `this side has hit only ${l.season} games this season, so the model may be leaning on an old role` : 'small role, so the chance is less reliable'}.`]));
  ls.filter((l) => l.p < 0.25).forEach((l) => w.push(['warn', `${legName(l)} is a long shot (${pct1(l.p)}). Most of its EV rests on the model being right about a rare event, and it cuts the parlay's hit chance a lot.`]));
  if (!PBOOKS.some((b) => ls.every((l) => l.offers[b] != null))) {
    const only = ls.filter((l) => Object.keys(l.offers).length === 1).map((l) => `${legName(l)} (${Object.keys(l.offers)[0]} only)`);
    w.push(['bad', `No single book offers every leg${only.length ? ': ' + only.join(', ') : ''}. Remove it or pick DraftKings' own number for that bet.`]);
  }
  return w;
}
function verdict(m, n, ws) {
  if (!n) return null;
  if (!m.book) return ['bad', 'Can\'t place as one parlay', 'Not every leg is offered at DraftKings. See the notes below.'];
  if (m.ev >= 0 && ws.some((w) => w[0] === 'bad')) return ['bad', 'Fix the legs first', 'Positive on paper, but at least one leg is negative EV or doubles up a market. See the notes below.'];
  if (m.ev >= 0.08 && ws.some((w) => w[0] === 'warn')) return ['warn', 'Positive, with caveats', `EV of ${(m.ev * 100).toFixed(0)}% on the model\'s numbers, but some legs are flagged or share a game, so trust it less. See the notes below.`];
  if (m.ev < 0) return ['bad', 'Skip it', `The legs together are worth less than the payout pays. You lose about ${Math.abs(m.ev * 100).toFixed(0)} cents per dollar on average.`];
  if (m.ev < 0.08) return ['warn', 'Thin edge', 'Slightly positive on the model\'s numbers, but small enough that model error or a worse price at your book could wipe it out.'];
  return ['good', 'Worth taking on the model\'s numbers', `Positive EV of ${(m.ev * 100).toFixed(0)}%. Remember that the edges multiply: if each leg's true edge is half what the model thinks, so is much of this.`];
}
// game windows (Thursday night, Sunday 1 PM, ...) for the parlay builder
const winOf = (g) => {
  const h = Number(g.time.split(':')[0]);
  if (g.weekday === 'Sunday') return h < 12 ? 'Sunday morning' : h < 15 ? 'Sunday 1 PM' : h < 19 ? 'Sunday 4 PM' : 'Sunday night';
  return `${g.weekday} night`;
};
const GWIN = Object.fromEntries(games.map((g) => [g.game, winOf(g)]));
const WINS = [...new Set(games.map(winOf))];
const inScope = (l) => (state.game === 'all' || l.game === state.game) && (state.win === 'all' || GWIN[l.game] === state.win);
const scopeName = () => (state.game !== 'all' ? state.game : state.win !== 'all' ? state.win : 'the whole week');
// suggested parlay for the chosen game or window: clean, likely (55%+), underpriced (edge 3+ pts) legs at DraftKings.
// One game: up to 3 legs, one per player or market, at most 2 per team and 1 game line.
// Several games: the best leg from each game, up to 4.
// suggested parlays for the chosen scope and leg count, best edge first. Qualifying legs: no flag, DraftKings price,
// 55%+ and 3+ pts edge first, then near-value (52%+, 1.5+ pts). One leg per player or market, one game line per game,
// at most 2 legs per team in a single game. Across games: 1 leg per game (3 for slips over 6 legs). No leg is reused
// across suggestions, so each one is different.
const SUG_SIZES = [1, 2, 3, 4, 5, 6, 11];
const sizeName = (k) => (k === 1 ? 'Straight' : String(k));
const SS = { size: null, idx: -1 };
try { SS.size = +localStorage.getItem('props-legs') || null; } catch (e) {}
let SAVED = []; try { SAVED = JSON.parse(localStorage.getItem('props-saved') || '[]').map((s) => ({ ...s, legs: s.legs.filter((id) => LEG[id]) })).filter((s) => s.legs.length); } catch (e) { SAVED = []; }
const saveSaved = () => { try { localStorage.setItem('props-saved', JSON.stringify(SAVED)); } catch (e) {} };
function sugPool() {
  const ok = (l) => inScope(l) && !l.flag && l.offers.DraftKings != null && (PS.kind === 'all' || mkt(l) === PS.kind);
  // Most likely to hit: the highest-chance legs that still pay more than they risk on average (edge 1+ pt, 55%+)
  if (PS.mode === 'likely') return LEGS.filter((l) => ok(l) && l.p >= 0.55 && l.edge >= 0.01).sort((a, b) => b.p - a.p || b.edge - a.edge);
  const v = LEGS.filter((l) => ok(l) && l.p >= 0.55 && l.edge >= 0.03).sort((a, b) => b.edge - a.edge);
  const nv = LEGS.filter((l) => ok(l) && !(l.p >= 0.55 && l.edge >= 0.03) && l.p >= 0.52 && l.edge >= 0.015).sort((a, b) => b.edge - a.edge);
  return v.concat(nv);
}
function buildSlips(size, n = 6) {
  const pool = sugPool(), out = [], used = new Set();
  const nG = new Set(pool.map((l) => l.game)).size, one = state.game !== 'all' || nG === 1;   // a window can hold just one game
  // across games: 1 leg per game, more only when the scope has too few games to fill the slip (max 3 per game)
  const perGame = one ? size : Math.min(3, Math.max(size > 6 ? 3 : 1, Math.ceil(size / nG)));
  for (let s = 0; s < n; s++) {
    const pick = [], g = {}, gl = {}, team = {};
    for (const l of pool) {
      if (pick.length >= size) break;
      if (used.has(l.id) || (g[l.game] || 0) >= perGame) continue;
      if (pick.some((x) => x.key === l.key || (x.kind !== 'Game' && l.kind !== 'Game' && x.who === l.who))) continue;
      if (l.kind === 'Game') { if (gl[l.game]) continue; gl[l.game] = 1; }
      else if (one && size <= 3) { const t = l.team || ''; if ((team[t] || 0) >= 2) continue; team[t] = (team[t] || 0) + 1; }
      pick.push(l); g[l.game] = (g[l.game] || 0) + 1;
    }
    if (pick.length < size) break;
    pick.forEach((l) => used.add(l.id)); out.push(pick.map((l) => l.id));
  }
  return out;
}
// Kelly bankroll growth of a slip at DraftKings, each leg's chance cut 2 points for model error
function growth(ids) {
  const p = ids.reduce((a, id) => a * Math.max(0.01, LEG[id].p - 0.02), 1), b = ids.reduce((a, id) => a * dec(LEG[id].offers.DraftKings), 1) - 1;
  const f = (b * p - (1 - p)) / b; if (f <= 0) return 0;
  return p * Math.log(1 + f * b) + (1 - p) * Math.log(1 - f);
}
function sugState() {
  const sizes = SUG_SIZES.filter((k) => buildSlips(k, 1).length);
  // best parlay size by growth; when no parlay has positive growth (or none can be built), suggest a straight bet
  const ps = sizes.filter((k) => k > 1 && growth(buildSlips(k, 1)[0]) > 0);
  const best = ps.length ? ps.reduce((a, k) => (growth(buildSlips(k, 1)[0]) > growth(buildSlips(a, 1)[0]) ? k : a), ps[0]) : sizes.includes(1) ? 1 : null;
  const size = sizes.includes(SS.size) ? SS.size : best;
  return { sizes, best, size, slips: size ? buildSlips(size) : [] };
}
function renderWins() {
  const box = document.getElementById('cats'); box.replaceChildren();
  for (const k of ['all', ...WINS]) {
    const n = k === 'all' ? games.length : games.filter((g) => winOf(g) === k).length;
    const b = el('button', 'chip'); b.type = 'button'; b.append(el('span', null, k === 'all' ? 'Whole week' : k), el('b', null, String(n)));
    b.setAttribute('aria-pressed', state.game === 'all' && state.win === k);
    b.onclick = () => { state.win = k; state.game = 'all'; PS.note = ''; render(); };
    box.append(b);
  }
}
function renderParlay() {
  document.getElementById('lede').textContent = 'Build a parlay from any priced leg this week: game lines, touchdowns, yards over/unders and milestones. The slip shows the chance it hits, the payout, the EV, and a verdict on whether it is worth taking.';
  document.getElementById('legend').innerHTML = '<span><i class="leanmark" style="margin:0 4px 0 0">★</i>Our lean on an over/under or spread</span><span>Tap either side to see its chance, edge and EV, then Add it. You can always go against our lean.</span>';
  document.querySelector('.bar').style.display = 'none';
  renderWins(); renderGames();
  const board = document.getElementById('board'); board.replaceChildren(); board.className = 'cols pl';
  // picker
  const pick = el('section', 'col'); const ph = el('div', 'colhead'); ph.append(el('h2', null, 'Add legs'), el('span', null, '')); pick.append(ph);
  const ctl = el('div', 'plctl');
  const q = el('input'); q.type = 'search'; q.placeholder = 'Search a player, team or game'; q.value = PS.q; q.setAttribute('aria-label', 'Search legs');
  q.oninput = (e) => { PS.q = e.target.value; drawList(); };
  const seg = el('div', 'seg');
  seg.setAttribute('aria-label', 'Market');
  for (const [k, t] of MKTS) {
    const n = k === 'all' ? 0 : GROUPS.filter((g) => g.mkt === k && inScope(g.sides[0])).length;
    if (k !== 'all' && !n) continue;
    const b = el('button', null, t); b.type = 'button'; b.setAttribute('aria-pressed', PS.kind === k);
    b.onclick = () => { PS.kind = k; SS.idx = -1; renderParlay(); }; seg.append(b);
  }
  const tg = el('label', 'tog'); const cb = el('input'); cb.type = 'checkbox'; cb.checked = PS.plus; cb.onchange = (e) => { PS.plus = e.target.checked; drawList(); };
  tg.append(cb, document.createTextNode(' Positive EV side only'));
  const tg2 = el('label', 'tog'); const cb2 = el('input'); cb2.type = 'checkbox'; cb2.checked = PS.clean; cb2.onchange = (e) => { PS.clean = e.target.checked; drawList(); };
  tg2.append(cb2, document.createTextNode(' Hide flagged roles'));
  const so = el('select'); so.setAttribute('aria-label', 'Sort legs');
  for (const [v, t] of [['edge', 'Sort: best balance (edge)'], ['ev', 'Sort: highest EV'], ['p', 'Sort: most likely']]) { const o = el('option', null, t); o.value = v; so.append(o); }
  so.value = PS.sort; so.onchange = (e) => { PS.sort = e.target.value; drawList(); };
  const mp = el('div', 'seg'); mp.setAttribute('aria-label', 'Minimum chance');
  for (const [v, t] of [[0, 'Any chance'], [0.25, '25%+'], [0.4, '40%+'], [0.55, '55%+'], [0.7, '70%+']]) {
    const b = el('button', null, t); b.type = 'button'; b.setAttribute('aria-pressed', PS.minp === v); b.onclick = () => { PS.minp = v; renderParlay(); }; mp.append(b);
  }
  ctl.append(q, seg, so, mp, tg, tg2); pick.append(ctl);
  const list = el('div', 'pllist'); pick.append(list);
  function drawList() {
    const qq = PS.q.trim().toLowerCase();
    const okSide = (l) => (!PS.plus || l.ev > 0) && l.p >= PS.minp;
    const metric = PS.sort === 'ev' ? (l) => l.ev : PS.sort === 'p' ? (l) => l.p : (l) => l.edge;
    const gs = GROUPS.filter((g) => inScope(g.sides[0]) && (PS.kind === 'all' || g.mkt === PS.kind) && (!PS.clean || !g.flag)
      && (!qq || g.text.includes(qq)) && g.sides.some(okSide))
      .map((g) => ({ g, m: Math.max(...g.sides.filter(okSide).map(metric)) })).sort((a, b) => b.m - a.m).slice(0, 80).map((x) => x.g);
    ph.lastChild.textContent = `${gs.length >= 80 ? 'top 80' : gs.length} bets`;
    list.replaceChildren();
    if (!gs.length) list.append(el('div', 'empty', 'Nothing matches. Try another search or turn off Positive EV only.'));
    for (const g of gs) list.append(groupRow(g));
  }
  function groupRow(g) {
    const r = el('div', 'leg'); const w = el('div', 'who'); const l0 = g.sides[0];
    const kindName = l0.kind === 'Milestone' ? 'Milestone' : l0.kind === 'Game' ? 'Game line' : l0.kind === 'TD' ? 'Touchdown' : l0.kind + ' yards';
    const lean = g.sides.reduce((a, b) => (b.edge > a.edge ? b : a));
    const cat = g.sides.map((x) => x.cat).find((c) => c) || '';
    const nm = l0.pid && LOGS[l0.pid] ? el('button', 'n namebtn', g.title) : el('span', 'n', g.title);
    if (nm.tagName === 'BUTTON') {
      nm.type = 'button'; nm.title = 'Season game log';
      nm.onclick = () => { const c = g.sides.find((x) => x.id === PS.sel[g.grp]) || g.sides.find((x) => slip.includes(x.id)) || g.sides.reduce((a, b) => (b.edge > a.edge ? b : a));
        const num = Number((c.label.match(/[\d.]+/) || [])[0]);
        showLog(l0.pid, l0.kind === 'TD' ? { kind: 'td' } : l0.kind === 'Game' ? null : { kind: /rush/.test(c.label) ? 'rush' : 'rec', line: l0.kind === 'Milestone' ? num - 0.5 : num, side: l0.kind === 'Milestone' ? 'Over' : c.sl }); };
    }
    const mv = l0.pid && LOGS[l0.pid] && LOGS[l0.pid].move;
    w.append(nm, el('span', 's', `${kindName} · ${l0.game}${cat ? ' · ' + cat : ''}${g.flag ? ' · ' + g.flag : ''}${mv ? ` · new team (from ${mv.frm})` : ''}`));
    const inSlip = g.sides.find((x) => slip.includes(x.id));
    const cur = g.sides.find((x) => x.id === PS.sel[g.grp]) || inSlip || lean;
    const box = el('div', 'sidebox');
    const seg = el('div', 'seg sides');
    for (const x of g.sides) {
      const b = el('button', null); b.type = 'button'; b.setAttribute('aria-pressed', x === cur);
      b.append(el('span', null, g.sides.length > 1 ? x.sl : 'Yes'), el('small', null, ' ' + fmtOdds(x.price)));
      if (g.sides.length > 1 && x === lean && lean.edge > 0) b.append(el('i', 'leanmark', '★'));
      b.setAttribute('aria-label', `${x.sl} ${fmtOdds(x.price)}${x === lean ? ', our lean' : ''}`);
      b.onclick = () => { PS.sel[g.grp] = x.id; renderParlay(); };
      seg.append(b);
    }
    const st = el('span', 'e ' + (cur.edge >= 0 ? 'pos' : 'neg'), `${pct(cur.p)} · edge ${pts(cur.edge)} · EV ${cur.ev > 0 ? '+' : ''}${(cur.ev * 100).toFixed(0)}%${cur.season ? ` · hit ${cur.season} this season` : ''}`);
    box.append(seg, st);
    if (g.sides.length > 1 && cur !== lean && lean.edge > 0) box.append(el('span', 'e dim', `Going against our lean (${lean.sl})`));
    if (cur.flag === 'season disagrees') box.append(el('span', 'e warnc', `Caution: hit only ${cur.season} this season`));
    const on = slip.includes(cur.id);
    const b = el('button', 'add' + (on ? ' on' : ''), on ? 'Added' : 'Add'); b.type = 'button'; b.setAttribute('aria-label', (on ? 'Remove ' : 'Add ') + legName(cur));
    b.onclick = () => { slip = on ? slip.filter((i) => i !== cur.id) : [...slip.filter((i) => !g.sides.some((x) => x.id === i)), cur.id]; SS.idx = -1; saveSlip(); renderParlay(); };
    r.append(w, box, b); return r;
  }
  drawList();
  // slip
  const sl = el('section', 'col slip'); const sh = el('div', 'colhead'); sh.append(el('h2', null, 'Your parlay'));
  const acts = el('span', 'acts');
  const SG = sugState();
  if (SS.idx >= 0 && (SS.idx >= SG.slips.length || SG.slips[SS.idx].join() !== slip.join())) SS.idx = -1;
  const loadSug = (i) => { if (!SG.slips.length) { PS.note = `Nothing in ${scopeName()} qualifies for a ${SG.size || ''}-leg suggestion. Skipping is the better bet here.`; renderParlay(); return; }
    SS.idx = (i + SG.slips.length) % SG.slips.length; slip = SG.slips[SS.idx].slice(); PS.price = '';
    PS.note = state.game !== 'all' ? 'Same-game legs: DraftKings prices same-game parlays itself and usually pays less than the math here. Enter its price to check.' : ''; saveSlip(); renderParlay(); };
  const sug = el('button', 'lnk sugb', SS.idx >= 0 && SG.slips.length > 1 ? 'Shuffle' : `Suggest for ${scopeName()}`); sug.type = 'button';
  sug.onclick = () => { if (SS.idx < 0 || SG.slips.length < 2) return loadSug(0); let k = SS.idx; while (k === SS.idx) k = Math.floor(Math.random() * SG.slips.length); loadSug(k); };
  const clr = el('button', 'lnk', 'Clear'); clr.type = 'button'; clr.onclick = () => { slip = []; SS.idx = -1; PS.price = ''; PS.note = ''; saveSlip(); renderParlay(); };
  acts.append(sug, clr); sh.append(acts); sl.append(sh);
  {
    const md = el('div', 'sugnav'); md.append(el('b', null, 'Build for'));
    const seg = el('div', 'seg');
    for (const [k, t] of [['value', 'Best value'], ['likely', 'Most likely to hit']]) {
      const b = el('button', null, t); b.type = 'button'; b.setAttribute('aria-pressed', PS.mode === k);
      b.onclick = () => { PS.mode = k; try { localStorage.setItem('props-mode', k); } catch (e) {} SS.idx = -1; const g2 = sugState(); if (g2.slips.length) { SS.idx = 0; slip = g2.slips[0].slice(); PS.price = ''; PS.note = ''; saveSlip(); } renderParlay(); };
      seg.append(b);
    }
    const mk = PS.kind === 'all' ? '' : ` Only ${MKTS.find((m) => m[0] === PS.kind)[1].toLowerCase()} legs (market filter on the left).`;
    md.append(seg, el('span', 'dim sugbest', (PS.mode === 'likely' ? 'Highest-chance legs that still pay more than they risk on average (edge 1+ pt, 55%+ chance, no flags).' : 'Biggest edge first (edge 3+ pts, 55%+ chance), then near-value legs.') + mk));
    sl.append(md);
  }
  if (SG.sizes.length) {
    const lc = el('div', 'sugnav'); lc.append(el('b', null, 'Legs'));
    const seg = el('div', 'seg');
    SG.sizes.forEach((k) => { const b = el('button', null, k === SG.best ? `${sizeName(k)} ★` : sizeName(k)); b.type = 'button'; b.setAttribute('aria-pressed', k === SG.size);
      b.onclick = () => { SS.size = k; try { localStorage.setItem('props-legs', k); } catch (e) {} SS.idx = -1; const s2 = buildSlips(k); if (s2.length) { SS.idx = 0; slip = s2[0].slice(); PS.price = ''; PS.note = ''; saveSlip(); } renderParlay(); }; seg.append(b); });
    lc.append(seg, el('span', 'dim sugbest', SG.best === 1 ? `★ No parlay is worth it for ${scopeName()}: take a straight bet` : `★ ${SG.best} legs is best for ${scopeName()}`)); sl.append(lc);
    const nav = el('div', 'sugnav');
    const prev = el('button', 'lnk', '‹'); prev.type = 'button'; prev.setAttribute('aria-label', 'Previous suggestion'); prev.onclick = () => loadSug(SS.idx < 0 ? SG.slips.length - 1 : SS.idx - 1);
    const next = el('button', 'lnk', '›'); next.type = 'button'; next.setAttribute('aria-label', 'Next suggestion'); next.onclick = () => loadSug(SS.idx + 1);
    nav.append(prev, el('span', 'suglab', SS.idx >= 0 ? `${SG.size === 1 ? 'Straight bet' : 'Suggestion'} ${SS.idx + 1} of ${SG.slips.length}` : `${SG.slips.length} suggested parlays`), next); sl.append(nav);
  }
  if (SAVED.length || slip.length) {
    const sv = el('div', 'savedrow'); const key = (ids) => ids.slice().sort().join('|');
    if (slip.length) { const sb = el('button', 'lnk', 'Save this slip'); sb.type = 'button';
      sb.onclick = () => { if (!SAVED.some((s) => key(s.legs) === key(slip))) { SAVED.push({ name: SS.idx >= 0 ? `Suggestion ${SS.idx + 1} (${slip.length} legs)` : `My slip ${SAVED.length + 1}`, legs: slip.slice() }); saveSaved(); } renderParlay(); }; sv.append(sb); }
    SAVED.forEach((s, i) => { const c = el('button', 'chip', s.name); c.type = 'button'; c.setAttribute('aria-pressed', key(s.legs) === key(slip)); c.onclick = () => { slip = s.legs.slice(); SS.idx = -1; PS.price = ''; saveSlip(); renderParlay(); };
      const x = el('button', 'x', '×'); x.type = 'button'; x.setAttribute('aria-label', 'Delete ' + s.name); x.onclick = () => { SAVED.splice(i, 1); saveSaved(); renderParlay(); };
      const w = el('span', 'savedchip'); w.append(c, x); sv.append(w); });
    sl.append(sv);
  }
  if (PS.note) { const n = el('p', 'note sugnote', PS.note); sl.append(n); }
  if (!slip.length) sl.append(el('div', 'empty', 'Add legs from the list, or pick a game or game window above, choose how many legs, and press Suggest. Use the arrows or Shuffle to flip between suggestions, and Save to keep one. Suggested legs are 55%+ likely and 3+ points better than their DraftKings price first, then near-value legs, with no role flags. ★ marks the leg count whose top suggestion grows a bankroll fastest (Kelly growth, each leg\'s chance cut 2 points for model error).'));
  else {
    const m = parlayMath(slip, PS.price && Number(PS.price) && Math.abs(Number(PS.price)) >= 100 ? Number(PS.price) : null);
    const lsx = el('div', 'books slipl');
    for (const l of m.ls) {
      const r = el('div'); const left = el('span'); left.append(el('b', null, legName(l)), el('small', null, `${l.game} · ${PBOOKS.filter((b) => l.offers[b] != null).map((b) => `${ABBR[b]} ${fmtOdds(l.offers[b])}`).join(' · ')}`));
      const right = el('span', 'num ' + (l.ev >= 0 ? 'pos' : 'neg'), `${pct(l.p)} · ${pts(l.edge)} · EV ${l.ev > 0 ? '+' : ''}${(l.ev * 100).toFixed(0)}%`);
      const x = el('button', 'x', '×'); x.type = 'button'; x.setAttribute('aria-label', 'Remove ' + legName(l)); x.onclick = () => { slip = slip.filter((i) => i !== l.id); SS.idx = -1; saveSlip(); renderParlay(); };
      r.append(left, right, x); lsx.append(r);
    }
    sl.append(lsx);
    if (m.book) {
      const pl = el('div', 'placeat'); pl.append(el('b', null, `Place at ${m.book}: ${fmtOdds(amer(m.dBook))}`),
        el('span', null, 'Every leg priced at DraftKings\' current number. DraftKings may boost or trim the payout on its slip; if so, enter what it shows below.'));
      sl.append(pl);
    }
    const pin = el('label', 'pin'); pin.append(document.createTextNode("Your book's parlay price (optional) "));
    const ip = el('input'); ip.type = 'text'; ip.inputMode = 'numeric'; ip.placeholder = fmtOdds(amer(m.dBook)); ip.value = PS.price; ip.setAttribute('aria-label', "Your book's parlay price");
    ip.onchange = (e) => { PS.price = e.target.value.replace(/[^0-9+-]/g, ''); renderParlay(); };
    pin.append(ip); sl.append(pin);
    const st = stats([[pct1(m.p), `chance it hits (about 1 in ${Math.max(1, Math.round(1 / m.p))})`], [fmtOdds(amer(m.d)), PS.price ? 'your price' : m.book ? `payout at ${m.book}` : 'payout (mixed books)'],
      [pct1(m.be), 'break-even chance'], [`${m.ev > 0 ? '+' : ''}${(m.ev * 100).toFixed(0)}%`, 'expected value'], [`$${(10 * (m.d - 1)).toFixed(0)}`, 'profit on a $10 win'], [`${m.ev > 0 ? '+' : '-'}$${Math.abs(10 * m.ev).toFixed(2)}`, 'average result per $10']]);
    st.classList.add('pad'); sl.append(st);
    const v = verdict(m, slip.length, warnings(slip));
    const vb = el('div', 'verdict ' + v[0]); vb.append(el('b', null, v[1]), el('span', null, v[2])); sl.append(vb);
    if (m.ls.length > 1) {
      const drops = m.ls.map((l) => ({ l, ev: parlayMath(slip.filter((i) => i !== l.id), null).ev })).sort((a, b) => b.ev - a.ev);
      const evBest = parlayMath(slip, null).ev;
      if (drops[0].ev > evBest + 0.005) { const t = el('p', 'note', `Tip: dropping ${legName(drops[0].l)} raises the EV to ${(drops[0].ev * 100).toFixed(0)}%.`); t.style.padding = '0 14px'; sl.append(t); }
    }
    const wl = el('ul', 'warns'); for (const [k, t] of warnings(slip)) wl.append(el('li', k, t)); if (wl.children.length) sl.append(wl);
  }
  board.append(pick, sl);
  document.getElementById('foot').textContent = 'Legs are ranked by edge: our chance minus the break-even chance the price implies. EV alone favors long shots, because a small overestimate of a 5% chance turns into a huge EV at +2500; edge in percentage points does not, so it rewards legs that are both likely and underpriced. Each leg\'s chance blends our model with the books\' own chance, 50/50 for normal prices and leaning more on the books for long shots (down to 20% model below about a 12% book chance), since the model is least reliable in the tails. Game lines are blended too, because on past closing lines the spread model showed no edge by itself. Only DraftKings is used: each leg is DraftKings\' own number and price, and the parlay is priced at DraftKings. The parlay chance multiplies the legs, which assumes they are independent, so legs from the same game are flagged. EV uses that book\'s price unless you enter the parlay price your app shows (books sometimes boost or trim parlay payouts). None of these leg types has been graded against real lines yet, so treat the EV as the model\'s opinion, not a promise. Tracking only, not betting advice.';
}
function render() {
  if (state.tab === 'test') { renderTabs(); renderTest(); return; }
  if (state.tab === 'parlay') { renderTabs(); renderParlay(); return; }
  document.querySelector('.bar').style.display = '';
  const cf = CONF[state.tab];
  document.getElementById('lede').textContent = cf.lede;
  document.getElementById('legend').innerHTML = state.tab === 'td' ? cf.legend : state.tab === 'ms' ? MS_LEGEND : YARDS_LEGEND;
  document.getElementById('foot').textContent = (state.tab === 'td' ? cf.foot : state.tab === 'ms' ? MS_FOOT : YARDS_FOOT) + ` Odds are from The Odds API, taken ${state.tab === 'td' ? D.taken : state.tab === 'ms' ? (D.altTaken || D.yardsTaken) : D.yardsTaken}. Check injury news and current prices before using any of this. These are tracking picks, not betting advice.`;
  renderTabs(); renderGames(); renderPos(); renderSort();
  const { base, list } = filtered(); renderCats(base);
  document.getElementById('count').textContent = `${list.length} player${list.length === 1 ? '' : 's'}`;
  const board = document.getElementById('board'); board.replaceChildren();
  if (state.game !== 'all') {
    const g = games.find((x) => x.game === state.game);
    board.className = 'cols two';
    for (const t of [g.away, g.home]) board.append(column(t, impOf[t] != null ? `expected ${impOf[t]} pts` : '', list.filter((p) => p.team === t)));
  } else {
    board.className = 'cols';
    board.append(column(state.cat === 'all' ? 'All games' : state.cat, '', list));
  }
}
document.getElementById('q').addEventListener('input', (e) => { state.q = e.target.value; state.open = null; render(); });
document.getElementById('sort').addEventListener('change', (e) => { state.sort = e.target.value; render(); });
document.getElementById('small').addEventListener('change', (e) => { state.small = e.target.checked; render(); });
render();
