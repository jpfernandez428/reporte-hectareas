// Secciones "Ayer" y "Flota (GPS)" de la app (etapa 2 de la reorganizacion,
// pedido del usuario 26-oct-2026; reglas en CLAUDE.md). Las usa app.html.
// - Ayer: lo de ayer y los ultimos 7 dias (datos/reporte_v2.json, el mismo de
//   reporte2.html): resumen, alertas, maquinas que trabajaron ayer, camionetas,
//   camion y ultimos 7 dias. Lo de hoy (maquinas en operacion) va en Operacion.
// - Flota: el tablero de la flota (datos/flota.json, cada 4 horas; el mismo de
//   index.html#flota): estados, GPS sin senal, detalle de 30 dias por maquina y
//   maquinas sin geocerca de los ultimos 30 dias.
// Todo va dentro de este bloque (app.html tiene sus propias funciones con
// nombres parecidos); hacia afuera solo window.SeccionAyer y window.SeccionFlota.
(function () {
  const esc = t => String(t ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const sinT = t => String(t || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const n = (v, d = 1) => Number(v || 0).toLocaleString('es-CL', { minimumFractionDigits: d, maximumFractionDigits: d });
  const DIAS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];
  const fc = iso => { const [a, m, d] = iso.split('-').map(Number); return `${DIAS[new Date(a, m - 1, d).getDay()]} ${String(d).padStart(2, '0')}-${String(m).padStart(2, '0')}`; };
  const mapa = (url, txt = 'mapa') => url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${txt}</a>` : '';
  const haTxt = (ha, sin) => (ha ? n(ha, 2) : (sin ? '' : '–')) + (sin ? ` <span class="estim">(~${n(sin)})</span>` : '');
  const minTxt = m => m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min` : `${m} min`;
  const lugaresTxt = (lugares, sep) => lugares.map(l => l.tipo === 'campo' ? `<b>${esc(l.nombre)}</b>` : esc(l.nombre)).join(sep);
  // Maquina por texto: los numeros deben calzar enteros ("10" = Tractor 10, no Tractor 1).
  const calza = (nombre, q) => {
    const nums = String(nombre).match(/\d+/g) || [];
    return sinT(q).split(/\s+/).filter(Boolean).every(t => /^\d+$/.test(t) ? nums.includes(t) : sinT(nombre).includes(t));
  };

  const estilo = document.createElement('style');
  estilo.textContent = `
    .ay .tarjetas { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; }
    .ay .tarjeta { background: var(--verde-f); border-left: 4px solid var(--verde); padding: 8px 10px; border-radius: 4px; }
    .ay .tarjeta b { display: block; font-size: 20px; color: var(--verde); }
    .ay .tarjeta span { font-size: 12px; color: var(--gris); }
    .ay .estim, .fl .estim { color: var(--rojo); }
    .ay .alerta { background: var(--rojo-f); border-left: 4px solid var(--rojo); padding: 8px 10px; margin: 6px 0; font-size: 14px; border-radius: 4px; }
    .ay .alerta-grande { background: var(--rojo); color: #fff; padding: 12px 14px; border-radius: 10px; margin-bottom: 12px; }
    .ay .alerta-grande a { color: #fff; }
    .ay details { border-top: 1px solid var(--borde); }
    .ay details:first-of-type { border-top: 0; }
    .ay summary { cursor: pointer; list-style: none; padding: 10px 2px; display: flex; gap: 10px; align-items: baseline; }
    .ay summary::-webkit-details-marker { display: none; }
    .ay summary::before { content: "▸"; color: #888; flex: none; transition: transform .15s; }
    .ay details[open] > summary::before { transform: rotate(90deg); }
    .ay summary .tit { flex: 1; min-width: 0; }
    .ay summary .tit small { display: block; color: var(--gris); font-size: 12px; margin-top: 2px; }
    .ay summary .cif { flex: none; text-align: right; font-variant-numeric: tabular-nums; font-size: 14px; }
    .ay .dentro { padding: 0 0 10px 20px; }
    .ay .dentro details summary { padding: 8px 2px; font-size: 14px; }
    .ay .tabla, .fl .tabla { overflow-x: auto; }
    /* Dentro de un cuadro con desplazamiento el encabezado no se fija bajo el menu (tapaba la primera fila). */
    .ay th, .fl th { position: static; }
    .ay td.n, .ay th.n, .fl td.n, .fl th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .ay tfoot td { font-weight: 700; background: #eef1ee; }
    .ay .barra { display: inline-block; height: 8px; background: var(--verde); vertical-align: middle; margin-left: 6px; }
    .ay ol.visitas { margin: 4px 0 6px; padding-left: 20px; font-size: 14px; }
    .ay ol.visitas li { margin: 5px 0; }
    .ay ol.visitas .hora { font-variant-numeric: tabular-nums; color: var(--gris); }
    .ay tr.sin-geo td { background: var(--rojo-f); }
    .fl { --am: #8a6a00; --am-f: #fff4cc; --am-b: #e8c547; --ve: #1f6b34; --ve-f: #e3f2e6; --ve-b: #6fbf83;
          --ro: #b3261e; --ro-f: #fdecea; --ro-b: #e98f88; --gr: #5d6660; --gr-f: #eceeed; --gr-b: #b9c0bb; }
    .fl .conteo { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
    .fl .conteo button { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 999px; font: inherit; font-weight: 600; font-size: 13px; border: 1px solid; cursor: pointer; }
    .fl .conteo button b { font-size: 15px; font-variant-numeric: tabular-nums; }
    .fl .conteo button.activo { outline: 2px solid #1a1a1a; outline-offset: 1px; }
    .fl .amarillo { color: var(--am); background: var(--am-f); border-color: var(--am-b); }
    .fl .verde { color: var(--ve); background: var(--ve-f); border-color: var(--ve-b); }
    .fl .rojo { color: var(--ro); background: var(--ro-f); border-color: var(--ro-b); }
    .fl .gris { color: var(--gr); background: var(--gr-f); border-color: var(--gr-b); }
    .fl tr.grupo td { background: #eef1ee; font-weight: 700; font-size: 13px; color: #4a524c; }
    .fl tr.maquina { cursor: pointer; }
    .fl tr.maquina td:first-child { border-left: 5px solid transparent; }
    .fl tr.maquina.amarillo td:first-child { border-left-color: var(--am-b); }
    .fl tr.maquina.verde td:first-child { border-left-color: var(--ve-b); }
    .fl tr.maquina.rojo td:first-child { border-left-color: var(--ro-b); }
    .fl tr.maquina.gris td:first-child { border-left-color: var(--gr-b); }
    .fl tr.maquina, .fl tr.maquina td { color: #1a1a1a; background: transparent; }
    .fl tr.maquina:hover td { background: #f6f8f6; }
    .fl .nombre { background: none; color: inherit; border: 0; padding: 0; font: inherit; font-weight: 600; cursor: pointer; text-align: left; }
    .fl .flecha { display: inline-block; width: 1em; color: #777; transition: transform .15s; }
    .fl tr.abierta .flecha { transform: rotate(90deg); }
    .fl .estado { display: inline-block; padding: 3px 10px; border-radius: 999px; border: 1px solid; font-size: 13px; }
    .fl .chica { color: #666; font-size: 12px; }
    .fl tr.detalle > td { background: #f5f6f7; padding: 10px 12px 14px; }
    .fl .detalle h4 { margin: 0 0 8px; font-size: 13px; }
    .fl .detalle th, .fl .detalle td { font-size: 13px; }
    .fl .sin { color: var(--ro); font-weight: 600; }
    .fl .gps { background: #fff3e0; border: 2px solid #e8892b; border-radius: 10px; padding: 12px 14px; margin-bottom: 12px; }
    .fl .gps h3 { margin: 0 0 6px; font-size: 15px; color: #8a4500; }
    .fl .gps .item { padding: 6px 0; border-top: 1px solid #f3cf9f; font-size: 13px; }
    .fl .gps .item:first-of-type { border-top: none; }
    .fl details.alertas { background: var(--ro-f); border: 2px solid var(--ro-b); border-radius: 10px; margin-top: 12px; }
    .fl details.alertas summary { cursor: pointer; padding: 12px 14px; color: var(--ro); font-weight: 700; font-size: 15px; }
    .fl details.alertas .tabla { margin: 0 10px 10px; background: #fff; border-radius: 8px; }
    @media (prefers-reduced-motion: reduce) { .ay summary::before, .fl .flecha { transition: none; } }
    /* Celular: cada fila de tabla como tarjeta (sin mover hacia el lado). */
    @media (max-width: 600px) {
      .ay .tabla, .fl .tabla { overflow-x: visible; }
      table.resp thead { display: none; }
      table.resp, table.resp tbody, table.resp tfoot, table.resp tr { display: block; width: 100%; }
      table.resp tr { border: 1px solid var(--borde); border-radius: 8px; margin: 0 0 8px; padding: 6px 10px; background: #fff; }
      table.resp tfoot tr { background: #eef1ee; }
      table.resp td { display: block; border: 0; padding: 3px 0; text-align: left !important; white-space: normal !important; }
      table.resp td.n { display: inline-block; min-width: 31%; margin-right: 6px; vertical-align: top; }
      table.resp td[data-label]:not([data-label=""])::before { content: attr(data-label); display: block; font-size: 11px;
        font-weight: 600; color: var(--gris); text-transform: uppercase; letter-spacing: .02em; }
      table.resp td:empty { display: none; }
      .ay table.resp tr.sin-geo { background: var(--rojo-f); } .ay table.resp tr.sin-geo td { background: none; }
      .fl table.resp tr.grupo { border: 0; padding: 0; background: none; margin: 12px 0 4px; }
      .fl table.resp tr.grupo td { background: none; padding: 0; }
      .fl table.resp tr.maquina td:first-child { border-left: 0; }
      .fl table.resp tr.maquina { border-left: 5px solid var(--gr-b); }
      .fl table.resp tr.maquina.amarillo { border-left-color: var(--am-b); } .fl table.resp tr.maquina.verde { border-left-color: var(--ve-b); }
      .fl table.resp tr.maquina.rojo { border-left-color: var(--ro-b); }
      .fl table.resp tr.detalle { padding: 0; border: 0; background: none; }
      .fl table.resp tr.detalle > td { padding: 8px; border-radius: 8px; }
    }`;
  document.head.appendChild(estilo);

  // Celular: cada celda lleva el titulo de su columna (las tablas se ven como tarjetas).
  function tablasMovil(raiz) {
    if (!raiz) return;
    raiz.querySelectorAll('table').forEach(t => {
      t.classList.add('resp');
      const ths = [...t.querySelectorAll(':scope > thead th')].map(th => th.textContent.trim());
      t.querySelectorAll(':scope > tbody > tr, :scope > tfoot > tr').forEach(tr => {
        let i = 0;
        [...tr.cells].forEach(td => { if (!td.hasAttribute('data-label')) td.setAttribute('data-label', td.colSpan > 1 ? '' : (ths[i] || '')); i += td.colSpan; });
      });
    });
  }

  // =========================================================================
  // Ayer
  // =========================================================================
  const AY = { q: '' };

  function alarmasDeAyer(d) {
    return (d.alarmas_labor || []).filter(a => a.fecha === d.fecha).map(a => a.tipo === 'Trabajo sin hectáreas'
      ? `<b>Trabajo sin hectáreas:</b> ${esc(a.maquina)} – ${n(a.horas)} h en ${esc(a.cuartel)} (${esc(a.labor)}) y 0 ha${a.motivo ? ': ' + esc(a.motivo) : ''}`
      : `<b>Alarma de labor (${esc(a.tipo)}):</b> ${esc(a.maquina)} – ${esc(a.labor)} en ${esc(a.cuartel)}, ${a.no_suma ? '~' : ''}${n(a.ha, 2)} ha${a.no_suma ? ' (no suma hasta definir la labor)' : ''}`);
  }

  function resumen(d, v) {
    const r = d.resumen;
    const grande = (v.alerta_grande || []).length ? `<div class="alerta-grande"><b>⚠ Máquinas en campo sin señal GPS (más de 15 días)</b><br>` +
      v.alerta_grande.map(a => `${esc(a.maquina)} – en ${esc(a.campo_planilla)} · sin señal hace ${a.dias_sin_senal} días ${mapa(a.mapa)}`).join('<br>') + '</div>' : '';
    const senal = d.alertas.sin_senal.length ? d.alertas.sin_senal.map(x => `${esc(x.maquina)} (desde ${esc((x.ultima_conexion || '').slice(0, 5))}${x.ubicacion ? ', ' + esc(x.ubicacion) : ''}) ${mapa(x.mapa)}`).join('; ') : 'ninguna';
    const sinGeo = (v.maquinas_ayer || []).filter(m => m.sin_geocerca).map(m => `${esc(m.maquina)} (~${n(m.ha_sin)} ha${m.posible ? ', probable ' + esc(m.posible) : ''})`).join('; ') || 'ninguno';
    const alarmas = alarmasDeAyer(d).map(a => `<div class="alerta">${a}</div>`).join('');
    return grande + `<section id="ayer-resumen"><h2>Resumen de ayer (${esc(d.fecha_texto)})</h2>
      <div class="tarjetas">
        <div class="tarjeta"><b>${r.maquinas} de ${r.total_maquinas}</b><span>máquinas trabajaron</span></div>
        <div class="tarjeta"><b>${n(r.ha, 2)} ha</b><span>en geocercas${r.ha_sin ? ` <span class="estim">+ ~${n(r.ha_sin)} ha sin geocerca</span>` : ''}</span></div>
        <div class="tarjeta"><b>${n(r.horas)} h</b><span>de las máquinas</span></div>
        <div class="tarjeta"><b>${n(r.km_camionetas, 0)} km</b><span>camionetas (${r.camionetas_movidas} de ${r.total_camionetas}) · ${n(r.km_camion, 0)} km camión</span></div>
      </div>
      <div class="alerta"><b>GPS sin señal:</b> ${senal}</div>
      <div class="alerta"><b>Trabajo sin geocerca ayer:</b> ${sinGeo}</div>
      ${alarmas}
      <p class="nota">No trabajaron ayer: ${r.no_trabajaron} máquinas — ${r.en_cyh} en CYH, ${r.detenidas_fuera} detenidas fuera de CYH y ${r.sin_senal_30} sin señal hace más de 30 días (<a href="#flota">ver en Flota</a>).</p>
    </section>`;
  }

  function maquinasAyer(v) {
    const lista = (v.maquinas_ayer || []).filter(m => !AY.q.trim() || calza(m.maquina, AY.q) || [m.geocercas, m.posible, m.operador, m.labor].some(t => sinT(t).includes(sinT(AY.q.trim()))));
    const filas = lista.map(m =>
      `<tr${m.sin_geocerca || m.no_cyh ? ' class="sin-geo"' : ''}><td>${esc(m.maquina)}${m.no_cyh ? '<br><small style="color:var(--rojo)">No es de CYH (por revisar)</small>' : ''}</td><td>${esc(m.labor)}</td><td>${esc(m.operador || '–')}</td>` +
      `<td>${esc(m.geocercas || '')}${m.sin_geocerca ? `${m.geocercas ? '<br>' : ''}<span class="estim">sin geocerca${m.posible ? ' · posiblemente ' + esc(m.posible) : ''}</span>` : ''}</td>` +
      `<td class="n">${n(m.horas)}</td><td class="n">${haTxt(m.ha, m.ha_sin)}</td></tr>`).join('');
    const nuestras = (v.maquinas_ayer || []).filter(m => !m.no_cyh);
    return `<section id="ayer-maquinas"><h2>Máquinas que trabajaron ayer</h2>
      <input class="buscador" style="width:100%;margin-bottom:8px" type="search" placeholder="Buscar máquina, operador o campo" value="${esc(AY.q)}" oninput="SeccionAyer.buscar(this.value)">
      <div class="tabla" id="ayerMaquinasTabla"><table>
      <thead><tr><th>Máquina</th><th>Labor</th><th>Operador</th><th>Dónde</th><th class="n">Horas</th><th class="n">Ha</th></tr></thead>
      <tbody>${filas || '<tr><td colspan="6" class="vacio">Ninguna.</td></tr>'}</tbody>
      <tfoot><tr><td colspan="4">Total (sin las que no son de CYH)</td><td class="n">${n(nuestras.reduce((t, m) => t + m.horas, 0))}</td><td class="n">${haTxt(nuestras.reduce((t, m) => t + m.ha, 0), nuestras.reduce((t, m) => t + m.ha_sin, 0))}</td></tr></tfoot></table></div>
      <p class="nota">Entre paréntesis y en rojo, las hectáreas estimadas sin geocerca (horas × rendimiento real de la máquina). El día a día de cada máquina (30 días) está en <a href="#flota">Flota</a>.</p></section>`;
  }

  function diaVehiculo(x, recorrido) {
    if (!x.se_movio) return `<details><summary><span class="tit">${fc(x.fecha)} · 0 km<small>No se movió${x.donde_quedo ? ' · en ' + esc(x.donde_quedo) : ''}</small></span></summary></details>`;
    const visitas = x.visitas.map(v => `<li><span class="hora">${esc(v.llegada)}</span> ${v.tipo === 'campo' ? `<b>${esc(v.nombre)}</b>${v.detalle && v.detalle !== v.nombre ? ` (${esc(v.detalle)})` : ''}` : esc(v.nombre)} · ${minTxt(v.minutos)} ${mapa(v.mapa)}</li>`).join('');
    return `<details><summary><span class="tit">${fc(x.fecha)} · ${n(x.km)} km · ${esc(x.salida || '')}–${esc(x.llegada || '')}<small>${lugaresTxt(x.lugares, recorrido ? ' → ' : ' · ') || 'camino'}</small></span></summary>
      <div class="dentro"><ol class="visitas">${visitas || '<li>Solo camino (sin paradas largas).</li>'}</ol></div></details>`;
  }

  function vehiculos(id, titulo, lista, recorrido, fecha) {
    const html = lista.map(v => {
      const ayer = v.dias.find(x => x.fecha === fecha);
      const ayerTxt = !ayer ? 'ayer sin dato' : ayer.se_movio ? `ayer ${n(ayer.km)} km · ${lugaresTxt(ayer.lugares, recorrido ? ' → ' : ' · ') || 'camino'}` : 'ayer no se movió';
      return `<details><summary><span class="tit">${esc(v.nombre)}<small>${ayerTxt}</small></span>
        <span class="cif">${n(v.km)} km<small class="nota" style="display:block;margin:0">7 días</small></span></summary><div class="dentro">${v.dias.slice().reverse().map(x => diaVehiculo(x, recorrido)).join('')}</div></details>`;
    }).join('');
    const total = lista.reduce((t, v) => t + v.km, 0);
    return `<section id="${id}"><h2>${titulo}</h2>${html || '<p class="vacio">Sin datos.</p>'}
      <p class="nota">Total 7 días: <b>${n(total)} km</b>. Al tocar un día: los lugares en orden, con hora de llegada, tiempo ahí y mapa. En negrita, los campos (geocercas); en texto normal, las comunas donde se detuvo 15 min o más.</p></section>`;
  }

  function semana(d) {
    const max = Math.max(...d.semana.map(x => x.ha), 0);
    const filas = d.semana.map(x => `<tr><td>${fc(x.fecha)}</td><td class="n">${x.maquinas}</td><td class="n">${n(x.ha, 2)}${x.ha_sin ? ` <span class="estim">~${n(x.ha_sin)}</span>` : ''}${max ? `<span class="barra" style="width:${Math.round(40 * x.ha / max)}px"></span>` : ''}</td><td class="n">${n(x.horas)}</td><td class="n">${n(x.km_camionetas, 0)}</td><td class="n">${n(x.km_camion, 0)}</td></tr>`).join('');
    const s = k => d.semana.reduce((t, x) => t + x[k], 0);
    const campos = (d.campos || []).map(c => `<tr><td>${esc(c.campo)}</td><td>${esc(c.labores.join(', '))}</td><td class="n">${n(c.ha, 2)}</td><td class="n">${c.terminados}</td></tr>`).join('');
    return `<section id="ayer-semana"><h2>Últimos 7 días</h2>
      <div class="tarjetas">
        <div class="tarjeta"><b>${n(s('ha'), 2)} ha</b><span>en geocercas${s('ha_sin') ? ` <span class="estim">+ ~${n(s('ha_sin'))} ha sin geocerca</span>` : ''}</span></div>
        <div class="tarjeta"><b>${n(s('horas'))} h</b><span>de las máquinas</span></div>
        <div class="tarjeta"><b>${n(s('km_camionetas'), 0)} km</b><span>camionetas · ${n(s('km_camion'), 0)} km camión</span></div>
      </div>
      <div class="tabla"><table style="margin-top:10px"><thead><tr><th>Día</th><th class="n">Máq.</th><th class="n">Ha</th><th class="n">Horas</th><th class="n">Km cam.</th><th class="n">Km camión</th></tr></thead>
        <tbody>${filas}</tbody><tfoot><tr><td>Total</td><td></td><td class="n">${haTxt(s('ha'), s('ha_sin'))}</td><td class="n">${n(s('horas'))}</td><td class="n">${n(s('km_camionetas'), 0)}</td><td class="n">${n(s('km_camion'), 0)}</td></tr></tfoot></table></div>
      ${campos ? `<details style="margin-top:8px"><summary><span class="tit">Avance por campo (7 días)</span></summary><div class="dentro"><div class="tabla"><table><thead><tr><th>Campo</th><th>Labores</th><th class="n">Ha</th><th class="n">Terminados</th></tr></thead><tbody>${campos}</tbody></table></div></div></details>` : ''}
    </section>`;
  }

  window.SeccionAyer = {
    // full = reporte_v2.json completo (lo del correo + v2).
    html(full, actualizado) {
      if (!full || !full.resumen || !full.v2) return '<h1>Ayer</h1><section><p class="vacio">Todavía no hay datos de ayer publicados.</p></section>';
      const d = full, v = full.v2;
      return `<div class="ay"><h1>Ayer</h1><div class="sub">${esc(d.fecha_texto)} · datos de ${esc(v.actualizado || d.generado || '')}${actualizado ? ' · ' + actualizado : ''}</div>
        ${resumen(d, v)}${maquinasAyer(v)}
        ${vehiculos('ayer-camionetas', 'Camionetas', d.camionetas || [], false, d.fecha)}${vehiculos('ayer-camion', 'Camión', d.camion || [], true, d.fecha)}
        ${semana(d)}
        <p class="nota">Operadores y trabajo por campo de la temporada: por ahora en la <a href="reporte2.html#operadores">página anterior</a> (pasan a Historial en la etapa 3).</p></div>`;
    },
    despues(raiz) { tablasMovil(raiz); },
    buscar(q) {
      AY.q = q;
      const caja = document.getElementById('ayerMaquinasTabla');
      if (!caja || !window.SeccionAyer._full) return;
      const tmp = document.createElement('div'); tmp.innerHTML = maquinasAyer(window.SeccionAyer._full.v2);
      caja.innerHTML = tmp.querySelector('#ayerMaquinasTabla').innerHTML;
      tablasMovil(caja);
    },
  };

  // =========================================================================
  // Flota (GPS)
  // =========================================================================
  const ETIQUETA = { amarillo: 'En CYH', verde: 'En geocerca', rojo: 'Sin geocerca (7 días)', gris: 'Detenida / sin señal' };
  const FL = { q: '', estado: '', abiertas: new Set() };
  const fechaCorta = iso => { const [a, m, d] = iso.split('-'); return `${d}-${m}`; };
  const ha2 = v => n(v, 2);
  const horaDe = t => t ? new Date(t * 1000).toLocaleString('es-CL', { timeZone: 'America/Santiago', hour: '2-digit', minute: '2-digit' }) : '';
  const mapaDe = (lat, lon) => `https://www.google.com/maps?q=${lat},${lon}`;

  function detalle(m) {
    const horometro = m.horometro ? ` · horómetro según Wialon: ${m.horometro.toLocaleString('es-CL', { maximumFractionDigits: 1 })} h` : '';
    const dias = (m.dias || []).filter(d => !d.sin_datos).slice().reverse();
    if (!dias.length) return `<h4>${esc(m.nombre)} · últimos 30 días${horometro}</h4><p class="chica">Sin datos GPS en los últimos 30 días.</p>`;
    const filas = dias.map(d => {
      const horasGeo = d.horas_geocercas || {}, haGeo = d.ha || {}, sin = d.sin_geocerca || [];
      const geos = [...new Set([...Object.keys(horasGeo), ...Object.keys(haGeo)])].sort();
      const lugares = geos.map(g => {
        const h = horasGeo[g], v = haGeo[g];
        return `${esc(g)} <span class="chica">${h ? n(h) + ' h' : ''}${h && v ? ' · ' : ''}${v ? ha2(v) + ' ha' : ''}</span>`;
      });
      sin.forEach(x => lugares.push(`<span class="sin">Sin geocerca</span> <span class="chica">${n(x.horas)} h · ${n(x.ha)} ha</span> · ${mapa(x.mapa)}`));
      const horas = Object.values(horasGeo).reduce((t, h) => t + h, 0) + sin.reduce((t, x) => t + x.horas, 0);
      const hect = Object.values(haGeo).reduce((t, v) => t + v, 0) + sin.reduce((t, x) => t + x.ha, 0);
      const quedo = d.fin ? `${mapa(mapaDe(d.fin.lat, d.fin.lon), esc(d.fin.lugar || 'Fuera de geocercas'))} <span class="chica">${horaDe(d.fin.t)}</span>` : '—';
      return `<tr><td class="n">${fechaCorta(d.fecha)}</td><td>${lugares.join('<br>') || '<span class="chica">Sin trabajo en geocercas</span>'}</td>` +
        `<td>${esc(d.labor || m.labor)}</td><td class="n">${horas ? n(horas) + ' h' : '—'}</td><td class="n">${hect ? ha2(hect) + ' ha' : '—'}</td><td>${quedo}</td></tr>`;
    }).join('');
    return `<h4>${esc(m.nombre)} · últimos 30 días${horometro}</h4><div class="tabla"><table>` +
      `<thead><tr><th class="n">Día</th><th>Dónde trabajó</th><th>Labor</th><th class="n">Horas</th><th class="n">Hectáreas</th><th>Dónde quedó</th></tr></thead>` +
      `<tbody>${filas}</tbody></table></div>`;
  }

  function filasLista(f) {
    const q = FL.q.trim();
    let grupo = null, html = '';
    f.maquinas.forEach((m, i) => {
      if (FL.estado && m.estado !== FL.estado) return;
      // Con numeros se busca solo en el nombre ("10" no debe encontrar fechas como 10-10).
      if (q && !calza(m.nombre, q) && (/\d/.test(q) || ![m.labor, m.texto, m.ubicacion].some(t => sinT(t).includes(sinT(q))))) return;
      if (m.grupo !== grupo) { grupo = m.grupo; html += `<tr class="grupo"><td colspan="6">${esc(grupo)}</td></tr>`; }
      const abierta = FL.abiertas.has(m.nombre);
      html += `<tr class="maquina ${esc(m.estado)}${abierta ? ' abierta' : ''}" data-i="${i}"><td data-label=""><button type="button" class="nombre" aria-expanded="${abierta}"><span class="flecha">▸</span>${esc(m.nombre)}</button></td>` +
        `<td data-label="Labor">${esc(m.labor)}</td><td data-label="Estado"><span class="estado ${esc(m.estado)}">${esc(m.texto)}</span></td><td data-label="Ubicación">${m.mapa ? mapa(m.mapa, esc(m.ubicacion)) : '—'}</td>` +
        `<td class="n" data-label="Última conexión">${esc(m.ultima_conexion || '—')}</td>` +
        `<td class="n" data-label="Horómetro">${m.horometro ? m.horometro.toLocaleString('es-CL', { maximumFractionDigits: 1 }) + ' h' : '—'}</td></tr>` +
        (abierta ? `<tr class="detalle"><td colspan="6" data-label=""><div class="detalle">${detalle(m)}</div></td></tr>` : '');
    });
    return html || '<tr><td colspan="6" class="vacio">Ninguna máquina para este filtro.</td></tr>';
  }

  function dibujarLista() {
    const f = window.SeccionFlota._datos, cuerpo = document.getElementById('flotaLista');
    if (!f || !cuerpo) return;
    cuerpo.innerHTML = filasLista(f);
    tablasMovil(cuerpo.closest('.fl'));
    document.querySelectorAll('.fl .conteo button').forEach(b => b.classList.toggle('activo', b.dataset.estado === FL.estado));
  }

  window.SeccionFlota = {
    _datos: null,
    html(f) {
      this._datos = f;
      if (!f) return '<h1>Flota (GPS)</h1><section><p class="vacio">Todavía no hay datos de la flota: aparecen después de la próxima corrida.</p></section>';
      const gps = (f.alertas_sin_senal || []).length ? `<div class="gps"><h3>⚠ GPS sin señal (más de ${f.horas_sin_senal} horas): revisar el equipo</h3>` +
        f.alertas_sin_senal.map(a => `<div class="item"><b>${esc(a.maquina)}</b> · última señal ${esc(a.ultima_conexion)} · ${a.mapa ? mapa(a.mapa, esc(a.ubicacion || 'última ubicación')) : 'sin ubicación'}</div>`).join('') + '</div>' : '';
      const cuentas = { amarillo: 0, verde: 0, rojo: 0, gris: 0 };
      f.maquinas.forEach(m => cuentas[m.estado]++);
      const conteo = ['verde', 'rojo', 'amarillo', 'gris'].map(e => `<button type="button" class="${e}${FL.estado === e ? ' activo' : ''}" data-estado="${e}" onclick="SeccionFlota.estado('${e}')"><b>${cuentas[e]}</b> ${ETIQUETA[e]}</button>`).join('');
      const sin = f.sin_geocerca_30_dias || [];
      const filasSin = sin.map(a => `<tr><td><b>${esc(a.maquina)}</b></td><td>${esc(a.labor)}</td><td class="n">${fechaCorta(a.primera_fecha)} a ${fechaCorta(a.ultima_fecha)}</td>` +
        `<td class="n">${a.dias_trabajados}</td><td class="n">${n(a.horas)} h</td><td class="n">${n(a.ha_aprox)} ha</td><td>${mapa(a.mapa)}</td></tr>`).join('') ||
        '<tr><td colspan="7">No hay máquinas trabajando fuera de geocercas en los últimos 30 días.</td></tr>';
      return `<div class="fl"><h1>Flota (GPS)</h1>
        <div class="sub">${f.maquinas.length} máquinas · actualizado el ${esc(f.actualizado)} (cada 4 horas). Toca una máquina para ver sus últimos 30 días.</div>
        ${gps}
        <section><div class="conteo">${conteo}</div>
          <input class="buscador" style="width:100%;margin-bottom:8px" type="search" placeholder="Buscar máquina, labor o lugar (ej. 10, Aurora)" value="${esc(FL.q)}" oninput="SeccionFlota.buscar(this.value)">
          <div class="tabla"><table><thead><tr><th>Máquina</th><th>Labor</th><th>Estado</th><th>Ubicación</th><th class="n">Última conexión</th><th class="n">Horómetro</th></tr></thead>
          <tbody id="flotaLista">${filasLista(f)}</tbody></table></div>
          <p class="nota">Toca un color para ver solo esas máquinas (otra vez para verlas todas). Verde: trabajó hoy o ayer en geocercas · rojo: trabajó sin geocerca en los últimos 7 días · amarillo: en CYH · gris: detenida o sin señal.</p></section>
        <details class="alertas"><summary>Ver máquinas sin geocerca de los últimos 30 días (${sin.length})</summary>
          <div style="margin:0 14px 8px;font-size:12px;color:#7a2a24">Trabajo en hileras (no traslados), mínimo 1 hora por día. Al crear la geocerca en Wialon, ese trabajo se recupera y la alerta desaparece.</div>
          <div class="tabla"><table><thead><tr><th>Máquina</th><th>Labor</th><th class="n">Fechas</th><th class="n">Días</th><th class="n">Horas</th><th class="n">Hectáreas aprox.</th><th>Mapa</th></tr></thead>
          <tbody>${filasSin}</tbody></table></div></details></div>`;
    },
    despues(raiz) {
      tablasMovil(raiz);
      const cuerpo = document.getElementById('flotaLista');
      if (cuerpo) cuerpo.onclick = ev => {
        if (ev.target.closest('a')) return;
        const fila = ev.target.closest('tr.maquina');
        if (!fila) return;
        const m = this._datos.maquinas[fila.dataset.i];
        if (FL.abiertas.has(m.nombre)) FL.abiertas.delete(m.nombre); else FL.abiertas.add(m.nombre);
        dibujarLista();
      };
    },
    buscar(q) { FL.q = q; dibujarLista(); },
    estado(e) { FL.estado = FL.estado === e ? '' : e; dibujarLista(); },
  };
})();
