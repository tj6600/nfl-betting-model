// "Line changed?" editor (Thomas, 2026-11-19). The board only moves on scheduled odds pulls, so when DraftKings moves a
// line (Tyler Warren receptions 5.5 -> 4.5) or a price, the user types the new number on the leg and the page re-prices it
// in the browser: the model's chance at the new line comes from the player's (or game's) projected distribution, the
// book's chance from the new price with the board's margin, blended with the board's own weights. The leg object itself
// is updated, so every chance, edge, EV, the parlay chance (game simulation included) and the share card follow.
// Edits are saved in this browser (localStorage) until the next board update, then dropped. No odds pulls, no credits.
//
// A page calls LineEdit.setup({ sport, stamp, legs, model, weight, sibling, lineOf, signed, fields, onChange }) once,
// right after it builds its legs, then uses LineEdit.btn(leg), LineEdit.tag(leg) and LineEdit.banner() in its views.
(function () {
  const dec = (a) => (a > 0 ? 1 + a / 100 : 1 + 100 / -a);
  const imp = (a) => 1 / dec(a);
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  function ndtri(p) {   // inverse normal CDF (Acklam), same as sim.js
    p = clamp(p, 1e-12, 1 - 1e-12);
    const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
    const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
    const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
    const q = p < 0.5 ? p : 1 - p; let x;
    if (q < 0.02425) { const t = Math.sqrt(-2 * Math.log(q)); x = (((((c[0] * t + c[1]) * t + c[2]) * t + c[3]) * t + c[4]) * t + c[5]) / ((((d[0] * t + d[1]) * t + d[2]) * t + d[3]) * t + 1); }
    else { const u = q - 0.5, r = u * u; x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * u / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1); }
    return p < 0.5 ? x : -x;
  }
  function ncdf(z) {   // normal CDF (Abramowitz-Stegun 7.1.26 on erf, error < 1.5e-7)
    const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2);
    const e = 1 - (((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t) * Math.exp(-z * z / 2);
    return z >= 0 ? (1 + e) / 2 : (1 - e) / 2;
  }
  function lgamma(x) {   // Lanczos
    const g = [676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059, 12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
    if (x < 0.5) return Math.log(Math.PI / Math.abs(Math.sin(Math.PI * x))) - lgamma(1 - x);
    x -= 1; let a = 0.99999999999980993; const t = x + 7.5;
    for (let i = 0; i < 8; i++) a += g[i] / (x + i + 1);
    return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
  }
  // ---- distributions: each gives P(stat > line) ----
  const D = {
    normal: (mu, sd, line) => 1 - ncdf((line - mu) / sd),
    // negative binomial, mean mu and size r (nhlmodel/stats.py): P(X > line) = 1 - P(X <= floor(line))
    nb(mu, r, line) {
      const k = Math.floor(line); if (k < 0) return 1;
      const p = r / (r + mu); let cdf = 0;
      for (let i = 0; i <= k; i++) cdf += Math.exp(lgamma(i + r) - lgamma(r) - lgamma(i + 1) + r * Math.log(p) + i * Math.log(1 - p));
      return clamp(1 - cdf, 0, 1);
    },
    poisson(mu, line) {
      const k = Math.floor(line); if (k < 0) return 1; let t = Math.exp(-mu), s = t;
      for (let i = 1; i <= k; i++) { t *= mu / i; s += t; }
      return clamp(1 - s, 0, 1);
    },
    pmf: (ps, line) => ps.reduce((a, p, k) => a + (k > line ? p : 0), 0),
    // the yards model's empirical actual/expected ratios by projection bucket (nflmodel/yards.py Spread.p_over)
    emp(dist, mu, line) {
      if (!(mu > 0)) return null;
      let bi = 0; while (bi < dist.edges.length - 2 && mu >= dist.edges[bi + 1]) bi++;
      const keys = Object.keys(dist.r).map(Number); if (!keys.length) return null;
      const k = keys.includes(bi) ? bi : keys.reduce((a, b) => (Math.abs(b - bi) < Math.abs(a - bi) ? b : a));
      const q = dist.r[k], x = line / mu, n = q.length - 1;
      if (x < q[0]) return 1; if (x >= q[n]) return 0;
      let lo = 0, hi = n; while (hi - lo > 1) { const m = (lo + hi) >> 1; if (q[m] <= x) lo = m; else hi = m; }
      const f = q[hi] > q[lo] ? (x - q[lo]) / (q[hi] - q[lo]) : 1;
      return 1 - (lo + f) / n;
    },
    // fallback when the page has no stored spread: log-normal through the median and the middle half of outcomes
    logn(median, q25, q75, line) {
      if (!(median > 0) || !(line > 0)) return line <= 0 ? 1 : null;
      const s = q25 > 0 && q75 > q25 ? Math.log(q75 / q25) / 1.349 : 0.6;
      return 1 - ncdf(Math.log(line / median) / Math.max(0.15, s));
    },
  };
  // The leg keeps the board's own chance at the board's line; a moved line shifts it by the distribution's change
  // (in normal-score terms), so small differences between this distribution and the model's own (rounding, weather) cancel.
  function anchored(fNew, fOld, p0) {
    if (fNew == null || fOld == null || !isFinite(fNew) || !isFinite(fOld)) return null;
    const c = (v) => clamp(v, 1e-4, 1 - 1e-4);
    return ncdf(ndtri(c(fNew)) + ndtri(c(p0)) - ndtri(c(fOld)));
  }
  const g = (v) => String(Math.round(v * 100) / 100);
  const fmtLine = (v, signed) => (signed && v > 0 ? '+' : '') + g(v);
  const fmtOdds = (o) => (o > 0 ? '+' : '') + o;
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  function swapNum(str, from, to, signed) {
    if (typeof str !== 'string') return str;
    const tries = signed ? [[fmtLine(from, true), fmtLine(to, true)], [g(Math.abs(from)), g(Math.abs(to))]] : [[g(from), g(to)]];
    for (const [a, b] of tries) { const re = new RegExp('(^|[^\\d.+-])' + esc(a) + '(?![\\d])'); if (re.test(str)) return str.replace(re, (m, p) => p + b); }
    return str;
  }

  let C = null, EDITS = {}; const ORIG = {};
  const KEY = () => 'line-edits-' + C.sport;
  function load() {
    try { const s = JSON.parse(localStorage.getItem(KEY()) || 'null'); EDITS = s && s.stamp === C.stamp ? s.edits || {} : {}; if (s && s.stamp !== C.stamp) localStorage.removeItem(KEY()); } catch (e) { EDITS = {}; }
  }
  function save() { try { if (Object.keys(EDITS).length) localStorage.setItem(KEY(), JSON.stringify({ stamp: C.stamp, edits: EDITS })); else localStorage.removeItem(KEY()); } catch (e) { /* storage unavailable: edits last this visit */ } }
  const F = () => C.fields || { pm: 'pm', pb: 'pb', pct: true };
  const TXT = ['label', 'gt', 'sl'];
  function snap(l) {
    if (ORIG[l.id]) return ORIG[l.id];
    const f = F(), o = { p: l.p, pm: l[f.pm], pb: l[f.pb], price: l.price, edge: l.edge, ev: l.ev, line: C.lineOf(l), hasLine: 'line' in l,
      dk: l.offers ? l.offers.DraftKings : undefined };
    TXT.forEach((k) => { if (k in l) o[k] = l[k]; });
    return (ORIG[l.id] = o);
  }
  // can this leg's line be changed? (alt rungs and moneylines are fixed numbers: price only)
  const lineOk = (l) => { const o = snap(l); return o.line != null && !l.alt && C.model(l, o.line) != null; };
  // the leg's numbers at edit e = { line, price } (either may be missing)
  function price(l, e) {
    const o = snap(l), f = F();
    const line = e && e.line != null && lineOk(l) ? e.line : o.line, px = e && e.price != null ? e.price : o.price;
    let pm = o.pm;
    if (line !== o.line) { const v = anchored(C.model(l, line), C.model(l, o.line), o.pm); if (v != null) pm = v; }
    let pb = null;
    if (o.pb != null) { let m = imp(o.price) / o.pb; if (!(m >= 1 && m < 1.3)) m = 1.045; pb = clamp(imp(px) / m, 0.005, 0.995); }
    const w = pb == null ? 1 : C.weight(l, pb), p = pb == null ? pm : w * pm + (1 - w) * pb, k = f.pct ? 100 : 1, dp = f.pct ? 10 : 10000;
    return { line, price: px, pm, pb, p, edge: Math.round((p - imp(px)) * k * dp) / dp, ev: Math.round((p * dec(px) - 1) * k * dp) / dp };
  }
  function restore(l) {
    const o = ORIG[l.id]; if (!o) return; const f = F();
    Object.assign(l, { p: o.p, price: o.price, edge: o.edge, ev: o.ev }); l[f.pm] = o.pm; l[f.pb] = o.pb;
    if (o.dk !== undefined) l.offers.DraftKings = o.dk;
    if (o.hasLine) l.line = o.line;
    TXT.forEach((k) => { if (k in o) l[k] = o[k]; });
    delete l.edited;
  }
  function applyOne(l) {
    restore(l); const e = EDITS[l.id]; if (!e) return;
    const o = snap(l), f = F(), r = price(l, e);
    l.p = Math.round(r.p * 1e4) / 1e4; l[f.pm] = Math.round(r.pm * 1e4) / 1e4; l[f.pb] = r.pb == null ? null : Math.round(r.pb * 1e4) / 1e4;
    l.price = r.price; l.edge = r.edge; l.ev = r.ev; if (o.dk !== undefined) l.offers.DraftKings = r.price;
    if (r.line !== o.line) { if (o.hasLine) l.line = r.line; const sg = C.signed(l); TXT.forEach((k) => { if (k in o) l[k] = swapNum(o[k], o.line, r.line, sg); }); }
    l.edited = { line0: o.line, price0: o.price, p0: o.p, line: r.line, price: r.price, moved: r.line !== o.line, repriced: r.price !== o.price };
  }
  function applyAll() { C.legs.forEach(applyOne); }
  function commit() { save(); applyAll(); if (C.onChange) C.onChange(); }

  // ---- the editor sheet ----
  function css() {
    if (document.getElementById('le-css')) return;
    const s = document.createElement('style'); s.id = 'le-css';
    s.textContent = `.le-btn{border:1px dashed var(--line);background:transparent;color:var(--muted);font:600 12px var(--body);border-radius:7px;padding:3px 7px;cursor:pointer;white-space:nowrap}
.lecell .le-btn{display:block;margin:4px 0 0 auto}
.le-btn.on{border-style:solid;border-color:var(--gold);color:var(--gold);background:var(--gold-soft)}
.le-tag{display:block;color:var(--gold)!important;font:600 12px var(--body)!important;margin-top:2px}
.lerow,.books .lerow{display:flex;flex-wrap:wrap;gap:4px 8px;align-items:center;justify-content:flex-start;border-bottom:0;margin-top:4px;padding:0}
.lerow .le-tag{margin-top:0}
.slipl .le-btn{margin-top:4px}
.le-ban{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;background:var(--gold-soft);color:var(--ink);border-radius:8px;padding:8px 12px;margin:8px 14px;font-size:13px}
.le-ban .lnk{font-size:13px}
.le-ov{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1000;display:flex;align-items:flex-end;justify-content:center}
.le-sh{background:var(--panel);color:var(--ink);width:100%;max-width:460px;border-radius:14px 14px 0 0;padding:16px 16px calc(16px + env(safe-area-inset-bottom));box-shadow:0 -6px 24px rgba(0,0,0,.25);max-height:90vh;overflow:auto}
@media (min-width:700px){.le-ov{align-items:center}.le-sh{border-radius:14px}}
.le-sh h3{margin:0 0 2px;font:700 20px var(--display)}
.le-sh .le-who{margin:0 0 2px;font-weight:600}
.le-sh .dim{color:var(--muted);font-size:13px;margin:0 0 10px}
.le-row{display:flex;align-items:center;gap:8px;margin:10px 0}
.le-row label{flex:0 0 92px;font-weight:600;font-size:14px}
.le-row input{flex:1;min-width:0;font:600 18px var(--body);padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);text-align:center}
.le-row button{flex:0 0 44px;height:42px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:700 18px var(--body);cursor:pointer}
.le-prev{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:12px 0;text-align:center}
.le-prev div{background:var(--bg);border-radius:8px;padding:8px 4px}
.le-prev b{display:block;font:700 18px var(--display)}
.le-prev span{font-size:11px;color:var(--muted)}
.le-prev .pos b{color:var(--pos)}.le-prev .neg b{color:var(--neg)}
.le-act{display:flex;gap:10px;justify-content:flex-end;align-items:center;margin-top:12px}
.le-act .lnk.sugb{font-size:15px;padding:9px 16px}
.le-err{color:var(--neg);font-size:13px;min-height:1em;margin:0}`;
    document.head.append(s);
  }
  const mk = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
  const pc = (v) => (v * 100).toFixed(v < 0.1 ? 1 : 0) + '%';
  function open(l) {
    css();
    const o = snap(l), e0 = EDITS[l.id] || {}, canLine = lineOk(l), sg = C.signed(l), f = F();
    const ov = mk('div', 'le-ov'), sh = mk('div', 'le-sh'); sh.setAttribute('role', 'dialog'); sh.setAttribute('aria-modal', 'true'); sh.setAttribute('aria-label', 'Line changed?');
    ov.onclick = (ev) => { if (ev.target === ov) ov.remove(); };
    const name = C.name ? C.name(l) : l.label;
    sh.append(mk('h3', null, canLine ? 'Line changed?' : 'Price changed?'), mk('p', 'le-who', name),
      mk('p', 'dim', `Board has ${canLine ? fmtLine(o.line, sg) + ' at ' : ''}${fmtOdds(o.price)} (DraftKings). Enter what DraftKings shows now${canLine ? '' : '; this bet has a fixed number, so only the price can change'}.`));
    const num = (v) => { const x = Number(String(v).replace(/[^0-9.+-]/g, '')); return String(v).trim() === '' || !isFinite(x) ? null : x; };
    let li = null;
    if (canLine) {
      const r = mk('div', 'le-row'); r.append(mk('label', null, 'New line'));
      const minus = mk('button', null, '−'), plus = mk('button', null, '+'); minus.type = plus.type = 'button';
      minus.setAttribute('aria-label', 'Line down half a point'); plus.setAttribute('aria-label', 'Line up half a point');
      li = mk('input'); li.inputMode = 'decimal'; li.value = fmtLine(e0.line != null ? e0.line : o.line, sg); li.setAttribute('aria-label', 'New line');
      const step = (d) => { const v = num(li.value); li.value = fmtLine((v == null ? o.line : v) + d, sg); upd(); };
      minus.onclick = () => step(-0.5); plus.onclick = () => step(0.5);
      r.append(minus, li, plus); sh.append(r);
      if (sg) { const t = mk('p', 'dim', 'Tap − / + to move half a point; a minus line means that side gives points.'); t.style.margin = '0'; sh.append(t); }
    }
    const pr = mk('div', 'le-row'); pr.append(mk('label', null, 'New price'));
    const sign = mk('button', null, '±'); sign.type = 'button'; sign.setAttribute('aria-label', 'Switch between minus and plus price');
    const pi = mk('input'); pi.inputMode = 'numeric'; pi.value = fmtOdds(e0.price != null ? e0.price : o.price); pi.setAttribute('aria-label', 'New American price, like -115');
    sign.onclick = () => { const v = num(pi.value); if (v != null) pi.value = fmtOdds(-v); upd(); };
    pr.append(sign, pi); sh.append(pr);
    const err = mk('p', 'le-err'), pv = mk('div', 'le-prev');
    sh.append(pv, err);
    sh.append(mk('p', 'dim', `Re-priced here from the model's projection${canLine ? ' at the new line' : ''} and the new price. Saved on this device until the next board update.`));
    const act = mk('div', 'le-act');
    if (EDITS[l.id]) { const u = mk('button', 'lnk', 'Undo my change'); u.type = 'button'; u.onclick = () => { clear(l); ov.remove(); }; act.append(u); }
    const cancel = mk('button', 'lnk', 'Cancel'); cancel.type = 'button'; cancel.onclick = () => ov.remove();
    const ok = mk('button', 'lnk sugb', 'Save'); ok.type = 'button';
    act.append(cancel, ok); sh.append(act);
    function read() {
      const e = {}; let bad = '';
      if (li) { const v = num(li.value); if (v == null || Math.abs(v - Math.round(v * 2) / 2) > 1e-9) bad = 'Lines are whole or half numbers, like 4.5.'; else if (v !== o.line) e.line = v; }
      const p = num(pi.value); if (p == null || Math.abs(p) < 100 || Math.round(p) !== p) bad = bad || 'Prices look like -115 or +120.'; else if (p !== o.price) e.price = p;
      return { e, bad };
    }
    function upd() {
      const { e, bad } = read(); err.textContent = bad; pv.replaceChildren(); if (bad) return;
      const r = price(l, e), k = f.pct ? 1 : 100;
      [[`${pc(o.p)} → ${pc(r.p)}`, 'chance'], [`${r.edge * k > 0 ? '+' : ''}${(r.edge * k).toFixed(1)}`, 'edge (pts)'], [`${r.ev * k > 0 ? '+' : ''}${(r.ev * k).toFixed(0)}%`, 'EV']].forEach(([v, t], i) => {
        const d = mk('div', i ? (r[i === 1 ? 'edge' : 'ev'] >= 0 ? 'pos' : 'neg') : null); d.append(mk('b', null, v), mk('span', null, t)); pv.append(d); });
    }
    [li, pi].forEach((x) => x && (x.oninput = upd, x.onkeydown = (ev) => { if (ev.key === 'Enter') ok.click(); }));
    ok.onclick = () => {
      const { e, bad } = read(); if (bad) { err.textContent = bad; return; }
      set(l, e); ov.remove();
    };
    upd(); ov.append(sh); document.body.append(ov); (li || pi).focus({ preventScroll: true });
  }
  // the other side of a two-way market moves with it (Over/Under share the number, spreads flip its sign)
  function set(l, e) {
    const o = snap(l), had = EDITS[l.id] || {}, sib = C.sibling ? C.sibling(l) : null;
    if (e.line == null && e.price == null) delete EDITS[l.id]; else EDITS[l.id] = e;
    if (sib && lineOk(sib)) {
      const se = { ...(EDITS[sib.id] || {}) };
      if (e.line != null) se.line = C.signed(l) ? -e.line : e.line; else if (had.line != null) delete se.line;
      if (se.line == null && se.price == null) delete EDITS[sib.id]; else EDITS[sib.id] = se;
    }
    void o; commit();
  }
  function clear(l) {
    const sib = C.sibling ? C.sibling(l) : null, had = EDITS[l.id] || {};
    delete EDITS[l.id];
    if (sib && EDITS[sib.id] && had.line != null) { delete EDITS[sib.id].line; if (EDITS[sib.id].price == null) delete EDITS[sib.id]; }
    commit();
  }

  window.LineEdit = {
    setup(cfg) {
      C = Object.assign({ lineOf: (l) => (l.line == null ? null : Number(l.line)), signed: () => false, weight: () => 0.5, model: () => null }, cfg);
      C.legs.forEach(snap);
      // "until the next board update": the stamp also carries every leg's board price and number, so any new pull clears edits
      let h = 0; for (const l of C.legs) { const o = ORIG[l.id], t = `${l.id}:${o.price}:${o.line}`; for (let i = 0; i < t.length; i++) h = (Math.imul(h, 31) + t.charCodeAt(i)) | 0; }
      C.stamp = `${C.stamp}|${h}`;
      load(); applyAll();
    },
    // small button for a leg: "✎ Line" (or "✎ Price" when the number is fixed); gold once edited
    btn(l, long) {
      css(); const on = !!l.edited, line = lineOk(l);
      const b = mk('button', 'le-btn' + (on ? ' on' : ''), on ? '✎ Edited' : long ? (line ? '✎ Line changed?' : '✎ Price changed?') : (line ? '✎ Line' : '✎ Price'));
      b.type = 'button'; b.title = line ? 'DraftKings moved this line? Enter the new one' : 'DraftKings changed this price? Enter the new one';
      b.setAttribute('aria-label', `${line ? 'Line' : 'Price'} changed? ${C.name ? C.name(l) : l.label}`);
      b.onclick = (ev) => { ev.stopPropagation(); ev.preventDefault(); open(l); };
      return b;
    },
    // "✎ Your number · board was 5.5 at -120 (58%)" under an edited leg, else null
    tag(l) {
      if (!l.edited) return null; css(); const x = l.edited, sg = C.signed(l);
      return mk('small', 'le-tag', `✎ Your number · board was ${x.moved ? fmtLine(x.line0, sg) + ' at ' : ''}${fmtOdds(x.price0)} (${pc(x.p0)})`);
    },
    edited: (l) => !!(l && l.edited),
    shareTag: (l) => (l && l.edited ? '✎ line you entered' : ''),
    count: () => Object.keys(EDITS).length,
    // note with an "Undo all" link when any leg on this board was changed
    banner() {
      if (!C) return null;
      const seen = new Set(), moved = C.legs.filter((l) => l.edited && l.edited.moved).length;
      for (const l of C.legs) if (l.edited) { const sb = C.sibling ? C.sibling(l) : null; seen.add(sb && sb.edited ? [l.id, sb.id].sort()[0] : l.id); }
      const n = seen.size; if (!n) return null; css();
      const b = mk('div', 'le-ban'); b.append(mk('span', null, `✎ You changed ${n} bet${n === 1 ? '' : 's'} on this device. Chances, edges and parlays use your numbers until the next board update.${moved ? ' The DraftKings link may still load the old line: check it in the betslip.' : ''}`));
      const u = mk('button', 'lnk', 'Undo all'); u.type = 'button'; u.onclick = () => { EDITS = {}; commit(); }; b.append(u); return b;
    },
    open, dist: D, anchored, _price: price,
  };
})();
