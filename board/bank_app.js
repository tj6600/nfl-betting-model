const D = JSON.parse(document.getElementById('bank-data').textContent);
// Bank Builder (bank.py builds the data): 2-3 heavy favorites (about -400 at DraftKings) from any of the three boards, so a
// $10 stake comes back as about $15 to $20. Legs whose game has started drop out of suggestions and the DraftKings link.
const EXTRA = D.backup || [];
const LEG = Object.fromEntries(D.pool.concat(EXTRA).map((l) => [l.key, l]));
const SPORTS = ['NFL', 'CFB', 'NHL'];   // NBA removed 2026-11-18; college football added 2026-11-18
const started = (l) => !l.start || Date.parse(l.start) <= Date.now();
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const dec = (a) => a > 0 ? 1 + a / 100 : 1 + 100 / -a;
const fmt = (o) => (o > 0 ? '+' : '') + o;
const pct = (p) => Math.round(p * 100) + '%';
const money = (x) => '$' + x.toFixed(2);
const toAm = (d) => d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1));
const when = (s) => new Date(s).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' });
const $ = (id) => document.getElementById(id);
const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };
let tab = store('bank-tab') || 'slips';
let stake = Number(store('bank-stake')) || D.stake;
let own = [];
try { own = JSON.parse(store('bank-own-' + D.built.slice(0, 10)) || '[]').filter((k) => LEG[k]); } catch (e) { own = []; }
// league filter (Thomas, 2026-11-16): slips use only the checked leagues; when they don't have enough Bank Builder legs,
// the next-best legs of those leagues (D.backup: DK -150 to -1200, model 55%+) fill in and the slip says its hit chance is lower
let leagues = new Set(SPORTS);
try { const v = JSON.parse(store('bank-leagues') || 'null'); if (Array.isArray(v) && v.length) leagues = new Set(v.filter((x) => SPORTS.includes(x))); } catch (e) {}
function leagueBox(root) {
  const f = el('fieldset', 'bk-leagues'); f.append(el('legend', null, 'Leagues'));
  for (const s of SPORTS) {
    const lb = el('label', 'bk-lg'); const cb = el('input'); cb.type = 'checkbox'; cb.checked = leagues.has(s);
    cb.onchange = () => {
      if (cb.checked) leagues.add(s); else if (leagues.size > 1) leagues.delete(s); else { cb.checked = true; return; }
      store('bank-leagues', JSON.stringify([...leagues])); render();
    };
    lb.append(cb); lb.append(el('span', 'sp ' + s, s)); f.append(lb);
  }
  root.append(f);
}
// same rule as bank.py slips(): one leg per game and per player, payout in the size's window, likeliest combined chance first,
// a leg in at most max_use slips
const who = (l) => { const m = /^(.*?)\s(?:Over|Under|[\d.]+\+)/.exec(l.label); return m && !['Game', 'Moneyline', 'Spread', 'Total', 'Puck line'].includes(l.kind) ? l.sport + m[1] : null; };
function combos(legs, k, cb) {
  const n = legs.length, idx = [];
  const rec = (start) => { if (idx.length === k) { cb(idx.map((i) => legs[i])); return; } for (let i = start; i < n; i++) { idx.push(i); rec(i + 1); idx.pop(); } };
  rec(0);
}
// last resort for a league with few games: same-game legs (different players) and a payout window $1 wider each way
function makeSlips(legs, k, n, uses, skip, loose) {
  let [lo, hi] = D.rules.ret[String(k)]; if (loose) { lo -= 0.1; hi += 0.1; }
  const cands = [];
  combos(legs.slice(0, D.top + 15), k, (c) => {
    if (!loose && new Set(c.map((l) => l.sport + l.game)).size < k) return;
    if (loose && c.some((l) => ['Game', 'Moneyline', 'Spread', 'Total', 'Puck line'].includes(l.kind)) && new Set(c.map((l) => l.sport + l.game)).size < k) return;
    const w = c.map(who).filter(Boolean); if (new Set(w).size < w.length) return;
    const s = sum(c); if (s.r < lo || s.r > hi) return;
    cands.push([s.p, s.ev, c]);
  });
  cands.sort((a, b) => b[0] - a[0] || b[1] - a[1]);
  const out = [];
  for (const [, , c] of cands) {
    if (out.length >= n) break;
    const key = c.map((l) => l.key).sort().join(',');
    if (skip.has(key) || c.some((l) => (uses[l.key] || 0) >= D.max_use)) continue;
    out.push(c); skip.add(key); c.forEach((l) => { uses[l.key] = (uses[l.key] || 0) + 1; });
  }
  return out;
}
function slipsFor(k) {
  const ok = (l) => leagues.has(l.sport) && !started(l);
  const uses = {}, skip = new Set();
  const out = makeSlips(D.pool.filter(ok), k, D.n_slips, uses, skip);
  if (out.length < D.n_slips) {
    const more = D.pool.concat(EXTRA).filter(ok).sort((a, b) => b.p - a.p || b.edge - a.edge);
    out.push(...makeSlips(more, k, D.n_slips - out.length, uses, skip));
    if (out.length < D.n_slips) out.push(...makeSlips(more, k, D.n_slips - out.length, uses, skip, true));
  }
  return out;
}
const sum = (legs) => {
  const r = legs.reduce((a, l) => a * dec(l.price), 1), p = legs.reduce((a, l) => a * l.p, 1), dk = legs.reduce((a, l) => a * l.dk, 1);
  return { r, p, dk, ev: p * r - 1 };
};
function dkLink(legs) {
  const sids = legs.map((l) => l.sid).filter(Boolean);
  if (!legs.length || sids.length < legs.length) return null;
  const a = el('a', 'btn dk', 'Open in DraftKings');
  a.href = 'https://sportsbook.draftkings.com/?outcomes=' + sids.map(encodeURIComponent).join('+'); a.target = '_blank'; a.rel = 'noopener';
  return a;
}
// Share (Thomas, 2026-11-19): a compact card of the slip for a screenshot or a text (board/site/share.js)
function shareBtn(legs, title) {
  const b = el('button', 'btn', 'Share slip'); b.type = 'button';
  b.onclick = () => { const s = sum(legs), bk = legs.filter((l) => l.backup).length;
    if (window.shareSlip) window.shareSlip({ title, legs: legs.map((l) => ({ label: l.label, sub: l.sport + ' · ' + l.game + ' · ' + when(l.start), odds: fmt(l.price), tag: l.backup ? '⚠ next-best' : '' })),
      odds: fmt(toAm(s.r)), chance: pct(s.p), pays: money(10 * s.r), warn: bk ? `⚠ ${bk} next-best pick${bk === 1 ? '' : 's'}: lower hit chance` : '' }); };
  return b;
}
function legRow(l) {
  const r = el('div', 'bk-leg');
  r.append(el('span', 'sp ' + l.sport, l.sport));
  const n = el('div', 'nm', l.label); if (l.backup) { n.append(' '); n.append(el('span', 'pill check', 'next-best')); }
  n.append(el('small', null, l.game + ' · ' + when(l.start))); r.append(n);
  const num = el('div', 'num'); num.append(el('b', null, fmt(l.price)));
  const s = el('small', null, 'model ' + pct(l.p) + ' · DK ' + pct(l.dk));
  if (l.edge >= 0) { s.append(' '); s.append(el('span', 'ok', '✓')); s.title = 'Model chance beats DraftKings\' implied chance'; }
  num.append(s); r.append(num);
  return r;
}
function payTiles(legs, st) {
  const s = sum(legs), w = el('div', 'bk-pay');
  for (const [k, v, c] of [['$' + st + ' returns', money(st * s.r), 'win'], ['Profit', money(st * (s.r - 1)), ''], ['Hit chance', pct(s.p), ''], ['DK implied', pct(s.dk), '']]) {
    const d = el('div'); d.append(el('span', 'k', k)); d.append(el('span', 'v ' + c, v)); w.append(d);
  }
  return w;
}

function renderSlips(root) {
  leagueBox(root);
  const picked = [...leagues];
  let backupUsed = false;
  for (const k of [2, 3]) {
    const ss = slipsFor(k);
    const h = el('h2', 'colhead', k + ' legs'); h.style.margin = '6px 0 0'; root.append(h);
    if (!ss.length) { root.append(el('div', 'bk-empty', 'No ' + k + '-leg slip from ' + picked.join(', ') + ' right now: not enough favorites in games that haven\'t started. New ones come with the next board run.')); continue; }
    const g = el('div', 'bk-cards');
    ss.forEach((s, i) => {
      const bk = s.filter((l) => l.backup);
      if (bk.length) backupUsed = true;
      const c = el('div', 'bk-card' + (i === 0 && !bk.length ? ' top' : '') + (bk.length ? ' weak' : ''));
      const hd = el('div', 'bk-head'); hd.append(el('span', 't', i === 0 && !bk.length ? '★ Likeliest' : '#' + (i + 1)));
      hd.append(el('span', 'count', 'pays ' + fmt(toAm(sum(s).r)) + ' · EV ' + (sum(s).ev >= 0 ? '+' : '') + (sum(s).ev * 100).toFixed(1) + '%'));
      c.append(hd);
      const sg = new Set(s.map((l) => l.sport + l.game)).size < s.length, why = [];
      if (bk.length) why.push('⚠ Lower hit chance: ' + bk.length + ' next-best ' + (bk.length === 1 ? 'pick' : 'picks'));
      if (sg) why.push('same game, so DraftKings prices it as a same-game parlay');
      if (why.length) c.append(el('p', 'bk-warn', why.join(' · ')));
      c.append(payTiles(s, stake));
      s.forEach((l) => c.append(legRow(l)));
      const act = el('div', 'bk-actions'); const a = dkLink(s); if (a) act.append(a);
      const e = el('button', 'btn', 'Edit this slip'); e.onclick = () => { own = s.map((l) => l.key); saveOwn(); go('own'); }; act.append(e);
      act.append(shareBtn(s, 'Bank Builder · ' + k + '-leg slip'));
      c.append(act); g.append(c);
    });
    root.append(g);
  }
  const none = picked.filter((sp) => !D.pool.concat(EXTRA).some((l) => l.sport === sp && !started(l)));
  if (none.length) root.insertBefore(el('p', 'bk-warn', 'No ' + none.join(' or ') + ' legs are on the board right now (no games soon, or the next lines haven\'t been pulled yet).'), root.children[1]);
  if (backupUsed) root.insertBefore(el('p', 'bk-warn', '⚠ The leagues you picked don\'t have enough strong -400 favorites right now, so some slips use next-best picks (marked NEXT-BEST). Those picks are less likely to hit, so these slips are lower-probability than usual. Same-game slips can also pay differently on DraftKings.'), root.children[1]);
}

function saveOwn() { store('bank-own-' + D.built.slice(0, 10), JSON.stringify(own)); }
function renderOwn(root) {
  leagueBox(root);
  const legs = D.pool.concat(EXTRA).filter((l) => !started(l) && leagues.has(l.sport));
  own = own.filter((k) => LEG[k] && !started(LEG[k]));
  const list = el('div', 'bk-list');
  if (!legs.length) list.append(el('div', 'bk-empty', 'No heavy favorites in games that haven\'t started.'));
  for (const l of legs) {
    const r = el('label', 'bk-row'); const cb = el('input'); cb.type = 'checkbox'; cb.checked = own.includes(l.key);
    cb.onchange = () => { own = cb.checked ? own.concat(l.key) : own.filter((k) => k !== l.key); saveOwn(); render(); };
    r.append(cb); r.append(el('span', 'sp ' + l.sport, l.sport));
    const n = el('div', null); n.append(el('b', null, l.label)); if (l.backup) { n.append(' '); n.append(el('span', 'pill check', 'next-best')); } n.append(el('small', null, l.game + ' · ' + when(l.start))); r.append(n);
    const num = el('div', 'num'); num.append(el('b', null, fmt(l.price)));
    const s = el('small', null, 'model ' + pct(l.p) + ' · DK ' + pct(l.dk)); if (l.edge >= 0) { s.append(' '); s.append(el('span', 'ok', '✓')); }
    num.append(s); r.append(num); list.append(r);
  }
  root.append(list);
  const box = el('div', 'bk-own');
  const sel = own.map((k) => LEG[k]);
  const top = el('div', 'bk-head'); top.append(el('span', 't', 'Your slip · ' + sel.length + (sel.length === 1 ? ' leg' : ' legs')));
  const lb = el('label', null, 'Stake $'); const inp = el('input'); inp.type = 'number'; inp.min = '1'; inp.step = '1'; inp.value = stake; inp.inputMode = 'decimal';
  inp.onchange = () => { stake = Math.max(1, Number(inp.value) || D.stake); store('bank-stake', String(stake)); render(); };
  lb.append(inp); top.append(lb); box.append(top);
  if (sel.length) {
    box.append(payTiles(sel, stake));
    const games = sel.map((l) => l.sport + l.game);
    if (new Set(games).size < games.length) box.append(el('p', 'note', 'Two legs share a game: DraftKings may treat that as a same-game parlay and price it differently.'));
    const r = sum(sel).r;
    if (sel.some((l) => l.backup)) box.append(el('p', 'bk-warn', '⚠ Lower hit chance: this slip has next-best picks, not legs the Bank Builder rates as solid -400 favorites.'));
    const tg = D.rules.ret[String(sel.length)];
    if (!tg || r < tg[0] || r > tg[1]) box.append(el('p', 'note', 'Outside the Bank Builder target (about $15 on $10 for 2 legs, $20 for 3): this slip returns ' + money(10 * r) + ' on $10.'));
    const act = el('div', 'bk-actions'); const a = dkLink(sel); if (a) act.append(a);
    act.append(shareBtn(sel, 'Bank Builder · ' + sel.length + '-leg slip'));
    const c = el('button', 'btn', 'Clear'); c.onclick = () => { own = []; saveOwn(); render(); }; act.append(c); box.append(act);
  } else box.append(el('p', 'note', 'Tick 2 or 3 legs above to see the payout and hit chance.'));
  root.append(box);
}

// Refresh results (Thomas, 2026-11-18): grade open slips' legs from ESPN in the browser (liveCheck in head.html), as on the sport pages.
const BANK_GROUPS = ['All Bank Builder slips', 'Top slip of each build', '2-leg slips', '3-leg slips', 'Mixed-sport slips'];
let bankStatus = { text: '', cls: '' };
function bankLive(src, inPeriod) {
  const P = src.pending; if (!P) return src;
  const res = {}; let at = 0;
  for (const sp of ['nba', 'nhl', 'nfl', 'cfb']) { const st = liveLoad('bank-' + sp); if (st && st.res) { Object.assign(res, st.res); at = Math.max(at, st.at || 0); } }
  if (!Object.keys(res).length) return src;
  const R = JSON.parse(JSON.stringify(src)); let n = 0; const seen = new Set();
  for (const [size, top, sports, p, , legs, day, gday] of P.slips) {
    if (inPeriod && !inPeriod(gday || day)) continue;
    const rs = legs.map(([k, known]) => known || res[k] || null);
    let out, u;
    if (rs.includes('loss')) { out = 'lost'; u = -1; }
    else if (rs.includes(null)) continue;
    else { const live = legs.filter((_, i) => rs[i] === 'win'); out = live.length ? 'won' : 'push'; u = live.reduce((a, [, , pr]) => a * recDec(pr), 1) - 1; }
    n += 1; R.open = Math.max(0, (R.open || 0) - 1);
    R.recent.unshift({ day, size, result: out, units: u, live: true, legs: legs.map(([k, , price, label], i) => ({ sport: k.split('|')[0], label, price, result: rs[i] })) });
    legs.forEach(([k, , price, label], i) => { const key = label + '|' + price; if (!seen.has(key) && (rs[i] === 'win' || rs[i] === 'loss') && !legs[i][1]) { seen.add(key); R.legs.n += 1; if (rs[i] === 'win') R.legs.won += 1; } });
    if (out === 'push') continue;
    const names = ['All Bank Builder slips'].concat(top ? ['Top slip of each build'] : [], [size + '-leg slips'], sports.length > 1 ? ['Mixed-sport slips'] : []);
    for (const nm of names) {
      let g = R.groups.find((x) => x.group === nm);
      if (!g) { g = { group: nm, bets: 0, won: 0, lost: 0, hit: 0, exp_hit: 0, units: 0, roi: 0, dollars: 0 }; R.groups.push(g); }
      g.exp_hit = (g.exp_hit * g.bets + p) / (g.bets + 1); g.bets += 1; if (out === 'won') g.won += 1; else g.lost += 1;
      g.hit = g.won / g.bets; g._u = (g._u ?? g.units) + u; g.units = Math.round(g._u * 100) / 100; g.roi = g._u / g.bets; g.dollars = Math.round(g._u * D.stake * 100) / 100;
    }
  }
  R.groups.sort((a, b) => BANK_GROUPS.indexOf(a.group) - BANK_GROUPS.indexOf(b.group));
  R.recent = R.recent.slice(0, 15); R._live = { n, at };
  return R;
}
function bankRefreshBar(root) {
  const bar = el('div', 'recbar'), row = el('div', 'recrow');
  const b = el('button', 'refbtn'); b.type = 'button'; b.append(el('span', 'ico', '↻'), el('span', null, 'Refresh results'));
  const P = D.record.pending;
  if (!P) { b.disabled = true; b.title = 'Available after the next board build'; }
  b.onclick = async () => {
    if (b.getAttribute('aria-busy') === 'true') return;
    b.setAttribute('aria-busy', 'true'); bankStatus = { text: 'Checking finished games on ESPN…', cls: '' }; render();
    let graded = 0, failed = 0, waiting = 0;
    for (const sp of ['nba', 'nhl', 'nfl', 'cfb']) {
      const legs = P.legs.filter((L) => L[7] === sp.toUpperCase()); if (!legs.length) continue;
      let msg = '';
      try { graded += await liveCheck(sp, { legs }, (t, c) => { msg = c === 'bad' ? t : msg; }, 'bank-' + sp); } catch (e) { failed += 1; }
      if (msg) failed += 1;
      const st = liveLoad('bank-' + sp) || { res: {} }; waiting += legs.filter((L) => !(st.res || {})[L[0]]).length;
    }
    bankStatus = failed && !graded ? { text: 'Could not reach ESPN. Check the connection and try again.', cls: 'bad' }
      : { text: graded ? `Graded ${graded} leg${graded === 1 ? '' : 's'}.${waiting ? ` ${waiting} still waiting for their games to finish or for the overnight grading.` : ''}` : (P.legs.length ? 'No new results yet.' : 'No open slips to check.'), cls: graded ? 'ok' : '' };
    render();
  };
  if (bankStatus.text === 'Checking finished games on ESPN…') b.setAttribute('aria-busy', 'true');
  row.append(b); bar.append(row);
  const lv = bankLive(D.record)._live;
  const t = bankStatus.text || (lv && lv.n ? `Includes ${lv.n} slip${lv.n === 1 ? '' : 's'} checked live on ESPN at ${new Date(lv.at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}. The overnight grading makes them official.` : '');
  if (t) bar.append(el('p', 'refstatus ' + bankStatus.cls, t));
  root.append(bar);
  return bar;
}

// Day / week / month filter, the same menus as the sport pages' Model record (Thomas, 2026-11-18). A slip counts on the day
// of its last game; bank.py writes the reports to D.record.by_period. Weeks run Monday to Sunday.
function bankPeriod(bar) {
  const bp = D.record.by_period || { menu: { day: [], week: [], month: [] }, reports: {} };
  const st = Object.assign({ kind: 'all', keys: {} }, recLoad('bank'));
  if (st.kind !== 'all' && !(bp.menu[st.kind] || []).length) st.kind = 'all';
  let key = null;
  if (st.kind !== 'all') { const l = bp.menu[st.kind]; let i = l.findIndex((x) => x.key === st.keys[st.kind]); if (i < 0) i = 0; key = l[i].key; st.keys[st.kind] = key; }
  recSave('bank', st);
  const redo = () => { recSave('bank', st); render(); };
  const seg = el('div', 'seg'); seg.setAttribute('role', 'group'); seg.setAttribute('aria-label', 'Time period');
  for (const [k, lab] of REC_KINDS) {
    const b = el('button', null, lab); b.type = 'button'; b.setAttribute('aria-pressed', st.kind === k);
    if (k !== 'all' && !(bp.menu[k] || []).length) { b.disabled = true; b.title = 'Nothing graded yet'; }
    b.onclick = () => { if (st.kind !== k) { st.kind = k; redo(); } }; seg.append(b);
  }
  const r1 = el('div', 'recrow'); r1.append(seg); bar.prepend(r1);
  if (key) {
    const l = bp.menu[st.kind], i = l.findIndex((x) => x.key === key);
    const nav = el('div', 'recnav');
    const prev = el('button', 'arrow', '‹'); prev.type = 'button'; prev.setAttribute('aria-label', 'Earlier'); prev.disabled = i >= l.length - 1;
    const next = el('button', 'arrow', '›'); next.type = 'button'; next.setAttribute('aria-label', 'Later'); next.disabled = i <= 0;
    const sel = el('select'); sel.setAttribute('aria-label', 'Choose the ' + st.kind);
    l.forEach((x) => { const op = el('option', null, x.label); op.value = x.key; if (x.key === key) op.selected = true; sel.append(op); });
    sel.onchange = () => { st.keys[st.kind] = sel.value; redo(); };
    prev.onclick = () => { st.keys[st.kind] = l[i + 1].key; redo(); };
    next.onclick = () => { st.keys[st.kind] = l[i - 1].key; redo(); };
    nav.append(prev, sel, next); const r2 = el('div', 'recrow'); r2.append(nav); r1.after(r2);
    if (st.kind === 'week') r2.after(el('p', 'recsum', 'Weeks run Monday to Sunday. A slip counts on the day of its last game.'));
    else if (st.kind === 'day') r2.after(el('p', 'recsum', 'A slip counts on the day of its last game.'));
  }
  const monday = (d) => { const t = new Date(d + 'T12:00:00Z'); t.setUTCDate(t.getUTCDate() - (t.getUTCDay() + 6) % 7); return t.toISOString().slice(0, 10); };
  const inPeriod = !key ? null : (d) => (key[0] === 'd' ? 'd:' + d : key[0] === 'm' ? 'm:' + d.slice(0, 7) : 'w:' + monday(d)) === key;
  const sub = key ? bp.reports[key] : null;
  return { src: sub ? Object.assign({}, D.record, sub) : D.record, inPeriod, label: key ? bp.menu[st.kind].find((x) => x.key === key).label : '' };
}

function renderRecord(root) {
  const per = bankPeriod(bankRefreshBar(root));
  const R = bankLive(per.src, per.inPeriod);
  if (!R.groups.length) {
    root.append(el('div', 'bk-empty', per.label ? 'No graded slips for ' + per.label + (R.open ? ' (' + R.open + ' waiting on results).' : '.') : 'No graded slips yet. Every build\'s suggestions are saved and graded at DraftKings prices once their games finish' + (R.open ? ' (' + R.open + ' waiting on results).' : '.')));
  } else {
    const t = el('div', 'tiles'), a = R.groups[0];
    for (const [k, v, s] of [['Slips', a.won + '-' + a.lost, pct(a.hit) + ' hit · expected ' + pct(a.exp_hit)], ['Profit on $' + D.stake + ' each', (a.dollars >= 0 ? '+$' : '-$') + Math.abs(a.dollars).toFixed(2), (a.roi >= 0 ? '+' : '') + (a.roi * 100).toFixed(1) + '% per slip'],
      ['Legs', R.legs.won + '-' + (R.legs.n - R.legs.won), R.legs.n ? pct(R.legs.won / R.legs.n) + ' of legs hit' : '']]) {
      const d = el('div', 'tile'); d.append(el('span', 'k', k)); d.append(el('span', 'big', v)); d.append(el('span', 's', s)); t.append(d);
    }
    root.append(t);
    const w = el('div', 'tablewrap'), tb = el('table', 'res');
    const hr = el('tr'); ['Group', 'W-L', 'Hit', 'Expected', 'Profit ($' + D.stake + ')'].forEach((h) => hr.append(el('th', h === 'Group' ? null : 'num', h))); tb.append(hr);
    for (const g of R.groups) {
      const r = el('tr'); r.append(el('td', null, g.group)); r.append(el('td', 'num', g.won + '-' + g.lost)); r.append(el('td', 'num', pct(g.hit)));
      r.append(el('td', 'num', pct(g.exp_hit))); r.append(el('td', 'num', (g.dollars >= 0 ? '+$' : '-$') + Math.abs(g.dollars).toFixed(2))); tb.append(r);
    }
    w.append(tb); root.append(w);
    if (R.open) root.append(el('p', 'note', R.open + ' slips still waiting on results.'));
  }
  if (R.recent.length) {
    root.append(el('h2', 'colhead', 'Latest graded slips'));
    const l = el('div', 'bk-list');
    for (const s of R.recent) {
      const r = el('div', 'bk-row'); r.style.cursor = 'default'; r.style.gridTemplateColumns = 'auto minmax(0, 1fr) auto';
      r.append(el('span', s.result === 'won' ? 'res-w' : s.result === 'lost' ? 'res-l' : 'count', s.result === 'won' ? 'W' : s.result === 'lost' ? 'L' : 'P'));
      const n = el('div'); n.append(el('b', null, s.legs.map((x) => x.label).join(' + ')));
      n.append(el('small', null, s.day + (s.live ? ' · checked live' : '') + ' · ' + s.legs.map((x) => x.sport + ' ' + fmt(x.price) + (x.result === 'win' ? ' ✓' : x.result === 'loss' ? ' ✗' : '')).join(' · '))); r.append(n);
      r.append(el('span', 'num', s.units == null ? '' : (s.units >= 0 ? '+$' : '-$') + Math.abs(s.units * D.stake).toFixed(2))); l.append(r);
    }
    root.append(l);
  }
}

const TABS = [['slips', 'Suggested slips'], ['own', 'Build your own'], ['record', 'Record']];
function go(t) { tab = t; store('bank-tab', t); render(); window.scrollTo(0, 0); }
function render() {
  const tabs = $('tabs'); tabs.textContent = '';
  for (const [k, t] of TABS) { const b = el('button', 'tab', t); b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', k === tab); b.onclick = () => go(k); tabs.append(b); }
  const root = $('board'); root.textContent = ''; root.style.display = 'flex'; root.style.flexDirection = 'column'; root.style.gap = '12px';
  $('foot').textContent = 'Legs: DraftKings ' + D.rules.hi + ' to ' + D.rules.lo + ', model chance ' + pct(D.rules.pmin) + '+, no more than ' + D.rules.juice
    + ' pts under DraftKings\' implied chance, one per game. ✓ = the model\'s chance beats DraftKings\' implied chance. Lines are the boards\' latest pulls ('
    + Object.entries(D.taken).map(([s, t]) => s + ': ' + t).join('; ') + '); check the price on DraftKings before betting.';
  ({ slips: renderSlips, own: renderOwn, record: renderRecord })[tab](root);
}
$('lede').textContent = 'Two or three heavy favorites (about -400 at DraftKings) from the NFL, college football and NHL boards, so $10 comes back as about $15 to $20. '
  + 'Ranked by the model\'s chance that every leg hits. Built ' + new Date(D.built.replace(/T(\d\d)(\d\d)Z/, 'T$1:$2:00Z')).toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) + '.';
if (!TABS.some(([k]) => k === tab)) tab = 'slips';
render();
