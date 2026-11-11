const D = JSON.parse(document.getElementById('td-data').textContent);
const P = D.players.map((p) => ({ ...p, opps: p.carries + p.targets, edge: p.book == null ? null : p.model - p.book }));
document.getElementById('taken').textContent = D.taken;
const state = { cat: 'all', game: 'all', pos: 'all', q: '', sort: 'model', small: true, open: null };
const CATS = [['all', 'All players'], ['TD value', 'TD value'], ['Most likely', 'Most likely'], ['Check role', 'Check role']];
const PILL = { 'TD value': 'value', 'Most likely': 'likely', 'Check role': 'check' };
const fmtOdds = (o) => o == null ? '—' : (o > 0 ? '+' : '') + o;
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const DAY = { Thursday: 'Thu', Sunday: 'Sun', Monday: 'Mon', Saturday: 'Sat', Friday: 'Fri' };
function clock(t) { const [h, m] = t.split(':').map(Number); return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${h >= 12 ? 'PM' : 'AM'}`; }

// games strip, in kickoff order
const games = [...new Map(P.map((p) => [p.game, p])).values()].sort((a, b) => (a.day + a.time).localeCompare(b.day + b.time));
function renderGames() {
  const box = document.getElementById('games'); box.replaceChildren();
  const all = el('button', 'game'); all.type = 'button'; all.append(el('span', 'm', 'All games'), el('span', 't', `${games.length} games`));
  all.setAttribute('aria-pressed', state.game === 'all'); all.onclick = () => { state.game = 'all'; state.open = null; render(); };
  box.append(all);
  for (const g of games) {
    const b = el('button', 'game'); b.type = 'button';
    b.append(el('span', 'm', `${g.away} @ ${g.home}`), el('span', 't', `${DAY[g.weekday] || g.weekday} ${clock(g.time)} ET`));
    b.setAttribute('aria-pressed', state.game === g.game);
    b.onclick = () => { state.game = state.game === g.game ? 'all' : g.game; state.open = null; render(); };
    box.append(b);
  }
}
function renderCats(base) {
  const box = document.getElementById('cats'); box.replaceChildren();
  for (const [k, label] of CATS) {
    const n = k === 'all' ? base.length : base.filter((p) => p.cat === k).length;
    const b = el('button', 'chip'); b.type = 'button'; b.append(el('span', null, label), el('b', null, String(n)));
    b.setAttribute('aria-pressed', state.cat === k); b.onclick = () => { state.cat = k; state.open = null; render(); };
    box.append(b);
  }
}
function renderPos() {
  const box = document.getElementById('pos'); box.replaceChildren();
  for (const k of ['all', 'RB', 'WR', 'TE', 'QB']) {
    const b = el('button', null, k === 'all' ? 'All' : k); b.type = 'button';
    b.setAttribute('aria-pressed', state.pos === k); b.onclick = () => { state.pos = k; state.open = null; render(); };
    box.append(b);
  }
}
const SORTS = {
  model: (a, b) => b.model - a.model,
  edge: (a, b) => (b.edge ?? -999) - (a.edge ?? -999),
  ev: (a, b) => (b.ev ?? -999) - (a.ev ?? -999),
  odds: (a, b) => (b.best ?? -1e9) - (a.best ?? -1e9),
};
function filtered() {
  const q = state.q.trim().toLowerCase();
  const base = P.filter((p) => (state.game === 'all' || p.game === state.game)
    && (state.pos === 'all' || p.pos === state.pos)
    && (!state.small || p.opps >= 3 || p.cat)
    && (!q || p.name.toLowerCase().includes(q) || p.team.toLowerCase() === q || p.opp.toLowerCase() === q));
  return { base, list: base.filter((p) => state.cat === 'all' || p.cat === state.cat).sort(SORTS[state.sort]) };
}
function row(p) {
  const frag = document.createDocumentFragment();
  const r = el('button', 'row'); r.type = 'button'; r.setAttribute('aria-expanded', state.open === p.id);
  const who = el('div', 'who'); const n = el('span', 'n', p.name);
  const dc = p.depth == null ? '' : ` · ${p.pos}${p.depth} on depth chart${p.depthPrev != null && p.depthPrev !== p.depth ? ` (was ${p.pos}${p.depthPrev})` : ''}`;
  const s = el('span', 's', `${p.pos} · ${p.team} vs ${p.opp}${dc}${p.missed ? ` · missed last ${p.missed}` : ''}`);
  who.append(n, s);
  if (p.cat) { const pill = el('span', `pill ${PILL[p.cat]}`, p.cat); pill.style.alignSelf = 'flex-start'; pill.style.marginTop = '3px'; who.append(pill); }
  const m = el('div', 'meter'); const tr = el('div', 'track'); const f = el('div', 'fill'); f.style.width = Math.min(100, p.model) + '%'; tr.append(f);
  if (p.book != null) { const t = el('div', 'tick'); t.style.left = `calc(${Math.min(100, p.book)}% - 1px)`; t.title = `Books: ${p.book}%`; tr.append(t); }
  const l = el('div', 'l'); const lm = el('span'); lm.append(el('b', null, p.model.toFixed(0) + '%'), document.createTextNode(' model'));
  l.append(lm, el('span', null, p.book == null ? 'no line' : `books ${p.book.toFixed(0)}%`)); m.append(tr, l);
  const pr = el('div', 'price'); pr.append(el('span', 'o', fmtOdds(p.best)));
  const small = p.opps < 3;
  pr.append(el('span', 'e ' + (p.ev == null || small ? 'dim' : p.ev >= 0 ? 'pos' : 'neg'),
    p.ev == null ? '' : small ? 'small role' : `EV ${p.ev > 0 ? '+' : ''}${p.ev.toFixed(0)}%`));
  r.append(who, m, pr);
  r.onclick = () => { state.open = state.open === p.id ? null : p.id; render(); };
  frag.append(r);
  if (state.open === p.id) frag.append(detail(p));
  return frag;
}
function detail(p) {
  const d = el('div', 'detail');
  const a = el('div'); a.append(el('h3', null, 'Recent usage'));
  const st = el('div', 'stats');
  for (const [v, k] of [[p.carries.toFixed(1), 'carries a game'], [p.targets.toFixed(1), 'targets a game'], [p.tdpg.toFixed(2), 'TDs a game'],
    [p.gl + '%', 'goal-line share'], [p.rz + '%', 'red-zone share'], [p.room + '%', 'share at his position']]) {
    const x = el('div', 'stat'); x.append(el('b', null, v), el('span', null, k)); st.append(x);
  }
  a.append(st);
  const b = el('div'); b.append(el('h3', null, 'Why'), el('p', 'why', p.why));
  const ctx = el('p', 'note', `${p.opp} allows ${Math.abs(p.deftd).toFixed(2)} ${p.deftd >= 0 ? 'more' : 'fewer'} TDs a game than average to ${p.pos}s. Last game he had ${p.last}% of his team's touches.`);
  ctx.style.marginTop = '8px'; b.append(ctx);
  const c = el('div'); c.append(el('h3', null, 'Prices by book'));
  const bk = el('div', 'books');
  if (!p.books.length) bk.append(el('span', 'dim', 'No book is offering this player yet.'));
  p.books.forEach((x, i) => { const row = el('div', i === 0 ? 'best' : null); row.append(el('span', null, x.b), el('span', null, fmtOdds(x.p))); bk.append(row); });
  c.append(bk);
  if (p.books.length) {
    const fair = p.model / 100; const need = fair > 0 ? (fair >= .5 ? -Math.round(100 * fair / (1 - fair)) : Math.round(100 * (1 - fair) / fair)) : null;
    const t = el('p', 'note', `The model's fair price is ${fmtOdds(need)}. Any price longer than that is value if the model is right.`); t.style.marginTop = '8px'; c.append(t);
  }
  d.append(a, b, c);
  return d;
}
function column(title, sub, list) {
  const c = el('section', 'col'); const h = el('div', 'colhead'); h.append(el('h2', null, title), el('span', null, sub)); c.append(h);
  if (!list.length) c.append(el('div', 'empty', 'No players match these filters. Try All players or turn off Hide small roles.'));
  list.forEach((p) => c.append(row(p)));
  return c;
}
function render() {
  renderGames(); renderPos();
  const { base, list } = filtered(); renderCats(base);
  document.getElementById('count').textContent = `${list.length} player${list.length === 1 ? '' : 's'}`;
  const board = document.getElementById('board'); board.replaceChildren();
  if (state.game !== 'all') {
    const g = games.find((x) => x.game === state.game);
    board.className = 'cols two';
    for (const t of [g.away, g.home]) {
      const tl = list.filter((p) => p.team === t);
      const imp = P.find((p) => p.team === t)?.imp;
      board.append(column(t, imp != null ? `expected ${imp} pts` : '', tl));
    }
  } else {
    board.className = 'cols';
    const label = state.cat === 'all' ? 'All games' : state.cat;
    board.append(column(label, '', list));
  }
}
document.getElementById('q').addEventListener('input', (e) => { state.q = e.target.value; state.open = null; render(); });
document.getElementById('sort').addEventListener('change', (e) => { state.sort = e.target.value; render(); });
document.getElementById('small').addEventListener('change', (e) => { state.small = e.target.checked; render(); });
render();
