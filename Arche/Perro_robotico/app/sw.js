// Service worker de la app del perro.
// Solo guarda la "carcasa" de la app (la pantalla y los iconos) para que abra rapido
// y muestre un aviso claro si el banco esta apagado. Nada de /api, /frame ni el video:
// eso siempre va en vivo al PC.
const VERSION = "perro-v13";
const CARCASA = ["/app", "/manifest.webmanifest", "/iconos/icono-180.png", "/iconos/icono-192.png", "/iconos/icono-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(CARCASA)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (!CARCASA.includes(url.pathname)) return;           // todo lo demas: directo a la red
  // primero la red (para tener siempre la ultima version); si el PC no responde, la copia guardada
  e.respondWith(
    fetch(e.request)
      .then(r => { const copia = r.clone(); caches.open(VERSION).then(c => c.put(e.request, copia)); return r; })
      .catch(() => caches.match(e.request))
  );
});
