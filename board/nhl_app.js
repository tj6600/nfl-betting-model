const D = JSON.parse(document.getElementById('nhl-data').textContent);
// games that have started: DraftKings pulls pregame lines at the start, so their legs leave suggestions and the DraftKings link
const STARTS = {}; (D.games || []).forEach((g) => { if (g.start) STARTS[g.game] = g.start; });
const started = (game) => !!STARTS[game] && Date.parse(STARTS[game]) <= Date.now();
const LEG = Object.fromEntries(D.legs.map((l) => [l.id, l]));
// "Line changed?" (board/site/lines.js, Thomas 2026-11-19): the user enters DraftKings' new line or price and the leg is
// re-priced here: shots and saves from the props model's negative binomial around the player's projection, totals from the
// game model's total-goals chances. Moneylines, puck lines (always 1.5) and alt rungs: price only.
const P_BY = Object.fromEntries(D.players.map((p) => [p.id, p])), G_BY = Object.fromEntries(D.goalies.map((p) => [p.id, p])), GM_BY = Object.fromEntries(D.games.map((g) => [g.id, g]));
function nbSize(k, pr) {   // the model's NB size; older pages without D.nb: fit it to the board's own numbers
  if (D.nb && D.nb[k]) return D.nb[k];
  if (k === 'saves' && pr.hi > pr.proj) { const sd = (pr.hi - pr.proj) / 1.28, v = sd * sd - pr.proj; return v > 0 ? pr.proj * pr.proj / v : 50; }
  if (pr.ch && pr.ch['3+'] != null) { let best = 8, err = 9; for (let r = 0.5; r < 400; r *= 1.05) { const e = Math.abs(LineEdit.dist.nb(pr.proj, r, 2.5) - pr.ch['3+']); if (e < err) { err = e; best = r; } } return best; }
  return 8;
}
function nhlModel(L, line) {
  if (L.alt) return null;
  if (L.kind === 'Total') { const g = GM_BY[L.gid]; if (!g) return null; const o = g.tpmf ? LineEdit.dist.pmf(g.tpmf, line) : LineEdit.dist.poisson(g.total, line); return L.side === 'Under' ? 1 - o : o; }
  const k = L.kind === 'Shots on goal' ? 'sog' : L.kind === 'Saves' ? 'saves' : null, pl = k && (k === 'sog' ? P_BY : G_BY)[L.pid];
  if (!pl || !pl[k]) return null;
  const o = LineEdit.dist.nb(pl[k].proj, nbSize(k, pl[k]), line); return L.side === 'Under' ? 1 - o : o;
}
function patchNhl() {
  for (const [k, src] of [['sog', D.players], ['saves', D.goalies]]) for (const p of src) {
    const pr = p[k]; if (!pr) continue; p.edited = false;
    for (const sd of ['over', 'under']) { const x = pr[sd], L = x && LEG[x.id]; if (!L) continue; Object.assign(x, { price: L.price, p: L.p, edge: L.edge, ev: L.ev }); pr.line = L.line; if (L.edited) p.edited = true; }
  }
  for (const g of D.games) { const t = g.legs.map((id) => LEG[id]).find((L) => L && L.market === 'total'); if (t) g.line_total = t.line; }
}
LineEdit.setup({ sport: 'nhl', stamp: [D.day, D.propsTaken].join('|'), legs: D.legs, model: nhlModel, name: (L) => L.label,
  bar: (r) => r.p >= 0.55 && r.edge >= 0 && r.price >= -200, barText: '55%+ to hit, fair price or better, -200 or longer',
  inSlip: (L) => slip.includes(L.id), swap: (a, b) => { slip = slip.map((i) => (i === a ? b : i)); sugIdx = -1; saveSlip(); render(); },
  weight: (L) => (D.weights[L.kind] != null ? D.weights[L.kind] : 0.5),
  sibling: (L) => D.legs.find((x) => x.id !== L.id && !x.alt && x.gid === L.gid && x.market === L.market && x.pid === L.pid) || null,
  onChange: () => { patchNhl(); render(); } });
patchNhl();
const STATS = [['sog', 'Shots on goal'], ['saves', 'Goalie saves']];
const SRC = (k) => (k === 'saves' ? D.goalies : D.players);
const SL = Object.fromEntries(STATS);
const TABS = [['games', 'Games']].concat(STATS).concat([['parlay', 'Parlay builder'], ['record', 'Model record']]);
const state = { tab: 'games', game: 'all', pos: 'all', q: '', sort: 'edge', pmin: 0.25, pq: '' };
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const fmt = (o) => o == null ? '—' : (o > 0 ? '+' : '') + o;
const pct = (p) => p == null ? '—' : p < 0.01 ? (p * 100).toFixed(2) + '%' : Math.round(p * 100) + '%';
const sgn = (x) => (x > 0 ? '+' : '') + x;
const dec = (a) => a > 0 ? 1 + a / 100 : 1 + 100 / -a;
const toAm = (d) => d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1));
const $ = (id) => document.getElementById(id);
let slip = [];
try { slip = JSON.parse(localStorage.getItem('nhl-slip-' + D.day) || '[]').filter((id) => LEG[id]); } catch (e) { slip = []; }
const saveSlip = () => { try { localStorage.setItem('nhl-slip-' + D.day, JSON.stringify(slip)); } catch (e) {} };
// suggested parlays are built here so the leg count can be chosen: best remaining legs, 1 per game and 1 per player,
// no leg reused across suggestions (same rule as scripts/nhl_board.py)
// two ways to build: 'value' = biggest edge first (scripts/nhl_board.py pool); 'likely' = most likely to hit first,
// among legs that still pay more than they risk on average (edge 1+ pt) and carry no flags
// alternate lines (alt: true, Over only, e.g. "25+ points") as in the NFL builder: a shaky Over main line (under 60%) gives way to
// the same player's likeliest fairly priced alt line at 60%+, and Most likely to hit slips of 3+ legs lead with alt lines
// that are 70%+, cost at most 3 pts of juice and are priced -500 or longer, likeliest first (parlays.py uses the same rules)
// Thomas, 2026-11-16: no leg heavier than -200 and at most 3 legs (live grading: 3+ leg parlays 0 for ~200 on NBA), 'likely' legs judged on
// their chance at no worse than DraftKings' usual juice (edge -3+) instead of a model edge (parlays.py likely(), MAX_JUICE, SHORT_SIZES)
const SECURE = 0.6, ALT_FIRST_P = 0.7, ALT_FIRST_SIZE = 3, ALT_JUICE = 3, ALT_MIN_PRICE = -200, MAX_LEGS = 3;
const ALT_BY = {};
for (const l of D.legs) if (l.alt && !l.flags.length && l.p >= SECURE && l.edge >= -3 && l.price >= ALT_MIN_PRICE) (ALT_BY[l.pid + '|' + l.market] = ALT_BY[l.pid + '|' + l.market] || []).push(l);
Object.values(ALT_BY).forEach((xs) => xs.sort((a, b) => b.p - a.p));
const safer = (l) => (l.alt || l.side !== 'Over' || l.p >= SECURE) ? l : ((ALT_BY[l.pid + '|' + l.market] || []).find((a) => a.p > l.p) || l);
const dedupe = (xs) => { const s = new Set(); return xs.filter((l) => !s.has(l.id) && s.add(l.id)); };
const ALT_FIRST = D.legs.filter((l) => l.alt && !l.flags.length && l.p >= ALT_FIRST_P && l.edge >= -ALT_JUICE && l.price >= ALT_MIN_PRICE).sort((a, b) => b.p - a.p || b.edge - a.edge);
const capped = (xs) => xs.filter((l) => l.price >= ALT_MIN_PRICE);
const VALUE_POOL = capped(dedupe((D.pool || []).map((id) => LEG[id]).filter(Boolean).map(safer)));
// NHL: the board's winner picks count as "likely" even without an edge (Thomas wants correct picks more than edge),
// but nothing priced shorter than -200, so no leg risks much more than it pays
const LIKELY_POOL = capped(dedupe(D.legs.filter((l) => (l.edge >= -3 || l.pick) && l.p >= 0.55 && l.price >= ALT_MIN_PRICE && !l.flags.length).sort((a, b) => b.p - a.p || b.edge - a.edge).map(safer)));
let mode = 'value';
try { mode = localStorage.getItem('nhl-mode') === 'likely' ? 'likely' : 'value'; } catch (e) {}
let POOL = mode === 'likely' ? LIKELY_POOL : VALUE_POOL;
// market filter: pick any mix of markets (e.g. Points + Assists); none picked = every market. Suggestions follow it.
let KINDS = new Set();
const OPEN = new Set(), GLIM = {};
try { KINDS = new Set(JSON.parse(localStorage.getItem('nhl-kinds') || '[]')); } catch (e) {}
const kindOk = (L) => !KINDS.size || KINDS.has(L.kind);
const MKTS = [...new Set(D.legs.map((L) => L.kind))];
// markets DraftKings won't take in a same-game parlay: such a leg can't share its game with any other leg
const NO_SGP = new Set(['Saves', 'Alt saves']);
// market family, for mixing markets within a slip (alt and main lines of a stat are one family)
function fam(L) {
  if (L.kind === 'Milestone') return (L.key || '').split('-').pop().toLowerCase();
  let k = L.kind.toLowerCase(); if (k.startsWith('alt ')) k = k.slice(4);
  return k === 'shots on goal' ? 'shots' : k;
}
// up to n slips: at most half of a slip from one market family when the pool allows; legs are used once across the
// suggestions first, then (least-used first) a leg may appear in up to 3, so each size shows n different slips
// whenever the pool allows. Same rule as parlays.py many(). pick(pool, size, allowed, cap) -> array of legs or null
function many(pool, size, n, pick) {
  const out = [], uses = {}, seen = new Set(), cap = size < 2 ? size : Math.ceil(size / 2);
  for (let s = 0; s < n; s++) {
    let slip = null;
    for (const [mx, c] of [[0, cap], [0, size], [1, cap], [1, size], [2, cap], [2, size]]) {
      const cand = mx ? pool.map((L, i) => [L, i]).sort((a, b) => (uses[a[0].id] || 0) - (uses[b[0].id] || 0) || a[1] - b[1]).map((x) => x[0]) : pool;
      const t = pick(cand, size, (L) => (uses[L.id] || 0) <= mx, c);
      if (t && !seen.has(t.map((L) => L.id).sort().join('|'))) { slip = t; break; }
    }
    if (!slip) break;
    seen.add(slip.map((L) => L.id).sort().join('|')); out.push(slip.map((L) => L.id));
    slip.forEach((L) => { uses[L.id] = (uses[L.id] || 0) + 1; });
  }
  return out;
}
// one market of one game (of one player for props): a slip never holds two of them, e.g. both teams to win
const sideKey = (L) => `${L.game}|${L.market}|${L.pid && L.kind !== 'Winner' ? L.pid : ''}`;
// the usual pool for a slip of this size (relax 0 in buildSlips)
const usualPool = (size) => (mode === 'likely' && size >= ALT_FIRST_SIZE ? dedupe(ALT_FIRST.concat(POOL)) : POOL).filter((L) => kindOk(L) && !started(L.game));
// next-best legs (Thomas, 2026-11-19): every other leg not yet started, ranked like the mode (chance for Most likely to hit, edge for
// Best value), with legs that carry no flags, are priced no shorter than ALT_MIN_PRICE and are 40%+ to hit ahead of the rest
// fill order (Thomas, 2026-11-19): alt-line rungs that are 60%+ to hit and priced -500 or longer go first (likeliest first, since
// they hit more often than next-best main lines), then the next-best legs. Boards with no alt lines saved go straight to next-best.
const FILL_ALT_P = 0.6, FILL_ALT_MIN = -500;
const fillTag = (L) => (L.alt ? 'alt line' : 'next-best');
const HAS_ALT = D.legs.some((L) => L.alt);
// "2 alt lines and 1 next-best leg" for the warnings and the share card
function fillWords(ls) {
  const a = ls.filter((l) => l.alt).length, b = ls.length - a, w = [];
  if (a) w.push(`${a} alt line${a === 1 ? '' : 's'}`); if (b) w.push(`${b} next-best leg${b === 1 ? '' : 's'}`);
  return w.join(' and ');
}
const fillHow = () => (HAS_ALT ? 'likely alt lines first (60%+ to hit), then next-best legs' : 'the next-best legs');
function fillPool() {
  const by = mode === 'likely' ? (a, b) => b.p - a.p || b.edge - a.edge : (a, b) => b.edge - a.edge || b.p - a.p;
  const ls = D.legs.filter((L) => kindOk(L) && !started(L.game));
  const ok = (L) => !L.flags.length && L.price >= ALT_MIN_PRICE && L.p >= 0.4;
  const alt = ls.filter((L) => L.alt && !L.flags.length && L.p >= FILL_ALT_P && L.price >= FILL_ALT_MIN).sort((a, b) => b.p - a.p || b.edge - a.edge);
  const rest = ls.filter((L) => !alt.includes(L));
  return alt.concat(rest.filter(ok).sort(by), rest.filter((L) => !ok(L)).sort(by));
}
// relax: 0 = usual rules; 1 = next-best legs fill in after the usual ones; 2 = also any number of legs per game and market;
// 3 = also more than one leg per player; 4 = as many legs as the slate has (a shorter slip than asked when it runs out)
function buildSlips(size, n = 6, relax = 0) {
  let pool = usualPool(size);
  if (relax) pool = dedupe(pool.concat(fillPool()));
  const nG = new Set(pool.map((L) => L.game)).size;
  const perGame = relax >= 2 ? size : Math.min(3, Math.max(size > 6 ? 3 : 1, Math.ceil(size / Math.max(1, nG))));   // more per game only when the slate is too small
  const metric = mode === 'likely' ? (L) => L.p : (L) => L.edge / 100;
  return many(pool, size, n, (pool, size, allowed, cap) => {
    if (relax >= 2) cap = size;
    const slip = [], g = {}, pl = new Set(), fm = {}, sk = new Set();
    const fits = (L) => {
      if (sk.has(sideKey(L))) return false;   // never both sides (or two lines) of one market
      if (!allowed(L) || (g[L.game] || 0) >= perGame || (relax < 3 && L.pid && pl.has(L.pid)) || (fm[fam(L)] || 0) >= cap) return false;
      return !((g[L.game] || 0) && (NO_SGP.has(L.kind) || slip.some((x) => x.game === L.game && NO_SGP.has(x.kind))));
    };
    while (slip.length < size) {
      const c = []; for (const L of pool) if (fits(L) && c.push(L) >= LINK_W) break;
      if (!c.length) break;
      const L = linkedPick(c, slip, metric, simLink);
      slip.push(L); sk.add(sideKey(L)); g[L.game] = (g[L.game] || 0) + 1; fm[fam(L)] = (fm[fam(L)] || 0) + 1; if (L.pid) pl.add(L.pid);
    }
    return slip.length >= size || (relax >= 4 && slip.length) ? slip : null;
  });
}
// Builders use the game simulation (Thomas, 2026-11-21): each next leg is chosen from the next few legs that fit (LINK_W, in
// the mode's order) by its chance given the slip's other legs from its game (goalie saves rise with the other team's shots,
// and so on). The mode's own leg stays first unless another one is at least half a point better after the links. Legs from
// different games are unaffected. Same rule as parlays.py linked_pick().
const LINK_W = 6, LINK_EPS = 0.005;
const simLink = (a, b) => (window.GameSim && GameSim.ready('nhl') && GameSim.nhl.link ? GameSim.nhl.link(a, b, D.legs || [], (l) => SIM_POS[String(l.pid)]) : 1);
function linkedPick(c, slip, metric, link) {
  if (!slip.length || c.length < 2) return c[0];
  const gain = (L) => { let r = 1; for (const x of slip) if (x.game === L.game) r *= link(L, x); return Math.min(1, L.p * r) - L.p; };   // extra chance
  let best = c[0], bg = gain(best);
  for (const L of c.slice(1)) { const g = gain(L); if (g > bg + LINK_EPS && metric(L) + g > metric(best) + bg + LINK_EPS) { best = L; bg = g; } }
  return best;
}
// growth score: Kelly bankroll growth of the slip, with each leg's chance cut 2 points for model error
// Game simulation (board/site/sim.js, Thomas 2026-11-19): same-game legs are drawn together with correlations measured on
// past NHL games (goalie saves rise with the other team's shots and with his team winning, etc.); different games multiply
const SIM_POS = Object.fromEntries((D.players || []).map((x) => [String(x.id), x.pos]));
const simOf = (ls, shade = 0) => (window.GameSim && GameSim.ready('nhl') ? GameSim.nhl.parlay(ls, D.legs || [], (l) => SIM_POS[String(l.pid)], shade) : null);
function growth(ids) {
  const sm = simOf(ids.map((id) => LEG[id]), 0.02);
  const p = sm ? sm.p : ids.reduce((a, id) => a * Math.max(0.01, LEG[id].p - 0.02), 1), b = ids.reduce((a, id) => a * dec(LEG[id].price), 1) - 1;
  const f = (b * p - (1 - p)) / b; if (f <= 0) return 0;
  return p * Math.log(1 + f * b) + (1 - p) * Math.log(1 - f);
}
// Legs picker (Thomas, 2026-11-19): any size from 1 to 12 from a menu. A size the usual rules can't fill is still built, with the
// next-best legs (relax levels in buildSlips); those legs are marked and warned about. ★ marks the best size among the usual ones.
const MAX_PICK = 12;
let SIZES = [], BEST = null, OK_SIZES = new Set(), FILL = 0;
// best parlay size by growth; when no parlay has positive growth (or none can be built), suggest a straight bet
function sizesFor() {
  OK_SIZES = new Set(Array.from({ length: MAX_PICK }, (_, i) => i + 1).filter((k) => buildSlips(k, 1).length));
  SIZES = [...OK_SIZES].filter((k) => k <= MAX_LEGS);
  const PS = SIZES.filter((k) => k > 1 && growth(buildSlips(k, 1)[0]) > 0);
  BEST = PS.length ? PS.reduce((a, k) => (growth(buildSlips(k, 1)[0]) > growth(buildSlips(a, 1)[0]) ? k : a), PS[0]) : SIZES.includes(1) ? 1 : null;
}
sizesFor();
const sizeName = (k) => (k === 1 ? 'Straight' : String(k));
let legCount = null;
try { legCount = +localStorage.getItem('nhl-legs') || null; } catch (e) {}
if (!(legCount >= 1 && legCount <= MAX_PICK)) legCount = BEST || 1;
let SLIPS = [];
const setMode = (m) => {
  mode = m; POOL = m === 'likely' ? LIKELY_POOL : VALUE_POOL; try { localStorage.setItem('nhl-mode', m); } catch (e) {}
  sizesFor(); if (!legCount) legCount = BEST || 1;
};
const setSize = (k) => { legCount = k; try { localStorage.setItem('nhl-legs', k); } catch (e) {} SLIPS = !k ? [] : slipsFor(k); };
// the first relax level that builds at least one slip of k legs (FILL says which); the saved suggestions as a last resort
function slipsFor(k) {
  for (let r = 0; r <= 4; r++) { const s = buildSlips(k, 6, r); if (s.length) { FILL = r; return s; } }
  FILL = 0; return D.slips || [];
}
const sizeOpt = (k) => (k === 1 ? '1 · straight bet' : `${k} legs`) + (k === BEST ? ' ★' : '') + (OK_SIZES.has(k) ? '' : ' ⚠');
setSize(legCount);
let sugIdx = -1;   // which suggestion is loaded (-1 = own slip)
let saved = [];
try { saved = JSON.parse(localStorage.getItem('nhl-saved-' + D.day) || '[]').map((s) => ({ ...s, legs: s.legs.filter((id) => LEG[id]) })).filter((s) => s.legs.length); } catch (e) { saved = []; }
const saveSaved = () => { try { localStorage.setItem('nhl-saved-' + D.day, JSON.stringify(saved)); } catch (e) {} };
const loadSug = (i) => { sugIdx = (i + SLIPS.length) % SLIPS.length; slip = SLIPS[sugIdx].slice(); saveSlip(); render(); };
const hasLines = (k) => SRC(k).some((p) => p[k] && p[k].line != null);
const hasProps = hasLines('sog') || hasLines('saves');
if (!hasProps) state.sort = 'proj';

const nLegs = (k) => `${k} leg${k === 1 ? '' : 's'}`;
// warning under the Legs menu when the chosen size needs next-best legs or goes past the usual cap
function fillWarn() {
  const t = [];
  const got = SLIPS.length ? SLIPS[0].length : 0;
  if (FILL >= 4) t.push(`Only ${got} leg${got === 1 ? '' : 's'} can go in one slip on this slate, so this parlay has ${got}, not ${nLegs(legCount)}.`);
  else if (FILL) t.push(`Not enough legs meet the usual bar for ${nLegs(legCount)}, so this parlay is filled with ${fillHow()} (marked ⚠ below)${HAS_ALT ? '' : '. No alt lines are on this board yet'}${FILL >= 2 ? ', with more legs from the same game, market or player than usual' : ''}. Expect a lower hit chance and value.`);
  if (legCount > MAX_LEGS) t.push(`${nLegs(legCount)} is past the usual ${MAX_LEGS}-leg cap: every extra leg multiplies the chance of a miss.`);
  if (!t.length) return null;
  const ul = el('ul', 'warns'); ul.style.paddingTop = '8px'; ul.style.paddingBottom = '0'; t.forEach((x) => ul.append(el('li', 'warn', '⚠ ' + x))); return ul;
}
// legs of a loaded suggestion that came from the next-best fill, not the usual pool
const fillers = (legs) => { if (sugIdx < 0 || !FILL) return new Set(); const u = new Set(usualPool(legCount).map((L) => L.id)); return new Set(legs.filter((L) => !u.has(L.id)).map((L) => L.id)); };

function header() {
  $('eyebrow').textContent = `NHL · ${D.dayLabel}`;
  $('lede').textContent = 'Tonight\'s winners, puck lines and totals, plus shots on goal and goalie saves, set against DraftKings. Chances blend the model with the book; pick a game, open a player for his game log, or build a parlay.';
  const t = $('tabs'); t.innerHTML = '';
  TABS.forEach(([k, label]) => { const b = el('button', 'tab', label); b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', state.tab === k); b.onclick = () => { state.tab = k; render(); }; t.append(b); });
}

function strip() {
  const s = $('games'); s.innerHTML = '';
  s.style.display = state.tab === 'record' || state.tab === 'parlay' ? 'none' : '';
  const mk = (id, m, sub) => { const b = el('button', 'game'); b.setAttribute('aria-pressed', state.game === id); b.append(el('span', 'm', m), el('span', 't', sub)); b.onclick = () => { state.game = id; render(); }; s.append(b); };
  mk('all', 'All games', `${D.games.length} tonight`);
  D.games.forEach((g) => mk(g.game, g.game, g.tip));
}

function bar() {
  const show = STATS.some(([k]) => k === state.tab);
  $('bar').style.display = show ? '' : 'none'; $('legend').style.display = show ? '' : 'none';
  if (!show) return;
  const pos = $('pos'); pos.innerHTML = '';
  $('pos').style.display = state.tab === 'saves' ? 'none' : '';
  [['all', 'All'], ['F', 'Forwards'], ['D', 'Defense']].forEach(([k, l]) => { const b = el('button', null, l); b.setAttribute('aria-pressed', state.pos === k); b.onclick = () => { state.pos = k; render(); }; pos.append(b); });
  const so = $('sort');
  if (!so.options.length) {
    [['edge', 'Best edge'], ['proj', 'Projection'], ['chance', 'Highest chance'], ['name', 'Name']].forEach(([k, l]) => so.append(new Option(l, k)));
    so.onchange = () => { state.sort = so.value; render(); };
    $('q').oninput = (e) => { state.q = e.target.value.toLowerCase(); render(); };
  }
  so.value = state.sort;
  const lg = $('legend'); lg.innerHTML = '';
  const i1 = el('i'); i1.style.cssText = 'width:22px;height:8px;background:var(--bar);border-radius:3px';
  const i2 = el('i'); i2.style.cssText = 'width:3px;height:12px;background:var(--turf)';
  const i3 = el('i'); i3.style.cssText = 'width:2px;height:14px;background:var(--tick)';
  [[i1, 'Likely range (10th to 90th percentile)'], [i2, 'Projection'], [i3, 'DraftKings line']].forEach(([i, t]) => { const s = el('span'); s.append(i, t); lg.append(s); });
}

function bestSide(pr) {
  const c = [pr.over, pr.under].filter(Boolean);
  if (!c.length) return null;
  return c.reduce((a, b) => (b.edge > a.edge ? b : a));
}

function propRows(k) {
  let ps = SRC(k).filter((p) => p[k]);
  if (state.game !== 'all') ps = ps.filter((p) => p.game === state.game);
  if (state.pos !== 'all' && k !== 'saves') ps = ps.filter((p) => p.pos === state.pos);
  if (state.q) ps = ps.filter((p) => (p.name + ' ' + p.team).toLowerCase().includes(state.q));
  if (hasLines(k)) ps = ps.filter((p) => p[k].line != null);
  const key = { edge: (p) => -((bestSide(p[k]) || {}).edge ?? -99), proj: (p) => -p[k].proj, chance: (p) => -((bestSide(p[k]) || {}).p ?? (p[k].ch ? p[k].ch['3+'] : 0)), name: (p) => p.name };
  const f = key[state.sort] || key.proj;
  return ps.sort((a, b) => { const x = f(a), y = f(b); return x < y ? -1 : x > y ? 1 : 0; });
}

function meter(pr) {
  const max = Math.max(pr.hi, pr.line || 0) * 1.12 || 1;
  const m = el('div', 'meter'); const tr = el('div', 'track');
  const r = el('div', 'range'); r.style.left = (pr.lo / max * 100) + '%'; r.style.width = ((pr.hi - pr.lo) / max * 100) + '%';
  const mk = el('div', 'mark'); mk.style.left = (pr.proj / max * 100) + '%';
  tr.append(r, mk);
  if (pr.line != null) { const ln = el('div', 'line'); ln.style.left = (pr.line / max * 100) + '%'; tr.append(ln); }
  const l = el('div', 'l'); const a = el('span'); a.append(el('b', null, pr.proj.toFixed(1)), document.createTextNode(' proj'));
  l.append(a, el('span', null, pr.line != null ? `line ${pr.line}` : `${Math.round(pr.lo)}–${Math.round(pr.hi)}`));
  m.append(tr, l); return m;
}

function boardProps(k) {
  const B = $('board'); B.innerHTML = '';
  const rows = propRows(k);
  $('count').textContent = `${rows.length} ${k === 'saves' ? 'goalies' : 'players'}`;
  const col = el('div', 'col');
  const h = el('div', 'colhead'); h.append(el('h2', null, SL[k]), el('span', null, hasLines(k) ? 'Lean side and DraftKings price' : 'DraftKings prop lines not pulled for this slate'));
  col.append(h);
  if (!rows.length) col.append(el('div', 'empty', 'No players match.'));
  rows.forEach((p) => {
    const pr = p[k]; const best = bestSide(pr);
    const row = el('div', 'row');
    const who = el('div', 'who'); const nb = el('button', 'namebtn', p.name); nb.onclick = () => openLog(p, k);
    const sub = k === 'saves' ? `${p.team} vs ${p.opp} · ${p.confirmed ? 'confirmed starter' : 'projected starter'} · save rate ${pr.sv.toFixed(3).slice(1)}` : `${p.team} ${p.pos} vs ${p.opp} · ${p.toi} min${p.avg != null ? ' · ' + p.avg + ' shots/game this season' : ''}`;
    who.append(nb, el('span', 's', `${sub}${p.flags.length ? ' · ' + p.flags.join('; ') : ''}`));
    const price = el('div', 'price');
    if (best) {
      const side = best === pr.over ? 'Over' : 'Under';
      const sd = el('span', 'side ' + side.toLowerCase(), `${side} ${pr.line}`);
      price.append(sd, el('span', 'o', fmt(best.price)), el('span', 'e ' + (best.edge > 0 ? 'pos' : 'neg'), `${pct(best.p)} · edge ${sgn(best.edge)}`));
      const L = LEG[best.id];
      if (L && L.cat === 'Value') price.append(el('span', 'pill value', 'Value'));
      if (L) { price.append(LineEdit.btn(L)); if (p.edited) price.append(el('span', 'le-tag', '✎ your line')); }
    } else {
      price.append(el('span', 'o dim', pr.proj.toFixed(1)), el('span', 'e dim', pr.ch ? `3+ shots ${pct(pr.ch['3+'])}` : `proj saves`));
    }
    row.append(who, meter(pr), price); col.append(row);
  });
  B.append(col);
  $('foot').textContent = hasLines(k) ? `Props from DraftKings, pulled ${D.propsTaken || ''}. Chance = half model, half DraftKings no-vig. Edge = chance minus the price's break-even, in points. Value = edge 3+ and chance 55%+ with no flag. In testing, shots-on-goal edges came almost all from Unders.` :
    'DraftKings prop lines have not been pulled for this slate, so this shows projections and the model\'s chances only. Pulling shots on goal and saves costs about 2 Odds API credits per game.';
}

function boardGames() {
  const B = $('board'); B.innerHTML = '';
  const wrap = el('div', 'gcards');
  let gs = D.games; if (state.game !== 'all') gs = gs.filter((g) => g.game === state.game);
  if (!gs.length) wrap.append(el('div', 'empty', 'No games on this slate.'));
  gs.forEach((g) => {
    const c = el('div', 'col gcard');
    const h = el('div', 'colhead'); h.append(el('h2', null, g.game), el('span', null, g.tip)); c.append(h);
    const pj = el('div', 'proj');
    const gk = (n, okk) => n ? `${n}${okk ? '' : ' (projected)'}` : 'unknown';
    [[g.pick ? `${g.pick} ${pct(g.pick_p)}` : '—', 'Pick to win'], [`${g.xg_away.toFixed(1)} – ${g.xg_home.toFixed(1)}`, 'Model goals, away – home'], [g.total.toFixed(1), 'Model total'],
     [g.line_total ?? '—', 'DK total']].forEach(([v, k]) => { const d = el('div'); d.append(el('b', null, v), el('span', null, k)); pj.append(d); });
    c.append(pj);
    c.append(el('div', 'outs', `Goalies: ${g.away} ${gk(g.gk_away, g.gk_away_ok)}; ${g.home} ${gk(g.gk_home, g.gk_home_ok)}.`));
    if (g.legs.length) {
      const tw = el('div', 'tablewrap'); const t = el('table', 'res');
      const hr = el('tr'); ['Bet', 'DK', 'Chance', 'Edge', ''].forEach((x, i) => hr.append(el('th', i ? 'num' : null, x))); t.append(hr);
      g.legs.map((id) => LEG[id]).forEach((L) => {
        const tr = el('tr'); if (L.cat === 'Value') tr.className = 'hl';
        const lab = el('td', null, `${L.kind}: ${L.label}`); { const tg = LineEdit.tag(L); if (tg) lab.append(tg); }
        tr.append(lab, el('td', 'num', fmt(L.price)), el('td', 'num', pct(L.p)), el('td', 'num ' + (L.edge > 0 ? 'pos' : 'neg'), sgn(L.edge)));
        const td = el('td', 'num lecell'); td.append(addBtn(L.id), LineEdit.btn(L)); tr.append(td); t.append(tr);
      });
      tw.append(t); c.append(tw);
    } else c.append(el('div', 'outs', 'DraftKings lines not posted yet.'));
    const outs = [...g.out_away.map((o) => `${g.away}: ${o}`), ...g.out_home.map((o) => `${g.home}: ${o}`)];
    if (outs.length) c.append(el('div', 'outs', `Out (ESPN injury report): ${outs.join(', ')}.`));
    wrap.append(c);
  });
  B.append(wrap);
  const w = D.weights;
  $('foot').textContent = `Pick to win = the side with the higher blended chance (moneyline ${w.Moneyline * 100}% model, ${100 - w.Moneyline * 100}% DraftKings no-vig). Puck lines and totals lean on DraftKings (${w['Puck line'] * 100}% model) because the model did not beat them in testing. Goalies are ESPN's probable starters; "projected" means not yet listed, so it uses the team's most-used goalie lately. Box scores through ${D.through}.`;
}

function addBtn(id) {
  const on = slip.includes(id);
  const b = el('button', 'add' + (on ? ' on' : ''), on ? 'Added' : 'Add');
  b.onclick = () => { slip = on ? slip.filter((x) => x !== id) : slip.concat(id); sugIdx = -1; saveSlip(); render(); };
  return b;
}

function boardParlay() {
  const B = $('board'); B.innerHTML = '';
  const cols = el('div', 'cols pl');
  const list = el('div', 'col');
  const h = el('div', 'colhead'); h.append(el('h2', null, 'Legs'), el('span', null, mode === 'likely' ? 'Ranked by chance to hit, DraftKings prices' : 'Ranked by edge, DraftKings prices')); list.append(h);
  const ctl = el('div', 'plctl');
  const q = el('input'); q.type = 'search'; q.placeholder = 'Search legs'; q.value = state.pq; q.oninput = (e) => { state.pq = e.target.value.toLowerCase(); drawList(); };
  const kl = el('span', 'dim seglab', 'Markets: tap one or more');
  const kinds = el('div', 'seg'); kinds.setAttribute('aria-label', 'Markets (pick one or more)');
  [['all', 'All']].concat(MKTS.map((k) => [k, k])).forEach(([k, l]) => {
    const b = el('button', null, l); b.setAttribute('aria-pressed', k === 'all' ? !KINDS.size : KINDS.has(k));
    b.onclick = () => {
      if (k === 'all') KINDS.clear(); else if (KINDS.has(k)) KINDS.delete(k); else KINDS.add(k);
      try { localStorage.setItem('nhl-kinds', JSON.stringify([...KINDS])); } catch (e) {}
      sizesFor(); if (!legCount) legCount = BEST || 1; setSize(legCount); sugIdx = -1; render();
    };
    kinds.append(b);
  });
  const mins = el('div', 'seg'); [[0.25, '25%+'], [0.4, '40%+'], [0.55, '55%+']].forEach(([k, l]) => { const b = el('button', null, l); b.setAttribute('aria-pressed', state.pmin === k); b.onclick = () => { state.pmin = k; render(); }; mins.append(b); });
  ctl.append(q, kl, kinds, mins); list.append(ctl);
  const pl = el('div', 'pllist'); list.append(pl);
  function drawList() {
    pl.innerHTML = '';
    let ls = D.legs.filter((l) => l.p >= state.pmin);
    ls = ls.filter(kindOk);
    if (state.pq) ls = ls.filter((l) => (l.label + ' ' + l.game).toLowerCase().includes(state.pq));
    ls.sort(mode === 'likely' ? (a, b) => (b.edge >= 1) - (a.edge >= 1) || b.p - a.p : (a, b) => b.edge - a.edge);
    if (!ls.length) pl.append(el('div', 'empty', 'No legs match.'));
    const row = (L) => {
      const r = el('div', 'leg'); const who = el('div', 'who');
      who.append(legLabel(L, 'n'), el('span', 's', `${L.kind} · ${L.game}${L.flags.length ? ' · ' + L.flags.join('; ') : ''}`));
      const sb = el('div', 'sidebox'); sb.append(el('span', 'o', fmt(L.price)), el('span', 'e ' + (L.edge > 0 ? 'pos' : 'neg'), `${pct(L.p)} · ${sgn(L.edge)}`));
      r.append(who, sb, addBtn(L.id)); return r;
    };
    // phones and tablets: one tap-to-open section per market, so you can jump between markets without scrolling past every leg
    if (matchMedia('(max-width: 1024px)').matches) {
      const ks = MKTS.filter((k) => ls.some((L) => L.kind === k));
      ks.forEach((k) => {
        const gl = ls.filter((L) => L.kind === k), lim = GLIM[k] || 25;
        const d = el('details', 'mgrp'); d.open = OPEN.has(k) || ks.length === 1 || !!state.pq;
        const sm = el('summary'); sm.append(el('span', 'mname', k), el('span', 'dim', `${gl.length} leg${gl.length > 1 ? 's' : ''} · best ${mode === 'likely' ? pct(gl[0].p) : sgn(gl[0].edge)}`));
        d.append(sm); d.ontoggle = () => { if (d.open) OPEN.add(k); else OPEN.delete(k); };
        gl.slice(0, lim).forEach((L) => d.append(row(L)));
        if (gl.length > lim) { const m = el('button', 'lnk more', `Show more ${k} (${gl.length - lim} left)`); m.type = 'button'; m.onclick = () => { GLIM[k] = lim + 25; OPEN.add(k); drawList(); }; d.append(m); }
        pl.append(d);
      });
      return;
    }
    ls.slice(0, 200).forEach((L) => pl.append(row(L)));
  }
  drawList();
  const sl = el('div', 'col slip');
  const sh = el('div', 'colhead'); sh.append(el('h2', null, 'Slip'));
  const acts = el('span', 'acts');
  const clr = el('button', 'lnk', 'Clear'); clr.onclick = () => { slip = []; sugIdx = -1; saveSlip(); render(); };
  acts.append(clr); sh.append(acts); sl.append(sh);
  {
    const md = el('div', 'sugnav');
    md.append(el('b', null, 'Build for'));
    const seg = el('div', 'seg');
    [['value', 'Best value'], ['likely', 'Most likely to hit']].forEach(([k, l]) => { const b = el('button', null, l); b.setAttribute('aria-pressed', mode === k); b.onclick = () => { setMode(k); setSize(legCount); if (SLIPS.length) loadSug(0); else { sugIdx = -1; render(); } }; seg.append(b); });
    md.append(seg);
    md.append(el('span', 'dim sugbest', (mode === 'likely' ? 'Highest-chance legs: board winner picks plus legs 55%+ to hit at DraftKings\' usual juice or better, nothing shorter than -200, up to 3 legs. A shaky Over swaps to a safer alt line' : 'Value first: shots on goal with expected value 3%+, game lines with edge 3+ and 55%+ chance (saves don\'t count), nothing shorter than -200') + (KINDS.size ? `. Only ${[...KINDS].join(' + ')} legs (market filter).` : '')));
    sl.append(md);
  }
  if (D.legs.length) {
    const lc = el('div', 'sugnav');
    lc.append(el('b', null, 'Legs'));
    const sel = el('select', 'legsel'); sel.setAttribute('aria-label', 'Number of legs');
    for (let k = 1; k <= MAX_PICK; k++) sel.append(new Option(sizeOpt(k), k));
    sel.value = legCount; sel.onchange = () => { setSize(+sel.value); if (SLIPS.length) loadSug(0); else { sugIdx = -1; render(); } };
    lc.append(sel);
    lc.append(el('span', 'dim sugbest', (BEST == null ? 'No leg meets the usual bar tonight' : BEST === 1 ? '★ No parlay is worth it tonight: take a straight bet' : `★ ${BEST} legs is best tonight`) + '. ⚠ = needs alt lines or next-best legs.'));
    sl.append(lc);
    const fw = fillWarn(); if (fw) sl.append(fw);
  }
  if (SLIPS.length) {
    const nav = el('div', 'sugnav');
    const prev = el('button', 'lnk', '‹'); prev.setAttribute('aria-label', 'Previous suggestion'); prev.onclick = () => loadSug(sugIdx < 0 ? SLIPS.length - 1 : sugIdx - 1);
    const lab = el('span', 'suglab', sugIdx >= 0 ? `${legCount === 1 ? 'Straight bet' : 'Suggestion'} ${sugIdx + 1} of ${SLIPS.length}` : `${SLIPS.length} suggested parlays`);
    const next = el('button', 'lnk', '›'); next.setAttribute('aria-label', 'Next suggestion'); next.onclick = () => loadSug(sugIdx + 1);
    const shuf = el('button', 'lnk sugb', sugIdx < 0 ? 'Load suggested' : 'Shuffle');
    shuf.onclick = () => { if (sugIdx < 0 || SLIPS.length < 2) return loadSug(0); let k = sugIdx; while (k === sugIdx) k = Math.floor(Math.random() * SLIPS.length); loadSug(k); };
    nav.append(prev, lab, next, shuf); sl.append(nav);
  }
  if (saved.length || slip.length) {
    const sv = el('div', 'savedrow');
    if (slip.length) {
      const sb = el('button', 'lnk', 'Save this slip');
      sb.onclick = () => { const key = slip.slice().sort().join('|'); if (!saved.some((s) => s.legs.slice().sort().join('|') === key)) { saved.push({ name: sugIdx >= 0 ? `Suggestion ${sugIdx + 1}` : `My slip ${saved.length + 1}`, legs: slip.slice() }); saveSaved(); } render(); };
      sv.append(sb);
    }
    saved.forEach((s, i) => {
      const on = s.legs.slice().sort().join('|') === slip.slice().sort().join('|');
      const c = el('button', 'chip', s.name); c.setAttribute('aria-pressed', on); c.onclick = () => { slip = s.legs.slice(); sugIdx = -1; saveSlip(); render(); };
      const x = el('button', 'x', '×'); x.setAttribute('aria-label', 'Delete ' + s.name); x.onclick = () => { saved.splice(i, 1); saveSaved(); render(); };
      const w = el('span', 'savedchip'); w.append(c, x); sv.append(w);
    });
    sl.append(sv);
  }
  const legs = slip.map((id) => LEG[id]).filter(Boolean);
  if (!legs.length) sl.append(el('div', 'empty', SLIPS.length ? 'Add legs, or load a suggested parlay. Use the arrows or Shuffle to flip between suggestions, and Save to keep one.' : mode === 'likely' ? 'Add legs from the list. No leg is 55%+ to hit at -200 or longer on this slate.' : 'Add legs from the list. No leg meets the value rule on this slate.'));
  const box = el('div', 'slipl'), FL = fillers(legs);
  legs.forEach((L) => { const d = el('div'); const n = el('span'); n.append(legLabel(L), el('small', null, `${L.game} · ${pct(L.p)}`)); if (FL.has(L.id)) { const m = el('small', null, L.alt ? '⚠ Alt line, added to fill the slip' : '⚠ Next-best leg, below the usual bar'); m.style.color = 'var(--gold)'; n.append(m); } { const t = LineEdit.tag(L); if (t) n.append(t); n.append(LineEdit.btn(L)); } const x = el('button', 'x', '×'); x.setAttribute('aria-label', 'Remove'); x.onclick = () => { slip = slip.filter((i) => i !== L.id); sugIdx = -1; saveSlip(); render(); }; d.append(n, el('span', 'num', fmt(L.price)), x); box.append(d); });
  if (legs.length) {
    sl.append(box);
    { const bn = LineEdit.banner(); if (bn) sl.append(bn); }
    const pInd = legs.reduce((a, l) => a * l.p, 1), sim = simOf(legs), p = sim ? sim.p : pInd, d = legs.reduce((a, l) => a * dec(l.price), 1), ev = p * d - 1;
    const simd = sim && sim.groups.length, sgOf = Object.fromEntries(((sim && sim.groups) || []).map((x) => [x.game, x]));
    const st = el('div', 'stats pad');
    [[pct(p), simd ? `Hit chance (simulated; ${pct(pInd)} if independent)` : 'Hit chance'], [fmt(toAm(d)), 'Payout'], [sgn(Math.round(ev * 100)) + '%', 'Expected value']].forEach(([v, k]) => { const s = el('div', 'stat'); s.append(el('b', null, v), el('span', null, k)); st.append(s); });
    sl.append(st);
    // DraftKings betslip link: every leg's DraftKings outcome id, so the slip opens in DraftKings ready to place
    const sids = legs.filter((l) => !started(l.game)).map((l) => l.sid).filter(Boolean);
    const dk = el('div', 'dkrow');
    if (sids.length) {
      const a = el('a', 'lnk sugb dkbtn', sids.length === legs.length ? 'Open in DraftKings' : `Open ${sids.length} of ${legs.length} legs in DraftKings`);
      a.href = 'https://sportsbook.draftkings.com/?outcomes=' + sids.map(encodeURIComponent).join('+'); a.target = '_blank'; a.rel = 'noopener';
      dk.append(a, el('span', 'dim', sids.length === legs.length ? 'Loads these legs into your DraftKings betslip. Sign in, check the prices, and place it.' : 'The other legs have no DraftKings link (game started, or none on this pull); add them by hand.'));
    } else dk.append(el('span', 'dim', 'No DraftKings link for these legs yet: links come with the next odds pull.'));
    sl.append(dk);
    // Share (Thomas, 2026-11-19): a compact card of the slip for a screenshot or a text (board/site/share.js)
    const shr = el('div', 'dkrow'), shb = el('button', 'lnk sugb', 'Share slip'); shb.type = 'button';
    shb.onclick = () => window.shareSlip && window.shareSlip({ title: `NHL · ${legs.length === 1 ? 'straight bet' : legs.length + '-leg parlay'}`,
      legs: legs.map((l) => ({ label: l.label, sub: l.game, odds: fmt(l.price), tag: [FL.has(l.id) ? '⚠ ' + fillTag(l) : '', LineEdit.shareTag(l)].filter(Boolean).join(' · ') })),
      odds: fmt(toAm(d)), chance: pct(p), pays: '$' + (10 * d).toFixed(2),
      warn: FL.size ? `⚠ ${fillWords(legs.filter((l) => FL.has(l.id)))} added to fill the slip` : '' });
    shr.append(shb, el('span', 'dim', 'A compact card of this slip to screenshot or send to a friend.')); sl.append(shr);
    const games = {}; legs.forEach((l) => { games[l.game] = (games[l.game] || 0) + 1; });
    const warns = [];
    Object.entries(games).filter(([, n]) => n > 1).forEach(([g, n]) => {
      const bad = legs.filter((l) => l.game === g && NO_SGP.has(l.kind));
      if (bad.length) warns.push(['bad', `DraftKings won't put goalie saves in a same-game parlay: ${bad.map((l) => l.label).join(', ')} can't be combined with the other ${g} leg${n > 2 ? 's' : ''}. Keep one leg from that game.`]);
      else { const x = sgOf[g], r = x ? x.p / Math.max(1e-9, x.pInd) : 1;
        warns.push(['warn', `${n} legs from ${g}: ${x ? `the game simulation puts them at ${pct(x.p)} to all hit, ${r >= 1.05 ? 'more than' : r <= 0.95 ? 'less than' : 'about the same as'} the ${pct(x.pInd)} from multiplying them. ` : ''}DraftKings prices same-game legs together, so the real payout differs from the legs multiplied.`]); }
    });
    legs.filter((l) => started(l.game)).forEach((l) => warns.push(['bad', `${l.game} has started: DraftKings has pulled its pregame lines, so ${l.label} won't load. Swap it out.`]));
    { const fa = legs.filter((l) => FL.has(l.id) && l.alt), fb = legs.filter((l) => FL.has(l.id) && !l.alt);
      if (fa.length) warns.push(['warn', `Alt lines, added to reach ${nLegs(legCount)}: ${fa.map((l) => l.label).join(', ')}. Likelier to hit, but they pay less and aren't the board's usual picks.`]);
      if (fb.length) warns.push(['warn', `Next-best legs, added to reach ${nLegs(legCount)}: ${fb.map((l) => l.label).join(', ')}. They miss the usual bar for ${mode === 'likely' ? 'Most likely to hit' : 'Best value'}.`]); }
    legs.filter((l) => l.edge < 0).forEach((l) => warns.push(['bad', `${l.label} has negative edge.`]));
    legs.filter((l) => l.flags.length).forEach((l) => warns.push(['warn', `${l.label}: ${l.flags.join('; ')}.`]));
    const good = ev > 0 && !warns.some((w) => w[0] === 'bad');
    const v = el('div', 'verdict ' + (good ? 'good' : ev > -0.1 ? 'warn' : 'bad'));
    v.append(el('b', null, good ? 'Positive expected value' : ev > -0.1 ? 'Close to break-even' : 'Long shot'), el('span', null, `${legs.length} leg${legs.length > 1 ? "s" : ""}. ${simd ? 'Same-game legs use the game simulation; different games multiply.' : 'Legs from different games are independent, so the chance multiplies them.'}`));
    sl.append(v);
    if (warns.length) { const ul = el('ul', 'warns'); warns.forEach(([c, t]) => ul.append(el('li', c, t))); sl.append(ul); }
  }
  cols.append(list, sl); B.append(cols);
  $('foot').textContent = 'Parlay chance: legs from the same game come from a game simulation (20,000 draws with correlations measured on 1,279 past games with DraftKings lines). NHL legs are close to independent except goalie saves, which rise with the other team\'s shots on goal and with his own team winning; legs from different games multiply. Edge is the leg\'s chance minus the break-even of its DraftKings price, in percentage points. Ranking by edge rather than payout keeps long shots from crowding the top. ★ marks the leg count whose top suggestion grows a bankroll fastest (Kelly growth, with each leg\'s chance cut 2 points for model error): more legs raise the payout, but every leg compounds the chance of being wrong. Your slip is saved in this browser.';
}

function boardRecord() {
  const B = $('board'); B.innerHTML = '';
  const M = recordMenus({ sport: 'nhl', src: D.live, rerender: boardRecord,
    views: [['all', 'Everything'], ['bets', 'Bets'], ['parlays', 'Parlays'], ['chance', 'Chance check'], ['tests', 'Backtests']] });
  B.append(M.bar);
  const LV = M.rep;
  if (LV && (LV.cal_sections || []).length && M.show('chance')) { const cw = renderCalibration(LV.cal_sections); cw.style.marginBottom = '8px'; B.append(cw); }
  const bt = D.backtest || {}; const lv = LV;
  const fmtp = (x) => x == null ? '—' : (x * 100).toFixed(1) + '%';
  const roi = (x) => x == null ? '—' : sgn(Math.round(x * 1000) / 10) + '%';
  const mk = (title, head, rows, note) => { const c = el('div', 'col'); c.style.marginTop = '16px'; const h = el('div', 'colhead'); h.append(el('h2', null, title)); c.append(h); const tw = el('div', 'tablewrap'); const t = el('table', 'res'); const hr = el('tr'); head.forEach((x, i) => hr.append(el('th', i ? 'num' : null, x))); t.append(hr); rows.forEach((r) => { const tr = el('tr'); r.forEach((x, i) => tr.append(el('td', i ? 'num' : null, String(x)))); t.append(tr); }); tw.append(t); c.append(tw); if (note) c.append(el('p', 'note logfoot', note)); B.append(c); };
  if (M.period && !(lv && lv.groups && lv.groups.length) && !(lv && lv.parlays && lv.parlays.groups.some((g) => g.bets))) B.append(el('div', 'empty', `Nothing graded for ${M.label} yet.`));
  if (lv && lv.groups && lv.groups.length && M.show('bets')) {
    mk('Live record at DraftKings', ['Group', 'Bets', 'W-L', 'Hit', 'Units', 'ROI'], lv.groups.map((g) => [g.group, g.bets, `${g.won}-${g.lost}`, fmtp(g.hit), sgn(g.units), roi(g.roi)]),
       `${lv.days.length} slate${lv.days.length > 1 ? 's' : ''} graded. Every priced leg is logged when the board is built and graded at that DraftKings price, 1 unit per leg.`);
  }
  const pz = lv && lv.parlays && lv.parlays.groups.filter((g) => g.bets);
  if (pz && pz.length && M.show('parlays')) mk('Suggested parlays at DraftKings', ['Parlays', 'Count', 'W-L', 'Hit', 'Expected', 'Units', 'ROI'], pz.map((g) => [g.group, g.bets, `${g.won}-${g.lost}`, fmtp(g.hit), fmtp(g.exp_hit), sgn(g.units), roi(g.roi)]),
     'Each day\'s suggested parlays are saved when the board is built, for both Best value and Most likely to hit and every leg count (up to 6 suggestions each a day; fewer on a slate without enough qualifying legs, and from Nov 15 a leg can repeat in up to 3 suggestions so the 6 fill more often), and graded as whole parlays at DraftKings prices, 1 unit each. A parlay loses if any leg loses; pushed or voided legs drop out. Expected is the chance the board gave the parlays.');
  if (!M.show('tests')) { $('foot').textContent = 'Every priced leg is graded at the DraftKings price the board showed, 1 unit per leg. Grading uses free box scores, so it costs no odds credits.'; return; }
  if (bt.winners) {
    const rows = []; Object.entries(bt.winners).forEach(([se, r]) => { [['model', 'Model'], ['blend', 'Board pick (blend)'], ['draftkings', 'DraftKings favorite']].forEach(([k, l]) => rows.push([`${se.slice(0, 4)}-${se.slice(6)}`, l, r.games, fmtp(r[k].all), r[k].conf60 ? `${fmtp(r[k].conf60[1])} (${r[k].conf60[0]})` : '—'])); });
    mk('Picking winners', ['Season', 'Picker', 'Games', 'Correct', 'When 60%+ sure (games)'], rows, 'Hockey is close to a coin flip: even DraftKings\' favorite wins only about 55-62% of the time. When the board is 60%+ sure, its pick wins about two times in three.');
  }
  if (bt.sog) {
    mk('Shots on goal vs real DraftKings lines', ['Test', 'Lines', 'Log loss: model / DK / blend', 'Edge 0+: bets, hit, ROI', 'Edge 3+: bets, hit, ROI'], Object.entries(bt.sog).map(([se, r]) => [se, r.lines, `${r.ll.model.toFixed(4)} / ${r.ll.market.toFixed(4)} / ${r.ll.blend_50.toFixed(4)}`, `${r.b0.bets}, ${fmtp(r.b0.hit)}, ${roi(r.b0.roi)}`, `${r.b3.bets}, ${fmtp(r.b3.hit)}, ${roi(r.b3.roi)}`]),
       'Lower log loss is better. The blend (half model, half DraftKings) beat DraftKings in both tests, and its picks were almost all Unders. Betting every Under blindly lost money, so the model is choosing which Unders. Samples are still small.');
  }
  const gr = [];
  if (bt.saves) gr.push(['Goalie saves (2025-26)', bt.saves.lines, `${bt.saves.ll.model.toFixed(4)} / ${bt.saves.ll.market.toFixed(4)} / ${bt.saves.ll.blend_50.toFixed(4)}`, `${bt.saves.b3.bets} bets edge 3+: ${roi(bt.saves.b3.roi)}`]);
  if (bt.ml) gr.push(['Moneyline (2025-26)', bt.ml.n, `${bt.ml.ll.model.toFixed(4)} / ${bt.ml.ll.market.toFixed(4)} / ${bt.ml.ll.blend_50.toFixed(4)}`, `${bt.ml.b0.bets} bets edge 0+: ${roi(bt.ml.b0.roi)}`]);
  if (bt.pl) gr.push(['Puck line (2025-26)', bt.pl.n, `${bt.pl.ll.model.toFixed(4)} / ${bt.pl.ll.market.toFixed(4)} / ${bt.pl.ll.blend_50.toFixed(4)}`, `model picks: ${roi(bt.pl.b0.roi)}`]);
  Object.entries(bt.totals || {}).forEach(([se, r]) => gr.push([`Totals at close (${se.slice(0, 4)}-${se.slice(6)})`, r.n, `${r.ll.model.toFixed(4)} / ${r.ll.market.toFixed(4)} / ${r.ll.blend_50.toFixed(4)}`, 'DraftKings better']));
  if (gr.length) mk('Other markets', ['Market', 'Lines', 'Log loss: model / DK / blend', 'Betting result'], gr, 'Models are fit only on earlier seasons. Saves and game lines have not shown a reliable edge, so the board leans on DraftKings for them.');
  if (B.children.length <= 1) B.append(el('div', 'empty', 'No backtest yet.'));
  $('foot').textContent = 'Backtests: scripts/nhl_props_backtest.py and scripts/nhl_game_backtest.py.';
}

// a leg's label, tappable to open the player's game log when the leg is a player prop
function legLabel(L, cls) {
  const pl = L.pid ? SRC(L.market).find((x) => x.id === L.pid) : null;
  if (!pl) return el('span', cls, L.label);
  const b = el('button', (cls ? cls + ' ' : '') + 'namebtn', L.label); b.type = 'button'; b.title = 'Game log';
  b.onclick = (e) => { e.stopPropagation(); openLog(pl, L.market, L); }; return b;
}
// the side the popup colors for: a parlay leg's own side and line, else the board's lean on the main line.
// Green = the game supports that side (Thomas, 2026-11-17); no lean -> plain over-the-line coloring.
function logSide(pr, leg) {
  if (leg && leg.side && leg.line != null) return { line: Number(leg.line), side: leg.side };
  if (!pr || pr.line == null) return { line: null, side: null };
  const b = bestSide(pr);
  return { line: pr.line, side: b ? (b === pr.under ? 'Under' : 'Over') : null };
}
const sideHit = (v, s) => (s.side === 'Under' ? v < s.line : v > s.line);
const sideNote = (s, stat) => (s.side ? `Green marks games that would have hit tonight's ${s.side} ${s.line}${stat ? ' ' + stat : ''}.` : `Green marks games over tonight's ${stat ? stat + ' ' : ''}line of ${s.line}.`);
function openLog(p, k, leg) {
  const ov = el('div', 'overlay'); ov.onclick = (e) => { if (e.target === ov) ov.remove(); };
  const pn = el('div', 'logpanel'); pn.setAttribute('role', 'dialog'); pn.setAttribute('aria-label', p.name + ' game log');
  const gkp = k === 'saves';
  const h = el('div', 'loghead'); const t = el('div'); t.append(el('h2', null, p.name), el('div', 'dim', gkp ? `${p.team} goalie · ${p.confirmed ? 'confirmed' : 'projected'} starter` : `${p.team} ${p.pos} · ${p.gp} games this season · ${p.toi} min lately`));
  const x = el('button', 'x', '×'); x.setAttribute('aria-label', 'Close'); x.onclick = () => ov.remove(); h.append(t, x); pn.append(h);
  const pr = p[k]; const S = logSide(pr, leg); const chips = el('div', 'lchips');
  chips.append(el('span', 'pill likely', `proj ${pr.proj}${pr.line != null ? ' · line ' + pr.line : ''}`));
  if (pr.ch) Object.entries(pr.ch).forEach(([c, v]) => chips.append(el('span', 'pill', `${c} shots: ${pct(v)}`)));
  pn.append(chips);
  if (p.flags.length) pn.append(el('div', 'loghit', p.flags.join('; ')));
  const tw = el('div', 'tablewrap'); const tb = el('table', 'res log');
  const cols = gkp ? [['d', 'Date'], ['o', 'Opp'], ['sa', 'Shots'], ['sv', 'Saves'], ['pct', 'SV%']] : [['d', 'Date'], ['o', 'Opp'], ['toi', 'TOI'], ['sog', 'SOG'], ['g', 'G'], ['a', 'A'], ['blk', 'BLK']];
  const key = gkp ? 'sv' : 'sog';
  const hr = el('tr'); cols.forEach(([, c], i) => hr.append(el('th', i > 1 ? 'num' : null, c))); tb.append(hr);
  p.log.forEach((g) => { const tr = el('tr'); cols.forEach(([c], i) => { const v = c === 'pct' && g[c] != null ? g[c].toFixed(3).slice(1) : g[c]; tr.append(el('td', (i > 1 ? 'num' : '') + (c === key && S.line != null && g[c] != null ? (sideHit(g[c], S) ? ' hit' : ' miss') : ''), v ?? '—')); }); tb.append(tr); });
  tw.append(tb); pn.append(tw);
  pn.append(el('p', 'note logfoot', S.line != null ? sideNote(S, '') : `Last ${p.log.length} games.`));
  ov.append(pn); document.body.append(ov);
  x.focus();
  const esc = (e) => { if (e.key === 'Escape') { ov.remove(); document.removeEventListener('keydown', esc); } }; document.addEventListener('keydown', esc);
}

function render() {
  header(); strip(); bar();
  if (state.tab === 'games') boardGames();
  else if (state.tab === 'parlay') boardParlay();
  else if (state.tab === 'record') boardRecord();
  else boardProps(state.tab);
}
render();
