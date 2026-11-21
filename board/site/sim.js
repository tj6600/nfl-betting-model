// Game simulation for same-game parlays (Thomas, 2026-11-19). Same model as nflmodel/sim.py.
// Each bet is driven by one hidden "game outcome" number: the home margin against the spread, the total against the line,
// or a player's stat against what was expected of him. Those numbers are drawn together 20,000 times per game with the
// correlations measured on past games (sim_tables.js, from scripts/sim_fit.py and scripts/nhl_sim_fit.py), so a QB's
// yards and his receivers' yards rise and fall together, a blowout goes with the winner's rushing, and so on. A leg hits
// when its number lands past the point that matches its own chance, so every leg keeps the board's chance; only how the
// legs move together changes. Legs from different games are independent.
(function () {
  const T = window.SIM_TABLES || {};
  const N = 20000;
  function ndtri(p) {   // inverse normal CDF (Acklam)
    p = Math.min(1 - 1e-12, Math.max(1e-12, p));
    const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
    const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
    const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
    const q = p < 0.5 ? p : 1 - p; let x;
    if (q < 0.02425) { const t = Math.sqrt(-2 * Math.log(q)); x = (((((c[0] * t + c[1]) * t + c[2]) * t + c[3]) * t + c[4]) * t + c[5]) / ((((d[0] * t + d[1]) * t + d[2]) * t + d[3]) * t + 1); }
    else { const u = q - 0.5, r = u * u; x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * u / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1); }
    return p < 0.5 ? x : -x;
  }
  // seeded normal draws (same numbers every time, so a slip's chance doesn't flicker between renders)
  const Z = {};
  function draws(k) {
    if (Z[k]) return Z[k];
    let s = 7 + k * 7919;
    const u = () => { s |= 0; s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
    const z = new Float64Array(N * k);
    for (let i = 0; i < z.length; i += 2) { const r = Math.sqrt(-2 * Math.log(u() + 1e-300)), th = 2 * Math.PI * u(); z[i] = r * Math.cos(th); if (i + 1 < z.length) z[i + 1] = r * Math.sin(th); }
    return (Z[k] = z);
  }
  function chol(C) {   // Cholesky; null when the matrix isn't positive definite
    const k = C.length, L = C.map(() => new Array(k).fill(0));
    for (let i = 0; i < k; i++) for (let j = 0; j <= i; j++) {
      let s = C[i][j]; for (let m = 0; m < j; m++) s -= L[i][m] * L[j][m];
      if (i === j) { if (s <= 1e-6) return null; L[i][i] = Math.sqrt(s); } else L[i][j] = s / L[j][j];
    }
    return L;
  }
  // P(X > a, Y > b) for standard normals with correlation rho: exact (Gauss-Legendre, 40 nodes, as nflmodel/sim.py's
  // bvn_upper), so two-leg chances and the builders' leg links match the Python logs exactly
  const GL = (() => {   // Legendre nodes and weights on [-1, 1]
    const n = 40, x = [], w = [];
    for (let i = 1; i <= n; i++) {
      let z = Math.cos(Math.PI * (i - 0.25) / (n + 0.5)), dp = 0;
      for (let it = 0; it < 100; it++) {
        let p0 = 1, p1 = z; for (let k = 2; k <= n; k++) { const p2 = ((2 * k - 1) * z * p1 - (k - 1) * p0) / k; p0 = p1; p1 = p2; }
        dp = n * (z * p1 - p0) / (z * z - 1); const dz = p1 / dp; z -= dz; if (Math.abs(dz) < 1e-15) break;
      }
      x.push(z); w.push(2 / ((1 - z * z) * dp * dp));
    }
    return { x, w };
  })();
  function erf(x) {   // Abramowitz-Stegun 7.1.26, as sim.py
    const s = Math.sign(x); x = Math.abs(x); const t = 1 / (1 + 0.3275911 * x);
    return s * (1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x));
  }
  const Phi = (x) => 0.5 * (1 + erf(x / Math.SQRT2)), phi = (x) => Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);
  function bvnUpper(a, b, rho) {
    const lo = Math.min(8, Math.max(-8, a)), hi = 8, s = Math.sqrt(Math.max(1 - rho * rho, 1e-12)); let t = 0;
    for (let i = 0; i < GL.x.length; i++) { const x = (hi - lo) / 2 * GL.x[i] + (hi + lo) / 2; t += GL.w[i] * phi(x) * (1 - Phi((b - rho * x) / s)); }
    return (hi - lo) / 2 * t;
  }
  // chance every leg hits. ps: each leg's chance; dirs: +1 = hits on a high number (Over, Yes, the home side), -1 = low;
  // C: correlations of the legs' hidden numbers before direction
  function joint(ps, dirs, C) {
    const k = ps.length; if (!k) return 1; if (k === 1) return ps[0];
    if (k === 2) { const r = Math.max(-0.999, Math.min(0.999, C[0][1] * dirs[0] * dirs[1])); return bvnUpper(ndtri(1 - ps[0]), ndtri(1 - ps[1]), r); }
    let A = C.map((r, i) => r.map((v, j) => (i === j ? 1 : v * dirs[i] * dirs[j]))), L = chol(A);
    for (let t = 0; !L && t < 40; t++) { A = A.map((r, i) => r.map((v, j) => (i === j ? 1 : v * 0.95))); L = chol(A); }   // shrink until consistent
    if (!L) return ps.reduce((a, p) => a * p, 1);
    const cut = ps.map((p) => ndtri(1 - p)), z = draws(k); let hit = 0;
    for (let n = 0; n < N; n++) {
      const o = n * k; let ok = true;
      for (let i = 0; i < k && ok; i++) { let y = 0; for (let j = 0; j <= i; j++) y += L[i][j] * z[o + j]; ok = y > cut[i]; }
      if (ok) hit++;
    }
    return hit / N;
  }
  const C1 = {};
  // legs: [{p, game, v}] with v = that sport's hidden-number description; rho(a, b) -> correlation of two v's
  function parlay(legs, rho) {
    const byGame = {}; legs.forEach((l) => (byGame[l.game] = byGame[l.game] || []).push(l));
    let p = 1, pInd = 1; const groups = [];
    for (const [game, xs] of Object.entries(byGame)) {
      const ind = xs.reduce((a, l) => a * l.p, 1); pInd *= ind;
      if (xs.length === 1) { p *= xs[0].p; continue; }
      const key = xs.map((l) => l.id + ':' + l.p).sort().join('|');
      if (!(key in C1)) {
        const C = xs.map((a, i) => xs.map((b, j) => (i === j ? 1 : rho(a.v, b.v))));
        C1[key] = joint(xs.map((l) => l.p), xs.map((l) => l.v.dir), C);
      }
      p *= C1[key]; groups.push({ game, n: xs.length, p: C1[key], pInd: ind });
    }
    return { p, pInd, groups };
  }
  // ---- NFL ----
  // a leg's hidden number: mar = home margin vs spread, tot = total vs line, or a player's pass/rush/rec/recs/td
  const NFL_POS = { pass: 'QB', rush: 'RB', rec: 'WR', recs: 'WR', td: 'WR' };
  function nflVar(l, pos, favHome) {
    const [away, home] = l.game.split(' @ ');
    if (l.kind === 'Game') {
      if (/-total$/.test(l.key)) return { stat: 'tot', dir: l.sl === 'Under' ? -1 : 1, favHome };
      const team = String(l.sl).split(' ')[0];
      return { stat: 'mar', dir: team === home ? 1 : -1, favHome };
    }
    const stat = l.kind === 'TD' ? 'td' : l.kind === 'Milestone' ? l.key.split('-').pop().toLowerCase() : l.kind.toLowerCase();
    let ps = pos || NFL_POS[stat]; if (!['QB', 'RB', 'WR', 'TE'].includes(ps)) ps = NFL_POS[stat];
    return { stat, pos: ps, pid: l.pid, team: l.team, home: l.team === home, dir: l.alt || l.sl === 'Over' || l.sl === 'Yes' ? 1 : -1 };
  }
  function nflRho(a, b) {
    const R = (T.nfl || {}).rho || {}, g = (s) => s === 'mar' || s === 'tot';
    if (g(a.stat) && !g(b.stat)) [a, b] = [b, a];
    if (g(a.stat)) { if (a.stat === b.stat) return 0.999; const m = a.stat === 'mar' ? a : b; return m.favHome == null ? 0 : (R['mar:fav|tot|g'] || 0) * (m.favHome ? 1 : -1); }
    if (b.stat === 'mar') return (R[`${a.stat}:${a.pos}|mar|tm`] || 0) * (a.home ? 1 : -1);
    if (b.stat === 'tot') return R[`${a.stat}:${a.pos}|tot|g`] || 0;
    if (a.pid === b.pid && a.stat === b.stat) return 0.999;
    const ta = `${a.stat}:${a.pos}`, tb = `${b.stat}:${b.pos}`, rel = a.pid === b.pid ? 'self' : a.team === b.team ? 'tm' : 'opp';
    return R[[ta, tb].sort().join('|') + '|' + rel] || 0;
  }
  // which side each game's favorite is, from the board's spread (or moneyline) legs
  function nflFavs(all) {
    const f = {};
    for (const l of all) if (l.kind === 'Game' && /-spread$/.test(l.key)) { const m = String(l.sl).match(/^(\S+) (-?[\d.]+)/); if (m && +m[2] < 0) f[l.game] = m[1] === l.game.split(' @ ')[1]; }
    for (const l of all) if (l.kind === 'Game' && /-moneyline$/.test(l.key) && !(l.game in f) && l.price < -100) f[l.game] = l.sl === l.game.split(' @ ')[1];
    return f;
  }
  let FAV = null;
  // ls: board legs; all: every leg on the board (for favorites); posOf(l): the player's position if known
  function nflParlay(ls, all, posOf, shade = 0) {
    FAV = FAV || nflFavs(all || ls);
    return parlay(ls.map((l) => ({ id: l.id, game: l.game, p: Math.max(0.01, l.p - shade), v: nflVar(l, posOf ? posOf(l) : l.pos, FAV[l.game]) })), nflRho);
  }
  // ---- NHL ----  mar = home goal difference vs the moneyline, tot = goals vs the total, sog (F or D skater), saves (G)
  function nhlVar(l, pos, favHome) {
    const home = l.game.split(' @ ')[1];
    if (l.kind === 'Moneyline' || l.kind === 'Puck line') return { stat: 'mar', dir: l.side === home ? 1 : -1, favHome };
    if (l.kind === 'Total') return { stat: 'tot', dir: l.side === 'Under' ? -1 : 1, favHome };
    const stat = /saves/i.test(l.kind) ? 'saves' : 'sog';
    return { stat, pos: stat === 'saves' ? 'G' : pos === 'D' ? 'D' : 'F', pid: l.pid, team: l.team, home: l.team === home, dir: l.side === 'Under' ? -1 : 1 };
  }
  function tableRho(sport) {
    return (a, b) => {
      const R = (T[sport] || {}).rho || {}, g = (s) => s === 'mar' || s === 'tot';
      if (g(a.stat) && !g(b.stat)) [a, b] = [b, a];
      if (g(a.stat)) { if (a.stat === b.stat) return 0.999; const m = a.stat === 'mar' ? a : b; return m.favHome == null ? 0 : (R['mar:fav|tot|g'] || 0) * (m.favHome ? 1 : -1); }
      if (b.stat === 'mar') return (R[`${a.stat}:${a.pos}|mar|tm`] || 0) * (a.home ? 1 : -1);
      if (b.stat === 'tot') return R[`${a.stat}:${a.pos}|tot|g`] || 0;
      if (a.pid === b.pid && a.stat === b.stat) return 0.999;
      const rel = a.pid === b.pid ? 'self' : a.team === b.team ? 'tm' : 'opp';
      return R[[`${a.stat}:${a.pos}`, `${b.stat}:${b.pos}`].sort().join('|') + '|' + rel] || 0;
    };
  }
  let NFAV = null;
  function nhlParlay(ls, all, posOf, shade = 0) {
    if (!NFAV) { NFAV = {}; for (const l of all || ls) if (l.kind === 'Moneyline' && l.p > 0.5) NFAV[l.game] = l.side === l.game.split(' @ ')[1]; }
    return parlay(ls.map((l) => ({ id: l.id, game: l.game, p: Math.max(0.01, l.p - shade), v: nhlVar(l, posOf ? posOf(l) : null, NFAV[l.game]) })), tableRho('nhl'));
  }
  // how much two same-game legs help each other: P(both) / (P(a) x P(b)); 1 for different games. The builders use it to
  // pick legs that rise together and skip legs that work against each other (Thomas, 2026-11-21)
  const LK = {};
  function linkOf(sport, a, b, va, vb, rho) {
    if (a.game !== b.game) return 1;
    const key = sport + '|' + [a.id + ':' + a.p, b.id + ':' + b.p].sort().join('|');
    if (!(key in LK)) {
      const pa = Math.max(0.01, Math.min(0.99, a.p)), pb = Math.max(0.01, Math.min(0.99, b.p));
      LK[key] = joint([pa, pb], [va.dir, vb.dir], [[1, rho(va, vb)], [rho(va, vb), 1]]) / (pa * pb);
    }
    return LK[key];
  }
  function nflLink(a, b, all, posOf) {
    if (a.game !== b.game) return 1; FAV = FAV || nflFavs(all || [a, b]);
    const v = (l) => nflVar(l, posOf ? posOf(l) : l.pos, FAV[l.game]);
    return linkOf('nfl', a, b, v(a), v(b), nflRho);
  }
  function nhlLink(a, b, all, posOf) {
    if (a.game !== b.game) return 1;
    if (!NFAV) { NFAV = {}; for (const l of all || [a, b]) if (l.kind === 'Moneyline' && l.p > 0.5) NFAV[l.game] = l.side === l.game.split(' @ ')[1]; }
    const v = (l) => nhlVar(l, posOf ? posOf(l) : null, NFAV[l.game]);
    return linkOf('nhl', a, b, v(a), v(b), tableRho('nhl'));
  }
  // ---- Simulation tab (Thomas, 2026-11-21): each game's simulation on one card ----
  // cfg: { sport: 'nfl'|'nhl', legs: DraftKings-priced legs, all: every board leg, posOf, name(l), price(l), ok(l) (fit for
  //        a same-game parlay), role(l): 'win' | 'total' | 'line' | 'player', main(l) (a main line, not an alt rung),
  //        slot(l) (one leg per slot in a parlay), who(l) (player id, '' for game lines), starts {game: iso}, onBuild(ids) }
  // A card shows: the game lines' chances; the game script (each player's chance if each team wins, and if the game goes over
  // or under); the likeliest same-game parlays (simulated vs multiplied); the legs that move together or against each other.
  // Every number is from the board's own chances and the correlations, so nothing here costs odds credits.
  function gameView(cfg, game) {
    const link = cfg.sport === 'nfl' ? (a, b) => nflLink(a, b, cfg.all, cfg.posOf) : (a, b) => nhlLink(a, b, cfg.all, cfg.posOf);
    const parl = cfg.sport === 'nfl' ? (ls) => nflParlay(ls, cfg.all, cfg.posOf) : (ls) => nhlParlay(ls, cfg.all, cfg.posOf);
    const ls = cfg.legs.filter((l) => l.game === game), home = game.split(' @ ')[1];
    const wins = ls.filter((l) => cfg.role(l) === 'win').sort((a, b) => b.p - a.p);
    const tots = ls.filter((l) => cfg.role(l) === 'total' && cfg.main(l));
    const over = tots.find((l) => /^Over/.test(cfg.side(l))), under = tots.find((l) => /^Under/.test(cfg.side(l)));
    const lines = ls.filter((l) => cfg.role(l) !== 'player' && cfg.main(l)).sort((a, b) => b.p - a.p);
    // game script: one row per player market (its Over / Yes side, main line), chance overall and in each scenario
    const cond = (l, a) => { if (!a) return null; const j = l.p * a.p * link(l, a); return { hit: j / a.p, miss: (l.p - j) / (1 - a.p) }; };
    const fav = wins[0], pl = {};
    for (const l of ls) if (cfg.role(l) === 'player' && cfg.main(l) && /^(Over|Yes)/.test(cfg.side(l))) { const k = cfg.slot(l); if (!pl[k] || Math.abs(l.p - 0.5) < Math.abs(pl[k].p - 0.5)) pl[k] = l; }
    const script = Object.values(pl).map((l) => {
      const w = cond(l, fav), t = cond(l, over);
      return { l, p: l.p, favWin: w && w.hit, dogWin: w && w.miss, over: t && t.hit, under: t && t.miss, swing: Math.max(w ? Math.abs(w.hit - w.miss) : 0, t ? Math.abs(t.hit - t.miss) : 0) };
    }).sort((a, b) => b.swing - a.swing);
    // likeliest same-game parlays from the legs fit for one (2 and 3 legs), screened on pair links, then simulated
    const pool = ls.filter(cfg.ok).sort((a, b) => b.p - a.p).slice(0, 14), fits = (xs) => {
      const sl = new Set(), wh = new Set(); let g = 0;
      for (const x of xs) { if (sl.has(cfg.slot(x))) return false; sl.add(cfg.slot(x)); const w = cfg.who(x); if (w) { if (wh.has(w)) return false; wh.add(w); } else if (++g > 1) return false; }
      return true;
    };
    const pairs = [];
    for (let i = 0; i < pool.length; i++) for (let j = i + 1; j < pool.length; j++) {
      const a = pool[i], b = pool[j]; if (!fits([a, b])) continue;
      const r = link(a, b); pairs.push({ ids: [a.id, b.id], ls: [a, b], r, p: a.p * b.p * r, pInd: a.p * b.p });
    }
    const top2 = pairs.slice().sort((a, b) => b.p - a.p).slice(0, 3);
    const tri = [];
    for (let i = 0; i < pool.length; i++) for (let j = i + 1; j < pool.length; j++) for (let k = j + 1; k < pool.length; k++) {
      const xs = [pool[i], pool[j], pool[k]]; if (!fits(xs)) continue;
      tri.push({ xs, est: xs[0].p * xs[1].p * xs[2].p * link(xs[0], xs[1]) * link(xs[0], xs[2]) * link(xs[1], xs[2]) });
    }
    const top3 = tri.sort((a, b) => b.est - a.est).slice(0, 12).map((t) => { const r = parl(t.xs); return { ids: t.xs.map((x) => x.id), ls: t.xs, p: r.p, pInd: r.pInd }; })
      .sort((a, b) => b.p - a.p).slice(0, 3);
    const big = pairs.filter((x) => x.ls.every((l) => l.p >= 0.3));
    const together = big.filter((x) => x.r > 1.03).sort((a, b) => b.r - a.r).slice(0, 3);
    const against = big.filter((x) => x.r < 0.97).sort((a, b) => a.r - b.r).slice(0, 3);
    return { game, home, wins, over, under, lines, fav, script, top2, top3, together, against };
  }
  const SIM_CSS = `.simcard{margin-bottom:16px}.simlines{display:flex;flex-wrap:wrap;gap:6px;padding:10px 14px}
.simchip{border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:13px;white-space:nowrap}
.simchip b{font-variant-numeric:tabular-nums}.simh{font-size:14px;margin:12px 14px 2px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.simcard .note{margin:0 14px 6px;font-size:13px;color:var(--muted)}td.simlegs{white-space:normal;min-width:180px;line-height:1.35}
.simcard table.res td,.simcard table.res th{padding:7px 8px}.simpairs{margin:4px 14px 12px;padding-left:18px;font-size:14px;line-height:1.45}.simpairs b{margin-right:4px;font-variant-numeric:tabular-nums}`;
  function renderTab(box, cfg) {
    if (!document.getElementById('sim-css')) { const st = document.createElement('style'); st.id = 'sim-css'; st.textContent = SIM_CSS; document.head.append(st); }
    const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
    const pc = (p) => (p == null ? '—' : p < 0.1 ? (p * 100).toFixed(1) + '%' : Math.round(p * 100) + '%');
    const dec = (a) => (a > 0 ? 1 + a / 100 : 1 + 100 / -a), am = (d) => (d >= 2 ? '+' + Math.round((d - 1) * 100) : String(Math.round(-100 / (d - 1))));
    const now = Date.now(), games = [...new Set(cfg.legs.map((l) => l.game))]
      .filter((g) => !(cfg.starts[g] && Date.parse(cfg.starts[g]) <= now))
      .sort((a, b) => (Date.parse(cfg.starts[a] || 0) || 0) - (Date.parse(cfg.starts[b] || 0) || 0));
    box.replaceChildren();
    if (!games.length) { box.append(el('div', 'empty', 'No upcoming games with DraftKings prices on this board.')); return; }
    const when = (g) => { const t = cfg.starts[g]; return t ? new Date(t).toLocaleString('en-US', { weekday: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) + ' ET' : ''; };
    for (const g of games) {
      const V = gameView(cfg, g), c = el('section', 'col simcard');
      const h = el('div', 'colhead'); h.append(el('h2', null, g), el('span', null, when(g))); c.append(h);
      const chips = el('div', 'simlines');
      for (const l of V.lines.slice(0, 6)) { const ch = el('span', 'simchip'); ch.append(el('b', null, pc(l.p)), el('span', null, ' ' + cfg.name(l))); chips.append(ch); }
      c.append(chips);
      // game script
      if (V.script.length && (V.fav || V.over)) {
        const fT = V.fav ? cfg.team(V.fav) : '', dT = V.fav ? (fT === V.home ? g.split(' @ ')[0] : V.home) : '';
        c.append(el('h3', 'simh', 'Game script'), el('p', 'note', 'Each player’s chance overall and if the game goes each way, from 20,000 simulated games.'));
        const tw = el('div', 'tablewrap'), t = el('table', 'res'), hr = el('tr');
        ['Leg', 'Overall'].concat(V.fav ? [`${fT} wins`, `${dT} wins`] : []).concat(V.over ? ['Over', 'Under'] : []).forEach((x, i) => hr.append(el('th', i ? 'num' : null, x)));
        t.append(hr);
        for (const r of V.script.slice(0, 8)) {
          const tr = el('tr'); tr.append(el('td', null, cfg.name(r.l)), el('td', 'num', pc(r.p)));
          const cell = (x) => { const d = el('td', 'num ' + (x - r.p > 0.03 ? 'pos' : x - r.p < -0.03 ? 'neg' : 'dim'), pc(x)); tr.append(d); };
          if (V.fav) { cell(r.favWin); cell(r.dogWin); } if (V.over) { cell(r.over); cell(r.under); }
          t.append(tr);
        }
        tw.append(t); c.append(tw);
      }
      // likeliest same-game parlays
      const sg = V.top2.concat(V.top3);
      if (sg.length) {
        c.append(el('h3', 'simh', 'Likeliest same-game parlays'), el('p', 'note', 'Simulated chance vs the legs multiplied as if unrelated. DraftKings prices same-game parlays itself, usually below the multiplied payout shown.'));
        const tw = el('div', 'tablewrap'), t = el('table', 'res'), hr = el('tr');
        ['Legs', 'Simulated', 'Multiplied', 'Payout', ''].forEach((x, i) => hr.append(el('th', i ? 'num' : null, x))); t.append(hr);
        for (const x of sg) {
          const tr = el('tr'), d = x.ls.reduce((a, l) => a * dec(cfg.price(l)), 1);
          const nm = el('td', 'simlegs'); x.ls.forEach((l, i) => { if (i) nm.append(el('br')); nm.append(document.createTextNode(cfg.name(l))); });
          const b = el('button', 'lnk', 'Build'); b.type = 'button'; b.onclick = () => cfg.onBuild(x.ids);
          const bt = el('td', 'num'); bt.append(b);
          tr.append(nm, el('td', 'num ' + (x.p - x.pInd >= 0.01 ? 'pos' : x.p - x.pInd <= -0.01 ? 'neg' : ''), pc(x.p)), el('td', 'num dim', pc(x.pInd)), el('td', 'num', am(d)), bt);
          t.append(tr);
        }
        tw.append(t); c.append(tw);
      }
      // legs that move together / against each other
      if (V.together.length || V.against.length) {
        c.append(el('h3', 'simh', 'Legs that move together'));
        const ul = el('ul', 'simpairs');
        const li = (x, up) => { const i = el('li'); i.append(el('b', up ? 'pos' : 'neg', (up ? '+' : '−') + Math.round(Math.abs(x.r - 1) * 100) + '%'), document.createTextNode(` ${cfg.name(x.ls[0])} + ${cfg.name(x.ls[1])}: both hit ${pc(x.p)} vs ${pc(x.pInd)} if unrelated`)); ul.append(i); };
        V.together.forEach((x) => li(x, true)); V.against.forEach((x) => li(x, false));
        c.append(ul);
      }
      box.append(c);
    }
  }
  window.GameSim = { joint, parlay, ndtri, nfl: { parlay: nflParlay, rho: nflRho, v: nflVar, link: nflLink }, nhl: { parlay: nhlParlay, link: nhlLink }, ready: (s) => !!(T[s] && T[s].rho), gameView, renderTab, games: (s) => (T[s] || {}).games || 0 };
})();
