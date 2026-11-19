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
  // chance every leg hits. ps: each leg's chance; dirs: +1 = hits on a high number (Over, Yes, the home side), -1 = low;
  // C: correlations of the legs' hidden numbers before direction
  function joint(ps, dirs, C) {
    const k = ps.length; if (!k) return 1; if (k === 1) return ps[0];
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
  window.GameSim = { joint, parlay, ndtri, nfl: { parlay: nflParlay, rho: nflRho, v: nflVar }, nhl: { parlay: nhlParlay }, ready: (s) => !!(T[s] && T[s].rho), games: (s) => (T[s] || {}).games || 0 };
})();
