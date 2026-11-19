const D = JSON.parse(document.getElementById('tennis-data').textContent);
// games that have started: DraftKings pulls pregame lines at the start, so their legs leave suggestions and the DraftKings link
const STARTS = {}; (D.matches || []).forEach((g) => { if (g.start) STARTS[g.game] = g.start; });
const started = (game) => !!STARTS[game] && Date.parse(STARTS[game]) <= Date.now();
const LEG = Object.fromEntries(D.legs.map((l) => [l.id, l]));
const TABS = [['games', 'Matches'], ['parlay', 'Parlay builder'], ['ratings', 'Player ratings'], ['record', 'Model record']];
const state = { tab: 'games', game: 'all', filt: 'all', q: '', pmin: 0.25, pq: '', rtour: 'atp' };
const GAME = Object.fromEntries((D.matches || []).map((g) => [g.id, g]));
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const fmt = (o) => o == null ? '—' : (o > 0 ? '+' : '') + o;
const pct = (p) => p == null ? '—' : p < 0.01 ? (p * 100).toFixed(2) + '%' : Math.round(p * 100) + '%';
const sgn = (x) => (x > 0 ? '+' : '') + x;
const dec = (a) => a > 0 ? 1 + a / 100 : 1 + 100 / -a;
const toAm = (d) => d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1));
const $ = (id) => document.getElementById(id);
let slip = [];
try { slip = JSON.parse(localStorage.getItem('tennis-slip-' + D.day) || '[]').filter((id) => LEG[id]); } catch (e) { slip = []; }
const saveSlip = () => { try { localStorage.setItem('tennis-slip-' + D.day, JSON.stringify(slip)); } catch (e) {} };
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
let mode;
// tennis opens on Most likely to hit (Thomas values picks that hit over edge)
mode = 'likely';
try { mode = localStorage.getItem('tennis-mode') === 'value' ? 'value' : 'likely'; } catch (e) {}
let POOL = mode === 'likely' ? LIKELY_POOL : VALUE_POOL;
// market filter: pick any mix of markets (e.g. Points + Assists); none picked = every market. Suggestions follow it.
let KINDS = new Set();
const OPEN = new Set(), GLIM = {};
try { KINDS = new Set(JSON.parse(localStorage.getItem('tennis-kinds') || '[]')); } catch (e) {}
const kindOk = (L) => !KINDS.size || KINDS.has(L.kind);
const MKTS = [...new Set(D.legs.map((L) => L.kind))];
// markets DraftKings won't take in a same-game parlay: such a leg can't share its game with any other leg
const NO_SGP = new Set();
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
  return many(pool, size, n, (pool, size, allowed, cap) => {
    if (relax >= 2) cap = size;
    const slip = [], g = {}, pl = new Set(), fm = {}, sk = new Set();
    for (const L of pool) {
      if (sk.has(sideKey(L))) continue;   // never both sides (or two lines) of one market
      if (!allowed(L) || (g[L.game] || 0) >= perGame || (relax < 3 && L.pid && pl.has(L.pid)) || (fm[fam(L)] || 0) >= cap) continue;
      if ((g[L.game] || 0) && (NO_SGP.has(L.kind) || slip.some((x) => x.game === L.game && NO_SGP.has(x.kind)))) continue;
      slip.push(L); sk.add(sideKey(L)); g[L.game] = (g[L.game] || 0) + 1; fm[fam(L)] = (fm[fam(L)] || 0) + 1; if (L.pid) pl.add(L.pid);
      if (slip.length >= size) return slip;
    }
    return relax >= 4 && slip.length ? slip : null;
  });
}
// growth score: Kelly bankroll growth of the slip, with each leg's chance cut 2 points for model error
function growth(ids) {
  const p = ids.reduce((a, id) => a * Math.max(0.01, LEG[id].p - 0.02), 1), b = ids.reduce((a, id) => a * dec(LEG[id].price), 1) - 1;
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
try { legCount = +localStorage.getItem('tennis-legs') || null; } catch (e) {}
if (!(legCount >= 1 && legCount <= MAX_PICK)) legCount = BEST || 1;
let SLIPS = [];
const setMode = (m) => {
  mode = m; POOL = m === 'likely' ? LIKELY_POOL : VALUE_POOL; try { localStorage.setItem('tennis-mode', m); } catch (e) {}
  sizesFor(); if (!legCount) legCount = BEST || 1;
};
const setSize = (k) => { legCount = k; try { localStorage.setItem('tennis-legs', k); } catch (e) {} SLIPS = !k ? [] : slipsFor(k); };
// the first relax level that builds at least one slip of k legs (FILL says which); the saved suggestions as a last resort
function slipsFor(k) {
  for (let r = 0; r <= 4; r++) { const s = buildSlips(k, 6, r); if (s.length) { FILL = r; return s; } }
  FILL = 0; return D.slips || [];
}
const sizeOpt = (k) => (k === 1 ? '1 · straight bet' : `${k} legs`) + (k === BEST ? ' ★' : '') + (OK_SIZES.has(k) ? '' : ' ⚠');
setSize(legCount);
let sugIdx = -1;   // which suggestion is loaded (-1 = own slip)
let saved = [];
try { saved = JSON.parse(localStorage.getItem('tennis-saved-' + D.day) || '[]').map((s) => ({ ...s, legs: s.legs.filter((id) => LEG[id]) })).filter((s) => s.legs.length); } catch (e) { saved = []; }
const saveSaved = () => { try { localStorage.setItem('tennis-saved-' + D.day, JSON.stringify(saved)); } catch (e) {} };
const loadSug = (i) => { sugIdx = (i + SLIPS.length) % SLIPS.length; slip = SLIPS[sugIdx].slice(); saveSlip(); render(); };function addBtn(id) {
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
      try { localStorage.setItem('tennis-kinds', JSON.stringify([...KINDS])); } catch (e) {}
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
    md.append(el('span', 'dim sugbest', (mode === 'likely' ? 'Highest-chance legs: board winner picks and other legs 55%+ to hit at DraftKings\' usual juice or better, nothing shorter than -200, up to 3 legs, one per match' : `Value first: winners whose blended chance beats DraftKings' price by ${D.value_ev}%+ in expected value; nothing shorter than -200, one leg per match`) + (KINDS.size ? `. Only ${[...KINDS].join(' + ')} legs (market filter).` : '')));
    sl.append(md);
  }
  if (D.legs.length) {
    const lc = el('div', 'sugnav');
    lc.append(el('b', null, 'Legs'));
    const sel = el('select', 'legsel'); sel.setAttribute('aria-label', 'Number of legs');
    for (let k = 1; k <= MAX_PICK; k++) sel.append(new Option(sizeOpt(k), k));
    sel.value = legCount; sel.onchange = () => { setSize(+sel.value); if (SLIPS.length) loadSug(0); else { sugIdx = -1; render(); } };
    lc.append(sel);
    lc.append(el('span', 'dim sugbest', (BEST == null ? 'No leg meets the usual bar today' : BEST === 1 ? '★ No parlay is worth it today: take a straight bet' : `★ ${BEST} legs is best today`) + '. ⚠ = needs alt lines or next-best legs.'));
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
  if (!legs.length) sl.append(el('div', 'empty', SLIPS.length ? 'Add legs, or load a suggested parlay. Use the arrows or Shuffle to flip between suggestions, and Save to keep one.' : mode === 'likely' ? (D.legs.length ? 'Add legs from the list. No leg is 55%+ to hit at -200 or longer on this slate.' : 'No DraftKings prices on this board yet, so there are no legs to add.') : (D.legs.length ? 'Add legs from the list. No leg meets the value rule on this slate.' : 'No DraftKings prices on this board yet, so there are no legs to add.')));
  const box = el('div', 'slipl'), FL = fillers(legs);
  legs.forEach((L) => { const d = el('div'); const n = el('span'); n.append(legLabel(L), el('small', null, `${L.game} · ${pct(L.p)}`)); if (FL.has(L.id)) { const m = el('small', null, L.alt ? '⚠ Alt line, added to fill the slip' : '⚠ Next-best leg, below the usual bar'); m.style.color = 'var(--gold)'; n.append(m); } const x = el('button', 'x', '×'); x.setAttribute('aria-label', 'Remove'); x.onclick = () => { slip = slip.filter((i) => i !== L.id); sugIdx = -1; saveSlip(); render(); }; d.append(n, el('span', 'num', fmt(L.price)), x); box.append(d); });
  if (legs.length) {
    sl.append(box);
    const p = legs.reduce((a, l) => a * l.p, 1), d = legs.reduce((a, l) => a * dec(l.price), 1), ev = p * d - 1;
    const st = el('div', 'stats pad');
    [[pct(p), 'Hit chance'], [fmt(toAm(d)), 'Payout'], [sgn(Math.round(ev * 100)) + '%', 'Expected value']].forEach(([v, k]) => { const s = el('div', 'stat'); s.append(el('b', null, v), el('span', null, k)); st.append(s); });
    sl.append(st);
    // DraftKings betslip link: every leg's DraftKings outcome id, so the slip opens in DraftKings ready to place
    const sids = legs.filter((l) => !started(l.game)).map((l) => l.sid).filter(Boolean);
    const dk = el('div', 'dkrow');
    if (sids.length) {
      const a = el('a', 'lnk sugb dkbtn', sids.length === legs.length ? 'Open in DraftKings' : `Open ${sids.length} of ${legs.length} legs in DraftKings`);
      a.href = 'https://sportsbook.draftkings.com/?outcomes=' + sids.map(encodeURIComponent).join('+'); a.target = '_blank'; a.rel = 'noopener';
      dk.append(a, el('span', 'dim', sids.length === legs.length ? 'Loads these legs into your DraftKings betslip. Sign in, check the prices, and place it.' : 'The other legs have no DraftKings link (match started, or none on this pull); add them by hand.'));
    } else dk.append(el('span', 'dim', 'No DraftKings link for these legs yet: links come with the next odds pull.'));
    sl.append(dk);
    // Share (Thomas, 2026-11-19): a compact card of the slip for a screenshot or a text (board/site/share.js)
    const shr = el('div', 'dkrow'), shb = el('button', 'lnk sugb', 'Share slip'); shb.type = 'button';
    shb.onclick = () => window.shareSlip && window.shareSlip({ title: `Tennis · ${legs.length === 1 ? 'straight bet' : legs.length + '-leg parlay'}`,
      legs: legs.map((l) => ({ label: l.label, sub: l.game, odds: fmt(l.price), tag: FL.has(l.id) ? '⚠ ' + fillTag(l) : '' })),
      odds: fmt(toAm(d)), chance: pct(p), pays: '$' + (10 * d).toFixed(2),
      warn: FL.size ? `⚠ ${fillWords(legs.filter((l) => FL.has(l.id)))} added to fill the slip` : '' });
    shr.append(shb, el('span', 'dim', 'A compact card of this slip to screenshot or send to a friend.')); sl.append(shr);
    const games = {}; legs.forEach((l) => { games[l.game] = (games[l.game] || 0) + 1; });
    const warns = [];
    Object.entries(games).filter(([, n]) => n > 1).forEach(([g, n]) => {
      const bad = legs.filter((l) => l.game === g && NO_SGP.has(l.kind));
      if (bad.length) warns.push(['bad', `DraftKings won't put goalie saves in a same-game parlay: ${bad.map((l) => l.label).join(', ')} can't be combined with the other ${g} leg${n > 2 ? 's' : ''}. Keep one leg from that game.`]);
      else warns.push(['warn', `${n} legs from ${g}: both players can't win. Keep one.`]);
    });
    legs.filter((l) => started(l.game)).forEach((l) => warns.push(['bad', `${l.game} has started: DraftKings has pulled its pregame lines, so ${l.label} won't load. Swap it out.`]));
    { const fa = legs.filter((l) => FL.has(l.id) && l.alt), fb = legs.filter((l) => FL.has(l.id) && !l.alt);
      if (fa.length) warns.push(['warn', `Alt lines, added to reach ${nLegs(legCount)}: ${fa.map((l) => l.label).join(', ')}. Likelier to hit, but they pay less and aren't the board's usual picks.`]);
      if (fb.length) warns.push(['warn', `Next-best legs, added to reach ${nLegs(legCount)}: ${fb.map((l) => l.label).join(', ')}. They miss the usual bar for ${mode === 'likely' ? 'Most likely to hit' : 'Best value'}.`]); }
    legs.filter((l) => l.edge < 0).forEach((l) => warns.push(['bad', `${l.label} has negative edge.`]));
    legs.filter((l) => l.flags.length).forEach((l) => warns.push(['warn', `${l.label}: ${l.flags.join('; ')}.`]));
    const good = ev > 0 && !warns.some((w) => w[0] === 'bad');
    const v = el('div', 'verdict ' + (good ? 'good' : ev > -0.1 ? 'warn' : 'bad'));
    v.append(el('b', null, good ? 'Positive expected value' : ev > -0.1 ? 'Close to break-even' : 'Long shot'), el('span', null, `${legs.length} leg${legs.length > 1 ? "s" : ""}. Chance assumes the legs are independent.`));
    sl.append(v);
    if (warns.length) { const ul = el('ul', 'warns'); warns.forEach(([c, t]) => ul.append(el('li', c, t))); sl.append(ul); }
  }
  cols.append(list, sl); B.append(cols);
  $('foot').textContent = 'Edge is the leg\'s chance minus the break-even of its DraftKings price, in percentage points. Ranking by edge rather than payout keeps long shots from crowding the top. ★ marks the leg count whose top suggestion grows a bankroll fastest (Kelly growth, with each leg\'s chance cut 2 points for model error): more legs raise the payout, but every leg compounds the chance of being wrong. Your slip is saved in this browser.';
}

function legLabel(L, cls) { return el('span', cls, L.label); }
const TOURN = { atp: 'ATP', wta: 'WTA' };
const oddsNote = () => D.priced ? `DraftKings prices pulled ${D.snap}.` : D.demo ? 'Page check with stand-in prices (not DraftKings).' : 'No DraftKings prices pulled for this board, so it shows the model\'s pick for each match without legs.';

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
  $('eyebrow').textContent = `Tennis · ${D.dayLabel}`;
  $('lede').textContent = 'Today\'s and tomorrow\'s ATP and WTA singles matches with a pick to win in each. The model rates every player from their results since 2021, overall and on each surface (Elo). ' + oddsNote();
  const t = $('tabs'); t.innerHTML = '';
  TABS.forEach(([k, label]) => { const b = el('button', 'tab', label); b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', state.tab === k); b.onclick = () => { state.tab = k; render(); }; t.append(b); });
}

function strip() { $('games').style.display = 'none'; }

function bar() {
  const show = state.tab === 'games';
  $('bar').style.display = show ? '' : 'none'; $('legend').style.display = 'none';
  if (!show) return;
  const pos = $('pos'); pos.innerHTML = '';
  [['all', 'All'], ['atp', 'ATP'], ['wta', 'WTA'], ['main', 'Main draw'], ['likely', 'Picks 70%+'], ['priced', 'DK priced'], ['value', 'Value']].forEach(([k, l]) => { const b = el('button', null, l); b.setAttribute('aria-pressed', state.filt === k); b.onclick = () => { state.filt = k; render(); }; pos.append(b); });
  $('sort').style.display = 'none';
  const q = $('q'); q.placeholder = 'Search a player or tournament'; q.setAttribute('aria-label', 'Search a player or tournament');
  q.oninput = (e) => { state.q = e.target.value.toLowerCase(); boardGames(); };
}

function matchRows() {
  let ms = D.matches.slice();
  const f = state.filt;
  if (f === 'atp' || f === 'wta') ms = ms.filter((m) => m.tour === f);
  if (f === 'main') ms = ms.filter((m) => !m.qual);
  if (f === 'likely') ms = ms.filter((m) => m.pick_p >= 0.7);
  if (f === 'priced') ms = ms.filter((m) => m.legs.length);
  if (f === 'value') ms = ms.filter((m) => m.legs.some((id) => LEG[id].cat === 'Value'));
  if (state.q) ms = ms.filter((m) => `${m.p1} ${m.p2} ${m.event}`.toLowerCase().includes(state.q));
  return ms;
}

function boardGames() {
  const B = $('board'); B.innerHTML = '';
  const ms = matchRows();
  $('count').textContent = `${ms.length} match${ms.length === 1 ? '' : 'es'}`;
  if (!ms.length) {
    B.append(el('div', 'empty', D.matches.length ? 'No matches match.' : 'No ATP or WTA singles matches scheduled today or tomorrow. The tour is in its off-season until the United Cup and Brisbane start around December 28.'));
  }
  const byEv = {};
  ms.forEach((m) => { const k = `${TOURN[m.tour]} · ${m.event}`; (byEv[k] = byEv[k] || []).push(m); });
  Object.entries(byEv).forEach(([ev, xs]) => {
    const c = el('div', 'col tcard');
    const h = el('div', 'colhead'); h.append(el('h2', null, ev), el('span', null, `${xs[0].surface}${xs[0].bo5 ? ' · best of 5' : ''} · ${xs.length} match${xs.length === 1 ? '' : 'es'}`)); c.append(h);
    const tw = el('div', 'tablewrap'); const t = el('table', 'res tmatch');
    const hr = el('tr'); ['Match', 'Pick to win', 'Model', 'DK', 'Chance', 'Edge', ''].forEach((x, i) => hr.append(el('th', i > 1 ? 'num' : null, x))); t.append(hr);
    xs.forEach((m) => {
      const L = m.legs.map((id) => LEG[id]).find((l) => l.side === m.pick);
      const tr = el('tr'); if (L && L.cat === 'Value') tr.className = 'hl';
      const who = el('td'); who.append(el('b', null, `${m.p1} vs ${m.p2}`), el('small', 'dim tsub', `${m.rnd} · ${m.time}${m.court ? ' · ' + m.court : ''}`));
      const fl = (L && L.flags.length) ? L.flags : (m.n1 < 10 || m.n2 < 10) ? ['few rated matches'] : [];
      if (fl.length) who.append(el('small', 'dim tsub', fl.join('; ')));
      const pmPick = m.pick === 'p1' ? m.pm1 : 1 - m.pm1;
      // phones: the Pick, Model and Edge columns fold into one line under the match
      const po = el('span', 'ponly'); po.append(el('b', null, 'Pick: ' + m.pick_name));
      if (L && L.cat === 'Value') po.append(document.createTextNode(' '), el('span', 'pill value', 'Value'));
      po.append(el('span', 'dim', ` · model ${pct(pmPick)}${L ? ' · edge ' + sgn(L.edge) : ''}`)); who.append(po);
      const pk = el('td'); pk.append(document.createTextNode(m.pick_name));
      if (L && L.cat === 'Value') pk.append(document.createTextNode(' '), el('span', 'pill value', 'Value'));
      tr.append(who, pk, el('td', 'num', pct(pmPick)), el('td', 'num', L ? fmt(L.price) : '—'), el('td', 'num', pct(m.pick_p)),
        el('td', 'num ' + (L ? (L.edge > 0 ? 'pos' : 'neg') : ''), L ? sgn(L.edge) : '—'));
      const td = el('td', 'num'); if (L) td.append(addBtn(L.id)); tr.append(td);
      t.append(tr);
      const O = m.legs.map((id) => LEG[id]).find((l) => l.side !== m.pick);
      if (O && (O.cat === 'Value' || slip.includes(O.id))) {
        const tr2 = el('tr', O.cat === 'Value' ? 'hl' : ''); const a = el('td', 'dim'); a.textContent = 'Other side';
        const po2 = el('span', 'ponly'); po2.append(el('b', null, O.who)); if (O.cat === 'Value') po2.append(document.createTextNode(' '), el('span', 'pill value', 'Value'));
        po2.append(el('span', 'dim', ` · model ${pct(O.pm)} · edge ${sgn(O.edge)}`)); a.append(po2);
        const b = el('td'); b.append(document.createTextNode(O.who)); if (O.cat === 'Value') b.append(document.createTextNode(' '), el('span', 'pill value', 'Value'));
        tr2.append(a, b, el('td', 'num', pct(O.pm)), el('td', 'num', fmt(O.price)), el('td', 'num', pct(O.p)), el('td', 'num ' + (O.edge > 0 ? 'pos' : 'neg'), sgn(O.edge)));
        const td2 = el('td', 'num'); td2.append(addBtn(O.id)); tr2.append(td2); t.append(tr2);
      }
    });
    tw.append(t); c.append(tw); B.append(c);
  });
  $('foot').textContent = `Pick to win: the player with the higher chance. Model = the Elo model alone; Chance = ${Math.round(D.w_model * 100)}% model and ${100 - Math.round(D.w_model * 100)}% DraftKings' no-vig price when DraftKings has priced the match (betting markets are usually sharper than ratings in tennis), else the model alone. Edge = chance minus the break-even of DraftKings' price, in points. Value = expected value ${D.value_ev}%+ at DraftKings' price, -200 or longer. Results through ${D.through} from ESPN.`;
}

function boardRatings() {
  const B = $('board'); B.innerHTML = '';
  const sg = el('div', 'seg'); [['atp', 'ATP'], ['wta', 'WTA']].forEach(([k, l]) => { const b = el('button', null, l); b.setAttribute('aria-pressed', state.rtour === k); b.onclick = () => { state.rtour = k; boardRatings(); }; sg.append(b); });
  const top = el('div', 'plctl'); top.append(sg); B.append(top);
  const c = el('div', 'col'); const h = el('div', 'colhead'); h.append(el('h2', null, `${TOURN[state.rtour]} Elo ratings`), el('span', null, 'Top 30 who played in the last 120 days')); c.append(h);
  const tw = el('div', 'tablewrap'); const t = el('table', 'res');
  const hr = el('tr'); ['#', 'Player', 'Overall', 'Hard', 'Clay', 'Grass', 'Matches'].forEach((x, i) => hr.append(el('th', i > 1 ? 'num' : null, x))); t.append(hr);
  (D.ratings[state.rtour] || []).forEach((r) => { const tr = el('tr'); [r.rank, r.name, r.elo, r.hard, r.clay, r.grass, r.matches].forEach((x, i) => tr.append(el('td', i > 1 ? 'num' : null, String(x)))); t.append(tr); });
  tw.append(t); c.append(tw); B.append(c);
  $('foot').textContent = 'A 100-point gap means the higher-rated player wins about 64% of the time; 200 points, about 76%. The surface columns blend 70% overall rating with 30% results on that surface, as the match picks do. New players start at 1500.';
}

function boardRecord() {
  const B = $('board'); B.innerHTML = '';
  const M = recordMenus({ sport: 'tennis', src: D.live, rerender: boardRecord,
    views: [['all', 'Everything'], ['bets', 'Picks'], ['parlays', 'Parlays'], ['chance', 'Chance check'], ['tests', 'Backtest']] });
  B.append(M.bar);
  const lv = M.rep;
  if (lv && (lv.cal_sections || []).length && M.show('chance')) { const cw = renderCalibration(lv.cal_sections); cw.style.marginBottom = '8px'; B.append(cw); }
  const fmtp = (x) => x == null ? '—' : (x * 100).toFixed(1) + '%';
  const roi = (x) => x == null ? '—' : sgn(Math.round(x * 1000) / 10) + '%';
  const mk = (title, head, rows, note) => { const c = el('div', 'col'); c.style.marginTop = '16px'; const h = el('div', 'colhead'); h.append(el('h2', null, title)); c.append(h); const tw = el('div', 'tablewrap'); const t = el('table', 'res'); const hr = el('tr'); head.forEach((x, i) => hr.append(el('th', i ? 'num' : null, x))); t.append(hr); rows.forEach((r) => { const tr = el('tr'); r.forEach((x, i) => tr.append(el('td', i ? 'num' : null, String(x)))); t.append(tr); }); tw.append(t); c.append(tw); if (note) c.append(el('p', 'note logfoot', note)); B.append(c); };
  if (!(lv && lv.groups && lv.groups.length) && M.show('bets')) B.append(el('div', 'empty', M.period ? `Nothing graded for ${M.label} yet.` : 'No live picks graded yet: each board run logs its picks, and they are graded once the matches finish.'));
  if (lv && lv.groups && lv.groups.length && M.show('bets'))
    mk('Live record', ['Group', 'Picks', 'W-L', 'Hit', 'Expected', 'Units', 'ROI'], lv.groups.map((g) => [g.group, g.bets, `${g.won}-${g.lost}`, fmtp(g.hit), fmtp(g.exp_hit), g.units == null ? '—' : sgn(g.units), roi(g.roi)]),
       'Every match\'s pick is logged when the board is built and graded once from ESPN\'s result. Units and ROI count only picks DraftKings priced, 1 unit each at that price. Walkovers and retirements are left out.');
  const pz = lv && lv.parlays && lv.parlays.groups.filter((g) => g.bets);
  if (pz && pz.length && M.show('parlays')) mk('Suggested parlays at DraftKings', ['Parlays', 'Count', 'W-L', 'Hit', 'Expected', 'Units', 'ROI'], pz.map((g) => [g.group, g.bets, `${g.won}-${g.lost}`, fmtp(g.hit), fmtp(g.exp_hit), sgn(g.units), roi(g.roi)]),
     'The first build of each day saves its suggested parlays, graded as whole parlays at DraftKings prices, 1 unit each.');
  if (!M.show('tests')) { $('foot').textContent = 'Grading uses ESPN\'s free results, so it costs no odds credits.'; return; }
  const bt = D.backtest;
  if (bt && bt.elo) {
    for (const [k, name] of [['atp', 'ATP'], ['wta', 'WTA']]) {
      const e = bt.elo[k]; if (!e) continue;
      mk(`${name} picks by how sure the model was (main draw, ${bt.since.slice(0, 4)} on)`, ['Model chance', 'Matches', 'Pick won', 'Model said'],
         e.bands.map((b) => [b.band, b.n, fmtp(b.hit), fmtp(b.avg_p)]).concat([['All', e.n, fmtp(e.hit), '']]),
         `Out of sample: each match was predicted from earlier results only. By surface: ${Object.entries(e.by_surface).map(([s, v]) => `${s} ${fmtp(v.hit)}`).join(', ')}.`);
    }
    if (bt.market) {
      const m = bt.market;
      mk('Against closing odds', ['Test', 'Result'], [['Matches with odds', m.n], ['Market favourite won', fmtp(m.fav_hit)], ['Model pick won', fmtp(m.elo_hit)]]
        .concat(Object.entries(m.rules).map(([k, v]) => [k, `${v.n} bets, ${fmtp(v.hit)}, ROI ${roi(v.roi)}`])), `Odds: ${m.odds}, from tennis-data.co.uk.`);
    } else B.append(el('p', 'note', 'Not yet tested against betting odds: that needs past closing prices (tennis-data.co.uk files).'));
  } else B.append(el('div', 'empty', 'No backtest yet.'));
  $('foot').textContent = 'Backtest: scripts/tennis_backtest.py on ESPN results (free).';
}

function render() {
  header(); strip(); bar();
  if (state.tab === 'games') boardGames();
  else if (state.tab === 'parlay') boardParlay();
  else if (state.tab === 'ratings') boardRatings();
  else boardRecord();
}
render();
