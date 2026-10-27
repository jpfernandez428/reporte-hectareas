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

// Cuadro para escribir el PIN, dentro de la pagina, junto al boton.
function pedirPin(boton) {
  return new Promise(listo => {
    const caja = boton.closest('.acciones, .cab-acciones, .sg-botones, td, div') || boton.parentElement;
    let cuadro = caja.nextElementSibling;
    if (cuadro && cuadro.classList.contains('pin-caja')) cuadro.remove();
    caja.insertAdjacentHTML('afterend', `<div class="pin-caja" style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:6px 0">
      <span style="font-size:13px;font-weight:600">PIN para guardar:</span>
      <input type="password" inputmode="numeric" autocomplete="off" style="padding:6px;font-size:15px;width:9em;border:1px solid #bbb;border-radius:6px">
      <button type="button" style="padding:6px 12px;border-radius:6px;border:1px solid #2f6f3e;background:#2f6f3e;color:#fff;font-weight:700">Usar PIN</button>
      <button type="button" style="padding:6px 10px;border-radius:6px;border:1px solid #ccc;background:#fff">Cancelar</button></div>`);
    cuadro = caja.nextElementSibling;
    const [entrada, usar, cancelar] = [cuadro.querySelector('input'), ...cuadro.querySelectorAll('button')];
    const fin = valor => { cuadro.remove(); listo(valor); };
    usar.onclick = () => { const v = entrada.value.trim(); if (v) { recordarPin(v); fin(v); } };
    entrada.onkeydown = ev => { if (ev.key === 'Enter') usar.onclick(); };
    cancelar.onclick = () => fin('');
    entrada.focus();
  });
}

// POST al Worker con el PIN. Devuelve {ok, j, pinMalo}. Si el PIN es
// incorrecto se olvida para que lo pidan de nuevo.
async function enviarConPin(url, cuerpo, boton) {
  let pin = pinGuardado();
  if (!pin) pin = await pedirPin(boton);
  if (!pin) return { ok: false, j: { error: 'sin PIN' }, cancelado: true };
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...cuerpo, pin }) });
  const j = await r.json().catch(() => ({}));
  if (r.status === 403 && j.error === 'pin') { recordarPin(''); return { ok: false, j, pinMalo: true, status: r.status }; }
  return { ok: r.ok, j, status: r.status };
}
const textoError = res => res.pinMalo ? 'PIN incorrecto: no se guardó nada.' : res.cancelado ? 'Sin PIN no se guarda.' : 'No se pudo guardar (' + ((res.j && res.j.error) || 'error') + ').';
