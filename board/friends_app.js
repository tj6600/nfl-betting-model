// Friends page: Google sign-in (Firebase Auth), friend groups and the weekly group parlay (Firestore).
// Kickoffs and results come only from the site's own files (group/<week>.json, built by friends.py) and ESPN box scores
// (head.html liveCheck), so a pick saved after its leg kicked off shows as late and never counts.
// firestore.rules is what keeps each group's data private; the config in firebase-config.js is public by design.
const SDK = 'https://www.gstatic.com/firebasejs/10.14.1/';
const APP = document.getElementById('app');
const KIND = [['all', 'All'], ['Game', 'Game lines'], ['TD', 'Anytime TD'], ['yds', 'Yards'], ['Recs', 'Receptions'], ['Milestone', 'Alt yards']];
const KIND_OF = (k) => (k === 'Rush' || k === 'Rec' || k === 'Pass' ? 'yds' : k);
const S = { user: null, profile: null, groups: [], gid: null, group: null, picks: [], names: {}, weeks: {}, index: null,
  tab: 'week', pick: { kind: 'all', game: 'all', q: '', open: false }, msg: '', unsub: [] };
let F = null;   // Firebase modules once loaded

const h = (tag, attrs, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v; else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k instanceof Node ? k : String(k));
  return e;
};
const am = (a) => (a > 0 ? '+' + a : String(a));
const decToAm = (d) => (d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1)));
const etDay = (iso) => new Date(iso).toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
const kickLabel = (iso) => new Date(iso).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' });
const weekLabel = (key) => { const [s, w] = key.split('_wk'); return `Week ${Number(w)}, ${s}`; };
const initials = (n) => String(n || '?').trim().split(/\s+/).map((x) => x[0]).slice(0, 2).join('').toUpperCase();
const avatar = (uid, sm) => {
  const p = S.names[uid] || {};
  if (p.photo) return h('img', { class: 'av' + (sm ? ' sm' : ''), src: p.photo, alt: '', referrerpolicy: 'no-referrer' });
  return h('span', { class: 'av' + (sm ? ' sm' : ''), 'aria-hidden': 'true' }, initials(p.name));
};
const nameOf = (uid) => (S.names[uid] && S.names[uid].name) || 'Friend';
const say = (t) => { S.msg = t || ''; render(); };

async function getJSON(u) { const r = await fetch(u, { cache: 'no-store' }); if (!r.ok) throw new Error(r.status); return r.json(); }
async function week(key) {
  if (!S.weeks[key]) S.weeks[key] = getJSON(`group/${key}.json`).catch(() => ({ key, legs: {} }));
  return S.weeks[key];
}

// ---------- results: the grader's final result, else what Refresh read from ESPN on this phone ----------
function liveRes() { const st = liveLoad('friends'); return (st && st.res) || {}; }
function legOf(p) { const W = S.weeks[p.week]; return W && W.then ? null : W && W.legs[p.leg]; }
function pickState(p, live) {
  const L = legOf(p);
  if (!L) return { st: 'unknown' };
  const at = p.at && p.at.toMillis ? p.at.toMillis() : null;
  if (!at || at >= Date.parse(L.kick)) return { st: 'late', L };
  const r = L.r || live[p.week + '|' + p.leg] || null;
  return { st: r || (Date.parse(L.kick) > Date.now() ? 'open' : 'waiting'), L };
}
const MARK = { win: ['✓ Hit', 'ok'], loss: ['✗ Missed', 'bad'], push: ['Push', 'wait'], void: ['Void', 'wait'], open: ['Not started', 'wait'],
  waiting: ['In play / waiting', 'wait'], late: ['Late, doesn\'t count', 'bad'], unknown: ['—', 'wait'] };
const mark = (st) => h('span', { class: MARK[st][1] }, MARK[st][0]);

function parlay(rows) {   // rows: [{st, L}] of counted legs
  const legs = rows.filter((r) => r.L && r.st !== 'late' && r.st !== 'unknown');
  if (!legs.length) return { n: 0 };
  const dec = legs.reduce((a, r) => a * (r.st === 'push' || r.st === 'void' ? 1 : recDec(r.L.price)), 1);
  let st = 'waiting';
  if (legs.some((r) => r.st === 'loss')) st = 'loss';
  else if (legs.every((r) => ['win', 'push', 'void'].includes(r.st)) && legs.some((r) => r.st === 'win')) st = 'win';
  else if (legs.every((r) => r.st === 'open')) st = 'open';
  return { n: legs.length, dec, st, lost: legs.filter((r) => r.st === 'loss').length };
}

// ---------- Firebase ----------
async function boot() {
  const cfg = window.GG_FIREBASE;
  if (!cfg || !cfg.apiKey) {
    APP.replaceChildren(h('div', { class: 'fcard' }, h('h2', null, 'Sign-in is coming soon'),
      h('p', { class: 'note' }, 'Google sign-in for groups isn\'t switched on yet. Check back once it\'s set up.')));
    return;
  }
  const [A, Au, Fs] = await Promise.all([import(SDK + 'firebase-app.js'), import(SDK + 'firebase-auth.js'), import(SDK + 'firebase-firestore.js')]);
  const app = A.initializeApp(cfg);
  F = { ...Au, ...Fs, auth: Au.getAuth(app), db: Fs.getFirestore(app) };
  F.getRedirectResult(F.auth).catch(() => {});
  F.onAuthStateChanged(F.auth, async (u) => {
    S.unsub.forEach((f) => f()); S.unsub = [];
    S.user = u; S.groups = []; S.group = null; S.picks = [];
    if (!u) return render();
    try { await saveProfile(); await joinFromLink(); watchGroups(); } catch (e) { say(errText(e)); }
    render();
  });
  S.index = await getJSON('group/index.json').catch(() => null);
  if (S.index && S.index.current) await week(S.index.current).then((W) => { S.weeks[S.index.current] = W; });
  render();
}

function errText(e) {
  const c = (e && e.code) || '';
  if (c.includes('permission-denied')) return 'That isn\'t allowed. If a game already kicked off, that pick is locked.';
  if (c.includes('popup-closed') || c.includes('cancelled-popup')) return '';
  if (c.includes('unauthorized-domain')) return 'This site isn\'t on the sign-in allow list yet (Firebase Authorized domains).';
  if (c.includes('network') || c.includes('unavailable')) return 'No connection. Try again in a moment.';
  return 'Something went wrong' + (c ? ` (${c})` : '') + '. Try again.';
}

async function signIn() {
  const pr = new F.GoogleAuthProvider(); pr.setCustomParameters({ prompt: 'select_account' });
  try { await F.signInWithPopup(F.auth, pr); }
  catch (e) {
    if (/popup-blocked|operation-not-supported|web-storage-unsupported/.test(e.code || '')) return F.signInWithRedirect(F.auth, pr);
    say(errText(e));
  }
}

async function saveProfile() {
  const ref = F.doc(F.db, 'users', S.user.uid);
  const snap = await F.getDoc(ref);
  const photo = /^https:\/\/[a-z0-9.-]+\.googleusercontent\.com\//.test(S.user.photoURL || '') ? S.user.photoURL.slice(0, 500) : null;
  const name = (snap.exists() && snap.data().name) || (S.user.displayName || 'Friend').slice(0, 40);
  if (!snap.exists() || snap.data().photo !== photo) await F.setDoc(ref, { name, photo, updated: F.serverTimestamp() });
  S.profile = { name, photo }; S.names[S.user.uid] = S.profile;
}

async function rename(name) {
  name = name.trim().slice(0, 40); if (!name) return;
  await F.setDoc(F.doc(F.db, 'users', S.user.uid), { name, photo: S.profile.photo, updated: F.serverTimestamp() });
  S.profile.name = name; S.names[S.user.uid] = { ...S.profile }; say('Name saved.');
}

async function loadNames(uids) {
  await Promise.all(uids.filter((u) => !S.names[u]).map(async (u) => {
    try { const d = await F.getDoc(F.doc(F.db, 'users', u)); S.names[u] = d.exists() ? d.data() : { name: 'Friend' }; } catch (e) { S.names[u] = { name: 'Friend' }; }
  }));
}

function watchGroups() {
  const q = F.query(F.collection(F.db, 'groups'), F.where('members', 'array-contains', S.user.uid));
  S.unsub.push(F.onSnapshot(q, (snap) => {
    S.groups = snap.docs.map((d) => ({ id: d.id, ...d.data() })).sort((a, b) => a.name.localeCompare(b.name));
    let want = S.gid && S.groups.find((g) => g.id === S.gid) ? S.gid : null;
    if (!want) { try { want = localStorage.getItem('gg-group'); } catch (e) { /* storage unavailable */ } }
    if (!S.groups.find((g) => g.id === want)) want = S.groups[0] && S.groups[0].id;
    if (want !== (S.group && S.group.id)) openGroup(want);
    else { S.group = S.groups.find((g) => g.id === want) || null; if (S.group) loadNames(S.group.members).then(render); render(); }
  }, (e) => say(errText(e))));
}

function openGroup(gid) {
  if (S.picksUnsub) S.picksUnsub();
  S.gid = gid; S.group = S.groups.find((g) => g.id === gid) || null; S.picks = [];
  try { if (gid) localStorage.setItem('gg-group', gid); } catch (e) { /* storage unavailable */ }
  if (!S.group) return render();
  loadNames(S.group.members).then(render);
  S.picksUnsub = F.onSnapshot(F.collection(F.db, 'groups', gid, 'picks'), async (snap) => {
    S.picks = snap.docs.map((d) => d.data());
    const keys = [...new Set(S.picks.map((p) => p.week))];
    await Promise.all(keys.map(async (k) => { S.weeks[k] = await week(k); }));
    render();
  }, (e) => say(errText(e)));
  S.unsub.push(() => S.picksUnsub && S.picksUnsub());
  render();
}

async function createGroup(name) {
  name = name.trim().slice(0, 40); if (!name) return;
  const ref = await F.addDoc(F.collection(F.db, 'groups'), { name, owner: S.user.uid, members: [S.user.uid], created: F.serverTimestamp() });
  S.gid = ref.id; S.tab = 'members'; say('Group made. Share the invite link with your friends.');
}

async function joinFromLink() {
  const gid = new URLSearchParams(location.search).get('join');
  if (!gid) return;
  history.replaceState(null, '', location.pathname);
  const ref = F.doc(F.db, 'groups', gid);
  const g = await F.getDoc(ref).catch(() => null);
  if (!g || !g.exists()) { S.msg = 'That invite link didn\'t work. Ask for a new one.'; return; }
  if (!g.data().members.includes(S.user.uid)) {
    if (!confirmJoin(g.data().name)) return;
    await F.updateDoc(ref, { members: F.arrayUnion(S.user.uid) });
    S.msg = `You joined ${g.data().name}.`;
  }
  S.gid = gid;
}
function confirmJoin(name) { S.joining = name; return true; }   // joining is the point of the link; the page names the group afterwards

async function leaveGroup() {
  await F.updateDoc(F.doc(F.db, 'groups', S.gid), { members: F.arrayRemove(S.user.uid) }); S.gid = null; say('You left the group.');
}
async function removeMember(uid) {
  await F.updateDoc(F.doc(F.db, 'groups', S.gid), { members: F.arrayRemove(uid) }); say(`${nameOf(uid)} was removed.`);
}
async function deleteGroup() {
  // picks first (rules let only each person delete their own unlocked picks, so finished ones simply stay unreadable)
  await F.deleteDoc(F.doc(F.db, 'groups', S.gid)); S.gid = null; say('Group deleted.');
}

async function savePick(key, id, L) {
  const ref = F.doc(F.db, 'groups', S.gid, 'picks', `${key}_${S.user.uid}`);
  await F.setDoc(ref, { uid: S.user.uid, week: key, leg: id, label: L.label, who: L.kind === 'Game' ? null : (L.who || null), game: L.game,
    kind: L.kind, price: L.price, kick: F.Timestamp.fromMillis(Date.parse(L.kick)), at: F.serverTimestamp() });
  S.pick.open = false; say('Pick saved. You can change it until that game kicks off.');
}
async function clearPick(key) {
  await F.deleteDoc(F.doc(F.db, 'groups', S.gid, 'picks', `${key}_${S.user.uid}`)); say('Pick removed.');
}

async function refresh(btn, status) {
  const live = liveRes();
  const legs = [];
  for (const p of S.picks) {
    const L = legOf(p); const k = p.week + '|' + p.leg;
    if (!L || L.r || live[k] || Date.parse(L.kick) > Date.now()) continue;
    legs.push([k, etDay(L.kick), L.x, L.price, L.p, [], []]);
  }
  btn.setAttribute('aria-busy', 'true');
  const tell = (t, c) => { status.textContent = t; status.className = 'refstatus ' + (c || ''); };
  try {
    if (!legs.length) tell('Nothing is waiting on a result right now.', 'ok');
    else await liveCheck('nfl', { legs }, tell, 'friends');
  } catch (e) { tell('Could not reach ESPN. Check the connection and try again.', 'bad'); }
  btn.setAttribute('aria-busy', 'false');
  setTimeout(render, 1200);
}

// ---------- views ----------
function render() {
  if (!F) return;
  const kids = [];
  if (S.msg) kids.push(h('p', { class: 'fmsg' + (/n't|wrong|No connection/.test(S.msg) ? ' bad' : ''), role: 'status' }, S.msg));
  if (!S.user) kids.push(signedOut());
  else {
    kids.push(meBar());
    kids.push(groupBar());
    if (S.group) {
      kids.push(h('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Group section' },
        [['week', 'This week'], ['board', 'Leaderboard'], ['history', 'History'], ['members', 'Members']].map(([k, t]) =>
          h('button', { class: 'tab', role: 'tab', 'aria-selected': String(S.tab === k), onclick: () => { S.tab = k; S.msg = ''; render(); } }, t))));
      kids.push({ week: weekView, board: boardView, history: historyView, members: membersView }[S.tab]());
    }
  }
  APP.replaceChildren(h('div', { class: 'fstack' }, kids));
}

function signedOut() {
  return h('div', { class: 'fcard' }, h('h2', null, 'Play with your friends'),
    h('p', { class: 'note' }, 'Sign in to make a group, invite friends with a link, pick your leg each week, and see who hits the most.'),
    h('div', { class: 'frow' }, h('button', { class: 'fbtn google', onclick: signIn },
      h('span', { 'aria-hidden': 'true', style: 'font-weight:700;color:#4285f4' }, 'G'), 'Sign in with Google')));
}

function meBar() {
  const inp = h('input', { class: 'fin grow', value: S.profile ? S.profile.name : '', maxlength: '40', 'aria-label': 'Your name in groups' });
  return h('div', { class: 'fcard' }, h('div', { class: 'frow' },
    h('span', { class: 'me' }, avatar(S.user.uid), h('b', null, S.profile ? S.profile.name : '')),
    h('span', { class: 'grow' }),
    h('button', { class: 'fbtn ghost so', onclick: () => F.signOut(F.auth) }, 'Sign out')),
  h('details', null, h('summary', { class: 'note' }, 'Change the name your friends see'),
    h('div', { class: 'frow', style: 'margin-top:8px' }, inp, h('button', { class: 'fbtn', onclick: () => rename(inp.value).catch((e) => say(errText(e))) }, 'Save'))));
}

function groupBar() {
  const inp = h('input', { class: 'fin grow', placeholder: 'Group name, e.g. Sunday crew', maxlength: '40', 'aria-label': 'New group name' });
  const make = h('div', { class: 'frow' }, inp, h('button', { class: 'fbtn', onclick: () => createGroup(inp.value).catch((e) => say(errText(e))) }, 'Make group'));
  if (!S.groups.length) return h('div', { class: 'fcard' }, h('h3', null, 'Your groups'),
    h('p', { class: 'note' }, 'You\'re not in a group yet. Make one and send the invite link, or open an invite link a friend sent you.'), make);
  return h('div', { class: 'fcard' }, h('h3', null, 'Your groups'),
    h('div', { class: 'chips' }, S.groups.map((g) => h('button', { class: 'chip', 'aria-pressed': String(g.id === S.gid), onclick: () => { S.msg = ''; openGroup(g.id); } },
      g.name, h('b', null, g.members.length)))),
    h('details', null, h('summary', { class: 'note' }, 'Make another group'), h('div', { style: 'margin-top:8px' }, make)));
}

function weekRows(key) {
  const live = liveRes();
  return S.group.members.map((uid) => {
    const p = S.picks.find((x) => x.week === key && x.uid === uid);
    return { uid, p, ...(p ? pickState(p, live) : { st: 'none' }) };
  });
}

function weekView() {
  const key = S.index && S.index.current;
  const W = key && S.weeks[key];
  if (!key || !W || W.then) return h('div', { class: 'fcard' }, h('p', { class: 'note' }, 'This week\'s board isn\'t posted yet. Picks open when it is (Mondays).'));
  const rows = weekRows(key), mine = rows.find((r) => r.uid === S.user.uid), pz = parlay(rows);
  const card = h('div', { class: 'fcard' }, h('h2', null, weekLabel(key)));
  // your pick
  if (mine.p && mine.L) {
    const locked = Date.parse(mine.L.kick) <= Date.now();
    card.append(h('div', { class: 'mypick' }, h('div', { class: 'grow' }, h('div', { class: 'note' }, 'Your leg'),
      h('div', { class: 'big' }, legTitle(mine.L)), h('div', { class: 'note' }, `${mine.L.game} · ${kickLabel(mine.L.kick)} · ${am(mine.p.price)}`)),
    locked ? mark(mine.st) : h('div', { class: 'frow' }, h('button', { class: 'fbtn ghost', onclick: () => { S.pick.open = !S.pick.open; render(); } }, S.pick.open ? 'Close' : 'Change'),
      h('button', { class: 'fbtn danger', onclick: () => clearPick(key).catch((e) => say(errText(e))) }, 'Remove'))));
  } else if (!S.pick.open) card.append(h('div', { class: 'frow' }, h('button', { class: 'fbtn', onclick: () => { S.pick.open = true; render(); } }, 'Pick your leg')));
  if (S.pick.open && !(mine.p && mine.L && Date.parse(mine.L.kick) <= Date.now())) card.append(picker(key, W, mine.p));
  // the group's parlay
  const tb = h('tbody');
  for (const r of rows) {
    tb.append(h('tr', { class: r.uid === S.user.uid ? 'hl' : null }, h('td', null, h('span', { class: 'fwho' }, avatar(r.uid, true), nameOf(r.uid))),
      h('td', null, r.L ? legCell(r.L) : r.p ? r.p.label : h('span', { class: 'wait' }, 'No pick yet')),
      h('td', { class: 'num' }, r.p ? am(r.p.price) : ''),
      h('td', null, r.p ? mark(r.st) : '')));
  }
  const tbl = h('div', { class: 'tablewrap' }, h('table', { class: 'res ftbl' }, h('thead', null, h('tr', null,
    ['Friend', 'Leg', 'Odds', 'Result'].map((t, i) => h('th', { class: i === 2 ? 'num' : null }, t)))), tb));
  const status = h('p', { class: 'refstatus' });
  const btn = h('button', { class: 'refbtn', type: 'button' }, h('span', { class: 'ico' }, '↻'), h('span', null, 'Refresh results'));
  btn.onclick = () => refresh(btn, status);
  const tiles = h('div', { class: 'sum' },
    tile(`${pz.n || 0} / ${S.group.members.length}`, 'legs picked'),
    tile(pz.n ? am(decToAm(pz.dec)) : '—', 'parlay odds'),
    tile(pz.n ? { win: 'Hit', loss: 'Missed', open: 'Not started', waiting: 'In play' }[pz.st] : '—', pz.st === 'loss' ? `${pz.lost} leg${pz.lost === 1 ? '' : 's'} missed` : 'parlay'));
  return h('div', { class: 'fstack' }, card, h('div', { class: 'fcard' }, h('div', { class: 'frow' }, h('h3', { class: 'grow' }, 'The group parlay'), btn), status, tiles, tbl));
}
const tile = (b, s) => h('div', { class: 'tile' }, h('b', null, b), h('span', null, s));
const legTitle = (L) => (L.kind === 'Game' ? L.label : `${L.who} ${L.label}`);
const legCell = (L) => h('span', { class: 'lc' }, legTitle(L), h('small', null, L.game));

function picker(key, W, cur) {
  const now = Date.now();
  const all = Object.entries(W.legs).filter(([, L]) => Date.parse(L.kick) > now);
  const games = [...new Set(all.map(([, L]) => L.game))].sort((a, b) => Date.parse(W.legs[all.find(([, L]) => L.game === a)[0]].kick) - Date.parse(W.legs[all.find(([, L]) => L.game === b)[0]].kick));
  const P = S.pick;
  const q = P.q.trim().toLowerCase();
  const list = all.filter(([, L]) => (P.kind === 'all' || KIND_OF(L.kind) === P.kind) && (P.game === 'all' || L.game === P.game)
    && (!q || legTitle(L).toLowerCase().includes(q) || L.game.toLowerCase().includes(q)))
    .sort(([, a], [, b]) => Date.parse(a.kick) - Date.parse(b.kick) || a.game.localeCompare(b.game) || b.p - a.p);
  const box = h('div', { class: 'legs', role: 'list' });
  for (const [id, L] of list.slice(0, 250)) {
    box.append(h('button', { class: 'leg', role: 'listitem', 'aria-pressed': String(cur && cur.leg === id), onclick: () => savePick(key, id, L).catch((e) => say(errText(e))) },
      h('span', { class: 't' }, legTitle(L)), h('span', { class: 's' }, `${L.game} · ${kickLabel(L.kick)}`),
      h('span', { class: 'pr' }, am(L.price), h('small', null, `model ${Math.round(L.p * 100)}%`))));
  }
  if (!list.length) box.append(h('p', { class: 'empty' }, all.length ? 'No legs match.' : 'Every game this week has kicked off.'));
  const search = h('input', { class: 'fin grow', type: 'search', placeholder: 'Search a player or team', value: P.q, 'aria-label': 'Search legs' });
  search.addEventListener('input', () => { P.q = search.value; const pos = search.selectionStart; render(); const s = APP.querySelector('input[type=search]'); if (s) { s.focus(); s.setSelectionRange(pos, pos); } });
  const gs = h('select', { 'aria-label': 'Game', onchange: (e) => { P.game = e.target.value; render(); } },
    h('option', { value: 'all' }, 'All games'), games.map((g) => h('option', { value: g, selected: P.game === g }, g)));
  return h('div', { class: 'fstack' },
    h('div', { class: 'chips' }, KIND.map(([k, t]) => h('button', { class: 'chip', 'aria-pressed': String(P.kind === k), onclick: () => { P.kind = k; render(); } }, t))),
    h('div', { class: 'frow' }, gs, search),
    h('p', { class: 'note' }, 'Tap a leg to lock it in. DraftKings odds and the model\'s chance are from the latest board.'), box);
}

function stats() {
  const live = liveRes();
  const M = {};
  for (const uid of S.group.members) M[uid] = { uid, w: 0, l: 0, pu: 0, late: 0, n: 0, streak: 0, sank: 0, seq: [] };
  const byWeek = {};
  for (const p of S.picks) { (byWeek[p.week] = byWeek[p.week] || []).push(p); }
  for (const p of [...S.picks].sort((a, b) => (a.week < b.week ? -1 : 1))) {
    const m = M[p.uid]; if (!m) continue;
    const { st } = pickState(p, live);
    m.n += 1;
    if (st === 'win') { m.w += 1; m.seq.push(1); } else if (st === 'loss') { m.l += 1; m.seq.push(0); } else if (st === 'push' || st === 'void') m.pu += 1; else if (st === 'late') m.late += 1;
  }
  for (const m of Object.values(M)) {
    let s = 0; const last = m.seq.at(-1);
    for (let i = m.seq.length - 1; i >= 0 && m.seq[i] === last; i--) s += 1;
    m.streak = m.seq.length ? (last ? s : -s) : 0;
    m.hit = m.w + m.l ? m.w / (m.w + m.l) : null;
  }
  return Object.values(M).sort((a, b) => b.w - a.w || (b.hit ?? -1) - (a.hit ?? -1) || a.l - b.l);
}

function boardView() {
  const rows = stats();
  const tb = h('tbody');
  rows.forEach((m, i) => tb.append(h('tr', { class: m.uid === S.user.uid ? 'hl' : null },
    h('td', null, h('span', { class: 'fwho' }, h('b', null, i + 1), avatar(m.uid, true), h('span', { class: 'lc' }, nameOf(m.uid),
      m.pu || m.late ? h('small', null, [m.pu ? `${m.pu} push/void` : '', m.late ? `${m.late} late` : ''].filter(Boolean).join(' · ')) : null))),
    h('td', { class: 'num' }, m.w), h('td', { class: 'num' }, m.l), h('td', { class: 'num' }, m.hit == null ? '—' : Math.round(m.hit * 100) + '%'),
    h('td', { class: 'num' }, m.streak > 0 ? `${m.streak}W` : m.streak < 0 ? `${-m.streak}L` : '—'))));
  const settled = weekKeys().map((k) => parlay(weekRows(k))).filter((z) => z.st === 'win' || z.st === 'loss');
  return h('div', { class: 'fcard' }, h('h3', null, 'Leaderboard, all weeks'),
    h('div', { class: 'sum' }, tile(`${settled.filter((z) => z.st === 'win').length} – ${settled.filter((z) => z.st === 'loss').length}`, 'group parlays hit – missed')),
    h('div', { class: 'tablewrap' }, h('table', { class: 'res ftbl' }, h('thead', null, h('tr', null,
      ['Friend', 'Hit', 'Miss', 'Hit %', 'Streak'].map((t, i) => h('th', { class: i ? 'num' : null }, t)))), tb)),
    h('p', { class: 'note' }, 'Ranked by legs hit, then hit rate. Pushes, voided props (player didn\'t play) and late picks don\'t count either way.'));
}

function weekKeys() { return [...new Set(S.picks.map((p) => p.week))].sort().reverse(); }

function historyView() {
  const keys = weekKeys();
  if (!keys.length) return h('div', { class: 'fcard' }, h('p', { class: 'note' }, 'No picks yet. The first week shows up here once someone picks.'));
  return h('div', { class: 'fcard' }, h('h3', null, 'Every week'), keys.map((k) => {
    const rows = weekRows(k).filter((r) => r.p), pz = parlay(rows);
    return h('div', { class: 'wk' }, h('div', { class: 'frow' }, h('b', { class: 'grow' }, weekLabel(k)),
      pz.n ? h('span', null, `${pz.n} legs · ${am(decToAm(pz.dec))} · `, mark(pz.st)) : null),
    h('div', { class: 'tablewrap' }, h('table', { class: 'res ftbl' }, h('tbody', null, rows.map((r) => h('tr', null,
      h('td', null, h('span', { class: 'fwho' }, avatar(r.uid, true), nameOf(r.uid))), h('td', null, r.L ? legCell(r.L) : r.p.label),
      h('td', { class: 'num' }, am(r.p.price)), h('td', null, mark(r.st))))))));
  }));
}

function membersView() {
  const g = S.group, owner = g.owner === S.user.uid;
  const link = location.origin + location.pathname + '?join=' + g.id;
  const copy = h('button', { class: 'fbtn', onclick: async () => {
    try { if (navigator.share) await navigator.share({ title: `Join ${g.name} on GoonerGamble`, url: link }); else { await navigator.clipboard.writeText(link); say('Invite link copied.'); } }
    catch (e) { /* share sheet closed */ }
  } }, navigator.share ? 'Share invite link' : 'Copy invite link');
  const tb = h('tbody', null, g.members.map((uid) => h('tr', null,
    h('td', null, h('span', { class: 'fwho' }, avatar(uid, true), nameOf(uid), uid === g.owner ? h('span', { class: 'badge' }, 'Owner') : null)),
    h('td', { class: 'num' }, owner && uid !== S.user.uid ? h('button', { class: 'fbtn danger', onclick: () => removeMember(uid).catch((e) => say(errText(e))) }, 'Remove') : ''))));
  const rn = h('input', { class: 'fin grow', value: g.name, maxlength: '40', 'aria-label': 'Group name' });
  return h('div', { class: 'fstack' },
    h('div', { class: 'fcard' }, h('h3', null, 'Invite friends'), h('p', { class: 'note' }, 'Anyone with this link can sign in and join. Up to 30 people per group.'),
      h('div', { class: 'invite' }, link), h('div', { class: 'frow' }, copy)),
    h('div', { class: 'fcard' }, h('h3', null, `Members (${g.members.length})`), h('div', { class: 'tablewrap' }, h('table', { class: 'res ftbl' }, tb)),
      owner ? h('div', { class: 'frow' }, rn, h('button', { class: 'fbtn ghost', onclick: () => F.updateDoc(F.doc(F.db, 'groups', g.id), { name: rn.value.trim().slice(0, 40) }).then(() => say('Renamed.')).catch((e) => say(errText(e))) }, 'Rename')) : null,
      h('div', { class: 'frow' }, owner
        ? h('button', { class: 'fbtn danger', onclick: () => { if (S.confirmDel) deleteGroup().catch((e) => say(errText(e))); else { S.confirmDel = true; say('Tap Delete group again to delete it for everyone.'); setTimeout(() => { S.confirmDel = false; }, 6000); } } }, 'Delete group')
        : h('button', { class: 'fbtn danger', onclick: () => leaveGroup().catch((e) => say(errText(e))) }, 'Leave group'))));
}

boot().catch((e) => { APP.replaceChildren(h('p', { class: 'empty' }, 'The page couldn\'t load. Check the connection and reload.')); console.error(e); });
