const D = JSON.parse(document.getElementById('nhl-data').textContent);
const LEG = Object.fromEntries(D.legs.map((l) => [l.id, l]));
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
// that are 70%+ and fairly priced (edge 0+), likeliest first (scripts parlays.py suggest() uses the same rules)
const SECURE = 0.6, ALT_FIRST_P = 0.7, ALT_FIRST_SIZE = 3;
const ALT_BY = {};
for (const l of D.legs) if (l.alt && !l.flags.length && l.p >= SECURE && l.edge >= 0) (ALT_BY[l.pid + '|' + l.market] = ALT_BY[l.pid + '|' + l.market] || []).push(l);
Object.values(ALT_BY).forEach((xs) => xs.sort((a, b) => b.p - a.p));
const safer = (l) => (l.alt || l.side !== 'Over' || l.p >= SECURE) ? l : ((ALT_BY[l.pid + '|' + l.market] || []).find((a) => a.p > l.p) || l);
const dedupe = (xs) => { const s = new Set(); return xs.filter((l) => !s.has(l.id) && s.add(l.id)); };
const ALT_FIRST = D.legs.filter((l) => l.alt && !l.flags.length && l.p >= ALT_FIRST_P && l.edge >= 0).sort((a, b) => b.p - a.p || b.edge - a.edge);
const VALUE_POOL = dedupe((D.pool || []).map((id) => LEG[id]).filter(Boolean).map(safer));
// NHL: the board's winner picks count as "likely" even without an edge (Thomas wants correct picks more than edge),
// but nothing priced shorter than -200, so no leg risks much more than it pays
const LIKELY_POOL = dedupe(D.legs.filter((l) => (l.edge >= 1 || l.pick) && l.p >= 0.55 && l.price >= -200 && !l.flags.length).sort((a, b) => b.p - a.p || b.edge - a.edge).map(safer));
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
const NO_SGP = new Set(['Saves']);
function buildSlips(size, n = 6) {
  const out = [], used = new Set();
  const pool = (mode === 'likely' && size >= ALT_FIRST_SIZE ? dedupe(ALT_FIRST.concat(POOL)) : POOL).filter(kindOk);
  for (let s = 0; s < n; s++) {
    const nG = new Set(pool.map((L) => L.game)).size;
    const slip = [], g = {}, pl = new Set(), perGame = Math.min(3, Math.max(size > 6 ? 3 : 1, Math.ceil(size / Math.max(1, nG))));   // more per game only when the slate is too small
    for (const L of pool) {
      if (used.has(L.id) || (g[L.game] || 0) >= perGame || (L.pid && pl.has(L.pid))) continue;
      if ((g[L.game] || 0) && (NO_SGP.has(L.kind) || slip.some((id) => LEG[id].game === L.game && NO_SGP.has(LEG[id].kind)))) continue;
      slip.push(L.id); g[L.game] = (g[L.game] || 0) + 1; if (L.pid) pl.add(L.pid);
      if (slip.length >= size) break;
    }
    if (slip.length < size) break;
    slip.forEach((id) => used.add(id)); out.push(slip);
  }
  return out;
}
// growth score: Kelly bankroll growth of the slip, with each leg's chance cut 2 points for model error
function growth(ids) {
  const p = ids.reduce((a, id) => a * Math.max(0.01, LEG[id].p - 0.02), 1), b = ids.reduce((a, id) => a * dec(LEG[id].price), 1) - 1;
  const f = (b * p - (1 - p)) / b; if (f <= 0) return 0;
  return p * Math.log(1 + f * b) + (1 - p) * Math.log(1 - f);
}
let SIZES = [], BEST = null;
// best parlay size by growth; when no parlay has positive growth (or none can be built), suggest a straight bet
function sizesFor() {
  SIZES = [1, 2, 3, 4, 5, 6, 11].filter((k) => buildSlips(k, 1).length);
  const PS = SIZES.filter((k) => k > 1 && growth(buildSlips(k, 1)[0]) > 0);
  BEST = PS.length ? PS.reduce((a, k) => (growth(buildSlips(k, 1)[0]) > growth(buildSlips(a, 1)[0]) ? k : a), PS[0]) : SIZES.includes(1) ? 1 : null;
}
sizesFor();
const sizeName = (k) => (k === 1 ? 'Straight' : String(k));
let legCount = null;
try { legCount = +localStorage.getItem('nhl-legs') || null; } catch (e) {}
if (!SIZES.includes(legCount)) legCount = BEST;
let SLIPS = [];
const setMode = (m) => {
  mode = m; POOL = m === 'likely' ? LIKELY_POOL : VALUE_POOL; try { localStorage.setItem('nhl-mode', m); } catch (e) {}
  sizesFor(); if (!SIZES.includes(legCount)) legCount = BEST;
};
const setSize = (k) => { legCount = k; try { localStorage.setItem('nhl-legs', k); } catch (e) {} SLIPS = !k ? [] : POOL.length ? buildSlips(k) : (D.slips || []); };
setSize(legCount);
let sugIdx = -1;   // which suggestion is loaded (-1 = own slip)
let saved = [];
try { saved = JSON.parse(localStorage.getItem('nhl-saved-' + D.day) || '[]').map((s) => ({ ...s, legs: s.legs.filter((id) => LEG[id]) })).filter((s) => s.legs.length); } catch (e) { saved = []; }
const saveSaved = () => { try { localStorage.setItem('nhl-saved-' + D.day, JSON.stringify(saved)); } catch (e) {} };
const loadSug = (i) => { sugIdx = (i + SLIPS.length) % SLIPS.length; slip = SLIPS[sugIdx].slice(); saveSlip(); render(); };
const hasLines = (k) => SRC(k).some((p) => p[k] && p[k].line != null);
const hasProps = hasLines('sog') || hasLines('saves');
if (!hasProps) state.sort = 'proj';

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
        tr.append(el('td', null, `${L.kind}: ${L.label}`), el('td', 'num', fmt(L.price)), el('td', 'num', pct(L.p)), el('td', 'num ' + (L.edge > 0 ? 'pos' : 'neg'), sgn(L.edge)));
        const td = el('td', 'num'); td.append(addBtn(L.id)); tr.append(td); t.append(tr);
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
      sizesFor(); if (!SIZES.includes(legCount)) legCount = BEST; setSize(legCount); sugIdx = -1; render();
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
    md.append(el('span', 'dim sugbest', (mode === 'likely' ? 'Highest-chance legs: board winner picks plus legs with edge 1+, 55%+ chance, nothing shorter than -200. Slips of 3+ legs start with alt lines 70%+ to hit, and a shaky Over swaps to a safer alt line' : 'Biggest edge first (edge 3+, 55%+ chance)') + (KINDS.size ? `. Only ${[...KINDS].join(' + ')} legs (market filter).` : '')));
    sl.append(md);
  }
  if (SIZES.length) {
    const lc = el('div', 'sugnav');
    lc.append(el('b', null, 'Legs'));
    const seg = el('div', 'seg');
    SIZES.forEach((k) => { const b = el('button', null, k === BEST ? `${sizeName(k)} ★` : sizeName(k)); b.setAttribute('aria-pressed', k === legCount); b.title = k === BEST ? 'Best number of legs tonight' : ''; b.onclick = () => { setSize(k); loadSug(0); }; seg.append(b); });
    lc.append(seg);
    lc.append(el('span', 'dim sugbest', BEST === 1 ? '★ No parlay is worth it tonight: take a straight bet' : `★ ${BEST} legs is best tonight`));
    sl.append(lc);
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
  if (!legs.length) sl.append(el('div', 'empty', SLIPS.length ? 'Add legs, or load a suggested parlay. Use the arrows or Shuffle to flip between suggestions, and Save to keep one.' : mode === 'likely' ? 'Add legs from the list. No leg is 55%+ to hit at -200 or longer on this slate.' : 'Add legs from the list. No leg meets the value rule (edge 3+, chance 55%+) on this slate.'));
  const box = el('div', 'slipl');
  legs.forEach((L) => { const d = el('div'); const n = el('span'); n.append(legLabel(L), el('small', null, `${L.game} · ${pct(L.p)}`)); const x = el('button', 'x', '×'); x.setAttribute('aria-label', 'Remove'); x.onclick = () => { slip = slip.filter((i) => i !== L.id); sugIdx = -1; saveSlip(); render(); }; d.append(n, el('span', 'num', fmt(L.price)), x); box.append(d); });
  if (legs.length) {
    sl.append(box);
    const p = legs.reduce((a, l) => a * l.p, 1), d = legs.reduce((a, l) => a * dec(l.price), 1), ev = p * d - 1;
    const st = el('div', 'stats pad');
    [[pct(p), 'Hit chance'], [fmt(toAm(d)), 'Payout'], [sgn(Math.round(ev * 100)) + '%', 'Expected value']].forEach(([v, k]) => { const s = el('div', 'stat'); s.append(el('b', null, v), el('span', null, k)); st.append(s); });
    sl.append(st);
    // DraftKings betslip link: every leg's DraftKings outcome id, so the slip opens in DraftKings ready to place
    const sids = legs.map((l) => l.sid).filter(Boolean);
    const dk = el('div', 'dkrow');
    if (sids.length) {
      const a = el('a', 'lnk sugb dkbtn', sids.length === legs.length ? 'Open in DraftKings' : `Open ${sids.length} of ${legs.length} legs in DraftKings`);
      a.href = 'https://sportsbook.draftkings.com/?outcomes=' + sids.map(encodeURIComponent).join('+'); a.target = '_blank'; a.rel = 'noopener';
      dk.append(a, el('span', 'dim', sids.length === legs.length ? 'Loads these legs into your DraftKings betslip. Sign in, check the prices, and place it.' : 'The other legs have no DraftKings link on this pull; add them by hand.'));
    } else dk.append(el('span', 'dim', 'No DraftKings link for these legs yet: links come with the next odds pull.'));
    sl.append(dk);
    const games = {}; legs.forEach((l) => { games[l.game] = (games[l.game] || 0) + 1; });
    const warns = [];
    Object.entries(games).filter(([, n]) => n > 1).forEach(([g, n]) => {
      const bad = legs.filter((l) => l.game === g && NO_SGP.has(l.kind));
      if (bad.length) warns.push(['bad', `DraftKings won't put goalie saves in a same-game parlay: ${bad.map((l) => l.label).join(', ')} can't be combined with the other ${g} leg${n > 2 ? 's' : ''}. Keep one leg from that game.`]);
      else warns.push(['warn', `${n} legs from ${g}: DraftKings prices same-game legs together, so the real payout differs and the legs are not independent.`]);
    });
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

function boardRecord() {
  const B = $('board'); B.innerHTML = '';
  const bt = D.backtest || {}; const lv = D.live;
  const fmtp = (x) => x == null ? '—' : (x * 100).toFixed(1) + '%';
  const roi = (x) => x == null ? '—' : sgn(Math.round(x * 1000) / 10) + '%';
  const mk = (title, head, rows, note) => { const c = el('div', 'col'); c.style.marginTop = '16px'; const h = el('div', 'colhead'); h.append(el('h2', null, title)); c.append(h); const tw = el('div', 'tablewrap'); const t = el('table', 'res'); const hr = el('tr'); head.forEach((x, i) => hr.append(el('th', i ? 'num' : null, x))); t.append(hr); rows.forEach((r) => { const tr = el('tr'); r.forEach((x, i) => tr.append(el('td', i ? 'num' : null, String(x)))); t.append(tr); }); tw.append(t); c.append(tw); if (note) c.append(el('p', 'note logfoot', note)); B.append(c); };
  if (lv && lv.groups && lv.groups.length) {
    mk('Live record at DraftKings', ['Group', 'Bets', 'W-L', 'Hit', 'Units', 'ROI'], lv.groups.map((g) => [g.group, g.bets, `${g.won}-${g.lost}`, fmtp(g.hit), sgn(g.units), roi(g.roi)]),
       `${lv.days.length} slate${lv.days.length > 1 ? 's' : ''} graded. Every priced leg is logged when the board is built and graded at that DraftKings price, 1 unit per leg.`);
  }
  const pz = lv && lv.parlays && lv.parlays.groups.filter((g) => g.bets);
  if (pz && pz.length) mk('Suggested parlays at DraftKings', ['Parlays', 'Count', 'W-L', 'Hit', 'Expected', 'Units', 'ROI'], pz.map((g) => [g.group, g.bets, `${g.won}-${g.lost}`, fmtp(g.hit), fmtp(g.exp_hit), sgn(g.units), roi(g.roi)]),
     'Each day\'s suggested parlays are saved when the board is built, for both Best value and Most likely to hit and every leg count (up to 6 suggestions each), and graded as whole parlays at DraftKings prices, 1 unit each. A parlay loses if any leg loses; pushed or voided legs drop out. Expected is the chance the board gave the parlays.');
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
  if (!B.children.length) B.append(el('div', 'empty', 'No backtest yet.'));
  $('foot').textContent = 'Backtests: scripts/nhl_props_backtest.py and scripts/nhl_game_backtest.py.';
}

// a leg's label, tappable to open the player's game log when the leg is a player prop
function legLabel(L, cls) {
  const pl = L.pid ? SRC(L.market).find((x) => x.id === L.pid) : null;
  if (!pl) return el('span', cls, L.label);
  const b = el('button', (cls ? cls + ' ' : '') + 'namebtn', L.label); b.type = 'button'; b.title = 'Game log';
  b.onclick = (e) => { e.stopPropagation(); openLog(pl, L.market); }; return b;
}
function openLog(p, k) {
  const ov = el('div', 'overlay'); ov.onclick = (e) => { if (e.target === ov) ov.remove(); };
  const pn = el('div', 'logpanel'); pn.setAttribute('role', 'dialog'); pn.setAttribute('aria-label', p.name + ' game log');
  const gkp = k === 'saves';
  const h = el('div', 'loghead'); const t = el('div'); t.append(el('h2', null, p.name), el('div', 'dim', gkp ? `${p.team} goalie · ${p.confirmed ? 'confirmed' : 'projected'} starter` : `${p.team} ${p.pos} · ${p.gp} games this season · ${p.toi} min lately`));
  const x = el('button', 'x', '×'); x.setAttribute('aria-label', 'Close'); x.onclick = () => ov.remove(); h.append(t, x); pn.append(h);
  const pr = p[k]; const chips = el('div', 'lchips');
  chips.append(el('span', 'pill likely', `proj ${pr.proj}${pr.line != null ? ' · line ' + pr.line : ''}`));
  if (pr.ch) Object.entries(pr.ch).forEach(([c, v]) => chips.append(el('span', 'pill', `${c} shots: ${pct(v)}`)));
  pn.append(chips);
  if (p.flags.length) pn.append(el('div', 'loghit', p.flags.join('; ')));
  const tw = el('div', 'tablewrap'); const tb = el('table', 'res log');
  const cols = gkp ? [['d', 'Date'], ['o', 'Opp'], ['sa', 'Shots'], ['sv', 'Saves'], ['pct', 'SV%']] : [['d', 'Date'], ['o', 'Opp'], ['toi', 'TOI'], ['sog', 'SOG'], ['g', 'G'], ['a', 'A'], ['blk', 'BLK']];
  const key = gkp ? 'sv' : 'sog';
  const hr = el('tr'); cols.forEach(([, c], i) => hr.append(el('th', i > 1 ? 'num' : null, c))); tb.append(hr);
  p.log.forEach((g) => { const tr = el('tr'); cols.forEach(([c], i) => { const v = c === 'pct' && g[c] != null ? g[c].toFixed(3).slice(1) : g[c]; tr.append(el('td', (i > 1 ? 'num' : '') + (c === key && pr.line != null && g[c] > pr.line ? ' hit' : ''), v ?? '—')); }); tb.append(tr); });
  tw.append(tb); pn.append(tw);
  pn.append(el('p', 'note logfoot', pr.line != null ? `Green marks games over tonight's line of ${pr.line}.` : `Last ${p.log.length} games.`));
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
