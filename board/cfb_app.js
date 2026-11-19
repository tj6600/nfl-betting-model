const D = JSON.parse(document.getElementById('cfb-data').textContent);
// games that have started: DraftKings pulls pregame lines at the start, so their legs leave suggestions and the DraftKings link
const STARTS = {}; (D.games || []).forEach((g) => { if (g.start) STARTS[g.game] = g.start; });
const started = (game) => !!STARTS[game] && Date.parse(STARTS[game]) <= Date.now();
const LEG = Object.fromEntries(D.legs.map((l) => [l.id, l]));
const TABS = [['games', 'Games'], ['parlay', 'Parlay builder'], ['ratings', 'Team ratings'], ['record', 'Model record']];
const state = { tab: 'games', game: 'all', filt: 'all', q: '', pmin: 0.25, pq: '' };
const GAME = Object.fromEntries((D.games || []).map((g) => [g.id, g]));
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const fmt = (o) => o == null ? '—' : (o > 0 ? '+' : '') + o;
const pct = (p) => p == null ? '—' : p < 0.01 ? (p * 100).toFixed(2) + '%' : Math.round(p * 100) + '%';
const sgn = (x) => (x > 0 ? '+' : '') + x;
const dec = (a) => a > 0 ? 1 + a / 100 : 1 + 100 / -a;
const toAm = (d) => d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1));
const $ = (id) => document.getElementById(id);
let slip = [];
try { slip = JSON.parse(localStorage.getItem('cfb-slip-' + D.week) || '[]').filter((id) => LEG[id]); } catch (e) { slip = []; }
const saveSlip = () => { try { localStorage.setItem('cfb-slip-' + D.week, JSON.stringify(slip)); } catch (e) {} };
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
try { mode = localStorage.getItem('cfb-mode') === 'likely' ? 'likely' : 'value'; } catch (e) {}
let POOL = mode === 'likely' ? LIKELY_POOL : VALUE_POOL;
// market filter: pick any mix of markets (e.g. Points + Assists); none picked = every market. Suggestions follow it.
let KINDS = new Set();
const OPEN = new Set(), GLIM = {};
try { KINDS = new Set(JSON.parse(localStorage.getItem('cfb-kinds') || '[]')); } catch (e) {}
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
try { legCount = +localStorage.getItem('cfb-legs') || null; } catch (e) {}
if (!(legCount >= 1 && legCount <= MAX_PICK)) legCount = BEST || 1;
let SLIPS = [];
const setMode = (m) => {
  mode = m; POOL = m === 'likely' ? LIKELY_POOL : VALUE_POOL; try { localStorage.setItem('cfb-mode', m); } catch (e) {}
  sizesFor(); if (!legCount) legCount = BEST || 1;
};
const setSize = (k) => { legCount = k; try { localStorage.setItem('cfb-legs', k); } catch (e) {} SLIPS = !k ? [] : slipsFor(k); };
// the first relax level that builds at least one slip of k legs (FILL says which); the saved suggestions as a last resort
function slipsFor(k) {
  for (let r = 0; r <= 4; r++) { const s = buildSlips(k, 6, r); if (s.length) { FILL = r; return s; } }
  FILL = 0; return D.slips || [];
}
const sizeOpt = (k) => (k === 1 ? '1 · straight bet' : `${k} legs`) + (k === BEST ? ' ★' : '') + (OK_SIZES.has(k) ? '' : ' ⚠');
setSize(legCount);
let sugIdx = -1;   // which suggestion is loaded (-1 = own slip)
let saved = [];
try { saved = JSON.parse(localStorage.getItem('cfb-saved-' + D.week) || '[]').map((s) => ({ ...s, legs: s.legs.filter((id) => LEG[id]) })).filter((s) => s.legs.length); } catch (e) { saved = []; }
const saveSaved = () => { try { localStorage.setItem('cfb-saved-' + D.week, JSON.stringify(saved)); } catch (e) {} };
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
      try { localStorage.setItem('cfb-kinds', JSON.stringify([...KINDS])); } catch (e) {}
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
    md.append(el('span', 'dim sugbest', (mode === 'likely' ? 'Highest-chance legs: board winner picks and other legs 55%+ to hit at DraftKings\' usual juice or better, nothing shorter than -200, up to 3 legs, one per game' : `Value first: spreads where the model's line is ${D.value_pts}+ points better than DraftKings' line, then 1.5+ points; nothing shorter than -200, one leg per game`) + (KINDS.size ? `. Only ${[...KINDS].join(' + ')} legs (market filter).` : '')));
    sl.append(md);
  }
  if (D.legs.length) {
    const lc = el('div', 'sugnav');
    lc.append(el('b', null, 'Legs'));
    const sel = el('select', 'legsel'); sel.setAttribute('aria-label', 'Number of legs');
    for (let k = 1; k <= MAX_PICK; k++) sel.append(new Option(sizeOpt(k), k));
    sel.value = legCount; sel.onchange = () => { setSize(+sel.value); if (SLIPS.length) loadSug(0); else { sugIdx = -1; render(); } };
    lc.append(sel);
    lc.append(el('span', 'dim sugbest', (BEST == null ? 'No leg meets the usual bar this week' : BEST === 1 ? '★ No parlay is worth it this week: take a straight bet' : `★ ${BEST} legs is best this week`) + '. ⚠ = needs alt lines or next-best legs.'));
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
      dk.append(a, el('span', 'dim', sids.length === legs.length ? 'Loads these legs into your DraftKings betslip. Sign in, check the prices, and place it.' : 'The other legs have no DraftKings link (game started, or none on this pull); add them by hand.'));
    } else dk.append(el('span', 'dim', 'No DraftKings link for these legs yet: links come with the next odds pull.'));
    sl.append(dk);
    // Share (Thomas, 2026-11-19): a compact card of the slip for a screenshot or a text (board/site/share.js)
    const shr = el('div', 'dkrow'), shb = el('button', 'lnk sugb', 'Share slip'); shb.type = 'button';
    shb.onclick = () => window.shareSlip && window.shareSlip({ title: `College football · ${legs.length === 1 ? 'straight bet' : legs.length + '-leg parlay'}`,
      legs: legs.map((l) => ({ label: l.label, sub: l.game, odds: fmt(l.price), tag: FL.has(l.id) ? '⚠ ' + fillTag(l) : '' })),
      odds: fmt(toAm(d)), chance: pct(p), pays: '$' + (10 * d).toFixed(2),
      warn: FL.size ? `⚠ ${fillWords(legs.filter((l) => FL.has(l.id)))} added to fill the slip` : '' });
    shr.append(shb, el('span', 'dim', 'A compact card of this slip to screenshot or send to a friend.')); sl.append(shr);
    const games = {}; legs.forEach((l) => { games[l.game] = (games[l.game] || 0) + 1; });
    const warns = [];
    Object.entries(games).filter(([, n]) => n > 1).forEach(([g, n]) => {
      const bad = legs.filter((l) => l.game === g && NO_SGP.has(l.kind));
      if (bad.length) warns.push(['bad', `DraftKings won't put goalie saves in a same-game parlay: ${bad.map((l) => l.label).join(', ')} can't be combined with the other ${g} leg${n > 2 ? 's' : ''}. Keep one leg from that game.`]);
      else warns.push(['warn', `${n} legs from ${g}: DraftKings prices same-game legs together, so the real payout differs and the legs are not independent.`]);
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

const tname = (g, side) => { const r = g[side + '_rank']; return (r ? `#${r} ` : '') + g[side + '_name']; };
const lineTxt = (g, ln) => ln == null ? '—' : ln === 0 ? 'Pick\'em' : ln < 0 ? `${g.home} ${ln}` : `${g.away} ${-ln}`;

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
  $('eyebrow').textContent = `College football · ${D.weekLabel}`;
  $('lede').textContent = 'This week\'s FBS games set against DraftKings: winners, spreads and totals. The model rates every team from this season\'s scores and DraftKings\' past closing lines; its spread edge held up against opening lines in testing, not closing lines, so value is best caught early in the week.';
  const t = $('tabs'); t.innerHTML = '';
  TABS.forEach(([k, label]) => { const b = el('button', 'tab', label); b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', state.tab === k); b.onclick = () => { state.tab = k; render(); }; t.append(b); });
}

function strip() { $('games').style.display = 'none'; }

function bar() {
  const show = state.tab === 'games';
  $('bar').style.display = show ? '' : 'none'; $('legend').style.display = 'none';
  if (!show) return;
  const pos = $('pos'); pos.innerHTML = '';
  [['all', 'All games'], ['likely', 'Winners 70%+'], ['top25', 'Top 25'], ['value', 'Value spreads']].forEach(([k, l]) => { const b = el('button', null, l); b.setAttribute('aria-pressed', state.filt === k); b.onclick = () => { state.filt = k; render(); }; pos.append(b); });
  $('sort').style.display = 'none';
  const q = $('q'); q.placeholder = 'Search a team'; q.setAttribute('aria-label', 'Search a team');
  q.oninput = (e) => { state.q = e.target.value.toLowerCase(); boardGames(); };
}

function gameRows() {
  let gs = D.games.slice();
  if (state.filt === 'value') gs = gs.filter((g) => g.legs.some((id) => LEG[id].cat === 'Value'));
  if (state.filt === 'top25') gs = gs.filter((g) => g.home_rank || g.away_rank);
  if (state.filt === 'likely') gs = gs.filter((g) => g.pick_p >= 0.7);
  if (state.q) gs = gs.filter((g) => `${g.home} ${g.away} ${g.home_name} ${g.away_name}`.toLowerCase().includes(state.q));
  return gs;
}

function boardGames() {
  const B = $('board'); B.innerHTML = '';
  const gs = gameRows();
  $('count').textContent = `${gs.length} game${gs.length === 1 ? '' : 's'}`;
  const wrap = el('div', 'gcards');
  if (!gs.length) wrap.append(el('div', 'empty', D.games.length ? 'No games match.' : 'No games with DraftKings lines this week yet.'));
  gs.forEach((g) => {
    const c = el('div', 'col gcard');
    const h = el('div', 'colhead'); h.append(el('h2', null, `${tname(g, 'away')} at ${tname(g, 'home')}`), el('span', null, `${g.kick}${g.tv ? ' · ' + g.tv : ''}${g.neutral ? ' · neutral site' : ''}`)); c.append(h);
    if (g.note) c.append(el('div', 'outs', g.note));
    const pj = el('div', 'proj');
    const pickName = g.pick ? g[g.pick + '_name'] : null;
    [[pickName ? `${pickName} ${pct(g.pick_p)}` : '—', 'Pick to win'], [lineTxt(g, g.line), 'DK spread'], [lineTxt(g, g.model_line), 'Model spread'],
     [g.line_total ?? '—', 'DK total'], [g.model_total, 'Model total']].forEach(([v, k]) => { const d = el('div'); d.append(el('b', null, v), el('span', null, k)); pj.append(d); });
    c.append(pj);
    const picks = [];
    if (g.pick) picks.push(`${g[g.pick + '_name']} to win (${pct(g.pick_p)})`);
    if (g.sp_pick) picks.push(`${LEG[g.sp_pick].label} (${pct(LEG[g.sp_pick].p)})`);
    if (g.to_pick) picks.push(LEG[g.to_pick].label.replace(/ \(.*\)$/, '') + ` (model ${g.model_total})`);
    if (picks.length) { const pk = el('div', 'outs picks'); pk.append(el('b', null, 'Board picks: '), document.createTextNode(picks.join(' · '))); c.append(pk); }
    const notes = [];
    if (g.diff != null) {
      const side = g.diff > 0 ? g.home_name : g.away_name, pts = Math.abs(g.diff);
      notes.push(pts >= 0.5 ? `Model likes ${side} by ${pts.toFixed(1)} points against the DraftKings spread.` : 'Model agrees with the DraftKings spread.');
    }
    if (g.open_line != null && g.moved) {
      const toward = (g.moved < 0) === (g.diff > 0);
      notes.push(`Opened ${lineTxt(g, g.open_line)}; moved ${Math.abs(g.moved)} point${Math.abs(g.moved) === 1 ? '' : 's'}${g.diff != null && Math.abs(g.diff) >= 0.5 ? (toward ? ' toward the model' : ' away from the model') : ''}.`);
    } else if (g.open_line != null) notes.push('Line has not moved since it opened.');
    if (g.fcs.length) notes.push(`${g.fcs.join(' and ')} ${g.fcs.length > 1 ? 'are' : 'is'} FCS.`);
    const fl = g.legs.length ? LEG[g.legs[0]].flags : [];
    if (fl.length) notes.push(fl.join('; ') + ': early-season rating, take it with care.');
    if (notes.length) c.append(el('div', 'outs', notes.join(' ')));
    if (g.legs.length) {
      const tw = el('div', 'tablewrap'); const t = el('table', 'res');
      const hr = el('tr'); ['Bet', 'DK', 'Chance', 'Edge', ''].forEach((x, i) => hr.append(el('th', i ? 'num' : null, x))); t.append(hr);
      g.legs.map((id) => LEG[id]).forEach((L) => {
        const tr = el('tr'); if (L.cat === 'Value') tr.className = 'hl';
        if (L.bpick) tr.classList.add('bp');
        const lab = el('td'); lab.append(document.createTextNode(`${L.kind}: ${L.kind === 'Total' ? L.label.replace(/ \(.*\)$/, '') : L.label}`));
        if (L.bpick) lab.append(document.createTextNode(' '), el('span', 'pill pk', 'Pick'));
        if (L.cat === 'Value') lab.append(document.createTextNode(' '), el('span', 'pill value', 'Value'));
        tr.append(lab, el('td', 'num', fmt(L.price)), el('td', 'num', pct(L.p)), el('td', 'num ' + (L.edge > 0 ? 'pos' : 'neg'), sgn(L.edge)));
        const td = el('td', 'num'); td.append(addBtn(L.id)); tr.append(td); t.append(tr);
      });
      tw.append(t); c.append(tw);
    } else c.append(el('div', 'outs', 'DraftKings lines not posted yet.'));
    wrap.append(c);
  });
  B.append(wrap);
  const w = D.weights;
  $('foot').textContent = `Board picks: the winner and spread side with the higher chance, and the total side of the model's projected score. In testing (2026 weeks 4-11) the winner pick was right about 72% of the time; spread and total picks are close to coin flips at DraftKings' lines (about 47% and 46% against closing lines; spread picks hit 52.5% against the opener), so the parlay builder's Most likely to hit mode leans on winners. Chances: spreads are ${w.Spread * 100}% model and ${100 - w.Spread * 100}% DraftKings no-vig, moneylines ${w.Moneyline * 100}% model, totals DraftKings only (the model's totals did worse than DraftKings in testing). Value = a spread where the model's line is ${D.value_pts}+ points better than DraftKings' line now. Home field is worth ${D.hfa} points in the ratings. Scores through ${D.through}. Lines from DraftKings via ESPN.`;
}

function legLabel(L, cls) { return el('span', cls, L.label); }

function boardRatings() {
  const B = $('board'); B.innerHTML = '';
  const c = el('div', 'col'); const h = el('div', 'colhead'); h.append(el('h2', null, 'Team ratings'), el('span', null, 'Points better than an average FBS team on a neutral field')); c.append(h);
  const tw = el('div', 'tablewrap'); const t = el('table', 'res');
  const hr = el('tr'); ['#', 'Team', 'Rating', 'Offense', 'Defense', 'Games'].forEach((x, i) => hr.append(el('th', i > 1 ? 'num' : null, x))); t.append(hr);
  D.ratings.forEach((r) => { const tr = el('tr'); [r.rank, r.team, sgn(r.rating), sgn(r.off), sgn(r.dfn), r.games].forEach((x, i) => tr.append(el('td', i > 1 ? 'num' : null, String(x)))); t.append(tr); });
  tw.append(t); c.append(tw); B.append(c);
  $('foot').textContent = 'Ratings come from this season\'s scores (and last season\'s, counted less), each pulled halfway toward DraftKings\' closing line for that game. Offense = points scored above average; defense = points held below average. A model spread is the rating gap plus home field.';
}

function boardRecord() {
  const B = $('board'); B.innerHTML = '';
  const M = recordMenus({ sport: 'cfb', src: D.live, rerender: boardRecord,
    views: [['all', 'Everything'], ['bets', 'Bets'], ['parlays', 'Parlays'], ['chance', 'Chance check'], ['tests', 'Backtest']] });
  B.append(M.bar);
  const lv = M.rep;
  if (lv && (lv.cal_sections || []).length && M.show('chance')) { const cw = renderCalibration(lv.cal_sections); cw.style.marginBottom = '8px'; B.append(cw); }
  const fmtp = (x) => x == null ? '—' : (x * 100).toFixed(1) + '%';
  const roi = (x) => x == null ? '—' : sgn(Math.round(x * 1000) / 10) + '%';
  const mk = (title, head, rows, note) => { const c = el('div', 'col'); c.style.marginTop = '16px'; const h = el('div', 'colhead'); h.append(el('h2', null, title)); c.append(h); const tw = el('div', 'tablewrap'); const t = el('table', 'res'); const hr = el('tr'); head.forEach((x, i) => hr.append(el('th', i ? 'num' : null, x))); t.append(hr); rows.forEach((r) => { const tr = el('tr'); r.forEach((x, i) => tr.append(el('td', i ? 'num' : null, String(x)))); t.append(tr); }); tw.append(t); c.append(tw); if (note) c.append(el('p', 'note logfoot', note)); B.append(c); };
  if (M.period && !(lv && lv.groups && lv.groups.length) && !(lv && lv.parlays && lv.parlays.groups.some((g) => g.bets))) B.append(el('div', 'empty', `Nothing graded for ${M.label} yet.`));
  if (lv && lv.groups && lv.groups.length && M.show('bets'))
    mk('Live record at DraftKings', ['Group', 'Bets', 'W-L', 'Hit', 'Units', 'ROI'], lv.groups.map((g) => [g.group, g.bets, `${g.won}-${g.lost}`, fmtp(g.hit), sgn(g.units), roi(g.roi)]),
       'Every priced leg is logged when the board is built and graded once, at the first DraftKings line and price the board showed for it, 1 unit per leg.');
  const pz = lv && lv.parlays && lv.parlays.groups.filter((g) => g.bets);
  if (pz && pz.length && M.show('parlays')) mk('Suggested parlays at DraftKings', ['Parlays', 'Count', 'W-L', 'Hit', 'Expected', 'Units', 'ROI'], pz.map((g) => [g.group, g.bets, `${g.won}-${g.lost}`, fmtp(g.hit), fmtp(g.exp_hit), sgn(g.units), roi(g.roi)]),
     'The first build of each week saves its suggested parlays (Best value and Most likely to hit, every leg count), graded as whole parlays at DraftKings prices, 1 unit each.');
  if (!M.show('tests')) { $('foot').textContent = 'Grading uses ESPN\'s free final scores, so it costs no odds credits.'; return; }
  const bt = D.backtest && D.backtest.weeks_4_on;
  if (bt) {
    const a = (r) => `${r.n} bets, ${fmtp(r.hit)}`;
    mk('Spreads vs DraftKings (2026, weeks 4-11)', ['Test', 'Against the opener', 'Against the close'],
       [['Every game, model side', a(bt.ats_open['edge>=0']), a(bt.ats_close['edge>=0'])], ['Model 3+ points off', a(bt.ats_open['edge>=3']), a(bt.ats_close['edge>=3'])],
        ['Model 5+ points off', a(bt.ats_open['edge>=5']), a(bt.ats_close['edge>=5'])]],
       `Break-even at -110 is 52.4%. Ratings were fit only on games before each week. Against the opening line the model's 3+ point picks hit ${fmtp(bt.ats_open['edge>=3'].hit)}, and when the line moved it moved toward the model ${fmtp(bt.clv_open.toward_model)} of the time (${bt.clv_open.n} games); against the closing line there was no edge. Treat it as a lead, not proof: it is one season, and stretching the model's spreads 10% wiped it out. Weeks 1-3 were worse (too little this-season data), so the board flags teams with under 3 games.`);
    mk('Other markets', ['Test', 'Result'],
       [['Spread miss, points (model / DK close / DK open)', `${bt.margin_mae.model} / ${bt.margin_mae.dk_close} / ${bt.margin_mae.dk_open}`],
        ['Totals: model side vs DK close', `${bt.totals_close.n} bets, ${fmtp(bt.totals_close.hit)}`],
        ['Straight-up winners: model / DK favorite', `${fmtp(bt.winners.model)} / ${fmtp(bt.winners.dk_favorite)}`],
        ['DK favorites -110 to -300', `${bt['fav_-110_to_-300'].n} games, won ${fmtp(bt['fav_-110_to_-300'].hit)}, ROI ${roi(bt['fav_-110_to_-300'].roi)}`],
        ['Moneyline value bets (model + DK)', `${bt.ml_value['w0.25_ev>=0.0'].n} bets, ROI ${roi(bt.ml_value['w0.25_ev>=0.0'].roi)}`]],
       'DraftKings was better than the model on totals and moneylines, so the board uses DraftKings\' chances there and never calls them Value.');
  } else B.append(el('div', 'empty', 'No backtest yet.'));
  $('foot').textContent = 'Backtest: scripts/cfb_backtest.py (free ESPN lines for 2026; 2025 games have no DraftKings lines on ESPN).';
}

function render() {
  header(); strip(); bar();
  if (state.tab === 'games') boardGames();
  else if (state.tab === 'parlay') boardParlay();
  else if (state.tab === 'ratings') boardRatings();
  else boardRecord();
}
render();
