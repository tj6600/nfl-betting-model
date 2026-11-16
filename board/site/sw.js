// Service worker for the installed app (Android, iPhone, Play Store wrapper).
// Network first: every open shows the newest board the scheduled runs pushed. The cached copy is only used
// when the phone is offline, so the app never shows a stale board while it has a connection.
const CACHE = 'props-board-v1';
const SHELL = ['/', '/index.html', '/nba.html', '/nhl.html', '/bank.html', '/icons/icon-192.png', '/offline.html'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const fonts = url.host === 'fonts.googleapis.com' || url.host === 'fonts.gstatic.com';
  if (url.origin !== self.location.origin && !fonts) return;   // DraftKings links etc. go straight to the network
  if (fonts) {   // fonts never change: cache first
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
      const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); return res;
    })));
    return;
  }
  // same-origin pages and files: network first (bypassing the HTTP cache), fall back to the last good copy
  const key = url.pathname === '/' ? '/index.html' : url.pathname;
  e.respondWith(fetch(req, {cache: 'no-store'}).then(res => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(key, copy)); }
    return res;
  }).catch(() => caches.match(key).then(hit => hit || (req.mode === 'navigate' ? caches.match('/offline.html') : Response.error()))));
});
