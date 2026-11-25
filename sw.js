/* Lets the app open offline and install as a full-screen app. Only the app's own files are cached;
   your data (GitHub) and prices are always fetched fresh. */
const CACHE = 'nwl-gh-v1';
const SHELL = ['./', 'index.html', 'manifest.webmanifest', 'icon-512.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== CACHE).map(x => caches.delete(x)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  const own = url.origin === location.origin && !url.pathname.endsWith('prices.json');
  const fonts = url.host.endsWith('gstatic.com') || url.host.endsWith('googleapis.com');
  if (!own && !fonts) return;                       // GitHub API, prices: straight to the network
  e.respondWith(fetch(e.request).then(res => {       // newest version first, saved copy when offline
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); }
    return res;
  }).catch(() => caches.match(e.request, { ignoreSearch: true }).then(r => r || caches.match('index.html'))));
});
