// App "Flota C&H" (reporte2.html en el celular, pedido del usuario 22-oct-2026).
// Guarda la pagina y los ultimos datos para abrir rapido y verlos sin senal.
// Siempre intenta la red primero; sin red responde lo guardado (los datos con
// el encabezado X-Desde-Cache para que la pagina avise "sin conexion").
// Solo maneja estos archivos: el resto (index.html, mapas, etc.) pasa directo.
const CACHE_APP = 'flota-app-v1';
const CACHE_DATOS = 'flota-datos-v1';
const APP = ['reporte2.html', 'manifest.webmanifest', 'icono-192.png', 'icono-512.png', 'apple-touch-icon.png'];
const DATOS = ['datos/reporte_diario.json', 'datos/campos.json', 'datos/confirmaciones.json'];

self.addEventListener('install', ev => {
  ev.waitUntil(caches.open(CACHE_APP).then(c => c.addAll(APP)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', ev => {
  ev.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k.startsWith('flota-') && k !== CACHE_APP && k !== CACHE_DATOS).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const conPlazo = (promesa, ms) => Promise.race([promesa, new Promise((_, no) => setTimeout(() => no(new Error('plazo')), ms))]);

async function redPrimero(peticion, cache, clave, plazo, marcar) {
  try {
    const r = await conPlazo(fetch(peticion), plazo);
    if (r.ok) { const c = await caches.open(cache); await c.put(clave, r.clone()); }
    return r;
  } catch (e) {
    const guardado = await (await caches.open(cache)).match(clave);
    if (!guardado) throw e;
    if (!marcar) return guardado;
    const h = new Headers(guardado.headers); h.set('X-Desde-Cache', '1');
    return new Response(await guardado.blob(), { status: 200, headers: h });
  }
}

self.addEventListener('fetch', ev => {
  const p = ev.request;
  if (p.method !== 'GET') return;
  const url = new URL(p.url);
  if (url.origin !== self.location.origin) return;
  const base = new URL('./', self.registration.scope).pathname;
  const rel = url.pathname.startsWith(base) ? url.pathname.slice(base.length) : null;
  const clave = url.origin + url.pathname;  // sin ?x=...
  if (DATOS.includes(rel)) ev.respondWith(redPrimero(p, CACHE_DATOS, clave, 15000, true));
  else if (APP.includes(rel)) ev.respondWith(redPrimero(p, CACHE_APP, clave, 4000, false));
});
