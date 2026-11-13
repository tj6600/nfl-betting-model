const D = JSON.parse(document.getElementById('nba-data').textContent);
const LEG = Object.fromEntries(D.legs.map((l) => [l.id, l]));
const STATS = [['pts', 'Points'], ['reb', 'Rebounds'], ['ast', 'Assists'], ['fg3m', 'Threes'], ['pra', 'Pts+Reb+Ast']];
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
try { slip = JSON.parse(localStorage.getItem('nba-slip-' + D.day) || '[]').filter((id) => LEG[id]); } catch (e) { slip = []; }
const saveSlip = () => { try { localStorage.setItem('nba-slip-' + D.day, JSON.stringify(slip)); } catch (e) {} };
// suggested parlays are built here so the leg count can be chosen: best remaining legs, 1 per game and 1 per player,
// no leg reused across suggestions (same rule as scripts/nba_board.py)
// two ways to build: 'value' = biggest edge first (scripts/nba_board.py pool); 'likely' = most likely to hit first,
// among legs that still pay more than they risk on average (edge 1+ pt) and carry no flags
const VALUE_POOL = (D.pool || []).map((id) => LEG[id]).filter(Boolean);
const LIKELY_POOL = D.legs.filter((l) => l.edge >= 1 && l.p >= 0.55 && !l.flags.length).sort((a, b) => b.p - a.p || b.edge - a.edge);
let mode = 'value';
try { mode = localStorage.getItem('nba-mode') === 'likely' ? 'likely' : 'value'; } catch (e) {}
let POOL = mode === 'likely' ? LIKELY_POOL : VALUE_POOL;
// market filter: pick any mix of markets (e.g. Points + Assists); none picked = every market. Suggestions follow it.
let KINDS = new Set();
const OPEN = new Set(), GLIM = {};
try { KINDS = new Set(JSON.parse(localStorage.getItem('nba-kinds') || '[]')); } catch (e) {}
const kindOk = (L) => !KINDS.size || KINDS.has(L.kind);
const MKTS = [...new Set(D.legs.map((L) => L.kind))];
function buildSlips(size, n = 6) {
  const out = [], used = new Set();
  const pool = POOL.filter(kindOk);
  for (let s = 0; s < n; s++) {
    const nG = new Set(pool.map((L) => L.game)).size;
    const slip = [], g = {}, pl = new Set(), perGame = Math.min(3, Math.max(size > 6 ? 3 : 1, Math.ceil(size / Math.max(1, nG))));   // more per game only when the slate is too small
    for (const L of pool) {
      if (used.has(L.id) || (g[L.game] || 0) >= perGame || (L.pid && pl.has(L.pid))) continue;
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
try { legCount = +localStorage.getItem('nba-legs') || null; } catch (e) {}
if (!SIZES.includes(legCount)) legCount = BEST;
let SLIPS = [];
const setMode = (m) => {
  mode = m; POOL = m === 'likely' ? LIKELY_POOL : VALUE_POOL; try { localStorage.setItem('nba-mode', m); } catch (e) {}
  sizesFor(); if (!SIZES.includes(legCount)) legCount = BEST;
};
const setSize = (k) => { legCount = k; try { localStorage.setItem('nba-legs', k); } catch (e) {} SLIPS = !k ? [] : POOL.length ? buildSlips(k) : (D.slips || []); };
setSize(legCount);
let sugIdx = -1;   // which suggestion is loaded (-1 = own slip)
let saved = [];
try { saved = JSON.parse(localStorage.getItem('nba-saved-' + D.day) || '[]').map((s) => ({ ...s, legs: s.legs.filter((id) => LEG[id]) })).filter((s) => s.legs.length); } catch (e) { saved = []; }
const saveSaved = () => { try { localStorage.setItem('nba-saved-' + D.day, JSON.stringify(saved)); } catch (e) {} };
const loadSug = (i) => { sugIdx = (i + SLIPS.length) % SLIPS.length; slip = SLIPS[sugIdx].slice(); saveSlip(); render(); };
const hasProps = D.players.some((p) => Object.values(p.props).some((x) => x.line != null));
if (!hasProps) state.sort = 'proj';

function header() {
  $('eyebrow').textContent = `NBA · ${D.dayLabel}`;
  $('lede').textContent = 'Game lines and player points, rebounds, assists and threes for tonight\'s slate, set against DraftKings. Chances blend the model with the book; pick a game, open a player for his game log, or build a parlay ranked by edge.';
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
  [['all', 'All'], ['G', 'Guards'], ['F', 'Forwards'], ['C', 'Centers']].forEach(([k, l]) => { const b = el('button', null, l); b.setAttribute('aria-pressed', state.pos === k); b.onclick = () => { state.pos = k; render(); }; pos.append(b); });
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
  let ps = D.players.filter((p) => p.props[k]);
  if (state.game !== 'all') ps = ps.filter((p) => p.game === state.game);
  if (state.pos !== 'all') ps = ps.filter((p) => p.pos === state.pos);
  if (state.q) ps = ps.filter((p) => (p.name + ' ' + p.team).toLowerCase().includes(state.q));
  if (hasProps) ps = ps.filter((p) => p.props[k].line != null);
  const key = { edge: (p) => -((bestSide(p.props[k]) || {}).edge ?? -99), proj: (p) => -p.props[k].proj, chance: (p) => -((bestSide(p.props[k]) || {}).p ?? 0), name: (p) => p.name };
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
  l.append(a, el('span', null, pr.line != null ? `line ${pr.line}` : `${pr.lo.toFixed(0)}–${pr.hi.toFixed(0)}`));
  m.append(tr, l); return m;
}

function boardProps(k) {
  const B = $('board'); B.innerHTML = '';
  const rows = propRows(k);
  $('count').textContent = `${rows.length} players`;
  const col = el('div', 'col');
  const h = el('div', 'colhead'); h.append(el('h2', null, SL[k]), el('span', null, hasProps ? 'Lean side and DraftKings price' : 'Lines not pulled for this slate yet'));
  col.append(h);
  if (!rows.length) col.append(el('div', 'empty', 'No players match.'));
  rows.forEach((p) => {
    const pr = p.props[k]; const best = bestSide(pr);
    const row = el('div', 'row');
    const who = el('div', 'who'); const nb = el('button', 'namebtn', p.name); nb.onclick = () => openLog(p, k);
    who.append(nb, el('span', 's', `${p.team} ${p.pos} vs ${p.opp} · ${p.mpg} min${p.boost ? ' · bigger role with ' + p.boost + ' out' : ''}${p.flags.length ? ' · ' + p.flags.join('; ') : ''}`));
    const price = el('div', 'price');
    if (best) {
      const side = best === pr.over ? 'Over' : 'Under';
      const sd = el('span', 'side ' + side.toLowerCase(), `${side} ${pr.line}`);
      price.append(sd, el('span', 'o', fmt(best.price)), el('span', 'e ' + (best.edge > 0 ? 'pos' : 'neg'), `${pct(best.p)} · edge ${sgn(best.edge)}`));
      const L = LEG[best.id];
      if (L && L.cat === 'Value') price.append(el('span', 'pill value', 'Value'));
    } else {
      price.append(el('span', 'o dim', pr.proj.toFixed(1)), el('span', 'e dim', `avg ${p.avg[k] ?? '—'}`));
    }
    row.append(who, meter(pr), price); col.append(row);
  });
  B.append(col);
  $('foot').textContent = hasProps ? `Props from DraftKings, pulled ${D.propsTaken || ''}. Chance = half model, half DraftKings no-vig. Edge = chance minus the price's break-even, in points. Value = edge 3+ and chance 55%+ with no role flag.` :
    'Player prop lines have not been pulled for this slate, so this shows projections only. Pulling props for one slate costs about 5 Odds API credits per game.';
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
    const fav = g.margin >= 0 ? `${g.home} by ${g.margin.toFixed(1)}` : `${g.away} by ${(-g.margin).toFixed(1)}`;
    [[fav, 'Model margin'], [g.total.toFixed(1), 'Model total'], [g.spread != null ? `${g.home} ${sgn(g.spread)}` : '—', 'DK spread'], [g.line_total ?? '—', 'DK total'], [`#${g.rank_away} / #${g.rank_home}`, 'Rating rank, away / home']].forEach(([v, k]) => { const d = el('div'); d.append(el('b', null, v), el('span', null, k)); pj.append(d); });
    c.append(pj);
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
    const outs = [...g.out_away.map((o) => `${g.away}: ${o.name}`), ...g.out_home.map((o) => `${g.home}: ${o.name}`)];
    c.append(el('div', 'outs', D.injuries ? (outs.length ? `Out tonight (ESPN injury report): ${outs.join(', ')}.` : 'No regulars listed out.') : (outs.length ? `Sat out their last game: ${outs.join(', ')}. Check the injury report.` : 'No regulars sat out either team\'s last game.')));
    wrap.append(c);
  });
  B.append(wrap);
  const bt = D.backtest;
  $('foot').textContent = `Game chances are 25% model and 75% DraftKings no-vig, because the model has not beaten the line in testing (${bt.rows ? Math.round(bt.rows[0].ats * 1000) / 10 + '% against the spread over ' + bt.games + ' games' : 'see Model record'}). Lines pulled ${D.taken || '—'}. Box scores through ${D.through}.`;
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
      try { localStorage.setItem('nba-kinds', JSON.stringify([...KINDS])); } catch (e) {}
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
    md.append(el('span', 'dim sugbest', (mode === 'likely' ? 'Highest-chance legs that still pay more than they risk on average (edge 1+, 55%+ chance, no flags)' : 'Biggest edge first (edge 3+, 55%+ chance)') + (KINDS.size ? `. Only ${[...KINDS].join(' + ')} legs (market filter).` : '')));
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
  if (!legs.length) sl.append(el('div', 'empty', SLIPS.length ? 'Add legs, or load a suggested parlay. Use the arrows or Shuffle to flip between suggestions, and Save to keep one.' : mode === 'likely' ? 'Add legs from the list. No leg is both 55%+ to hit and +EV on this slate.' : 'Add legs from the list. No leg meets the value rule (edge 3+, chance 55%+) on this slate.'));
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
    Object.entries(games).filter(([, n]) => n > 1).forEach(([g, n]) => warns.push(['warn', `${n} legs from ${g}: DraftKings prices same-game legs together, so the real payout differs and the legs are not independent.`]));
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
  const bt = D.backtest;
  const lv = D.live;
  const fmtp = (x) => x == null ? '—' : (x * 100).toFixed(1) + '%';
  const liveRows = lv ? lv.groups.concat(lv.by_kind || []).filter((g) => g.bets || g.clv_n) : [];
  if (liveRows.length) {
    const c = el('div', 'col'); const h = el('div', 'colhead'); h.append(el('h2', null, 'Live record at DraftKings'), el('span', null, `${lv.days.length} slate${lv.days.length > 1 ? 's' : ''} logged`)); c.append(h);
    const tw = el('div', 'tablewrap'); const t = el('table', 'res'); const hr = el('tr');
    ['Group', 'Bets', 'W-L', 'Hit', 'Expected', 'Units', 'ROI', 'Beat close', 'Lost to close'].forEach((x, i) => hr.append(el('th', i ? 'num' : null, x))); t.append(hr);
    liveRows.forEach((g) => { const tr = el('tr'); [g.group, g.bets, `${g.won}-${g.lost}`, g.bets ? fmtp(g.hit) : '—', fmtp(g.exp_hit), g.bets ? sgn(g.units) : '—', g.bets ? sgn(Math.round(g.roi * 1000) / 10) + '%' : '—',
      g.clv_n ? fmtp(g.beat) : '—', g.clv_n ? fmtp(g.lost_clv) : '—'].forEach((x, i) => tr.append(el('td', i ? 'num' : null, String(x)))); t.append(tr); });
    tw.append(t); c.append(tw);
    c.append(el('p', 'note logfoot', 'Every priced leg is logged when the board is built (about 2:47 PM ET) and graded at that DraftKings price, 1 unit per leg; players who sit are void. Beat close = DraftKings moved its line toward our side by tip-off, or kept the line and raised our side\'s chance by half a point or more. Beating the close more often than losing to it is the earliest sign of a real edge; results take hundreds of bets to mean much.'));
    c.style.marginBottom = '16px'; B.append(c);
  }
  if (!bt.rows) { B.append(el('div', 'empty', 'No backtest yet.')); return; }
  const tiles = el('div', 'tiles');
  const r0 = bt.rows[0];
  [[`${(r0.ats * 100).toFixed(1)}%`, 'Against the spread', `${r0.ats_n} games, ${bt.seasons}. Break-even is 52.4%.`],
   [`${(r0.tot * 100).toFixed(1)}%`, 'Totals', `${r0.tot_n} games with a listed total`],
   [`${bt.mae_model} vs ${bt.mae_line}`, 'Margin error, model vs line', 'Average miss in points; lower is better']].forEach(([b, k, s]) => { const t = el('div', 'tile'); t.append(el('span', 'k', k), el('span', 'big', b), el('span', 's', s)); tiles.append(t); });
  B.append(tiles);
  const mk = (title, head, rows) => { const c = el('div', 'col'); c.style.marginTop = '16px'; const h = el('div', 'colhead'); h.append(el('h2', null, title)); c.append(h); const tw = el('div', 'tablewrap'); const t = el('table', 'res'); const hr = el('tr'); head.forEach((x, i) => hr.append(el('th', i ? 'num' : null, x))); t.append(hr); rows.forEach((r) => { const tr = el('tr'); r.forEach((x, i) => tr.append(el('td', i ? 'num' : null, x))); t.append(tr); }); tw.append(t); c.append(tw); B.append(c); };
  mk('Game picks by edge size', ['Model edge', 'Spread picks', 'Hit', 'Total picks', 'Hit'], bt.rows.map((r) => [`${r.edge}+ pts`, r.ats_n, (r.ats * 100).toFixed(1) + '%', r.tot_n, (r.tot * 100).toFixed(1) + '%']));
  if (bt.props) {
    mk('Prop projections: average miss', ['Stat', 'Model', 'Season avg', 'Last 10'], bt.props.mae.map((r) => [r.stat, r.model, r.season_avg, r.last10]));
    mk('Prop leans vs a stand-in line (2025-26)', ['Stat', 'Leans', 'Predicted', 'Hit', 'Share overs'], bt.props.cal.map((r) => [r.stat, r.n, pct(r.pred), pct(r.hit), pct(r.overs)]));
  }
  $('foot').textContent = 'Every test fits the model only on games before the day it predicts. Game lines are ESPN\'s listed lines (DraftKings from 2025-26, consensus before). There are no historical prop lines in our data, so prop leans are tested against each player\'s season average rounded to the half point; real DraftKings lines are sharper, so expect less than the hit rate shown. Most leans are Unders because scoring is right-skewed.';
}

// a leg's label, tappable to open the player's game log when the leg is a player prop
function legLabel(L, cls) {
  const pl = L.pid ? D.players.find((x) => x.id === L.pid) : null;
  if (!pl) return el('span', cls, L.label);
  const b = el('button', (cls ? cls + ' ' : '') + 'namebtn', L.label); b.type = 'button'; b.title = 'Game log';
  b.onclick = (e) => { e.stopPropagation(); openLog(pl, L.stat || L.market); }; return b;
}
function openLog(p, k) {
  const ov = el('div', 'overlay'); ov.onclick = (e) => { if (e.target === ov) ov.remove(); };
  const pn = el('div', 'logpanel'); pn.setAttribute('role', 'dialog'); pn.setAttribute('aria-label', p.name + ' game log');
  const h = el('div', 'loghead'); const t = el('div'); t.append(el('h2', null, p.name), el('div', 'dim', `${p.team} ${p.pos} · ${p.gp} games this season · ${p.mpg} min lately`));
  const x = el('button', 'x', '×'); x.setAttribute('aria-label', 'Close'); x.onclick = () => ov.remove(); h.append(t, x); pn.append(h);
  const chips = el('div', 'lchips');
  STATS.forEach(([s, l]) => { const pr = p.props[s]; if (!pr) return; chips.append(el('span', 'pill likely', `${l}: proj ${pr.proj}${pr.line != null ? ' · line ' + pr.line : ''} · avg ${p.avg[s] ?? '—'}`)); });
  pn.append(chips);
  if (p.flags.length) pn.append(el('div', 'loghit', p.flags.join('; ')));
  const tw = el('div', 'tablewrap'); const tb = el('table', 'res log');
  const hr = el('tr'); ['Date', 'Opp', 'Min', 'Pts', 'Reb', 'Ast', '3PM', 'PRA'].forEach((c, i) => hr.append(el('th', i > 1 ? 'num' : null, c))); tb.append(hr);
  const line = p.props[k] && p.props[k].line;
  p.log.forEach((g) => { const tr = el('tr'); [g.d, g.o, g.m, g.pts, g.reb, g.ast, g.fg3m, g.pra].forEach((v, i) => { const keyc = ['', '', '', 'pts', 'reb', 'ast', 'fg3m', 'pra'][i]; tr.append(el('td', (i > 1 ? 'num' : '') + (keyc === k && line != null && v > line ? ' hit' : ''), v)); }); tb.append(tr); });
  tw.append(tb); pn.append(tw);
  pn.append(el('p', 'note logfoot', line != null ? `Green marks games over tonight's ${SL[k].toLowerCase()} line of ${line}.` : 'Last 12 games played.'));
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
