// PIN para guardar desde las paginas (pedido del usuario 26-oct-2026).
// Un solo PIN para todos; ver sigue abierto. El PIN de verdad vive como secreto
// del Worker de Cloudflare (PIN_EDICION): aqui solo se pide una vez por aparato
// y se recuerda en este navegador. Con PIN incorrecto el Worker no guarda nada.
const PIN_CLAVE = 'flota_pin';

function pinGuardado() {
  try { return localStorage.getItem(PIN_CLAVE) || ''; } catch (e) { return ''; }
}
function recordarPin(pin) {
  try { if (pin) localStorage.setItem(PIN_CLAVE, pin); else localStorage.removeItem(PIN_CLAVE); } catch (e) { /* sin almacenamiento */ }
}

// Cuadro para escribir el PIN: ventana al centro de la pantalla, encima de todo
// (11-nov-2026). Antes se ponia junto al boton, pero si la pagina se redibujaba
// en ese momento el cuadro quedaba fuera de la vista y el cambio nunca se
// enviaba (computador sin PIN guardado). El parametro boton ya no se usa.
let PIN_ESPERA = null;
function pedirPin() {
  if (PIN_ESPERA) return PIN_ESPERA; // un solo cuadro aunque se pida dos veces
  PIN_ESPERA = new Promise(listo => {
    const capa = document.createElement('div');
    capa.className = 'pin-capa';
    capa.setAttribute('role', 'dialog'); capa.setAttribute('aria-modal', 'true');
    capa.style.cssText = 'position:fixed;inset:0;z-index:100000;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;padding:16px';
    capa.innerHTML = `<div style="background:#fff;color:#161616;border-radius:12px;padding:18px 18px 14px;width:100%;max-width:340px;box-shadow:0 10px 30px rgba(0,0,0,.3);font-family:inherit">
      <div style="font-size:17px;font-weight:700;margin-bottom:4px">PIN para guardar</div>
      <div style="font-size:13px;color:#555;margin-bottom:10px">Se pide una sola vez en este aparato.</div>
      <input type="password" inputmode="numeric" autocomplete="off" aria-label="PIN" style="box-sizing:border-box;width:100%;padding:10px;font-size:18px;border:1px solid #bbb;border-radius:8px">
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
        <button type="button" data-pin="no" style="padding:9px 14px;border-radius:8px;border:1px solid #ccc;background:#fff;font-size:15px">Cancelar</button>
        <button type="button" data-pin="si" style="padding:9px 16px;border-radius:8px;border:1px solid #161616;background:#161616;color:#fff;font-weight:700;font-size:15px">Usar PIN</button>
      </div></div>`;
    document.body.appendChild(capa);
    const entrada = capa.querySelector('input');
    const fin = valor => { capa.remove(); PIN_ESPERA = null; listo(valor); };
    const usar = () => { const v = entrada.value.trim(); if (v) { recordarPin(v); fin(v); } else entrada.focus(); };
    capa.querySelector('[data-pin="si"]').onclick = usar;
    capa.querySelector('[data-pin="no"]').onclick = () => fin('');
    entrada.onkeydown = ev => { if (ev.key === 'Enter') usar(); else if (ev.key === 'Escape') fin(''); };
    setTimeout(() => entrada.focus(), 30);
  });
  return PIN_ESPERA;
}

// POST al Worker con el PIN. Devuelve {ok, j, pinMalo}. Si el PIN es
// incorrecto se olvida para que lo pidan de nuevo.
async function enviarConPin(url, cuerpo, boton) {
  let pin = pinGuardado();
  if (!pin) pin = await pedirPin();
  if (!pin) return { ok: false, j: { error: 'sin PIN' }, cancelado: true };
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...cuerpo, pin }) });
  const j = await r.json().catch(() => ({}));
  if (r.status === 403 && j.error === 'pin') { recordarPin(''); return { ok: false, j, pinMalo: true, status: r.status }; }
  return { ok: r.ok, j, status: r.status };
}
const textoError = res => res.pinMalo ? 'PIN incorrecto: no se guardó nada.' : res.cancelado ? 'Sin PIN no se guarda.' : 'No se pudo guardar (' + ((res.j && res.j.error) || 'error') + ').';
