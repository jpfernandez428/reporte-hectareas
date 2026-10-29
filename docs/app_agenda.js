// Agenda de trabajos (pestaña "Agenda" de Operacion en app.html; pedido del
// usuario 29-oct-2026, reglas en CLAUDE.md "Agenda de trabajos").
// Cada trabajo: campo, labor, inicio y termino aproximado, hectareas o
// cuarteles, que se necesita (tipo y cantidad de maquinas), estado (por
// confirmar -> confirmado -> en curso -> terminado), notas, y las maquinas y
// operadores exactos cuando se asignan.
// - Termino automatico: hectareas ÷ rendimiento real (ha por dia trabajado de
//   esas maquinas en esa labor, temporada; reporte_v2.json -> trabajo_campo),
//   en dias de lunes a sabado. Con el avance real (hectareas del historial y
//   ~ha sin geocerca del campo desde el inicio) la fecha se corre sola y avisa
//   "atrasado X dias". Se puede poner a mano.
// - Vistas Mes, Semana y Por maquina; avisos (parte en 2 dias o menos sin
//   asignar, choques, atrasados); sugerencias en Operacion (mover maquinas al
//   campo el dia de inicio, marcar terminado).
// - Guardar: Worker /agenda con el PIN (D1 al instante si esta; si no, GitHub
//   agenda.yml). Si el Worker no responde, queda en este aparato y se reintenta.
// Usa las funciones de app.html (elegir, nombreCampo, calzaCampo, valorDe, ...).
// Hacia afuera solo window.Agenda.
(function () {
  const DIAS_CORTOS = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom'];
  const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  const ESTADOS = { por_confirmar: 'Por confirmar', confirmado: 'Confirmado', en_curso: 'En curso', terminado: 'Terminado' };
  const hoy = () => new Date().toLocaleDateString('en-CA', { timeZone: 'America/Santiago' });
  const dt = iso => { const [a, m, d] = iso.split('-').map(Number); return new Date(Date.UTC(a, m - 1, d)); };
  const iso = d => d.toISOString().slice(0, 10);
  const mas = (f, n) => { const d = dt(f); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
  const entre = (a, b) => Math.round((dt(b) - dt(a)) / 86400000);
  const diaSemana = f => (dt(f).getUTCDay() + 6) % 7;  // 0 = lunes
  const lunes = f => mas(f, -diaSemana(f));
  const dm = f => f ? `${f.slice(8, 10)}-${f.slice(5, 7)}` : '';
  const dmLargo = f => f ? `${DIAS_CORTOS[diaSemana(f)]} ${dm(f)}` : '';
  const num = (v, d = 1) => Number(v || 0).toLocaleString('es-CL', { minimumFractionDigits: d, maximumFractionDigits: d });
  const haDe = t => Number(String(t.ha || '').replace(',', '.')) || 0;
  // n dias de trabajo (lunes a sabado) contando desde f si es dia de trabajo; devuelve el ultimo.
  function finTrabajo(f, n) {
    let d = f, k = 0;
    if (n <= 0) return f;
    for (;;) { if (diaSemana(d) !== 6) { k++; if (k >= n) return d; } d = mas(d, 1); }
  }

  const estilo = document.createElement('style');
  estilo.textContent = `
    .ag-barra { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }
    .ag-nav { display: inline-flex; align-items: center; gap: 4px; }
    .ag-nav button { border: 1px solid #cfe0d1; background: #fff; color: var(--verde); border-radius: 8px; padding: 6px 11px; font-weight: 700; cursor: pointer; }
    .ag-nav b { min-width: 9em; text-align: center; font-size: 14px; }
    .ag-nuevo { border: 0; background: var(--verde); color: #fff; border-radius: 8px; padding: 8px 14px; font-weight: 700; cursor: pointer; }
    .ag-avisos { margin-bottom: 10px; }
    .ag-aviso { background: var(--rojo-f); border-left: 4px solid var(--rojo); padding: 7px 10px; margin: 4px 0; font-size: 13px; border-radius: 4px; cursor: pointer; }
    .ag-aviso.am { background: var(--amarillo-f); border-left-color: #e8c547; }
    .ag-local { background: var(--amarillo-f); border: 1px solid #e8c547; border-radius: 8px; padding: 8px 10px; font-size: 13px; margin-bottom: 10px; }
    /* Colores por estado */
    .ag-c-en_curso { --c: #1a5fb4; --cf: #dfeafd; } .ag-c-confirmado { --c: #1f6b34; --cf: #e3f2e6; }
    .ag-c-amarillo { --c: #8a6a00; --cf: #fff4cc; } .ag-c-terminado { --c: #5d6660; --cf: #eceeed; }
    .ag-c-choque { --c: #b3261e; --cf: #fdecea; }
    /* Mes */
    .ag-mes { border: 1px solid var(--borde); border-radius: 8px; overflow: hidden; }
    .ag-cab, .ag-sem { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); }
    .ag-cab div { font-size: 11px; font-weight: 700; color: var(--gris); text-align: center; padding: 4px 0; background: #eef1ee; text-transform: uppercase; }
    .ag-sem { border-top: 1px solid var(--borde); grid-auto-rows: min-content; min-height: 64px; position: relative; }
    .ag-dia { grid-row: 1; font-size: 12px; padding: 3px 5px; color: #333; border-left: 1px solid #f0f2f0; min-height: 22px; }
    .ag-dia:first-child { border-left: 0; }
    .ag-dia.fuera { color: #b7bdb9; } .ag-dia.hoy b { background: var(--verde); color: #fff; border-radius: 9px; padding: 0 5px; }
    .ag-dia.dom { background: #fafbfa; }
    .ag-b { margin: 1px 2px 2px; padding: 3px 6px; border-radius: 5px; background: var(--cf); color: var(--c); border-left: 4px solid var(--c);
            font-size: 12px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; border-top: 0; border-right: 0; border-bottom: 0; text-align: left; font-family: inherit; }
    .ag-b.cont-izq { border-top-left-radius: 0; border-bottom-left-radius: 0; border-left-style: dashed; }
    .ag-b.cont-der { border-top-right-radius: 0; border-bottom-right-radius: 0; }
    .ag-b .falta { color: #8a6a00; }
    /* Semana */
    .ag-semana .dia { border-top: 1px solid var(--borde); padding: 8px 0; }
    .ag-semana .dia:first-child { border-top: 0; }
    .ag-semana .dia > b { display: block; font-size: 13px; color: var(--verde); margin-bottom: 4px; }
    .ag-semana .dia.hoy > b::after { content: " · hoy"; color: var(--gris); font-weight: 400; }
    .ag-tarjeta { display: block; width: 100%; text-align: left; border: 0; border-left: 5px solid var(--c); background: var(--cf); border-radius: 8px; padding: 8px 10px; margin: 5px 0; cursor: pointer; font: inherit; color: #1a1a1a; }
    .ag-tarjeta b { color: var(--c); }
    .ag-tarjeta small { display: block; color: var(--gris); font-size: 12px; margin-top: 2px; }
    .ag-chip { display: inline-block; padding: 1px 7px; border-radius: 9px; font-size: 11px; font-weight: 700; background: #fff; color: var(--c); border: 1px solid var(--c); margin-left: 4px; }
    .ag-chip.am { color: #8a6a00; border-color: #e8c547; background: #fff4cc; } .ag-chip.ro { color: #b3261e; border-color: #e98f88; background: #fdecea; }
    /* Por maquina */
    .ag-pm { overflow-x: auto; border: 1px solid var(--borde); border-radius: 8px; }
    .ag-pm table { border-collapse: collapse; font-size: 12px; min-width: 100%; }
    .ag-pm th, .ag-pm td { border-bottom: 1px solid #eee; padding: 0; text-align: center; position: static; }
    .ag-pm th { background: #eef1ee; font-size: 11px; padding: 4px 2px; min-width: 30px; }
    .ag-pm th.dom, .ag-pm td.dom { background: #fafbfa; }
    .ag-pm th.hoy { background: var(--verde); color: #fff; }
    .ag-pm td.nom, .ag-pm th.nom { text-align: left; padding: 4px 8px; white-space: nowrap; position: sticky; left: 0; top: auto; background: #fff; z-index: 1; font-weight: 600; min-width: 130px; }
    .ag-pm th.nom { background: #eef1ee; }
    .ag-pm tr.sub td { background: #f5f6f7; font-weight: 700; text-align: left; padding: 4px 8px; color: var(--gris); }
    .ag-pm td.oc { background: var(--cf); border-left: 2px solid #fff; cursor: pointer; height: 26px; color: var(--c); font-weight: 700; font-size: 10px; overflow: hidden; max-width: 30px; }
    /* Hoja de detalle y formulario */
    .ag-hoja h3 { margin: 0 0 4px; font-size: 18px; color: var(--verde); }
    .ag-hoja .est { display: inline-block; padding: 2px 9px; border-radius: 9px; font-size: 12px; font-weight: 700; background: var(--cf); color: var(--c); border: 1px solid var(--c); }
    .ag-hoja .acciones-grandes { grid-template-columns: 1fr 1fr; }
    .ag-hoja .fila { display: grid; gap: 4px; margin: 10px 0; clear: both; }
    .ag-hoja .fila > span { font-size: 12px; font-weight: 700; color: var(--gris); text-transform: uppercase; }
    .ag-hoja .fila input, .ag-hoja .fila select, .ag-hoja .fila textarea { padding: 9px; font-size: 15px; border: 1px solid #ccc; border-radius: 8px; width: 100%; font-family: inherit; background: #fff; }
    .ag-hoja .dos { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .ag-hoja .elegido { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 9px; border: 1px solid #ccc; border-radius: 8px; background: #fff; cursor: pointer; font-size: 15px; text-align: left; font-family: inherit; width: 100%; }
    .ag-hoja .lista-x { display: flex; flex-wrap: wrap; gap: 6px; }
    .ag-hoja .lista-x span { background: var(--verde-f); border: 1px solid #cfe0d1; border-radius: 999px; padding: 4px 6px 4px 10px; font-size: 13px; }
    .ag-hoja .lista-x span.am { background: #fff4cc; border-color: #e8c547; color: #8a6a00; }
    .ag-hoja .lista-x button { border: 0; background: none; color: var(--rojo); font-weight: 700; cursor: pointer; padding: 0 4px; }
    .ag-hoja .mas { border: 1px dashed var(--verde); background: #fff; color: var(--verde); border-radius: 999px; padding: 4px 10px; font-weight: 600; cursor: pointer; }
    .ag-hoja .nec { display: grid; grid-template-columns: 70px 1fr 36px; gap: 6px; margin-bottom: 6px; }
    .ag-hoja .nec button { border: 0; background: #eee; border-radius: 8px; cursor: pointer; }
    .ag-hoja .msg { font-size: 13px; font-weight: 600; margin-top: 6px; }
    .ag-hoja .cuarteles { max-height: 40vh; overflow: auto; border: 1px solid #ddd; border-radius: 8px; padding: 6px 8px; }
    .ag-hoja .cuarteles label { display: block; padding: 4px 0; font-size: 14px; }
    .ag-hoja .borrar { background: #fff; color: var(--rojo); border: 1px solid var(--rojo); border-radius: 8px; padding: 9px 12px; font-weight: 700; cursor: pointer; }
    @media (min-width: 700px) { .hoja.ag-hoja { left: 50%; right: auto; width: 560px; transform: translateX(-50%); bottom: auto; top: 6vh; border-radius: 16px; max-height: 88vh; } }
    @media (max-width: 520px) { .ag-b { font-size: 10.5px; padding: 2px 3px; border-left-width: 3px; } .ag-dia { font-size: 11px; padding: 2px 3px; } }`;
  document.head.appendChild(estilo);

  // -------------------------------------------------------------------------
  // Datos: lo publicado (agenda.json), lo de D1 y lo que quedo en este aparato.
  // -------------------------------------------------------------------------
  // Este archivo se carga antes que el script de app.html: lo que corre al cargar usa sus propias funciones.
  const leerLS = (k, d) => { try { const v = JSON.parse(localStorage.getItem(k)); return v ?? d; } catch (e) { return d; } };
  const escribirLS = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* sin almacenamiento */ } };
  const CLAVE_PEND = 'agenda_pendientes';
  let PUB = {}, CAMBIOS_PUB = [], CAMBIOS_D1 = [], PEND = leerLS(CLAVE_PEND, []), GUARDADOS = new Set();
  const AG = { vista: leerLS('agenda_vista', innerWidth < 700 ? 'semana' : 'mes'), mes: hoy().slice(0, 7), semana: lunes(hoy()), sel: null };
  let AREAS = null;  // cuartel -> {area, campo} (geocercas.json, se baja al elegir cuarteles)

  function trabajos() {
    const t = { ...PUB };
    for (const p of PEND) { if (p.cuerpo.borrar) delete t[p.cuerpo.borrar]; else t[p.cuerpo.trabajo.id] = { ...p.cuerpo.trabajo, _pend: p }; }
    return Object.values(t).sort((a, b) => a.inicio.localeCompare(b.inicio) || a.campo.localeCompare(b.campo));
  }
  const pendDe = id => PEND.filter(p => (p.cuerpo.trabajo && p.cuerpo.trabajo.id === id) || p.cuerpo.borrar === id).pop();

  // -------------------------------------------------------------------------
  // Rendimiento real y avance (reporte_v2.json -> trabajo_campo, temporada)
  // -------------------------------------------------------------------------
  const filasTC = () => (V && V.trabajo_campo) || [];
  function tasaMaquina(m, labor) {
    let ha = 0, dias = 0;
    for (const f of filasTC()) if (f.maquina === m && f.labor === labor) { ha += f.ha + f.ha_sin; dias += f.dias; }
    return dias >= 2 ? ha / dias : null;
  }
  function tasaLabor(labor) {
    const ms = [...new Set(filasTC().filter(f => f.labor === labor).map(f => f.maquina))].map(m => tasaMaquina(m, labor)).filter(x => x);
    return ms.length ? ms.reduce((a, b) => a + b, 0) / ms.length : null;
  }
  const cantidadNecesaria = t => (t.necesita || []).reduce((s, x) => s + (Number(x.cantidad) || 0), 0);
  // Rendimiento del trabajo (ha por dia): las maquinas asignadas (sin datos, el promedio
  // de la labor); sin asignar, lo que se necesita × promedio de la labor.
  function tasaTrabajo(t) {
    const prom = tasaLabor(t.labor);
    if ((t.maquinas || []).length) {
      const v = t.maquinas.map(m => tasaMaquina(m, t.labor) || prom).filter(x => x);
      return v.length ? { tasa: v.reduce((a, b) => a + b, 0), base: `${t.maquinas.length} máquina${t.maquinas.length === 1 ? '' : 's'} asignada${t.maquinas.length === 1 ? '' : 's'}` } : null;
    }
    const n = cantidadNecesaria(t);
    return n && prom ? { tasa: n * prom, base: `${n} × promedio de ${t.labor} (${num(prom, 2)} ha/día)` } : null;
  }
  function avance(t) {
    let ha = 0, sin = 0;
    const dias = new Set(), q = new Set(t.cuarteles || []);
    for (const f of filasTC()) {
      if (f.labor !== t.labor || !calzaCampo(t.campo, f.campo) && !calzaCampo(f.campo, t.campo) && clave(f.campo) !== clave(t.campo)) continue;
      for (const d of f.detalle) {
        if (d.fecha < t.inicio || d.fecha > hoy()) continue;
        const cs = q.size ? d.cuarteles.filter(c => q.has(c.cuartel)) : d.cuarteles;
        const h = cs.reduce((s, c) => s + c.ha, 0);
        ha += h; if (!q.size) sin += d.sin || 0;
        if (h > 0 || (!q.size && d.sin > 0)) dias.add(d.fecha);
      }
    }
    return { ha, sin, dias: dias.size };
  }
  // Maquina asignada vista en el campo por el GPS (confirma la llegada).
  const enElCampo = (t, m) => { const g = gpsDe(m); return g.lugar && calzaCampo(t.campo, g.lugar) || (g.lugar && clave(g.lugar) === clave(t.campo)); };

  function calc(t) {
    const h = hoy(), prog = haDe(t), av = avance(t), tr = tasaTrabajo(t);
    const hecho = av.ha + av.sin;
    const auto = tr && prog ? finTrabajo(t.inicio, Math.max(1, Math.ceil(prog / tr.tasa))) : '';
    const plan = t.termino || auto || t.termino_previsto || t.inicio;
    let estimado = plan, atraso = 0;
    if (t.estado !== 'terminado' && h > t.inicio) {
      const resta = Math.max(0, prog - hecho);
      if (prog && tr && resta > 0) estimado = finTrabajo(h, Math.ceil(resta / tr.tasa));
      else if (prog && resta > 0 && h > plan) estimado = h;
      if (estimado > plan) atraso = entre(plan, estimado);
    }
    const fin = estimado > plan ? estimado : plan;
    let estado = t.estado;
    if ((estado === 'confirmado' || estado === 'por_confirmar') && h >= t.inicio && h <= fin &&
        (hecho > 0 || (t.maquinas || []).some(m => enElCampo(t, m)))) estado = 'en_curso';
    const nec = cantidadNecesaria(t), nm = (t.maquinas || []).length, no = (t.operadores || []).length;
    const faltanMaq = Math.max(0, nec - nm) || (!nec && !nm ? 1 : 0), faltanOp = Math.max(0, Math.max(nm, nec) - no);
    const pct = prog ? hecho / prog : 0;
    return { prog, hecho, ha: av.ha, sin: av.sin, dias: av.dias, tasa: tr, auto, plan, fin, atraso, estado, faltanMaq, faltanOp,
             falta: faltanMaq > 0 || faltanOp > 0, pct, listo: estado !== 'terminado' && ((prog && pct >= 0.95) || h > fin) };
  }
  const colorDe = (t, c) => c.estado === 'terminado' ? 'terminado' : c.estado === 'en_curso' ? 'en_curso' : (c.estado === 'por_confirmar' || c.falta) ? 'amarillo' : 'confirmado';

  // Choques: la misma maquina u operador en dos trabajos que se cruzan en fechas.
  function choques(lista) {
    const r = [];
    const activos = lista.map(t => ({ t, c: calc(t) })).filter(x => x.c.estado !== 'terminado');
    for (let i = 0; i < activos.length; i++) for (let j = i + 1; j < activos.length; j++) {
      const a = activos[i], b = activos[j];
      if (a.t.inicio > b.c.fin || b.t.inicio > a.c.fin) continue;
      const desde = a.t.inicio > b.t.inicio ? a.t.inicio : b.t.inicio, hasta = a.c.fin < b.c.fin ? a.c.fin : b.c.fin;
      for (const m of (a.t.maquinas || []).filter(x => (b.t.maquinas || []).includes(x))) r.push({ quien: m, tipo: 'máquina', a: a.t, b: b.t, desde, hasta });
      for (const o of (a.t.operadores || []).filter(x => (b.t.operadores || []).includes(x))) r.push({ quien: o, tipo: 'operador', a: a.t, b: b.t, desde, hasta });
    }
    return r;
  }
  const nombreT = t => `${nombreCampo(t.campo)} · ${t.labor || 'sin labor'}`;

  function avisos() {
    const lista = trabajos(), h = hoy(), r = [];
    for (const t of lista) {
      const c = calc(t);
      if (c.estado === 'terminado') continue;
      const faltan = entre(h, t.inicio);
      if (faltan >= 0 && faltan <= 2 && c.falta) r.push({ t, rojo: true, texto: `<b>${esc(nombreT(t))}</b> parte ${faltan === 0 ? 'hoy' : faltan === 1 ? 'mañana' : 'en 2 días'} (${dmLargo(t.inicio)}) y falta asignar ${[c.faltanMaq ? `${c.faltanMaq || ''} máquina${c.faltanMaq === 1 ? '' : 's'}` : '', c.faltanOp ? `${c.faltanOp} operador${c.faltanOp === 1 ? '' : 'es'}` : ''].filter(Boolean).join(' y ')}` });
      if (c.atraso > 0) r.push({ t, rojo: true, texto: `<b>${esc(nombreT(t))}</b> atrasado ${c.atraso} día${c.atraso === 1 ? '' : 's'}: termina ~${dmLargo(c.fin)} (programado ${dmLargo(c.plan)}); van ${num(c.hecho)} de ${num(c.prog)} ha` });
    }
    for (const x of choques(lista)) r.push({ t: x.a, rojo: true, texto: `Choque: ${x.tipo} <b>${esc(x.quien)}</b> en <b>${esc(nombreT(x.a))}</b> y <b>${esc(nombreT(x.b))}</b> (${dm(x.desde)}${x.hasta !== x.desde ? ' al ' + dm(x.hasta) : ''})` });
    return r;
  }

  // -------------------------------------------------------------------------
  // Vistas
  // -------------------------------------------------------------------------
  const etiquetaBarra = (t, c) => `${esc(nombreT(t))}${c.falta ? ' <span class="falta">· por asignar</span>' : ''}`;
  function activosEn(lista, desde, hasta) { return lista.map(t => ({ t, c: calc(t) })).filter(x => x.t.inicio <= hasta && x.c.fin >= desde); }

  function vistaMes() {
    const [a, m] = AG.mes.split('-').map(Number), primero = `${AG.mes}-01`, h = hoy();
    const ultimo = iso(new Date(Date.UTC(a, m, 0)));
    let html = '<div class="ag-mes"><div class="ag-cab">' + DIAS_CORTOS.map(d => `<div>${d}</div>`).join('') + '</div>';
    const lista = trabajos();
    for (let s = lunes(primero); s <= ultimo; s = mas(s, 7)) {
      const fin = mas(s, 6);
      html += '<div class="ag-sem">';
      for (let i = 0; i < 7; i++) {
        const f = mas(s, i);
        html += `<div class="ag-dia${f.slice(0, 7) !== AG.mes ? ' fuera' : ''}${f === h ? ' hoy' : ''}${i === 6 ? ' dom' : ''}" style="grid-column:${i + 1}"><b>${Number(f.slice(8))}</b></div>`;
      }
      // Cada barra en su carril (fila) para que no se tapen.
      const carriles = [];
      for (const { t, c } of activosEn(lista, s, fin)) {
        const ini = t.inicio < s ? s : t.inicio, ter = c.fin > fin ? fin : c.fin;
        const col = entre(s, ini) + 1, ancho = entre(ini, ter) + 1;
        let k = carriles.findIndex(fc => fc < col);
        if (k < 0) { carriles.push(0); k = carriles.length - 1; }
        carriles[k] = col + ancho - 1;
        const izq = t.inicio < s, der = c.fin > fin;
        html += `<button type="button" class="ag-b ag-c-${colorDe(t, c)}${izq ? ' cont-izq' : ''}${der ? ' cont-der' : ''}" style="grid-column:${col} / span ${ancho};grid-row:${k + 2}" onclick="Agenda.abrir('${t.id}')" title="${esc(nombreT(t))}">${izq ? '← ' : ''}${etiquetaBarra(t, c)}${der ? ' →' : ''}</button>`;
      }
      html += '</div>';
    }
    return html + '</div>';
  }

  function tarjeta(t, c, f) {
    const chips = [];
    if (c.falta) chips.push('<span class="ag-chip am">por asignar</span>');
    if (c.atraso) chips.push(`<span class="ag-chip ro">atrasado ${c.atraso} d</span>`);
    if (t._pend) chips.push('<span class="ag-chip am">sin enviar</span>');
    const dia = f ? (f === t.inicio ? 'empieza' : f === c.fin ? 'termina' : `día ${entre(t.inicio, f) + 1}`) : `${dmLargo(t.inicio)} al ~${dmLargo(c.fin)}`;
    const maq = (t.maquinas || []).length ? t.maquinas.join(', ') : '';
    return `<button type="button" class="ag-tarjeta ag-c-${colorDe(t, c)}" onclick="Agenda.abrir('${t.id}')"><b>${esc(nombreT(t))}</b>${chips.join('')}
      <small>${ESTADOS[c.estado]} · ${dia}${c.prog ? ` · ${num(c.hecho)} de ${num(c.prog)} ha` : ''}</small>
      ${maq || (t.operadores || []).length ? `<small>${esc(maq)}${(t.operadores || []).length ? ' · ' + esc(t.operadores.join(', ')) : ''}</small>` : ''}</button>`;
  }

  function vistaSemana() {
    const lista = trabajos(), h = hoy();
    let html = '<div class="ag-semana">';
    for (let i = 0; i < 7; i++) {
      const f = mas(AG.semana, i);
      const del = activosEn(lista, f, f);
      html += `<div class="dia${f === h ? ' hoy' : ''}"><b>${DIAS_CORTOS[i]} ${dm(f)}</b>${del.map(({ t, c }) => tarjeta(t, c, f)).join('') || '<span class="nota">Sin trabajos.</span>'}</div>`;
    }
    return html + '</div>';
  }

  function vistaPorMaquina() {
    const lista = trabajos(), h = hoy(), desde = AG.semana, dias = [...Array(14)].map((_, i) => mas(desde, i)), hasta = dias[13];
    const act = activosEn(lista, desde, hasta).filter(x => x.c.estado !== 'terminado' || true);
    const fila = (nombre, campo) => {
      let celdas = '';
      for (const f of dias) {
        const en = act.filter(x => (x.t[campo] || []).includes(nombre) && x.t.inicio <= f && x.c.fin >= f);
        if (!en.length) { celdas += `<td class="${diaSemana(f) === 6 ? 'dom' : ''}"></td>`; continue; }
        const choque = en.filter(x => x.c.estado !== 'terminado').length > 1;
        const x = en[0];
        celdas += `<td class="oc ag-c-${choque ? 'choque' : colorDe(x.t, x.c)}" title="${esc(en.map(y => nombreT(y.t)).join(' + '))}" onclick="Agenda.abrir('${x.t.id}')">${choque ? '2+' : ''}</td>`;
      }
      return `<tr><td class="nom">${esc(nombre)}</td>${celdas}</tr>`;
    };
    const maquinas = [...new Set(act.flatMap(x => x.t.maquinas || []))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    const operadores = [...new Set(act.flatMap(x => x.t.operadores || []))].sort();
    const sinAsignar = act.filter(x => x.c.faltanMaq > 0);
    let html = `<div class="ag-pm"><table><thead><tr><th class="nom">Máquina / operador</th>${dias.map(f => `<th class="${f === h ? 'hoy' : diaSemana(f) === 6 ? 'dom' : ''}">${DIAS_CORTOS[diaSemana(f)].slice(0, 2)}<br>${f.slice(8)}</th>`).join('')}</tr></thead><tbody>`;
    html += `<tr class="sub"><td colspan="15">Máquinas</td></tr>` + (maquinas.map(m => fila(m, 'maquinas')).join('') || '<tr><td class="nom" style="font-weight:400;color:var(--gris)">Ninguna asignada</td><td colspan="14"></td></tr>');
    if (sinAsignar.length) {
      html += `<tr class="sub"><td colspan="15">Por asignar</td></tr>` + sinAsignar.map(({ t, c }) =>
        `<tr><td class="nom" style="color:#8a6a00">${esc(nombreT(t))} · faltan ${c.faltanMaq}</td>${dias.map(f => t.inicio <= f && c.fin >= f ? `<td class="oc ag-c-amarillo" onclick="Agenda.abrir('${t.id}')"></td>` : `<td class="${diaSemana(f) === 6 ? 'dom' : ''}"></td>`).join('')}</tr>`).join('');
    }
    html += `<tr class="sub"><td colspan="15">Operadores</td></tr>` + (operadores.map(o => fila(o, 'operadores')).join('') || '<tr><td class="nom" style="font-weight:400;color:var(--gris)">Ninguno asignado</td><td colspan="14"></td></tr>');
    return html + '</tbody></table></div><p class="nota">En rojo (2+): la máquina u operador está en dos trabajos a la vez. Toca una celda para ver el trabajo.</p>';
  }

  function historialHtml() {
    const vistos = new Set(CAMBIOS_PUB.map(c => (c.id || '') + '|' + c.trabajo + '|' + c.cambio));
    const todos = CAMBIOS_PUB.concat(CAMBIOS_D1.filter(c => !vistos.has((c.id || '') + '|' + c.trabajo + '|' + c.cambio)).reverse());
    const filas = todos.slice().reverse().slice(0, 60).map(c => `<tr><td>${esc(c.fecha)}</td><td>${esc(c.trabajo)}</td><td>${esc(c.cambio)}</td><td>${esc(c.antes || '—')} → <b>${esc(c.despues || '—')}</b></td></tr>`).join('');
    return `<details style="margin-top:12px"><summary style="cursor:pointer;font-weight:700;color:var(--verde)">Historial de cambios de la Agenda (${todos.length})</summary>
      <div style="overflow-x:auto"><table><thead><tr><th>Fecha y hora</th><th>Trabajo</th><th>Qué cambió</th><th>Antes → después</th></tr></thead><tbody>${filas || '<tr><td colspan="4" class="vacio">Sin cambios todavía.</td></tr>'}</tbody></table></div></details>`;
  }

  function html() {
    const av = avisos(), sinEnviar = PEND.filter(p => !p.ok).length;
    const seg = (k, t) => `<button type="button" class="${AG.vista === k ? 'activo' : ''}" onclick="Agenda.vista('${k}')">${t}</button>`;
    const [a, m] = AG.mes.split('-').map(Number);
    const titulo = AG.vista === 'mes' ? `${MESES[m - 1]} ${a}` : `${dm(AG.semana)} al ${dm(mas(AG.semana, AG.vista === 'maquina' ? 13 : 6))}`;
    const cuerpo = AG.vista === 'mes' ? vistaMes() : AG.vista === 'semana' ? vistaSemana() : vistaPorMaquina();
    const vacia = !trabajos().length ? '<p class="nota" style="margin-top:10px">Todavía no hay trabajos programados. Toca "+ Nuevo trabajo" para agregar el primero.</p>' : '';
    return `<section class="ag">
      ${sinEnviar ? `<div class="ag-local">⚠ ${sinEnviar} cambio${sinEnviar === 1 ? '' : 's'} de la Agenda guardado${sinEnviar === 1 ? '' : 's'} solo en este aparato: Cloudflare no respondió${PEND.some(p => p.sinRuta) ? ' (si es la primera vez, falta pegar el Worker nuevo, <code>cloudflare/worker.js</code>)' : ''}. Se enviará${sinEnviar === 1 ? '' : 'n'} solo${sinEnviar === 1 ? '' : 's'}.</div>` : ''}
      ${av.length ? `<div class="ag-avisos">${av.map(x => `<div class="ag-aviso${x.rojo ? '' : ' am'}" onclick="Agenda.abrir('${x.t.id}')">${x.texto}</div>`).join('')}</div>` : ''}
      <div class="ag-barra"><span class="seg">${seg('mes', 'Mes')}${seg('semana', 'Semana')}${seg('maquina', 'Por máquina')}</span>
        <span class="ag-nav"><button type="button" onclick="Agenda.mover(-1)" aria-label="Anterior">‹</button><b>${titulo}</b><button type="button" onclick="Agenda.mover(1)" aria-label="Siguiente">›</button><button type="button" onclick="Agenda.irHoy()">Hoy</button></span>
        <button type="button" class="ag-nuevo" onclick="Agenda.editar()">+ Nuevo trabajo</button></div>
      ${cuerpo}${vacia}
      <p class="nota">Colores: <b style="color:#1a5fb4">azul</b> en curso · <b style="color:#1f6b34">verde</b> confirmado · <b style="color:#8a6a00">amarillo</b> por confirmar o falta asignar · gris terminado. Término aproximado: hectáreas ÷ rendimiento real (ha por día trabajado de esas máquinas en esa labor, temporada), de lunes a sábado; con el avance real se corre solo.</p>
      ${historialHtml()}</section>`;
  }

  // -------------------------------------------------------------------------
  // Detalle y formularios (hoja propia: no choca con la de Operacion ni con la lista con buscador)
  // -------------------------------------------------------------------------
  function capa() {
    let c = document.getElementById('capaAgenda');
    if (!c) { c = document.createElement('div'); c.id = 'capaAgenda'; document.body.appendChild(c); }
    return c;
  }
  function hoja(contenido, color) {
    capa().innerHTML = `<div class="hoja-fondo" onclick="Agenda.cerrar()"></div><div class="hoja ag-hoja ${color ? 'ag-c-' + color : ''}" role="dialog"><button type="button" class="cerrar" onclick="Agenda.cerrar()" aria-label="Cerrar">×</button>${contenido}</div>`;
  }
  const cerrar = () => { AG.sel = null; capa().innerHTML = ''; };
  const msg = (texto, error) => { const m = document.querySelector('#capaAgenda .msg'); if (m) { m.textContent = texto; m.style.color = error ? 'var(--rojo)' : 'var(--verde)'; } };

  function detalle(id) {
    const t = trabajos().find(x => x.id === id);
    if (!t) return cerrar();
    AG.sel = id;
    const c = calc(t), col = colorDe(t, c);
    const faltan = [c.faltanMaq ? `${c.faltanMaq} máquina${c.faltanMaq === 1 ? '' : 's'}` : '', c.faltanOp ? `${c.faltanOp} operador${c.faltanOp === 1 ? '' : 'es'}` : ''].filter(Boolean).join(' y ');
    const p = t._pend;
    hoja(`<h3>${esc(nombreT(t))}</h3>
      <div><span class="est">${ESTADOS[c.estado]}${c.estado !== t.estado ? ' (según el GPS)' : ''}</span>${c.atraso ? ` <span class="ag-chip ro">atrasado ${c.atraso} día${c.atraso === 1 ? '' : 's'}</span>` : ''}${p ? ' <span class="ag-chip am">sin enviar</span>' : ''}</div>
      <div class="dato"><span>Fechas</span><b>${dmLargo(t.inicio)} al ~${dmLargo(c.fin)}</b></div>
      ${c.atraso ? `<div class="dato"><span>Programado</span><span>hasta ${dmLargo(c.plan)}</span></div>` : ''}
      <div class="dato"><span>Término</span><span>${t.termino ? 'puesto a mano' : c.auto ? `automático (${c.tasa ? num(c.tasa.tasa, 2) + ' ha/día: ' + esc(c.tasa.base) : ''})` : 'sin rendimiento: ponlo a mano'}</span></div>
      <div class="dato"><span>Hectáreas</span><b>${num(c.ha, 2)}${c.sin ? ` <span style="color:var(--rojo)">+ ~${num(c.sin)}</span>` : ''} de ${c.prog ? num(c.prog, 2) : '?'} ha${c.prog ? ` (${Math.round(c.pct * 100)} %)` : ''}</b></div>
      ${(t.cuarteles || []).length ? `<div class="dato"><span>Cuarteles</span><span>${esc(t.cuarteles.join(', '))}</span></div>` : ''}
      <div class="dato"><span>Se necesita</span><span>${esc((t.necesita || []).map(x => `${x.cantidad} ${x.tipo}`).join(', ') || '—')}</span></div>
      <div class="dato"><span>Máquinas</span><span>${esc((t.maquinas || []).join(', ') || '')}${c.faltanMaq ? ` <span class="ag-chip am">faltan ${c.faltanMaq}</span>` : ''}</span></div>
      <div class="dato"><span>Operadores</span><span>${esc((t.operadores || []).join(', ') || '')}${c.faltanOp ? ` <span class="ag-chip am">faltan ${c.faltanOp}</span>` : ''}</span></div>
      ${t.notas ? `<div class="dato"><span>Notas</span><span>${esc(t.notas)}</span></div>` : ''}
      ${faltan ? `<p class="nota" style="color:#8a6a00">Por asignar: ${faltan}.</p>` : ''}
      <div class="acciones-grandes">
        <button type="button" onclick="Agenda.editar('${t.id}')">Editar</button>
        <button type="button" class="sec" onclick="Agenda.fechas('${t.id}')">Mover fechas</button>
        <button type="button" class="sec" onclick="Agenda.asignar('${t.id}')">Asignar</button>
        <button type="button" class="sec" onclick="Agenda.terminar('${t.id}', this)"${t.estado === 'terminado' ? ' disabled' : ''}>Marcar terminado</button>
      </div><div class="msg"></div>`, col);
  }

  const labores = () => [...new Set([...((V && V.unidades) || []).map(u => u.labor), ...filasTC().map(f => f.labor), 'Barrido'].filter(Boolean))].sort((a, b) => a.localeCompare(b, 'es'));
  const tipos = () => [...new Set(((V && V.unidades) || []).map(u => u.grupo).filter(Boolean))];
  let BORRADOR = null;
  const nuevoId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

  function editar(id) {
    const t = id ? trabajos().find(x => x.id === id) : null;
    BORRADOR = t ? JSON.parse(JSON.stringify({ ...t, _pend: undefined })) : { id: nuevoId(), campo: '', labor: '', inicio: hoy(), termino: '', ha: '', cuarteles: [], necesita: [], estado: 'por_confirmar', notas: '', maquinas: [], operadores: [], creado: hoy() };
    pintarFormulario();
  }
  function pintarFormulario() {
    const b = BORRADOR, c = b.campo && b.inicio ? calc({ ...b, termino: '' }) : null;
    const opLab = labores().map(l => `<option${l === b.labor ? ' selected' : ''}>${esc(l)}</option>`).join('');
    const opTipo = sel => tipos().map(x => `<option${x === sel ? ' selected' : ''}>${esc(x)}</option>`).join('');
    hoja(`<h3>${trabajos().some(x => x.id === b.id) ? 'Editar trabajo' : 'Nuevo trabajo'}</h3>
      <label class="fila"><span>Campo</span><button type="button" class="elegido" onclick="Agenda.elegirCampo()">${b.campo ? esc(nombreCampo(b.campo)) : '<span style="color:var(--gris)">Elegir campo…</span>'}<span>▾</span></button></label>
      <label class="fila"><span>Labor</span><select onchange="Agenda.dato('labor', this.value)"><option value="">(elegir)</option>${opLab}</select></label>
      <div class="dos"><label class="fila"><span>Inicio</span><input type="date" value="${esc(b.inicio)}" onchange="Agenda.dato('inicio', this.value)"></label>
        <label class="fila"><span>Término (a mano)</span><input type="date" value="${esc(b.termino)}" onchange="Agenda.dato('termino', this.value)"></label></div>
      <p class="nota" style="margin-top:-4px">${c && c.auto ? `Automático: ~${dmLargo(c.auto)} (${num(c.tasa.tasa, 2)} ha/día · ${esc(c.tasa.base)}). Déjalo vacío para usar el automático.` : 'Automático: falta campo, labor, hectáreas o el rendimiento de las máquinas; puedes ponerlo a mano.'}</p>
      <div class="dos"><label class="fila"><span>Hectáreas</span><input inputmode="decimal" value="${esc(b.ha)}" placeholder="ej. 25" onchange="Agenda.dato('ha', this.value.trim())"></label>
        <label class="fila"><span>Cuarteles</span><button type="button" class="elegido" onclick="Agenda.cuarteles()">${b.cuarteles.length ? b.cuarteles.length + ' elegidos' : '<span style="color:var(--gris)">Elegir…</span>'}<span>▾</span></button></label></div>
      <div class="fila"><span>Qué se necesita</span>
        ${b.necesita.map((x, i) => `<div class="nec"><input type="number" min="1" max="50" value="${x.cantidad}" onchange="Agenda.necesita(${i}, 'cantidad', this.value)"><select onchange="Agenda.necesita(${i}, 'tipo', this.value)">${opTipo(x.tipo)}</select><button type="button" onclick="Agenda.necesita(${i})" aria-label="Quitar">×</button></div>`).join('')}
        <div><button type="button" class="mas" onclick="Agenda.necesita(-1)">+ Agregar máquinas (ej. 2 Barredoras)</button></div></div>
      <label class="fila"><span>Estado</span><select onchange="Agenda.dato('estado', this.value)">${Object.entries(ESTADOS).map(([k, v]) => `<option value="${k}"${k === b.estado ? ' selected' : ''}>${v}</option>`).join('')}</select></label>
      <label class="fila"><span>Notas</span><textarea rows="3" maxlength="1000" onchange="Agenda.dato('notas', this.value)">${esc(b.notas)}</textarea></label>
      <div class="acciones-grandes"><button type="button" onclick="Agenda.guardarBorrador(this)">Guardar</button><button type="button" class="sec" onclick="${trabajos().some(x => x.id === b.id) ? `Agenda.abrir('${b.id}')` : 'Agenda.cerrar()'}">Cancelar</button></div>
      <div class="msg"></div>
      ${trabajos().some(x => x.id === b.id) ? `<p style="margin-top:14px"><button type="button" class="borrar" onclick="Agenda.borrar('${b.id}', this)">Borrar este trabajo</button></p>` : ''}`);
  }
  function dato(k, v) { BORRADOR[k] = v; if (k === 'inicio' || k === 'labor' || k === 'ha') pintarFormulario(); }
  async function elegirCampo() {
    const v = await elegir('campo', 'Campo del trabajo', BORRADOR.campo);
    if (v == null || v === '' || esTaller(v)) return;
    if (v !== BORRADOR.campo) BORRADOR.cuarteles = [];
    BORRADOR.campo = v; pintarFormulario();
  }
  function necesita(i, k, v) {
    if (i === -1) BORRADOR.necesita.push({ tipo: tipos()[0] || 'Tractores', cantidad: 1 });
    else if (k === undefined) BORRADOR.necesita.splice(i, 1);
    else BORRADOR.necesita[i][k] = k === 'cantidad' ? Math.max(1, Math.min(50, parseInt(v, 10) || 1)) : v;
    pintarFormulario();
  }

  // Cuarteles del campo con su area (geocercas.json); la suma llena las hectareas.
  function campoDeCuartel(cuartel) {
    const palabras = [];
    for (const p of cuartel.split(/[\s_]+/)) { if (/\d/.test(p)) break; if (p) palabras.push(p); }
    const raiz = sinT(palabras.join(' ') || cuartel).trim();
    for (const [campo, raices] of Object.entries(CAMPOS.campos_unidos || {})) if (raices.includes(raiz)) return campo;
    return palabras.join(' ') || cuartel;
  }
  async function cuarteles() {
    if (!BORRADOR.campo) return msg('Primero elige el campo.', true);
    if (!AREAS) {
      msg('Cargando cuarteles…');
      try {
        const g = await (await fetch('datos/geocercas.json', { cache: 'no-store' })).json();
        AREAS = {};
        for (const [n, v] of Object.entries(g)) AREAS[n] = { area: v.area_ha, campo: campoDeCuartel(n) };
      } catch (e) { return msg('No se pudieron cargar los cuarteles.', true); }
    }
    const lista = Object.entries(AREAS).filter(([, v]) => clave(v.campo) === clave(BORRADOR.campo) || calzaCampo(BORRADOR.campo, v.campo))
      .sort((a, b) => a[0].localeCompare(b[0], undefined, { numeric: true }));
    if (!lista.length) return msg('Este campo no tiene cuarteles con geocerca: escribe las hectáreas.', true);
    const marcados = new Set(BORRADOR.cuarteles);
    hoja(`<h3>Cuarteles de ${esc(nombreCampo(BORRADOR.campo))}</h3><p class="nota">La suma de las áreas llena las hectáreas.</p>
      <div style="margin:6px 0"><a href="#" onclick="document.querySelectorAll('#capaAgenda .cuarteles input').forEach(c => c.checked = true); return false">Todos</a> · <a href="#" onclick="document.querySelectorAll('#capaAgenda .cuarteles input').forEach(c => c.checked = false); return false">Ninguno</a></div>
      <div class="cuarteles">${lista.map(([n, v]) => `<label><input type="checkbox" value="${esc(n)}"${marcados.has(n) ? ' checked' : ''}> ${esc(n)} <small style="color:var(--gris)">${num(v.area, 2)} ha</small></label>`).join('')}</div>
      <div class="acciones-grandes"><button type="button" onclick="Agenda.listoCuarteles()">Listo</button><button type="button" class="sec" onclick="Agenda.volverFormulario()">Cancelar</button></div>`);
  }
  function listoCuarteles() {
    BORRADOR.cuarteles = [...document.querySelectorAll('#capaAgenda .cuarteles input:checked')].map(c => c.value);
    if (BORRADOR.cuarteles.length) BORRADOR.ha = String(Math.round(BORRADOR.cuarteles.reduce((s, n) => s + (AREAS[n] ? AREAS[n].area : 0), 0) * 100) / 100);
    pintarFormulario();
  }

  async function guardarBorrador(boton) {
    const b = BORRADOR;
    if (!b.campo) return msg('Elige el campo.', true);
    if (!b.labor) return msg('Elige la labor.', true);
    if (!b.inicio) return msg('Pon la fecha de inicio.', true);
    if (b.termino && b.termino < b.inicio) return msg('El término no puede ser antes del inicio.', true);
    if (b.ha && !/^\d{1,5}([.,]\d{1,2})?$/.test(b.ha)) return msg('Hectáreas: un número, ej. 25 o 12,5.', true);
    const c = calc({ ...b, termino: '' });
    b.termino_previsto = b.termino || c.auto || '';
    if (await enviar({ trabajo: limpio(b) }, boton)) detalle(b.id);
  }
  const limpio = t => { const r = { ...t }; delete r._pend; return r; };

  function fechas(id) {
    const t = trabajos().find(x => x.id === id), c = calc(t);
    hoja(`<h3>Mover fechas</h3><p class="nota">${esc(nombreT(t))}. Al mover el inicio, el término a mano se corre lo mismo.</p>
      <div class="dos"><label class="fila"><span>Inicio</span><input type="date" id="agIni" value="${esc(t.inicio)}"></label>
      <label class="fila"><span>Término (a mano)</span><input type="date" id="agFin" value="${esc(t.termino)}" placeholder="automático"></label></div>
      <p class="nota">Vacío = automático (~${dmLargo(c.auto || c.plan)}).</p>
      <div class="acciones-grandes"><button type="button" onclick="Agenda.guardarFechas('${id}', this)">Guardar</button><button type="button" class="sec" onclick="Agenda.abrir('${id}')">Cancelar</button></div><div class="msg"></div>`);
    const ini = document.getElementById('agIni'), fin = document.getElementById('agFin');
    ini.onchange = () => { if (t.termino && ini.value) fin.value = mas(t.termino, entre(t.inicio, ini.value)); };
  }
  async function guardarFechas(id, boton) {
    const t = limpio(trabajos().find(x => x.id === id));
    const ini = document.getElementById('agIni').value, fin = document.getElementById('agFin').value;
    if (!ini) return msg('Pon la fecha de inicio.', true);
    if (fin && fin < ini) return msg('El término no puede ser antes del inicio.', true);
    t.inicio = ini; t.termino = fin; t.termino_previsto = fin || calc({ ...t, termino: '' }).auto || '';
    if (await enviar({ trabajo: t }, boton)) detalle(id);
  }

  function asignar(id) {
    const t = trabajos().find(x => x.id === id), c = calc(t);
    const chips = (lista, k) => lista.map((x, i) => `<span>${esc(x)}<button type="button" onclick="Agenda.quitar('${id}', '${k}', ${i}, this)" aria-label="Quitar">×</button></span>`).join('');
    hoja(`<h3>Asignar</h3><p class="nota">${esc(nombreT(t))} · ${dmLargo(t.inicio)} al ~${dmLargo(c.fin)}. Se guarda al tocar.</p>
      <div class="fila"><span>Máquinas${cantidadNecesaria(t) ? ` (se necesitan ${cantidadNecesaria(t)}: ${esc(t.necesita.map(x => x.cantidad + ' ' + x.tipo).join(', '))})` : ''}</span>
        <div class="lista-x">${chips(t.maquinas || [], 'maquinas')}${c.faltanMaq ? `<span class="am">faltan ${c.faltanMaq}</span>` : ''}<button type="button" class="mas" onclick="Agenda.agregar('${id}', 'maquinas', this)">+ Máquina</button></div></div>
      <div class="fila"><span>Operadores</span>
        <div class="lista-x">${chips(t.operadores || [], 'operadores')}${c.faltanOp ? `<span class="am">faltan ${c.faltanOp}</span>` : ''}<button type="button" class="mas" onclick="Agenda.agregar('${id}', 'operadores', this)">+ Operador</button></div></div>
      <div class="acciones-grandes"><button type="button" class="sec" onclick="Agenda.abrir('${id}')">Listo</button></div><div class="msg"></div>`);
  }
  async function agregar(id, k, boton) {
    const t = limpio(trabajos().find(x => x.id === id));
    const v = await elegir(k === 'maquinas' ? 'maquina' : 'operador', k === 'maquinas' ? 'Máquina para el trabajo' : 'Operador para el trabajo', '');
    if (!v) return;
    t[k] = [...new Set([...(t[k] || []), v])];
    if (await enviar({ trabajo: t }, boton)) asignar(id);
  }
  async function quitar(id, k, i, boton) {
    const t = limpio(trabajos().find(x => x.id === id));
    t[k] = (t[k] || []).filter((_, j) => j !== i);
    if (await enviar({ trabajo: t }, boton)) asignar(id);
  }
  async function terminar(id, boton) {
    const t = limpio(trabajos().find(x => x.id === id));
    t.estado = 'terminado';
    if (await enviar({ trabajo: t }, boton)) detalle(id);
  }
  async function borrar(id, boton) {
    if (boton.dataset.seguro !== '1') { boton.dataset.seguro = '1'; boton.textContent = 'Toca otra vez para borrar'; return; }
    if (await enviar({ borrar: id }, boton)) cerrar();
  }

  // -------------------------------------------------------------------------
  // Guardar: Worker /agenda con el PIN. Si Cloudflare no responde (o todavia no
  // tiene /agenda), queda en este aparato y se reintenta solo.
  // -------------------------------------------------------------------------
  function guardarPend() { escribirLS(CLAVE_PEND, PEND); }
  async function enviar(cuerpo, boton) {
    const id = nuevoId() + 'g';
    const p = { id, t0: Date.now(), cuerpo };
    PEND.push(p); guardarPend();
    msg('Guardando…');
    const r = await enviarUno(p, boton);
    refrescar();
    if (r === 'mal') return false;
    msg(r === 'ok' ? '✓ Guardado.' : r === 'github' ? 'Guardado, se actualiza en 2–3 minutos.' : 'Sin conexión con Cloudflare: quedó en este aparato y se enviará solo.', r === 'local');
    return true;
  }
  async function enviarUno(p, boton) {
    let res;
    try { res = await enviarConPin(WORKER + '/agenda', { ...p.cuerpo, id: p.id }, boton || document.body); }
    catch (e) { p.sinRuta = true; guardarPend(); return 'local'; }
    if (res.ok && res.j && res.j.d1) {
      PEND = PEND.filter(x => x.id !== p.id); guardarPend();
      desdeD1(res.j); return 'ok';
    }
    if (res.ok) { p.ok = true; guardarPend(); return 'github'; }  // sin D1: espera a que agenda.json lo muestre
    if (res.status === 404 || res.status >= 500) { p.sinRuta = res.status === 404; guardarPend(); return 'local'; }
    // PIN incorrecto o dato invalido: no se guardo, vuelve a como estaba.
    PEND = PEND.filter(x => x.id !== p.id); guardarPend();
    msg('No se guardó: ' + textoError(res), true);
    return 'mal';
  }
  setInterval(async () => {
    const sinEnviar = PEND.filter(p => !p.ok);
    if (!sinEnviar.length || !pinGuardado()) return;
    for (const p of sinEnviar) { if ((await enviarUno(p, null)) !== 'ok' && !p.ok) break; }
    refrescar();
  }, 30000);

  function desdeD1(e) {
    if (!e || !e.d1 || !Array.isArray(e.agenda)) return;
    PUB = Object.fromEntries(e.agenda.map(t => [t.id, t]));
    CAMBIOS_D1 = (e.agenda_cambios || []).map(c => ({ fecha: fechaChile(c.ts), trabajo: c.trabajo, cambio: c.cambio, antes: c.antes, despues: c.despues, id: c.guardado }));
  }
  function desdePublicado(ag, cambios) {
    if (ag && ag.trabajos && !D1) PUB = ag.trabajos;
    if (Array.isArray(cambios)) CAMBIOS_PUB = cambios;
    GUARDADOS = new Set(((ag && ag.guardados) || []).map(g => g.id));
    // Lo enviado sin D1 deja de estar pendiente cuando agenda.json ya lo muestra.
    const antes = PEND.length;
    PEND = PEND.filter(p => !(p.ok && GUARDADOS.has(p.id)));
    if (PEND.length !== antes) guardarPend();
  }
  function refrescar() {
    if (seccion() === 'operacion' && UI.pestana === 'agenda') {
      const caja = document.getElementById('vistaOp');
      if (caja) caja.innerHTML = html();
    }
  }

  // Sugerencias para la pestaña de Operacion: mover maquinas al campo el dia de inicio y marcar terminado.
  function sugerencias() {
    const r = [], h = hoy();
    for (const t of trabajos()) {
      const c = calc(t);
      if (c.estado === 'terminado' || t.inicio > h) continue;
      const destino = campoDeLugar(t.campo) || t.campo;
      for (const m of t.maquinas || []) {
        if (!OP.maquinas[m] || calzaCampo(valorDe(m).campo, t.campo) || clave(valorDe(m).campo) === clave(destino) || h > c.fin) continue;
        r.push({ m, texto: `¿Mover ${m} a ${nombreCampo(destino)}?`, sub: `Agenda: ${nombreT(t)} desde el ${dmLargo(t.inicio)}`, boton: `Mover a ${nombreCampo(destino)}`, fn: b => moverACampo(m, b, destino) });
      }
      if (c.listo) r.push({ m: '', texto: `¿Marcar terminado: ${nombreT(t)}?`, sub: c.prog && c.pct >= 0.95 ? `Van ${num(c.hecho)} de ${num(c.prog)} ha (${Math.round(c.pct * 100)} %)` : `Pasó la fecha de término (~${dmLargo(c.fin)})`,
        boton: 'Marcar terminado', fn: b => terminar(t.id, b) });
    }
    return r;
  }

  window.Agenda = {
    html, sugerencias, avisos: () => avisos(), desdeD1, desdePublicado,
    abrir: id => detalle(id), cerrar, editar, dato, elegirCampo, necesita, cuarteles, listoCuarteles,
    volverFormulario: () => pintarFormulario(), guardarBorrador, fechas, guardarFechas, asignar, agregar, quitar, terminar, borrar,
    vista(v) { AG.vista = v; escribirLS('agenda_vista', v); refrescar(); },
    mover(k) {
      if (AG.vista === 'mes') { const [a, m] = AG.mes.split('-').map(Number); const d = new Date(Date.UTC(a, m - 1 + k, 1)); AG.mes = iso(d).slice(0, 7); }
      else AG.semana = mas(AG.semana, 7 * k * (AG.vista === 'maquina' ? 2 : 1));
      refrescar();
    },
    irHoy() { AG.mes = hoy().slice(0, 7); AG.semana = lunes(hoy()); refrescar(); },
    // Para el correo y pruebas: trabajos con su calculo.
    _calc: calc, _trabajos: trabajos,
  };
})();
