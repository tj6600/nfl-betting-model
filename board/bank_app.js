const D = JSON.parse(document.getElementById('bank-data').textContent);
// Bank Builder (bank.py builds the data): 2-3 heavy favorites (about -400 at DraftKings) from any of the three boards, so a
// $10 stake comes back as about $15 to $20. Legs whose game has started drop out of suggestions and the DraftKings link.
const LEG = Object.fromEntries(D.pool.map((l) => [l.key, l]));
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
const sportF = new Set();
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
function legRow(l) {
  const r = el('div', 'bk-leg');
  r.append(el('span', 'sp ' + l.sport, l.sport));
  const n = el('div', 'nm', l.label); n.append(el('small', null, l.game + ' · ' + when(l.start))); r.append(n);
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
  let any = false;
  for (const k of ['2', '3']) {
    const ss = (D.slips[k] || []).map((s) => s.map((key) => LEG[key])).filter((s) => s.every((l) => l && !started(l)));
    const h = el('h2', 'colhead', k + ' legs'); h.style.margin = '6px 0 0'; root.append(h);
    if (!ss.length) { root.append(el('div', 'bk-empty', 'No ' + k + '-leg slip right now: not enough heavy favorites in games that haven\'t started. New ones come with the next board run.')); continue; }
    any = true;
    const g = el('div', 'bk-cards');
    ss.forEach((s, i) => {
      const c = el('div', 'bk-card' + (i === 0 ? ' top' : ''));
      const hd = el('div', 'bk-head'); hd.append(el('span', 't', i === 0 ? '★ Likeliest' : '#' + (i + 1)));
      hd.append(el('span', 'count', 'pays ' + fmt(toAm(sum(s).r)) + ' · EV ' + (sum(s).ev >= 0 ? '+' : '') + (sum(s).ev * 100).toFixed(1) + '%'));
      c.append(hd); c.append(payTiles(s, stake));
      s.forEach((l) => c.append(legRow(l)));
      const act = el('div', 'bk-actions'); const a = dkLink(s); if (a) act.append(a);
      const e = el('button', 'btn', 'Edit this slip'); e.onclick = () => { own = s.map((l) => l.key); saveOwn(); go('own'); }; act.append(e);
      c.append(act); g.append(c);
    });
    root.append(g);
  }
  if (!any) $('foot').textContent = '';
}

function saveOwn() { store('bank-own-' + D.built.slice(0, 10), JSON.stringify(own)); }
function renderOwn(root) {
  const bar = el('div', 'chips');
  for (const s of ['NFL', 'NBA', 'NHL']) {
    const b = el('button', 'chip', s); b.setAttribute('aria-pressed', sportF.has(s)); b.onclick = () => { sportF.has(s) ? sportF.delete(s) : sportF.add(s); render(); }; bar.append(b);
  }
  root.append(bar);
  const legs = D.pool.filter((l) => !started(l) && (!sportF.size || sportF.has(l.sport)));
  own = own.filter((k) => LEG[k] && !started(LEG[k]));
  const list = el('div', 'bk-list');
  if (!legs.length) list.append(el('div', 'bk-empty', 'No heavy favorites in games that haven\'t started.'));
  for (const l of legs) {
    const r = el('label', 'bk-row'); const cb = el('input'); cb.type = 'checkbox'; cb.checked = own.includes(l.key);
    cb.onchange = () => { own = cb.checked ? own.concat(l.key) : own.filter((k) => k !== l.key); saveOwn(); render(); };
    r.append(cb); r.append(el('span', 'sp ' + l.sport, l.sport));
    const n = el('div', null); n.append(el('b', null, l.label)); n.append(el('small', null, l.game + ' · ' + when(l.start))); r.append(n);
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
    const tg = D.rules.ret[String(sel.length)];
    if (!tg || r < tg[0] || r > tg[1]) box.append(el('p', 'note', 'Outside the Bank Builder target (about $15 on $10 for 2 legs, $20 for 3): this slip returns ' + money(10 * r) + ' on $10.'));
    const act = el('div', 'bk-actions'); const a = dkLink(sel); if (a) act.append(a);
    const c = el('button', 'btn', 'Clear'); c.onclick = () => { own = []; saveOwn(); render(); }; act.append(c); box.append(act);
  } else box.append(el('p', 'note', 'Tick 2 or 3 legs above to see the payout and hit chance.'));
  root.append(box);
}

function renderRecord(root) {
  const R = D.record;
  if (!R.groups.length) {
    root.append(el('div', 'bk-empty', 'No graded slips yet. Every build\'s suggestions are saved and graded at DraftKings prices once their games finish' + (R.open ? ' (' + R.open + ' waiting on results).' : '.')));
  } else {
    const t = el('div', 'tiles'), a = R.groups[0];
    for (const [k, v, s] of [['Slips', a.won + '-' + a.lost, pct(a.hit) + ' hit · expected ' + pct(a.exp_hit)], ['Profit on $' + D.stake + ' each', (a.dollars >= 0 ? '+$' : '-$') + Math.abs(a.dollars).toFixed(2), (a.roi >= 0 ? '+' : '') + (a.roi * 100).toFixed(1) + '% per slip'],
      ['Legs', R.legs.won + '-' + (R.legs.n - R.legs.won), R.legs.n ? pct(R.legs.won / R.legs.n) + ' of legs hit' : '']]) {
      const d = el('div', 'tile'); d.append(el('span', 'k', k)); d.append(el('span', 'big', v)); d.append(el('span', 's', s)); t.append(d);
    }
    root.append(t);
    const w = el('div', 'tablewrap'), tb = el('table', 'res');
    const hr = el('tr'); ['Group', 'W-L', 'Hit', 'Expected', 'Profit ($' + D.stake + ')'].forEach((h) => hr.append(el('td', h === 'Group' ? '' : 'num', h))); hr.style.fontWeight = '700'; tb.append(hr);
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
      n.append(el('small', null, s.day + ' · ' + s.legs.map((x) => x.sport + ' ' + fmt(x.price) + (x.result === 'win' ? ' ✓' : x.result === 'loss' ? ' ✗' : '')).join(' · '))); r.append(n);
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
$('lede').textContent = 'Two or three heavy favorites (about -400 at DraftKings) from the NFL, NBA and NHL boards, so $10 comes back as about $15 to $20. '
  + 'Ranked by the model\'s chance that every leg hits. Built ' + new Date(D.built.replace(/T(\d\d)(\d\d)Z/, 'T$1:$2:00Z')).toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) + '.';
if (!TABS.some(([k]) => k === tab)) tab = 'slips';
render();
