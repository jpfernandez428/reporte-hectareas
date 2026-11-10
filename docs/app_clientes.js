// ===========================================================================
// Operación → pestaña "Correos clientes" (pedido del usuario 10-nov-2026).
// Lista los campos con máquinas en Operación y los campos con trabajo ayer (GPS,
// v2.trabajo_campo), con sus máquinas, el cliente y sus correos. Un campo con
// máquinas o trabajo y sin correo sale en rojo: no recibirá el reporte diario.
//
// PRIVACIDAD: los correos viven solo en Cloudflare (D1) y en la planilla
// "Operación CYH"; nunca en GitHub ni en los datos publicados. Se leen y se
// guardan con el PIN (Worker POST /clientes). Este archivo no guarda nada en el
// aparato.
// ===========================================================================
(function () {
  // Una fila por campo: cliente (empresa) y hasta 2 contactos (nombre y correo; el 2 es opcional).
  const DATOS = ['cliente', 'nombre1', 'correo1', 'nombre2', 'correo2'];
  const RE_CORREO = /^[^\s@,;<>"'()]+@[^\s@,;<>"'()]+\.[a-z]{2,}$/i;
  const tieneCorreo = d => !!(d && (d.correo1 || d.correo2));
  const C = { borrador: {}, datos: null, cambios: [], cargando: false, error: '', editando: null, abiertoNuevo: false, msg: '' };

  // Nombre de campo "oficial": el de Wialon si es el mismo (sin mayúsculas ni tildes),
  // o el nombre de la planilla de una equivalencia; si no, tal cual.
  function canon(c) {
    c = String(c || '').trim();
    const w = (CAMPOS.campos || []).find(x => clave(x) === clave(c));
    if (w) return w;
    const e = Object.keys(CAMPOS.equivalencias || {}).find(k => clave(k) === clave(c));
    return e || c;
  }
  // Campo de Wialon con trabajo ayer -> nombre de la planilla que lo agrupa (ej. MGH Nancagua -> MGH), si se usa.
  function canonWialon(c, usados) {
    const k = Object.keys(CAMPOS.equivalencias || {}).find(n => (CAMPOS.equivalencias[n] || []).includes(c) && usados.has(clave(n)));
    return k || canon(c);
  }

  function filas() {
    const por = new Map();
    const fila = nombre => {
      const k = clave(nombre);
      if (!por.has(k)) por.set(k, { campo: nombre, maquinas: new Set(), ayer: new Set(), dato: null });
      return por.get(k);
    };
    for (const m of Object.keys((OP && OP.maquinas) || {})) {
      const c = valorDe(m).campo;
      if (c && !esTaller(c)) fila(canon(c)).maquinas.add(m);
    }
    const usados = new Set(por.keys());
    for (const t of ((V && V.trabajo_campo) || [])) {
      if ((t.ayer_ha || 0) > 0 || (t.ayer_sin || 0) > 0) fila(canonWialon(t.campo, usados)).ayer.add(t.maquina);
    }
    for (const d of (C.datos || [])) {
      const f = fila(d.campo);
      f.dato = d;
    }
    return [...por.values()].map(f => ({ ...f, activo: f.maquinas.size > 0 || f.ayer.size > 0, falta: (f.maquinas.size > 0 || f.ayer.size > 0) && !tieneCorreo(f.dato) }))
      .sort((a, b) => (b.falta - a.falta) || (b.activo - a.activo) || nombreCampo(a.campo).localeCompare(nombreCampo(b.campo), 'es'));
  }
  const nFaltan = () => C.datos ? filas().filter(f => f.falta).length : 0;

  async function cargar(boton) {
    if (C.cargando) return;
    C.cargando = true; C.error = '';
    let res;
    try { res = await enviarConPin(WORKER + '/clientes', { accion: 'leer' }, boton || document.getElementById('clientesCaja') || document.body); }
    catch (e) { res = { ok: false, j: { error: 'sin conexión con Cloudflare' } }; }
    C.cargando = false;
    if (res.ok && res.j && res.j.clientes) { C.datos = res.j.clientes; C.cambios = res.j.cambios || []; }
    else C.error = res.status === 404 ? 'Falta pegar el Worker nuevo en Cloudflare.' : textoError(res);
    dibujar();
  }

  const corto = m => m.replace(/^Shacker /, '').replace(/^Tractor (\d+).*/, 'Tractor $1');
  function maquinasTxt(f) {
    const op = [...f.maquinas], ay = [...f.ayer].filter(m => !f.maquinas.has(m));
    const partes = [];
    if (op.length) partes.push(`En Operación: ${op.map(corto).join(', ')}`);
    if (f.ayer.size) partes.push(`trabajaron ayer: ${[...f.ayer].map(corto).join(', ')}`);
    if (ay.length && !op.length) partes.push('(no están anotadas en Operación en este campo)');
    return partes.join(' · ');
  }

  function tarjeta(f) {
    const d = f.dato || {}, ed = C.editando === clave(f.campo), b = C.borrador[clave(f.campo)] || {};
    const nom = nombreCampo(f.campo);
    let html = `<div class="cli${f.falta ? ' falta' : ''}" data-cli="${esc(f.campo)}">
      <div class="cli-cab"><b>${esc(nom)}</b>${d.ts ? `<small>${esc(fechaChile(d.ts))} · ${esc(d.origen || 'App')}</small>` : ''}</div>
      ${f.activo ? `<div class="cli-maq">${esc(maquinasTxt(f))}</div>` : '<div class="cli-maq">Sin máquinas ni trabajo ayer.</div>'}
      ${f.falta ? '<div class="cli-alerta">⚠ Falta correo del cliente: este campo no recibirá reporte.</div>' : ''}`;

    const val = k => b[k] ?? d[k] ?? '';
    const contacto = (n, opc) => `<fieldset class="cli-contacto"><legend>Contacto ${n}${opc ? ' (opcional)' : ''}</legend>
        <label>Nombre<input data-cli-k="nombre${n}" value="${esc(val('nombre' + n))}" maxlength="120" autocomplete="off" placeholder="Nombre y apellido"></label>
        <label>Correo<input data-cli-k="correo${n}" type="email" inputmode="email" autocapitalize="off" spellcheck="false" value="${esc(val('correo' + n))}" maxlength="120" placeholder="nombre@empresa.cl"></label></fieldset>`;
    const persona = n => d['correo' + n] || d['nombre' + n] ? `${d['nombre' + n] ? esc(d['nombre' + n]) : '<i>sin nombre</i>'}<br>${d['correo' + n] ? esc(d['correo' + n]) : '<i>sin correo</i>'}` : '<i>—</i>';
    if (ed) {
      html += `<label>Cliente (empresa)<input data-cli-k="cliente" value="${esc(val('cliente'))}" maxlength="120" placeholder="Nombre de la empresa"></label>
        ${contacto(1, false)}${contacto(2, true)}
        <div class="cli-error"></div>
        <div class="cli-botones"><button type="button" class="si" data-cli-guardar>Guardar</button><button type="button" data-cli-cancelar>Cancelar</button>
        ${f.dato ? '<button type="button" class="borrar" data-cli-borrar>Borrar cliente y contactos</button>' : ''}</div>`;
    } else {
      html += `<div class="cli-datos"><div><span>Cliente</span>${d.cliente ? esc(d.cliente) : '<i>sin anotar</i>'}</div>
        <div><span>Contacto 1</span><div>${persona(1)}</div></div>
        ${d.correo2 || d.nombre2 ? `<div><span>Contacto 2</span><div>${persona(2)}</div></div>` : ''}</div>
        <button type="button" class="cli-editar" data-cli-editar>${f.dato ? 'Editar' : 'Agregar cliente y contactos'}</button>`;
    }
    return html + '</div>';
  }

  function html() {
    let cuerpo;
    if (!C.datos) {
      cuerpo = C.cargando ? '<div class="vacio">Cargando…</div>'
        : `<p>Los correos de los clientes son privados: se ven con el PIN.</p><button type="button" class="cli-editar" onclick="Clientes.cargar(this)">Ver correos de clientes</button>${C.error ? `<p style="color:var(--rojo)">${esc(C.error)}</p>` : ''}`;
    } else {
      const fs = filas(), act = fs.filter(f => f.activo), otros = fs.filter(f => !f.activo);
      const faltan = act.filter(f => f.falta).length;
      cuerpo = `${faltan ? `<div class="cli-resumen falta">⚠ ${faltan} campo${faltan > 1 ? 's' : ''} con máquinas sin correo del cliente: no recibirán reporte.</div>` : act.length ? '<div class="cli-resumen ok">✓ Todos los campos con máquinas tienen correo.</div>' : ''}
        ${C.msg ? `<div class="cli-msg">${C.msg}</div>` : ''}
        <h2>Campos con máquinas o trabajo ayer (${act.length})</h2>${act.map(tarjeta).join('') || '<div class="vacio">Ninguno.</div>'}
        <button type="button" class="cli-editar" data-cli-nuevo>+ Agregar otro campo</button>
        ${otros.length ? `<h2 style="margin-top:18px">Otros campos con cliente (${otros.length})</h2>${otros.map(tarjeta).join('')}` : ''}
        ${C.cambios.length ? `<details style="margin-top:14px"><summary style="cursor:pointer;font-weight:700">Historial de cambios (${C.cambios.length})</summary><table class="hist-cli"><tr><th>Fecha</th><th>Campo</th><th>Qué</th><th>Antes</th><th>Después</th><th>Origen</th></tr>
          ${C.cambios.map(c => `<tr><td>${esc(fechaChile(c.ts))}</td><td>${esc(c.campo)}</td><td>${esc(c.cambio)}</td><td>${esc(c.antes)}</td><td>${esc(c.despues)}</td><td>${esc(c.origen || 'App')}</td></tr>`).join('')}</table></details>` : ''}`;
    }
    return `<section id="clientesCaja"><h2>Correos de los clientes</h2>
      <p class="nota">El reporte diario sale a las 07:45 a los correos de los contactos de cada campo que tuvo trabajo el día anterior, con copia a jpfernandez@cosechamecanizada.cl. Se sincroniza con la pestaña "Correos clientes" de la planilla Operación CYH.</p>${cuerpo}</section>`;
  }

  async function guardar(campo, datos, boton, borrar) {
    boton.disabled = true;
    let res;
    try { res = await enviarConPin(WORKER + '/clientes', borrar ? { accion: 'borrar', campo } : { accion: 'guardar', campo, ...datos }, boton); }
    catch (e) { res = { ok: false, j: { error: 'sin conexión con Cloudflare' } }; }
    boton.disabled = false;
    if (res.ok && res.j && res.j.clientes) {
      C.datos = res.j.clientes; C.editando = null; delete C.borrador[clave(campo)];
      C.msg = `<span style="color:var(--ok)">✓ ${borrar ? 'Borrado' : 'Guardado'}: ${esc(nombreCampo(campo))}</span>`;
      cargarHistorial();
    } else C.msg = `<span style="color:var(--rojo)">No se guardó: ${esc(res.j && res.j.error ? res.j.error : textoError(res))}</span>`;
    dibujar();
  }
  async function cargarHistorial() {
    try { const r = await enviarConPin(WORKER + '/clientes', { accion: 'leer' }, document.body); if (r.ok && r.j) { C.cambios = r.j.cambios || []; if (UI.pestana === 'clientes') dibujar(); } } catch (e) { /* queda el anterior */ }
  }

  document.addEventListener('click', async ev => {
    if (ev.target.closest('[data-cli-nuevo]')) {
      const c = await elegir('campo', 'Campo del cliente', '');
      if (!c || esTaller(c)) return;
      if (!(C.datos || []).some(d => clave(d.campo) === clave(c))) C.datos = [...(C.datos || []), { campo: canon(c), nuevo: true }];
      C.editando = clave(canon(c)); C.msg = ''; dibujar(); return;
    }
    const t = ev.target.closest('.cli');
    if (!t) return;
    const campo = t.dataset.cli;
    if (ev.target.closest('[data-cli-editar]')) { C.editando = clave(campo); C.msg = ''; dibujar(); const i = document.querySelector(`.cli[data-cli="${CSS.escape(campo)}"] input`); if (i) i.focus(); return; }
    if (ev.target.closest('[data-cli-cancelar]')) { delete C.borrador[clave(campo)]; C.editando = null; C.datos = (C.datos || []).filter(d => !d.nuevo); dibujar(); return; }
    if (ev.target.closest('[data-cli-borrar]')) {
      const b = ev.target.closest('[data-cli-borrar]');
      if (!b.dataset.ok) { b.dataset.ok = '1'; b.textContent = '¿Seguro? Toca de nuevo para borrar'; return; }
      return guardar(campo, {}, b, true);
    }
    if (ev.target.closest('[data-cli-guardar]')) {
      const datos = Object.fromEntries(DATOS.map(k => [k, t.querySelector(`[data-cli-k="${k}"]`).value.trim()]));
      // Cada correo bien escrito (Cloudflare lo vuelve a revisar).
      const malo = ['correo1', 'correo2'].find(k => datos[k] && !RE_CORREO.test(datos[k]));
      const err = t.querySelector('.cli-error');
      if (malo) { err.textContent = `El correo del contacto ${malo.slice(-1)} no está bien escrito: ${datos[malo]}`; t.querySelector(`[data-cli-k="${malo}"]`).focus(); return; }
      if (datos.correo2 && !datos.correo1) { datos.correo1 = datos.correo2; datos.nombre1 = datos.nombre2 || datos.nombre1; datos.correo2 = ''; datos.nombre2 = ''; }
      return guardar(campo, datos, ev.target.closest('[data-cli-guardar]'), false);
    }
  });

  // Lo escrito queda guardado (en memoria) aunque la página se vuelva a dibujar.
  document.addEventListener('input', ev => {
    const i = ev.target.closest('[data-cli-k]'), t = i && i.closest('.cli');
    if (!t) return;
    const k = clave(t.dataset.cli);
    C.borrador[k] = { ...(C.borrador[k] || {}), [i.dataset.cliK]: i.value };
  });

  const estilo = document.createElement('style');
  estilo.textContent = `
    .cli { background: #fff; border: 1px solid var(--borde); border-radius: 12px; padding: 12px; margin: 0 0 10px; }
    .cli.falta { border: 2px solid var(--rojo); background: var(--rojo-f); }
    .cli-cab { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
    .cli-cab b { font-size: 17px; } .cli-cab small { color: var(--gris); font-size: 12px; }
    .cli-maq { font-size: 14px; color: var(--gris); margin: 4px 0 6px; }
    .cli-alerta { color: var(--rojo); font-weight: 700; font-size: 15px; margin: 6px 0; }
    .cli-datos { font-size: 15px; display: grid; gap: 4px; margin: 6px 0 8px; overflow-wrap: anywhere; }
    .cli-datos span { display: inline-block; min-width: 72px; font-size: 12px; font-weight: 600; color: var(--gris); text-transform: uppercase; }
    .cli label { display: block; font-size: 13px; font-weight: 600; color: var(--gris); margin: 8px 0 0; }
    .cli-contacto { border: 1px solid var(--borde); border-radius: 10px; margin: 10px 0 0; padding: 4px 10px 10px; background: #fff; }
    .cli-contacto legend { font-size: 13px; font-weight: 700; padding: 0 4px; }
    .cli-error { color: var(--rojo); font-weight: 700; font-size: 14px; margin-top: 8px; }
    .cli-datos > div { display: flex; gap: 6px; } .cli-datos > div > span { flex: none; }
    .cli input, .cli textarea { display: block; width: 100%; margin-top: 4px; padding: 10px; font-size: 16px; border: 1px solid #c9c9c9; border-radius: 8px; font-family: inherit; background: #fff; }
    .cli-botones { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
    .cli-botones button, .cli-editar { padding: 10px 14px; font-size: 15px; font-weight: 700; border-radius: 9px; border: 1px solid var(--verde); background: #fff; color: var(--verde); cursor: pointer; }
    .cli-botones button.si { background: var(--verde); color: #fff; }
    .cli-botones button.borrar { border-color: var(--rojo); color: var(--rojo); margin-left: auto; }
    .cli-resumen { padding: 10px 12px; border-radius: 8px; font-weight: 700; margin: 8px 0 12px; }
    .cli-resumen.falta { background: var(--rojo-f); color: var(--rojo); border-left: 4px solid var(--rojo); }
    .cli-resumen.ok { background: #e3f2e6; color: #1f6b34; }
    .cli-msg { margin: 6px 0 10px; font-weight: 700; }
    .hist-cli { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; }
    .hist-cli td, .hist-cli th { border-bottom: 1px solid var(--borde); padding: 5px; text-align: left; vertical-align: top; overflow-wrap: anywhere; }`;
  document.head.appendChild(estilo);

  window.Clientes = { html, cargar, nFaltan, cargado: () => !!C.datos, filas };
})();
