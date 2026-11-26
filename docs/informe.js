// Informe para el cliente (Excel y PDF), generado en el navegador con los datos
// publicados: historico.json (hectareas por dia, maquina y cuartel, con la regla
// del cuartel completo = area total), avance_cuarteles.json (pasadas de barrido)
// y geocercas.json (contornos para los mapas). Reglas en CLAUDE.md.

const INF_UMBRAL = 0.95;
const INF_VERDE = '2F6F3E';
const LIBS_INFORME = {
  exceljs: 'https://cdnjs.cloudflare.com/ajax/libs/exceljs/4.4.0/exceljs.min.js',
  jspdf: 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js',
  autotable: 'https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.8.2/jspdf.plugin.autotable.min.js',
};
let geocercasInforme = null;

function cargarScript(url) {
  return new Promise((ok, falla) => {
    if (document.querySelector(`script[src="${url}"]`)) return ok();
    const s = document.createElement('script');
    s.src = url; s.onload = ok; s.onerror = () => falla(new Error('No se pudo cargar ' + url));
    document.head.appendChild(s);
  });
}

// Campo = raiz del nombre del cuartel, sin el numero ni lo que sigue
// ("El Volcan 14" -> "el volcan"); mismo criterio que raiz_campo en Python.
function raizCampo(nombre) {
  const texto = nombre.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const palabras = [];
  for (const p of texto.split(/[\s_]+/)) {
    if (/\d/.test(p)) break;
    if (p) palabras.push(p);
  }
  return palabras.join(' ') || texto.trim();
}
function nombreCampo(nombreCuartel) {
  const palabras = [];
  for (const p of nombreCuartel.split(/[\s_]+/)) {
    if (/\d/.test(p)) break;
    if (p) palabras.push(p);
  }
  return palabras.join(' ') || nombreCuartel;
}
// Campo de un cuartel, con los nombres distintos del mismo campo unidos
// (docs/datos/campos.json = campos_unidos de config.json; ej. "El Volcan
// Nueces" es El Volcan, A1-A15 son Ballerina). Las "Nueva geocerca (id ...)"
// estan a mas de 20 km entre si: cada una es un campo. {id, nombre}
let CAMPO_DE_RAIZ = {};   // raiz -> nombre del campo unido
let RAICES_DE_CAMPO = {}; // nombre del campo unido -> [raices]
let CUARTELES_EN_USO = [];  // todas las geocercas en uso (para listar todos los campos)
let EQUIVALENCIAS = {};     // nombre en la planilla -> [campos de Wialon]
function cargarCamposUnidos(datosCampos) {
  CAMPO_DE_RAIZ = {}; RAICES_DE_CAMPO = (datosCampos && datosCampos.campos_unidos) || {};
  CUARTELES_EN_USO = (datosCampos && datosCampos.cuarteles) || [];
  EQUIVALENCIAS = (datosCampos && datosCampos.equivalencias) || {};
  for (const [campo, raices] of Object.entries(RAICES_DE_CAMPO)) for (const r of raices) CAMPO_DE_RAIZ[r] = campo;
}
function campoDe(nombreCuartel) {
  const raiz = raizCampo(nombreCuartel);
  if (raiz.startsWith('nueva geocerca')) return { id: 'g:' + nombreCuartel.toLowerCase(), nombre: nombreCuartel };
  if (CAMPO_DE_RAIZ[raiz]) return { id: 'u:' + CAMPO_DE_RAIZ[raiz], nombre: CAMPO_DE_RAIZ[raiz] };
  return { id: raiz, nombre: nombreCampo(nombreCuartel) };
}
const numeroCuartel = n => { const m = n.match(/(\d+)\s*$/); return m ? parseInt(m[1], 10) : 0; };
const ordenCuartel = (a, b) => campoDe(a).id.localeCompare(campoDe(b).id) || numeroCuartel(a) - numeroCuartel(b) || a.localeCompare(b);
const fechaCl = iso => iso ? iso.split('-').reverse().join('-') : '';
const hoyIso = () => new Date().toLocaleDateString('en-CA', { timeZone: 'America/Santiago' });
const n2 = v => Number(v).toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const p1 = v => (v * 100).toLocaleString('es-CL', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '%';

// Campos disponibles (con trabajo en el historial).
function camposDisponibles() {
  const campos = {};
  for (const d of datos) {
    const raiz = campoDe(d.cuartel).id;
    if (!campos[raiz]) campos[raiz] = campoDe(d.cuartel).nombre;
  }
  return Object.entries(campos).sort((a, b) => a[1].localeCompare(b[1], 'es')).map(([raiz, nombre]) => ({ raiz, nombre }));
}

// Datos del informe: filas del periodo y avance por cuartel (estado al "hasta").
// maquinas = las marcadas en el filtro de la pagina ([] = todas). El estado
// (completo / % de avance) siempre es el del cuartel con todas las maquinas.
// excluidos = filas (cuartel + labor) desmarcadas en la vista previa: no cuentan
// en ese informe (no cambia el calculo ni los datos guardados).
const claveFila = d => [d.cuartel, d.labor, d.temporada || '', d.repaso || 0].join('||');
function datosInforme(raices, desde, hasta, maquinas, excluidos, editados) {
  const pedidos = new Set(raices);
  const maq = new Set(maquinas || []);
  // Copias: el ajuste de redondeo de abajo no debe tocar los datos de la pagina.
  const filas = datos.filter(d => pedidos.has(campoDe(d.cuartel).id) && d.fecha >= desde && d.fecha <= hasta && d.area_trabajada_ha > 0 &&
    (!maq.size || maq.has(d.maquina))).map(d => ({ ...d }));
  const area = {};
  for (const d of datos) area[d.cuartel] = Math.max(area[d.cuartel] || 0, d.area_total_ha);
  // Fecha en que cada cuartel + labor llego al 95 % (todas las maquinas).
  const completos = {};
  const acumulado = {};
  for (const d of [...datos].sort((a, b) => a.fecha.localeCompare(b.fecha))) {
    if (d.labor === 'Barrido' || d.repaso) continue;  // cada temporada parte de cero; los repasos van aparte
    const k = d.cuartel + '||' + d.labor + '||' + (d.temporada || '');
    acumulado[k] = (acumulado[k] || 0) + d.area_trabajada_ha;
    if (!completos[k] && acumulado[k] >= INF_UMBRAL * area[d.cuartel] - 1e-6) completos[k] = d.fecha;
  }
  // Cuartel completo = area exacta (pedido del usuario 26-nov-2026): el historial
  // guarda cada dia con 2 decimales y la suma puede quedar 0,01-0,03 bajo el area
  // (4,54 en vez de 4,55). Esa diferencia de redondeo se suma el dia en que se
  // completo, como la regla del area total. No cambia el calculo de hectareas.
  for (const [k, fc] of Object.entries(completos)) {
    if (fc < desde || fc > hasta) continue;
    const [cuartel, labor, temporada] = k.split('||');
    const suma = datos.filter(d => d.cuartel === cuartel && d.labor === labor && (d.temporada || '') === temporada && !d.repaso && d.fecha <= hasta)
      .reduce((t, d) => t + d.area_trabajada_ha, 0);
    const dif = Math.round((area[cuartel] - suma) * 100) / 100;
    if (dif <= 0 || dif > 0.05) continue;
    const delDia = filas.filter(d => d.cuartel === cuartel && d.labor === labor && (d.temporada || '') === temporada && !d.repaso && d.fecha === fc)
      .sort((a, b) => b.area_trabajada_ha - a.area_trabajada_ha);
    if (delDia.length) delDia[0].area_trabajada_ha = Math.round((delDia[0].area_trabajada_ha + dif) * 100) / 100;
  }
  // Una fila por cuartel + labor + temporada (y repaso aparte).
  const mismo = (d, cuartel, labor, temporada, repaso) => d.cuartel === cuartel && d.labor === labor &&
    (d.temporada || '') === temporada && String(d.repaso || 0) === repaso;
  const claves = [...new Set(filas.map(claveFila))];
  const cuarteles = claves.map(k => {
    const [cuartel, laborBase, temporada, repaso] = k.split('||');
    const del = datos.filter(d => mismo(d, cuartel, laborBase, temporada, repaso));
    const ha = filas.filter(d => mismo(d, cuartel, laborBase, temporada, repaso)).reduce((t, d) => t + d.area_trabajada_ha, 0);
    const hastaFecha = del.filter(d => d.fecha <= hasta).reduce((t, d) => t + d.area_trabajada_ha, 0);
    const labor = laborBase + (repaso !== '0' ? ` – REPASO ${repaso}` : '');
    const c = { clave: k, campo: campoDe(cuartel).nombre, raiz: campoDe(cuartel).id, cuartel, labor, laborBase, area: area[cuartel], ha,
                haOriginal: ha, hastaFecha };
    if (laborBase === 'Barrido') {
      const info = avanceCuarteles && avanceCuarteles.cuarteles[cuartel] && avanceCuarteles.cuarteles[cuartel].labores.Barrido;
      const cierres = ((info && info.cierres) || []).filter(f => f <= hasta);
      const enPeriodo = cierres.filter(f => f >= desde);
      c.pasadas = enPeriodo.length;
      const enCurso = Math.max(0, hastaFecha - cierres.length * c.area) / c.area;
      c.completo = enPeriodo.length > 0;
      c.pct = c.completo && enCurso < 0.01 ? 1 : Math.min(1, enCurso);
      c.fechaCompleto = enPeriodo[0] || null;
    } else if (repaso !== '0') {
      c.completo = hastaFecha >= INF_UMBRAL * c.area - 1e-6;
      c.pct = Math.min(1, hastaFecha / c.area);
      c.fechaCompleto = null;
    } else {
      const fc = completos[[cuartel, laborBase, temporada].join('||')];
      c.completo = !!(fc && fc <= hasta);
      c.pct = c.completo ? 1 : Math.min(1, hastaFecha / c.area);
      c.fechaCompleto = c.completo ? fc : null;
    }
    return c;
  }).sort((a, b) => ordenCuartel(a.cuartel, b.cuartel) || a.labor.localeCompare(b.labor));
  if (editados && editados.size) aplicarEdiciones(filas, cuarteles, editados);
  if (excluidos && excluidos.size) {
    return { filas: filas.filter(d => !excluidos.has(claveFila(d))), cuarteles: cuarteles.filter(c => !excluidos.has(c.clave)) };
  }
  return { filas, cuarteles };
}

// Hectareas editadas a mano en la vista previa (pedido del usuario 26-nov-2026): solo
// para ese informe, nunca cambian los datos guardados. editados = Map(clave -> ha).
// - Las filas (maquina x dia) de ese cuartel + labor se escalan en proporcion a lo que
//   hizo cada una; con 2 decimales todo cuadra exacto con el numero escrito: lo que
//   sobre o falte va al dia con mas hectareas (a su fila mas grande).
// - % de avance = (avance hasta la fecha "hasta" - ha calculadas del periodo + ha
//   escritas) / area; si todo el trabajo fue en el periodo es ha escritas / area.
//   Completo si llega al 95 %; el numero escrito manda (no se cambia por el area).
// - Barrido: solo cambian las hectareas; el % y las pasadas siguen las del sistema.
const r2 = v => Math.round(v * 100) / 100;
function aplicarEdiciones(filas, cuarteles, editados) {
  for (const c of cuarteles) {
    if (!editados.has(c.clave)) continue;
    const v = r2(editados.get(c.clave));
    const propias = filas.filter(d => claveFila(d) === c.clave);
    const suma = propias.reduce((t, d) => t + d.area_trabajada_ha, 0);
    if (!propias.length || suma <= 0) continue;
    for (const d of propias) d.area_trabajada_ha = r2(d.area_trabajada_ha * v / suma);
    const dif = r2(v - propias.reduce((t, d) => t + d.area_trabajada_ha, 0));
    if (dif !== 0) {
      const porDia = {};
      for (const d of propias) porDia[d.fecha] = (porDia[d.fecha] || 0) + d.area_trabajada_ha;
      const dia = Object.keys(porDia).sort((a, b) => porDia[b] - porDia[a] || a.localeCompare(b))[0];
      const fila = propias.filter(d => d.fecha === dia).sort((a, b) => b.area_trabajada_ha - a.area_trabajada_ha)[0];
      fila.area_trabajada_ha = r2(fila.area_trabajada_ha + dif);
    }
    c.ha = v;
    c.editado = true;
    if (c.laborBase !== 'Barrido') {
      c.pct = Math.min(1, Math.max(0, (c.hastaFecha - c.haOriginal + v) / c.area));
      const eraCompleto = c.completo;
      c.completo = c.pct >= INF_UMBRAL - 1e-9;
      if (!c.completo) c.fechaCompleto = null;
      else if (!eraCompleto || !c.fechaCompleto) c.fechaCompleto = propias.map(d => d.fecha).sort().pop();
    }
  }
  // Filas que quedaron en 0 ha (cuartel editado a 0) no cuentan como dia ni maquina.
  for (let i = filas.length - 1; i >= 0; i--) if (filas[i].area_trabajada_ha <= 0) filas.splice(i, 1);
}

// Area total: cada cuartel + labor cuenta una sola vez (no por temporada ni repaso).
function areaSinRepetir(cs) {
  const area = {};
  for (const c of cs) area[c.cuartel + '||' + (c.laborBase || c.labor)] = c.area;
  return Object.values(area).reduce((t, a) => t + a, 0);
}

// Trabajo sin geocerca de esos campos y fechas (docs/datos/sin_geocerca.json,
// lo carga la pagina): estimado, nunca sumado al total exacto. "Probable" =
// asignado por cercania, sin confirmar.
function sinGeocercaInforme(campos, desde, hasta, maquinas) {
  if (typeof sinGeocerca === 'undefined' || !sinGeocerca) return [];
  const nombres = new Set(campos.map(c => c.nombre));
  const maq = new Set(maquinas || []);
  return sinGeocerca.trabajos.filter(t => t.estado !== 'resuelto' && t.fecha >= desde && t.fecha <= hasta && (!maq.size || maq.has(t.maquina)) &&
    (nombres.has(t.campo) || (t.estado === 'probable' && !t.campo && (t.opciones || []).some(o => nombres.has(o)))))
    .sort((a, b) => a.fecha.localeCompare(b.fecha) || a.maquina.localeCompare(b.maquina))
    .map(t => ({ ...t, campoTxt: t.estado === 'probable'
      ? (t.campo ? `${t.campo} (probable)` : `probable: ${(t.opciones || []).join(' o ')}`)
      : `${t.campo}${t.estado === 'confirmado' ? ' (confirmado)' : ''}` }));
}

function resumenDe(filas, cuarteles) {
  const labores = [...new Set(filas.map(d => d.labor))].sort();
  const porDia = {};
  for (const d of filas) {
    porDia[d.fecha] = porDia[d.fecha] || {};
    porDia[d.fecha][d.labor] = (porDia[d.fecha][d.labor] || 0) + d.area_trabajada_ha;
  }
  const completos = cuarteles.filter(c => c.completo).length;
  return {
    labores, porDia, completos,
    total: filas.reduce((t, d) => t + d.area_trabajada_ha, 0),
    dias: Object.keys(porDia).length,
    maquinas: new Set(filas.map(d => d.maquina)).size,
    hayBarrido: cuarteles.some(c => c.labor === 'Barrido'),
  };
}

// ---------------- Excel ----------------
async function informeExcel(campos, desde, hasta, maquinas, excluidos, editados) {
  await cargarScript(LIBS_INFORME.exceljs);
  const { filas, cuarteles } = datosInforme(campos.map(c => c.raiz), desde, hasta, maquinas, excluidos, editados);
  const wb = new ExcelJS.Workbook();
  wb.creator = 'C&H Maquinaria';
  const encabezado = { font: { bold: true, color: { argb: 'FFFFFFFF' }, size: 10 }, fill: { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF' + INF_VERDE } },
                       alignment: { horizontal: 'center', vertical: 'middle', wrapText: true } };
  const relleno = c => ({ type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF' + c } });
  const NUM = '#,##0.00', PCT = '0.0%', FEC = 'dd-mm-yyyy';
  const aFecha = iso => iso ? new Date(iso + 'T12:00:00') : null;

  function tabla(ws, fila, columnas, filasDatos, formatos, total, estadoCol) {
    const enc = ws.getRow(fila);
    columnas.forEach((c, j) => { const celda = enc.getCell(j + 1); celda.value = c; Object.assign(celda, encabezado); });
    enc.height = 30;
    filasDatos.forEach((valores, i) => {
      const r = ws.getRow(fila + 1 + i);
      valores.forEach((v, j) => {
        const celda = r.getCell(j + 1); celda.value = v; celda.font = { size: 10 };
        celda.border = { bottom: { style: 'thin', color: { argb: 'FFD0D7D1' } } };
        if (formatos[j]) celda.numFmt = formatos[j];
        if (i % 2) celda.fill = relleno('F2F5F2');
      });
      if (estadoCol) {
        const celda = r.getCell(estadoCol); const ok = celda.value === 'Completo';
        celda.fill = relleno(ok ? 'D6EFD9' : 'FFF3C4'); celda.font = { size: 10, bold: true, color: { argb: ok ? 'FF1F6B34' : 'FF8A6A00' } };
      }
    });
    let r = fila + 1 + filasDatos.length;
    if (total) {
      const rt = ws.getRow(r);
      total.forEach((v, j) => {
        const celda = rt.getCell(j + 1); celda.value = v; celda.font = { size: 10, bold: true }; celda.fill = relleno('DDE6DE');
        if (formatos[j] && typeof v === 'number') celda.numFmt = formatos[j];
      });
      r++;
    }
    return r + 1;
  }

  function hojaResumen(nombreHoja, camposTxt, fs, cs, conCampo) {
    const ws = wb.addWorksheet(nombreHoja, { views: [{ state: 'frozen', ySplit: 5, showGridLines: false }],
      pageSetup: { orientation: 'landscape', fitToPage: true, fitToWidth: 1, fitToHeight: 0 } });
    const r = resumenDe(fs, cs);
    ws.getCell('A1').value = 'C&H Maquinaria — Informe de hectáreas trabajadas';
    ws.getCell('A1').font = { size: 16, bold: true, color: { argb: 'FF' + INF_VERDE } };
    [['Campo(s)', camposTxt], ['Período', `${fechaCl(desde)} al ${fechaCl(hasta)}`], ['Labores', r.labores.join(', ')], ['Fecha de emisión', fechaCl(hoyIso())],
     ...(maquinas && maquinas.length ? [['Máquinas', textoMaquinas(maquinas)]] : [])]
      .forEach(([k, v], i) => { ws.getCell(2 + i, 1).value = k; ws.getCell(2 + i, 1).font = { bold: true, size: 10, color: { argb: 'FF555555' } }; ws.getCell(2 + i, 2).value = v; });
    ws.getCell(7, 1).value = 'Indicadores principales'; ws.getCell(7, 1).font = { size: 12, bold: true, color: { argb: 'FF' + INF_VERDE } };
    const haSG = sinGeocercaInforme(campos.filter(c => conCampo || camposTxt.includes(c.nombre)), desde, hasta, maquinas).reduce((t, x) => t + x.ha, 0);
    [['Hectáreas trabajadas', r.total, NUM], ['Cuarteles completos', r.completos, '0'], ['Cuarteles en proceso', cs.length - r.completos, '0'],
     ['Días trabajados', r.dias, '0'], ['Máquinas utilizadas', r.maquinas, '0'],
     ...(haSG > 0 ? [['Ha estimadas sin geocerca (no sumadas)', haSG, NUM]] : [])].forEach(([k, v, f], j) => {
      const a = ws.getCell(8, j + 1), b = ws.getCell(9, j + 1);
      a.value = k; a.font = { size: 9, bold: true, color: { argb: 'FF555555' } }; a.fill = relleno('EEF4EF'); a.alignment = { horizontal: 'center', wrapText: true };
      b.value = v; b.numFmt = f; b.font = { size: 16, bold: true, color: { argb: 'FF' + INF_VERDE } }; b.fill = relleno('EEF4EF'); b.alignment = { horizontal: 'center' };
    });
    ws.getRow(8).height = 28;
    let fila = 11;
    ws.getCell(fila, 1).value = 'Trabajo por día (hectáreas)'; ws.getCell(fila, 1).font = { size: 12, bold: true, color: { argb: 'FF' + INF_VERDE } };
    const dias = Object.keys(r.porDia).sort();
    fila = tabla(ws, fila + 1, ['Fecha', ...r.labores, 'Total del día'],
      dias.map(d => [aFecha(d), ...r.labores.map(l => r.porDia[d][l] || null), Object.values(r.porDia[d]).reduce((t, v) => t + v, 0)]),
      [FEC, ...r.labores.map(() => NUM), NUM],
      ['Total', ...r.labores.map(l => dias.reduce((t, d) => t + (r.porDia[d][l] || 0), 0)), r.total]);
    ws.getCell(fila, 1).value = `Avance por cuartel (estado al ${fechaCl(hasta)})`;
    ws.getCell(fila, 1).font = { size: 12, bold: true, color: { argb: 'FF' + INF_VERDE } };
    const columnas = [...(conCampo ? ['Campo'] : []), 'Cuartel', 'Labor', 'Área geocerca (ha)', 'Hectáreas en el período', '% de avance', 'Estado', 'Fecha completado', ...(r.hayBarrido ? ['Pasadas completas'] : [])];
    tabla(ws, fila + 1, columnas,
      cs.map(c => [...(conCampo ? [c.campo] : []), c.cuartel, c.labor, c.area, c.ha, c.pct, c.completo ? 'Completo' : 'En proceso', aFecha(c.fechaCompleto),
                   ...(r.hayBarrido ? [c.labor === 'Barrido' ? c.pasadas : null] : [])]),
      [...(conCampo ? [null] : []), null, null, NUM, NUM, PCT, null, FEC, ...(r.hayBarrido ? ['0'] : [])],
      [...(conCampo ? [null] : []), 'Total', null, areaSinRepetir(cs), cs.reduce((t, c) => t + c.ha, 0), null, `${r.completos} completos`, null, ...(r.hayBarrido ? [null] : [])],
      columnas.indexOf('Estado') + 1);
    [18, 16, 14, 14, 14, 12, 13, 14, 12].forEach((w, j) => { ws.getColumn(j + 1).width = w; });
  }

  const camposTxt = campos.map(c => c.nombre).join(', ');
  hojaResumen('Resumen', camposTxt, filas, cuarteles, campos.length > 1);
  if (campos.length > 1) {
    for (const c of campos) {
      hojaResumen(('Resumen ' + c.nombre).slice(0, 31), c.nombre, filas.filter(d => campoDe(d.cuartel).id === c.raiz),
                  cuarteles.filter(x => x.raiz === c.raiz), false);
    }
  }
  // Por maquina
  let ws = wb.addWorksheet('Por máquina', { views: [{ state: 'frozen', ySplit: 4, showGridLines: false }],
    pageSetup: { orientation: 'landscape', fitToPage: true, fitToWidth: 1, fitToHeight: 0 } });
  ws.getCell('A1').value = 'Hectáreas por máquina y por día'; ws.getCell('A1').font = { size: 16, bold: true, color: { argb: 'FF' + INF_VERDE } };
  ws.getCell('A2').value = `${camposTxt} · ${fechaCl(desde)} al ${fechaCl(hasta)}`; ws.getCell('A2').font = { color: { argb: 'FF555555' } };
  ['Máquina', 'Fecha', 'Labor', 'Cuarteles trabajados', 'Hectáreas', 'Operador'].forEach((c, j) => { Object.assign(ws.getCell(4, j + 1), encabezado, { value: c }); });
  const porMaq = {};
  for (const d of filas) {
    const k = d.maquina + '||' + d.fecha;
    porMaq[k] = porMaq[k] || { maquina: d.maquina, fecha: d.fecha, ha: 0, labores: new Set(), cuarteles: new Set() };
    porMaq[k].ha += d.area_trabajada_ha; porMaq[k].labores.add(d.labor); porMaq[k].cuarteles.add(d.cuartel);
  }
  let r = 5;
  const maquinasHoja = [...new Set(filas.map(d => d.maquina))].sort((a, b) => a.localeCompare(b, 'es', { numeric: true }));
  for (const m of maquinasHoja) {
    const filasM = Object.values(porMaq).filter(x => x.maquina === m).sort((a, b) => a.fecha.localeCompare(b.fecha));
    filasM.forEach((x, i) => {
      const fila = ws.getRow(r++);
      [m, aFecha(x.fecha), [...x.labores].sort().join(', '), [...x.cuarteles].sort(ordenCuartel).join(', '), x.ha, operadorDe(m, x.fecha)].forEach((v, j) => {
        const celda = fila.getCell(j + 1); celda.value = v; celda.font = { size: 10 };
        celda.border = { bottom: { style: 'thin', color: { argb: 'FFD0D7D1' } } };
        if (i % 2) celda.fill = relleno('F2F5F2');
      });
      fila.getCell(2).numFmt = FEC; fila.getCell(5).numFmt = NUM; fila.getCell(4).alignment = { wrapText: true, vertical: 'top' };
    });
    const ft = ws.getRow(r);
    [`Total ${m}`, `${filasM.length} días`, null, null, filasM.reduce((t, x) => t + x.ha, 0)].forEach((v, j) => {
      const celda = ft.getCell(j + 1); celda.value = v; celda.font = { size: 10, bold: true }; celda.fill = relleno('DDE6DE');
    });
    ft.getCell(5).numFmt = NUM;
    r += 2;
  }
  const fg = ws.getRow(r);
  ['Total general', null, null, null, filas.reduce((t, d) => t + d.area_trabajada_ha, 0)].forEach((v, j) => {
    const celda = fg.getCell(j + 1); celda.value = v; celda.font = { size: 11, bold: true, color: { argb: 'FFFFFFFF' } }; celda.fill = relleno(INF_VERDE);
  });
  fg.getCell(5).numFmt = NUM;
  [32, 12, 14, 60, 13, 22].forEach((w, j) => { ws.getColumn(j + 1).width = w; });
  // Detalle
  ws = wb.addWorksheet('Detalle', { views: [{ state: 'frozen', ySplit: 4, showGridLines: false }],
    pageSetup: { orientation: 'landscape', fitToPage: true, fitToWidth: 1, fitToHeight: 0 } });
  ws.getCell('A1').value = 'Detalle por cuartel, día y máquina'; ws.getCell('A1').font = { size: 16, bold: true, color: { argb: 'FF' + INF_VERDE } };
  ws.getCell('A2').value = `${camposTxt} · ${fechaCl(desde)} al ${fechaCl(hasta)}`; ws.getCell('A2').font = { color: { argb: 'FF555555' } };
  const det = [...filas].sort((a, b) => ordenCuartel(a.cuartel, b.cuartel) || a.fecha.localeCompare(b.fecha) || a.maquina.localeCompare(b.maquina));
  r = tabla(ws, 4, ['Campo', 'Cuartel', 'Fecha', 'Labor', 'Máquina', 'Hectáreas', 'Operador'],
    det.map(d => [campoDe(d.cuartel).nombre, d.cuartel, aFecha(d.fecha), d.labor, d.maquina, d.area_trabajada_ha, operadorDe(d.maquina, d.fecha)]),
    [null, null, FEC, null, null, NUM, null], ['Total', null, null, null, null, det.reduce((t, d) => t + d.area_trabajada_ha, 0), null]);
  ws.autoFilter = { from: 'A4', to: `G${4 + det.length}` };
  [14, 16, 12, 12, 32, 12, 22].forEach((w, j) => { ws.getColumn(j + 1).width = w; });
  // Trabajo sin geocerca (estimado, aparte)
  const sg = sinGeocercaInforme(campos, desde, hasta, maquinas);
  if (sg.length) {
    ws = wb.addWorksheet('Sin geocerca (estimado)', { views: [{ state: 'frozen', ySplit: 4, showGridLines: false }],
      pageSetup: { orientation: 'landscape', fitToPage: true, fitToWidth: 1, fitToHeight: 0 } });
    ws.getCell('A1').value = 'Trabajo sin geocerca (estimado, no sumado al total)'; ws.getCell('A1').font = { size: 16, bold: true, color: { argb: 'FF' + INF_VERDE } };
    ws.getCell('A2').value = `${camposTxt} · ${fechaCl(desde)} al ${fechaCl(hasta)} · ha = horas × rendimiento real de la máquina; "probable" = asignado por cercanía, sin confirmar`;
    ws.getCell('A2').font = { color: { argb: 'FF555555' } };
    r = tabla(ws, 4, ['Fecha', 'Máquina', 'Campo', 'Lugar', 'Horas', 'Ha estimadas', 'Mapa'],
      sg.map(t => [aFecha(t.fecha), t.maquina, t.campoTxt, t.comuna || '', t.horas, t.ha, t.mapa]),
      [FEC, null, null, null, NUM, NUM, null], ['Total', null, null, null, sg.reduce((a, t) => a + t.horas, 0), sg.reduce((a, t) => a + t.ha, 0), null]);
    [12, 30, 28, 18, 10, 13, 44].forEach((w, j) => { ws.getColumn(j + 1).width = w; });
  }
  // Notas
  ws = wb.addWorksheet('Notas', { views: [{ showGridLines: false }] });
  ws.getCell('A1').value = 'Cómo se calcula'; ws.getCell('A1').font = { size: 16, bold: true, color: { argb: 'FF' + INF_VERDE } };
  NOTAS_INFORME.forEach((n, i) => { ws.getCell(3 + i, 1).value = '• ' + n; ws.getCell(3 + i, 1).font = { size: 11 }; });
  ws.getColumn(1).width = 110;

  const buffer = await wb.xlsx.writeBuffer();
  descargarArchivo(new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
                   nombreArchivo(campos, desde, hasta) + '.xlsx');
}

const NOTAS_INFORME = [
  'Las hectáreas se miden con el GPS de cada máquina, solo dentro de cada cuartel (geocerca).',
  'Cada pasada cubre el ancho de una hilera; el trabajo repetido sobre la misma superficie se cuenta una sola vez.',
  'Un cuartel se considera completo cuando llega al 95 % de su superficie; desde ese momento se cuenta su área total.',
  'La diferencia hasta el área total se suma el día en que el cuartel se completó.',
  'En barrido, cada pasada completa por el cuartel suma su área total.',
  'No se cuentan los traslados, las vueltas en cabecera ni las pasadas por los bordes del cuartel.',
  'El % de avance y el estado son los del cuartel al último día del período del informe.',
  'Fuente: GPS de las máquinas (Wialon), procesado automáticamente cada día.',
];

// Maquinas del filtro, en orden natural (Shacker SBS 9 antes que SBS 10).
function textoMaquinas(maquinas) {
  return [...maquinas].sort((a, b) => a.localeCompare(b, 'es', { numeric: true })).join(', ');
}

function nombreArchivo(campos, desde, hasta) {
  return `Informe_hectareas_${campos.map(c => c.nombre.replace(/\s+/g, '_')).join('_')}_${desde}_a_${hasta}`;
}
function descargarArchivo(blob, nombre) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = nombre; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// ---------------- Mapas ----------------
// Grupos de cuarteles cercanos (a menos de 400 m): un mapa por grupo.
function gruposDeCuarteles(contornos) {
  const nombres = Object.keys(contornos);
  const caja = {};
  for (const n of nombres) {
    const c = contornos[n];
    const lat0 = c[0][1], k = 111320 * Math.cos(lat0 * Math.PI / 180);
    const xs = c.map(p => p[0] * k), ys = c.map(p => p[1] * 110574);
    caja[n] = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }
  const padre = Object.fromEntries(nombres.map(n => [n, n]));
  const raiz = n => { while (padre[n] !== n) { padre[n] = padre[padre[n]]; n = padre[n]; } return n; };
  for (let i = 0; i < nombres.length; i++) {
    for (let j = i + 1; j < nombres.length; j++) {
      const a = caja[nombres[i]], b = caja[nombres[j]];
      const dx = Math.max(0, a[0] - b[2], b[0] - a[2]), dy = Math.max(0, a[1] - b[3], b[1] - a[3]);
      if (Math.hypot(dx, dy) < 400) padre[raiz(nombres[i])] = raiz(nombres[j]);
    }
  }
  const grupos = {};
  for (const n of nombres) (grupos[raiz(n)] = grupos[raiz(n)] || []).push(n);
  return Object.values(grupos).map(g => g.sort(ordenCuartel)).sort((a, b) => ordenCuartel(a[0], b[0]));
}

// Mapa sobre imagen satelital (pedido del usuario 26-nov-2026): imagen de Esri
// World Imagery (con su atribucion), pasadas GPS que cuentan para las hectareas
// (todas en azul = trabajado, solo las del periodo y maquinas del informe),
// contorno de cada cuartel (verde completo, amarillo en proceso, blanco sin
// trabajo en el periodo), numero y % de avance de cada cuartel (100 % / su % /
// 0 %) y lo de afuera oscurecido.
const ESRI_TESELA = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const ESRI_ATRIBUCION = 'Imagen satelital: Esri, Maxar, Earthstar Geographics y la comunidad de usuarios SIG';
const COLOR_HILERAS = '#3D4BFF';
const COLOR_CONTORNO = { completo: '#22D45F', proceso: '#FFC61A', sin: '#FFFFFF' };

// Web Mercator a nivel 0 (el mundo mide 256 x 256).
function mercator(lon, lat) {
  const s = Math.sin(Math.max(-85, Math.min(85, lat)) * Math.PI / 180);
  return [(lon + 180) / 360 * 256, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * 256];
}

async function cargarTesela(z, x, y) {
  for (let intento = 0; intento < 3; intento++) {
    const img = await cargarTeselaUnaVez(z, x, y);
    if (img) return img;
    await new Promise(r => setTimeout(r, 800 * (intento + 1)));
  }
  return null;
}
function cargarTeselaUnaVez(z, x, y) {
  return new Promise(ok => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    const t = setTimeout(() => { img.src = ''; ok(null); }, 20000);
    img.onload = () => { clearTimeout(t); ok(img); };
    img.onerror = () => { clearTimeout(t); ok(null); };
    img.src = ESRI_TESELA.replace('{z}', z).replace('{y}', y).replace('{x}', x);
  });
}

// Geometria de cada maquina (docs/datos/geometria/<maquina>.json), una vez por sesion.
const geometriaInforme = {};
function slugMaquina(texto) {
  return texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'unidad';
}
async function geometriaDe(maquina) {
  if (!(maquina in geometriaInforme)) {
    geometriaInforme[maquina] = fetch('datos/geometria/' + slugMaquina(maquina) + '.json')
      .then(r => r.ok ? r.json() : null).catch(() => null);
  }
  return geometriaInforme[maquina];
}

// Pasadas que cuentan para las hectareas, del periodo: {maquina: [[p1, p2], ...]}.
async function pasadasDelMapa(nombres, maquinas, desde, hasta) {
  const enMapa = new Set(nombres);
  const salida = {};
  for (const m of maquinas) {
    const geo = await geometriaDe(m);
    if (!geo) continue;
    const lineas = [];
    for (const [cuartel, g] of Object.entries(geo)) {
      if (!enMapa.has(cuartel) || !g.hileras) continue;
      for (const fila of g.hileras) {
        if (!fila.cuenta) continue;
        const tramos = fila.tramos || (fila.fechas || []).map(f => [f, fila.p1, fila.p2]);
        for (const [fecha, p1, p2] of tramos) if (fecha >= desde && fecha <= hasta) lineas.push([p1, p2]);
      }
    }
    if (lineas.length) salida[m] = lineas;
  }
  return salida;
}

// Punto para la etiqueta: centroide del poligono (si cae afuera, el promedio de los vertices).
function centroEtiqueta(puntos) {
  let a = 0, cx = 0, cy = 0;
  for (let i = 0; i < puntos.length; i++) {
    const [x0, y0] = puntos[i], [x1, y1] = puntos[(i + 1) % puntos.length];
    const f = x0 * y1 - x1 * y0;
    a += f; cx += (x0 + x1) * f; cy += (y0 + y1) * f;
  }
  if (Math.abs(a) < 1e-9) return puntos.reduce((s, p) => [s[0] + p[0] / puntos.length, s[1] + p[1] / puntos.length], [0, 0]);
  return [cx / (3 * a), cy / (3 * a)];
}
function dentro([x, y], puntos) {
  let si = false;
  for (let i = 0, j = puntos.length - 1; i < puntos.length; j = i++) {
    const [xi, yi] = puntos[i], [xj, yj] = puntos[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) si = !si;
  }
  return si;
}

// Devuelve {imagen (JPEG), conSatelite}. estado: cuartel -> fila del avance.
async function dibujarMapaSatelital(nombres, contornos, estado, pasadas, ancho, alto) {
  // Caja de los cuarteles en Mercator, con margen y ajustada a la forma de la imagen.
  const todos = nombres.flatMap(n => contornos[n].map(p => mercator(p[0], p[1])));
  let [x0, y0, x1, y1] = [Math.min(...todos.map(p => p[0])), Math.min(...todos.map(p => p[1])),
                          Math.max(...todos.map(p => p[0])), Math.max(...todos.map(p => p[1]))];
  const mx = (x1 - x0) * 0.04 + 1e-6, my = (y1 - y0) * 0.04 + 1e-6;
  x0 -= mx; x1 += mx; y0 -= my; y1 += my;
  if ((x1 - x0) / (y1 - y0) > ancho / alto) {
    const h = (x1 - x0) * alto / ancho, c = (y0 + y1) / 2; y0 = c - h / 2; y1 = c + h / 2;
  } else {
    const w = (y1 - y0) * ancho / alto, c = (x0 + x1) / 2; x0 = c - w / 2; x1 = c + w / 2;
  }
  // Nivel de zoom: el menor que da al menos 1 pixel de imagen por pixel del mapa (maximo 18).
  let z = Math.max(1, Math.min(18, Math.ceil(Math.log2(ancho / (x1 - x0)))));
  const teselas = zz => (Math.floor(x1 * 2 ** zz / 256) - Math.floor(x0 * 2 ** zz / 256) + 1) * (Math.floor(y1 * 2 ** zz / 256) - Math.floor(y0 * 2 ** zz / 256) + 1);
  while (z > 1 && teselas(z) > 300) z--;
  const esc = ancho / ((x1 - x0) * 2 ** z);   // pixeles del mapa por pixel de la tesela
  const T = ([lon, lat]) => { const [x, y] = mercator(lon, lat); return [(x - x0) / (x1 - x0) * ancho, (y - y0) / (y1 - y0) * alto]; };

  const lienzo = document.createElement('canvas');
  lienzo.width = ancho; lienzo.height = alto;
  const ctx = lienzo.getContext('2d');
  ctx.fillStyle = '#3B4238'; ctx.fillRect(0, 0, ancho, alto);

  // 1) Imagen satelital
  const tx0 = Math.floor(x0 * 2 ** z / 256), tx1 = Math.floor(x1 * 2 ** z / 256);
  const ty0 = Math.floor(y0 * 2 ** z / 256), ty1 = Math.floor(y1 * 2 ** z / 256);
  const pedidos = [];
  for (let tx = tx0; tx <= tx1; tx++) for (let ty = ty0; ty <= ty1; ty++) pedidos.push(cargarTesela(z, tx, ty).then(img => ({ img, tx, ty })));
  let buenas = 0;
  for (const { img, tx, ty } of await Promise.all(pedidos)) {
    if (!img) continue;
    buenas++;
    const px = (tx * 256 - x0 * 2 ** z) * esc, py = (ty * 256 - y0 * 2 ** z) * esc;
    ctx.drawImage(img, Math.floor(px), Math.floor(py), Math.ceil(256 * esc) + 1, Math.ceil(256 * esc) + 1);
  }
  const conSatelite = buenas > 0;

  const camino = puntos => { ctx.beginPath(); puntos.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.closePath(); };
  const poligonos = Object.fromEntries(nombres.map(n => [n, contornos[n].map(T)]));

  // 2) Afuera de los cuarteles del informe, oscurecido
  const sombra = document.createElement('canvas');
  sombra.width = ancho; sombra.height = alto;
  const cs = sombra.getContext('2d');
  cs.fillStyle = 'rgba(0, 0, 0, 0.62)'; cs.fillRect(0, 0, ancho, alto);
  cs.globalCompositeOperation = 'destination-out'; cs.fillStyle = '#000';
  for (const n of nombres) { cs.beginPath(); poligonos[n].forEach(([x, y], i) => i ? cs.lineTo(x, y) : cs.moveTo(x, y)); cs.closePath(); cs.fill(); }
  ctx.drawImage(sombra, 0, 0);

  // 3) Hileras trabajadas, todas en azul (sin importar la maquina)
  ctx.lineCap = 'round'; ctx.lineWidth = Math.max(4, ancho / 450); ctx.globalAlpha = 0.9;
  for (const lineas of Object.values(pasadas)) {
    ctx.strokeStyle = COLOR_HILERAS;
    ctx.beginPath();
    for (const [p1, p2] of lineas) { const a = T(p1), b = T(p2); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); }
    ctx.stroke();
  }
  ctx.globalAlpha = 1;

  // 4) Contorno de cada cuartel (con un borde oscuro para que se vea sobre la imagen)
  ctx.lineJoin = 'round';
  for (const n of nombres) {
    const c = estado[n];
    const color = c && c.completo ? COLOR_CONTORNO.completo : c ? COLOR_CONTORNO.proceso : COLOR_CONTORNO.sin;
    camino(poligonos[n]);
    ctx.lineWidth = ancho / 300; ctx.strokeStyle = 'rgba(0, 0, 0, 0.45)'; ctx.stroke();
    ctx.lineWidth = ancho / 600; ctx.strokeStyle = color; ctx.stroke();
  }

  // 5) Numero del cuartel (y % si esta en proceso), en blanco con borde negro
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineJoin = 'round';
  const grande = Math.round(ancho / 85), chica = Math.round(ancho / 110);
  for (const n of nombres) {
    const c = estado[n];
    let p = centroEtiqueta(poligonos[n]);
    if (!dentro(p, poligonos[n])) p = poligonos[n].reduce((s, q) => [s[0] + q[0] / poligonos[n].length, s[1] + q[1] / poligonos[n].length], [0, 0]);
    const etiqueta = (n.match(/(\d+)\s*$/) || [null, n])[1];
    const pct = !c ? 0 : c.completo ? 100 : Math.round(c.pct * 100);
    const texto = (t, y, px) => {
      ctx.font = `bold ${px}px Helvetica, Arial, sans-serif`;
      ctx.lineWidth = px / 4; ctx.strokeStyle = 'rgba(0, 0, 0, 0.85)'; ctx.strokeText(t, p[0], y);
      ctx.fillStyle = '#FFFFFF'; ctx.fillText(t, p[0], y);
    };
    texto(etiqueta, p[1] - chica * 0.6, grande);
    texto(pct + '%', p[1] + grande * 0.6, chica);
  }

  // 6) Atribucion sobre la imagen
  if (conSatelite) {
    ctx.font = `${Math.round(ancho / 150)}px Helvetica, Arial, sans-serif`;
    ctx.textAlign = 'right'; ctx.textBaseline = 'bottom';
    const t = 'Esri, Maxar, Earthstar Geographics', w = ctx.measureText(t).width;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.7)'; ctx.fillRect(ancho - w - 16, alto - ancho / 150 - 10, w + 16, ancho / 150 + 10);
    ctx.fillStyle = '#333'; ctx.fillText(t, ancho - 8, alto - 5);
  }
  return { imagen: lienzo.toDataURL('image/jpeg', 0.85), conSatelite };
}

// Logo de C&H (docs/Logo_CYH.png), reducido a JPEG para que el PDF no pese de mas.
async function logoInforme() {
  try {
    const img = await new Promise((ok, falla) => { const i = new Image(); i.onload = () => ok(i); i.onerror = falla; i.src = 'Logo_CYH.png'; });
    const lienzo = document.createElement('canvas');
    lienzo.width = 640; lienzo.height = Math.round(640 * img.naturalHeight / img.naturalWidth);
    const ctx = lienzo.getContext('2d');
    ctx.fillStyle = '#FFFFFF'; ctx.fillRect(0, 0, lienzo.width, lienzo.height);
    ctx.drawImage(img, 0, 0, lienzo.width, lienzo.height);
    return { datos: lienzo.toDataURL('image/jpeg', 0.92), proporcion: lienzo.height / lienzo.width };
  } catch (e) {
    return null;
  }
}

// ---------------- PDF ----------------
async function informePdf(campos, desde, hasta, maquinas, excluidos, editados) {
  await cargarScript(LIBS_INFORME.jspdf);
  await cargarScript(LIBS_INFORME.autotable);
  if (!geocercasInforme) {
    const r = await fetch('datos/geocercas.json?_=' + Date.now());
    geocercasInforme = r.ok ? await r.json() : {};
  }
  maquinas = maquinas || [];
  const { filas, cuarteles } = datosInforme(campos.map(c => c.raiz), desde, hasta, maquinas, excluidos, editados);
  // Cuarteles desmarcados en todas sus labores: en el mapa no se dibujan (quedan oscurecidos).
  const ocultos = new Set(datosInforme(campos.map(c => c.raiz), desde, hasta, maquinas).cuarteles.map(c => c.cuartel));
  for (const c of cuarteles) ocultos.delete(c.cuartel);
  const logo = await logoInforme();
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });
  const VERDE = [47, 111, 62], GRIS = [85, 85, 85];

  // Texto con partes en negrita: [[texto, negrita], ...]
  function textoMixto(partes, x, y) {
    for (const [t, negrita] of partes) {
      doc.setFont('helvetica', negrita ? 'bold' : 'normal');
      doc.text(t, x, y);
      x += doc.getTextWidth(t);
    }
  }

  function bloque(titulo, camposLista, fs, cs, conCampo, conLogo) {
    const r = resumenDe(fs, cs);
    let x = 12;
    if (conLogo && logo) {
      doc.addImage(logo.datos, 'JPEG', 12, 7, 36, 36 * logo.proporcion);
      x = 54;
    }
    doc.setFont('helvetica', 'bold'); doc.setFontSize(16); doc.setTextColor(...VERDE);
    doc.text(titulo, x, 15);
    doc.setFontSize(9); doc.setTextColor(...GRIS);
    const sep = '  ·  ';
    textoMixto([[camposLista.length > 1 ? 'Campos: ' : 'Campo: ', false], [camposLista.join(', '), true],
                [`${sep}Período: ${fechaCl(desde)} al ${fechaCl(hasta)}${sep}${r.labores.length > 1 ? 'Labores' : 'Labor'}: ${r.labores.join(', ')}${sep}Emisión: ${fechaCl(hoyIso())}`, false]], x, 21);
    let yK = 27;
    if (maquinas.length) {
      const lineas = doc.splitTextToSize('Máquinas: ' + textoMaquinas(maquinas), 297 - 12 - x);
      doc.setFont('helvetica', 'normal'); doc.text(lineas[0] + (lineas.length > 1 ? '…' : ''), x, 26);
      yK = 30;
    }
    const kpis = [['Hectáreas trabajadas', n2(r.total)], ['Cuarteles completos', String(r.completos)], ['Cuarteles en proceso', String(cs.length - r.completos)],
                  ['Días trabajados', String(r.dias)], ['Máquinas utilizadas', String(r.maquinas)]];
    const anchoK = (297 - 24 - 4 * 3) / 5;
    kpis.forEach(([k, v], i) => {
      const xk = 12 + i * (anchoK + 3);
      doc.setFillColor(238, 244, 239); doc.rect(xk, yK, anchoK, 18, 'F');
      doc.setFont('helvetica', 'bold'); doc.setFontSize(8); doc.setTextColor(...GRIS); doc.text(k, xk + anchoK / 2, yK + 5, { align: 'center' });
      doc.setFontSize(16); doc.setTextColor(...VERDE); doc.text(v, xk + anchoK / 2, yK + 14, { align: 'center' });
    });
    const dias = Object.keys(r.porDia).sort();
    const estiloTabla = { theme: 'grid', styles: { fontSize: 7.5, cellPadding: 1.2, lineColor: [208, 215, 209], lineWidth: 0.1, textColor: 20 },
                          headStyles: { fillColor: VERDE, textColor: 255, halign: 'center', fontStyle: 'bold' },
                          alternateRowStyles: { fillColor: [242, 245, 242] }, footStyles: { fillColor: [221, 230, 222], textColor: 20, fontStyle: 'bold' },
                          margin: { left: 12, right: 12, bottom: 14 }, showFoot: 'lastPage' };
    const yT = yK + 26;
    doc.setFont('helvetica', 'bold'); doc.setFontSize(11); doc.setTextColor(...VERDE);
    doc.text('Trabajo por día (ha)', 12, yT);
    const derecha = Object.fromEntries([...Array(r.labores.length + 1).keys()].map(i => [i + 1, { halign: 'right' }]));
    doc.autoTable({ ...estiloTabla, startY: yT + 2, tableWidth: 30 + 28 * (r.labores.length + 1),
      head: [['Fecha', ...r.labores, 'Total del día']],
      body: dias.map(d => [fechaCl(d), ...r.labores.map(l => r.porDia[d][l] ? n2(r.porDia[d][l]) : ''), n2(Object.values(r.porDia[d]).reduce((t, v) => t + v, 0))]),
      foot: [['Total', ...r.labores.map(l => n2(dias.reduce((t, d) => t + (r.porDia[d][l] || 0), 0))), n2(r.total)]],
      columnStyles: derecha,
      didParseCell: h => { if (h.section === 'foot' && h.column.index > 0) h.cell.styles.halign = 'right'; } });
    // Avance por cuartel, en su propia pagina (como el informe de ejemplo).
    doc.addPage();
    const y = 15;
    doc.setFont('helvetica', 'bold'); doc.setFontSize(11); doc.setTextColor(...VERDE);
    doc.text(`Avance por cuartel (estado al ${fechaCl(hasta)})`, 12, y);
    const enc = [...(conCampo ? ['Campo'] : []), 'Cuartel', 'Labor', 'Área (ha)', 'Ha en el período', '% avance', 'Estado', 'Completado', ...(r.hayBarrido ? ['Pasadas'] : [])];
    const colEstado = enc.indexOf('Estado');
    const alinear = c => ['Área (ha)', 'Ha en el período', '% avance', 'Pasadas'].includes(c) ? 'right' : (c === 'Estado' || c === 'Completado' ? 'center' : 'left');
    doc.autoTable({ ...estiloTabla, startY: y + 2, styles: { ...estiloTabla.styles, fontSize: 8, cellPadding: 1.6 },
      head: [enc],
      body: cs.map(c => [...(conCampo ? [c.campo] : []), c.cuartel, c.labor, n2(c.area), n2(c.ha), p1(c.pct), c.completo ? 'Completo' : 'En proceso',
                          fechaCl(c.fechaCompleto), ...(r.hayBarrido ? [c.labor === 'Barrido' ? String(c.pasadas) : ''] : [])]),
      foot: [[...(conCampo ? [''] : []), 'Total', '', n2(areaSinRepetir(cs)), n2(cs.reduce((t, c) => t + c.ha, 0)), '', `${r.completos} completos`, '', ...(r.hayBarrido ? [''] : [])]],
      columnStyles: Object.fromEntries(enc.map((c, i) => [i, { halign: alinear(c) }])),
      didParseCell: h => {
        if (h.section === 'foot') h.cell.styles.halign = alinear(enc[h.column.index]);
        if (h.section === 'body' && h.column.index === colEstado) {
          const ok = h.cell.raw === 'Completo';
          h.cell.styles.fillColor = ok ? [214, 239, 217] : [255, 243, 196];
          h.cell.styles.textColor = ok ? [31, 107, 52] : [138, 106, 0]; h.cell.styles.fontStyle = 'bold';
        }
      } });
  }

  // Leyenda del mapa (en el PDF, con letra nitida): cuarteles e hileras trabajadas.
  function leyenda(conHileras, y) {
    let x = 12;
    doc.setFontSize(8); doc.setTextColor(40, 40, 40);
    const cuadro = (borde, relleno) => {
      doc.setLineWidth(0.7); doc.setDrawColor(borde); doc.setFillColor(relleno || '#FFFFFF');
      doc.rect(x, y - 3, 4, 4, relleno ? 'F' : 'D');
    };
    for (const [color, texto] of [[COLOR_CONTORNO.completo, 'Cuartel completo'], [COLOR_CONTORNO.proceso, 'Cuartel en proceso (% de avance)'], ['#C8CCC9', 'Sin trabajo en el período']]) {
      cuadro(color); doc.setFont('helvetica', 'normal'); doc.text(texto, x + 6, y);
      x += 6 + doc.getTextWidth(texto) + 7;
    }
    if (conHileras) { cuadro(COLOR_HILERAS, COLOR_HILERAS); doc.text('Hileras trabajadas', x + 6, y); }
    return y;
  }

  async function mapas(campo, cs, fs) {
    const contornos = Object.fromEntries(Object.entries(geocercasInforme).filter(([n]) => campoDe(n).id === campo.raiz && !ocultos.has(n)).map(([n, g]) => [n, g.contorno]));
    if (!Object.keys(contornos).length) return;
    // Estado de cada cuartel: la fila de su labor (sin repaso) si hay una.
    const estado = {};
    for (const c of cs) if (!estado[c.cuartel] || /REPASO/.test(estado[c.cuartel].labor)) estado[c.cuartel] = c;
    const maquinasCampo = [...new Set(fs.map(d => d.maquina))].sort((a, b) => a.localeCompare(b, 'es', { numeric: true }));
    const grupos = gruposDeCuarteles(contornos);
    for (let i = 0; i < grupos.length; i++) {
      const g = grupos[i];
      doc.addPage();
      doc.setFont('helvetica', 'bold'); doc.setFontSize(12); doc.setTextColor(...VERDE);
      const num = n => (n.match(/(\d+)\s*$/) || ['', n])[1];
      const rango = g.length > 1 ? ` (cuarteles ${num(g[0])} a ${num(g[g.length - 1])})` : '';
      doc.text(`Mapa de avance – campo ${campo.nombre}${grupos.length > 1 ? `, grupo ${i + 1} de ${grupos.length}${rango}` : ''} (al ${fechaCl(hasta)})`, 12, 14);
      // Pasadas solo en los cuarteles trabajados en el periodo.
      const trabajados = g.filter(n => estado[n]);
      const pasadas = await pasadasDelMapa(trabajados, maquinasCampo, desde, hasta);
      const { imagen, conSatelite } = await dibujarMapaSatelital(g, contornos, estado, pasadas, 2730, 1600);
      doc.addImage(imagen, 'JPEG', 12, 18, 273, 160, undefined, 'FAST');
      const yFin = leyenda(Object.keys(pasadas).length > 0, 184) || 184;
      doc.setFont('helvetica', 'normal'); doc.setFontSize(7.5); doc.setTextColor(...GRIS);
      const nota = (conSatelite ? ESRI_ATRIBUCION + '. ' : 'Sin imagen satelital (no se pudo descargar). ') +
        `Pasadas GPS (Wialon) del ${fechaCl(desde)} al ${fechaCl(hasta)} que cuentan para las hectáreas. ` +
        'Fuera de los cuarteles del informe, oscurecido.';
      doc.text(doc.splitTextToSize(nota, 273), 12, yFin + 5.5);
    }
  }

  const nombresCampos = campos.map(c => c.nombre);
  bloque('Informe de hectáreas trabajadas', nombresCampos, filas, cuarteles, campos.length > 1, true);
  if (campos.length === 1) {
    await mapas(campos[0], cuarteles, filas);
  } else {
    for (const c of campos) {
      doc.addPage();
      const cs = cuarteles.filter(x => x.raiz === c.raiz);
      const fs = filas.filter(d => campoDe(d.cuartel).id === c.raiz);
      bloque(`Campo ${c.nombre}`, [c.nombre], fs, cs, false, false);
      await mapas(c, cs, fs);
    }
  }
  const sg = sinGeocercaInforme(campos, desde, hasta, maquinas);
  if (sg.length) {
    doc.addPage();
    doc.setFont('helvetica', 'bold'); doc.setFontSize(16); doc.setTextColor(...VERDE);
    doc.text('Trabajo sin geocerca (estimado, no sumado al total)', 12, 15);
    doc.setFont('helvetica', 'normal'); doc.setFontSize(9); doc.setTextColor(...GRIS);
    doc.text(`Campo(s): ${nombresCampos.join(', ')}    Período: ${fechaCl(desde)} al ${fechaCl(hasta)}    ` +
             `Total: ~${n2(sg.reduce((t, x) => t + x.ha, 0))} ha estimadas en ${n2(sg.reduce((t, x) => t + x.horas, 0))} h. "Probable" = por cercanía, sin confirmar.`, 12, 21);
    doc.autoTable({ theme: 'grid', startY: 25, styles: { fontSize: 7.5, cellPadding: 1.2, lineColor: [208, 215, 209], lineWidth: 0.1 },
      headStyles: { fillColor: VERDE, textColor: 255, fontStyle: 'bold' }, alternateRowStyles: { fillColor: [242, 245, 242] },
      head: [['Fecha', 'Máquina', 'Campo', 'Lugar', 'Horas', 'Ha estimadas']],
      body: sg.map(t => [fechaCl(t.fecha), t.maquina, t.campoTxt, t.comuna || '', n2(t.horas), '~' + n2(t.ha)]) });
  }
  // Pie de pagina: solo el numero de pagina.
  const paginas = doc.getNumberOfPages();
  for (let i = 1; i <= paginas; i++) {
    doc.setPage(i);
    doc.setFont('helvetica', 'normal'); doc.setFontSize(7); doc.setTextColor(...GRIS);
    doc.text(`Página ${i}`, 285, 203, { align: 'right' });
  }
  descargarArchivo(doc.output('blob'), nombreArchivo(campos, desde, hasta) + '.pdf');
}

// ---------------- Panel en la pagina ----------------
// Vista previa (pedido del usuario 26-nov-2026): resumen del informe con los
// filtros (campos, fechas y maquinas de arriba) y una casilla por fila (cuartel
// + labor). Desmarcar una fila la saca solo de este informe (tablas, totales y
// mapa); no se guarda en ninguna parte y al abrir el panel todas parten marcadas.
let informeExcluidos = new Set();
let informeEditados = new Map();   // clave (cuartel + labor) -> ha escritas a mano (solo este informe)
let informeMsg = '';
let informeDiasAbierto = false;

function abrirInforme() {
  const panel = document.getElementById('panelInforme');
  panel.hidden = !panel.hidden;
  if (panel.hidden) return;
  informeExcluidos = new Set();
  informeEditados = new Map();
  informeMsg = '';
  const lista = document.getElementById('informeCampos');
  if (!lista.childElementCount) {
    lista.innerHTML = camposDisponibles().map((c, i) =>
      `<label class="campo-informe" data-nombre="${escaparXml(c.nombre.toLowerCase())}"><input type="checkbox" id="campoInf${i}" value="${escaparXml(c.raiz)}" data-nombre="${escaparXml(c.nombre)}"> ${escaparXml(c.nombre)}</label>`).join('');
  }
  const ultimo = datos.map(d => d.fecha).sort().pop() || hoyIso();
  // Respeta el filtro de la pagina: campos marcados y fechas Desde/Hasta.
  const marcados = typeof camposSeleccionados === 'function' ? camposSeleccionados() : [];
  if (marcados.length) {
    document.querySelectorAll('#informeCampos input').forEach(i => { i.checked = marcados.includes(i.value); });
  }
  const fDesde = document.getElementById('filtroDesde'), fHasta = document.getElementById('filtroHasta');
  if (fDesde && fDesde.value) document.getElementById('informeDesde').value = fDesde.value;
  if (fHasta && fHasta.value) document.getElementById('informeHasta').value = fHasta.value;
  if (!document.getElementById('informeHasta').value) document.getElementById('informeHasta').value = ultimo;
  if (!document.getElementById('informeDesde').value) document.getElementById('informeDesde').value = ultimo.slice(0, 8) + '01';
  document.getElementById('informeAviso').textContent = '';
  actualizarVistaPrevia();
}
function maquinasInforme() {
  return typeof maquinasSeleccionadas === 'function' ? maquinasSeleccionadas() : [];
}
function filtrarCamposInforme() {
  const texto = document.getElementById('buscarCampoInforme').value.trim().toLowerCase();
  document.querySelectorAll('#informeCampos .campo-informe').forEach(l => { l.hidden = !!texto && !l.dataset.nombre.includes(texto); });
}
function pedidoInforme() {
  return {
    campos: [...document.querySelectorAll('#informeCampos input:checked')].map(i => ({ raiz: i.value, nombre: i.dataset.nombre })),
    desde: document.getElementById('informeDesde').value,
    hasta: document.getElementById('informeHasta').value,
    maquinas: maquinasInforme(),
  };
}

function actualizarVistaPrevia() {
  const caja = document.getElementById('informeVistaPrevia');
  const panel = document.getElementById('panelInforme');
  if (!caja || !panel || panel.hidden) return;
  const { campos, desde, hasta, maquinas } = pedidoInforme();
  const textoMaq = maquinas.length ? `Máquinas (del filtro de arriba): ${escaparXml(textoMaquinas(maquinas))}`
    : 'Máquinas: todas (para elegir algunas, márcalas en el filtro de arriba)';
  if (!campos.length || !desde || !hasta || desde > hasta) {
    caja.innerHTML = `<div class="vp-vacio">${!campos.length ? 'Elige al menos un campo' : 'Revisa las fechas'} para ver la vista previa del informe.</div>`;
    return;
  }
  const raices = campos.map(c => c.raiz);
  const todas = datosInforme(raices, desde, hasta, maquinas).cuarteles;
  if (!todas.length) {
    caja.innerHTML = `<div class="vp-maq">${textoMaq}</div><div class="vp-vacio">No hay trabajo registrado en esos campos, fechas y máquinas.</div>`;
    return;
  }
  const { filas, cuarteles } = datosInforme(raices, desde, hasta, maquinas, informeExcluidos, informeEditados);
  const r = resumenDe(filas, cuarteles);
  // Filas de la lista con los valores editados (tambien las desmarcadas) y los originales al lado.
  const original = Object.fromEntries(todas.map(c => [c.clave, c]));
  const vista = informeEditados.size ? datosInforme(raices, desde, hasta, maquinas, null, informeEditados).cuarteles : todas;
  const conCampo = campos.length > 1;
  const kpis = [['Hectáreas trabajadas', n2(r.total)], ['Cuarteles completos', r.completos], ['Cuarteles en proceso', cuarteles.length - r.completos],
                ['Días trabajados', r.dias], ['Máquinas utilizadas', r.maquinas]];
  const marcadas = todas.length - todas.filter(c => informeExcluidos.has(c.clave)).length;
  const filasHtml = vista.map(c => {
    const fuera = informeExcluidos.has(c.clave), o = original[c.clave] || c;
    const maximo = c.laborBase === 'Barrido' ? Math.max(c.area, o.ha) : c.area;
    const celdaHa = `<input class="vp-ha" type="text" inputmode="decimal" value="${n2(c.ha)}" data-clave="${escaparXml(c.clave)}" data-max="${maximo}"
        data-orig="${o.ha}" onchange="editarHaInforme(this)" ${fuera ? 'disabled' : ''} aria-label="Hectáreas de ${escaparXml(c.cuartel)} en el período">` +
      (c.editado ? `<div class="vp-orig">editado · original ${n2(o.ha)} <button type="button" data-clave="${escaparXml(c.clave)}" onclick="volverHaInforme(this.dataset.clave)">↺ Volver</button></div>` : '');
    return `<tr class="${fuera ? 'vp-fuera' : ''}${c.editado ? ' vp-editada' : ''}">
      <td><input type="checkbox" data-clave="${escaparXml(c.clave)}" ${fuera ? '' : 'checked'} onchange="marcarFilaInforme(this)" aria-label="Incluir ${escaparXml(c.cuartel)} – ${escaparXml(c.labor)}"></td>
      ${conCampo ? `<td>${escaparXml(c.campo)}</td>` : ''}<td>${escaparXml(c.cuartel)}</td><td>${escaparXml(c.labor)}</td>
      <td class="num">${n2(c.area)}</td><td class="num">${celdaHa}</td><td class="num">${p1(c.pct)}</td>
      <td><span class="vp-estado ${c.completo ? 'ok' : 'proc'}">${c.completo ? 'Completo' : 'En proceso'}</span></td></tr>`;
  }).join('');
  const dias = Object.keys(r.porDia).sort();
  caja.innerHTML = `
    <div class="vp-maq">${textoMaq}</div>
    <div class="vp-kpis">${kpis.map(([k, v]) => `<div class="vp-kpi"><span>${k}</span><b>${v}</b></div>`).join('')}</div>
    <div class="vp-ayuda">Puedes corregir las hectáreas de un cuartel escribiendo en "Ha en el período" (solo para este informe; no cambia los datos guardados).${informeEditados.size ? ` <b>${informeEditados.size} cuartel${informeEditados.size === 1 ? '' : 'es'} editado${informeEditados.size === 1 ? '' : 's'}.</b>` : ''}</div>
    ${informeMsg ? `<div class="vp-msg" role="alert">${escaparXml(informeMsg)}</div>` : ''}
    <div class="vp-tabla"><table>
      <thead><tr><th><input type="checkbox" ${marcadas === todas.length ? 'checked' : ''} onchange="marcarTodasInforme(this.checked)" aria-label="Marcar o desmarcar todos"></th>
        ${conCampo ? '<th>Campo</th>' : ''}<th>Cuartel</th><th>Labor</th><th class="num">Área (ha)</th><th class="num">Ha en el período</th><th class="num">% avance</th><th>Estado</th></tr></thead>
      <tbody>${filasHtml}</tbody>
      <tfoot><tr><td></td>${conCampo ? '<td></td>' : ''}<td>Total (${marcadas} de ${todas.length} marcados)</td><td></td>
        <td class="num">${n2(areaSinRepetir(cuarteles))}</td><td class="num">${n2(r.total)}</td><td></td><td>${r.completos} completos</td></tr></tfoot>
    </table></div>
    <div class="vp-total">Total del informe: <b>${n2(r.total)} ha</b> trabajadas · área ${n2(areaSinRepetir(cuarteles))} ha · ${r.completos} completos · ${marcadas} de ${todas.length} cuarteles marcados</div>
    <details class="vp-dias" ${informeDiasAbierto ? 'open' : ''} ontoggle="informeDiasAbierto = this.open">
      <summary>Trabajo por día (${dias.length} días)</summary>
      <table><thead><tr><th>Fecha</th>${r.labores.map(l => `<th class="num">${escaparXml(l)}</th>`).join('')}<th class="num">Total del día</th></tr></thead>
      <tbody>${dias.map(d => `<tr><td>${fechaCl(d)}</td>${r.labores.map(l => `<td class="num">${r.porDia[d][l] ? n2(r.porDia[d][l]) : ''}</td>`).join('')}<td class="num">${n2(Object.values(r.porDia[d]).reduce((t, v) => t + v, 0))}</td></tr>`).join('')}</tbody>
      <tfoot><tr><td>Total</td>${r.labores.map(l => `<td class="num">${n2(dias.reduce((t, d) => t + (r.porDia[d][l] || 0), 0))}</td>`).join('')}<td class="num">${n2(r.total)}</td></tr></tfoot></table>
    </details>`;
}
// Numero escrito: acepta "5,50", "5.50" o "1.234,5". Nunca negativo ni mas que el area.
function leerNumeroInforme(texto) {
  let t = String(texto || '').trim().replace(/\s/g, '');
  if (t.includes(',')) t = t.replace(/\./g, '').replace(',', '.');
  return t === '' || !/^-?\d*\.?\d+$/.test(t) ? NaN : Number(t);
}
function editarHaInforme(campo) {
  const clave = campo.dataset.clave, maximo = Number(campo.dataset.max), orig = Number(campo.dataset.orig);
  const v = leerNumeroInforme(campo.value);
  informeMsg = '';
  if (isNaN(v)) informeMsg = `"${campo.value}" no es un número. Escribe las hectáreas, por ejemplo 5,50.`;
  else if (v < 0) informeMsg = 'No se pueden poner hectáreas negativas.';
  else if (r2(v) > r2(maximo) + 1e-9) informeMsg = `No se puede poner más que el área del cuartel (${n2(maximo)} ha).`;
  else if (Math.abs(r2(v) - r2(orig)) < 0.005) informeEditados.delete(clave);
  else informeEditados.set(clave, r2(v));
  actualizarVistaPrevia();
}
function volverHaInforme(clave) {
  informeEditados.delete(clave);
  informeMsg = '';
  actualizarVistaPrevia();
}
function marcarFilaInforme(casilla) {
  if (casilla.checked) informeExcluidos.delete(casilla.dataset.clave); else informeExcluidos.add(casilla.dataset.clave);
  actualizarVistaPrevia();
}
function marcarTodasInforme(marcar) {
  if (marcar) informeExcluidos.clear();
  else document.querySelectorAll('#informeVistaPrevia tbody input[data-clave]').forEach(i => informeExcluidos.add(i.dataset.clave));
  actualizarVistaPrevia();
}

async function generarInforme(tipo) {
  const { campos, desde, hasta, maquinas } = pedidoInforme();
  const aviso = document.getElementById('informeAviso');
  if (!campos.length) { aviso.textContent = 'Elige al menos un campo.'; return; }
  if (!desde || !hasta || desde > hasta) { aviso.textContent = 'Revisa las fechas: "desde" debe ser anterior o igual a "hasta".'; return; }
  const { filas } = datosInforme(campos.map(c => c.raiz), desde, hasta, maquinas, informeExcluidos, informeEditados);
  if (!filas.length) {
    aviso.textContent = datosInforme(campos.map(c => c.raiz), desde, hasta, maquinas).filas.length ? 'Marca al menos un cuartel en la vista previa.'
      : maquinas.length ? 'No hay trabajo de esas máquinas en esos campos y fechas.' : 'No hay trabajo registrado en esos campos y fechas.';
    return;
  }
  aviso.textContent = `Generando ${tipo === 'pdf' ? 'PDF (con imagen satelital, puede tardar unos segundos)' : 'Excel'}…`;
  try {
    if (tipo === 'pdf') await informePdf(campos, desde, hasta, maquinas, informeExcluidos, informeEditados);
    else await informeExcel(campos, desde, hasta, maquinas, informeExcluidos, informeEditados);
    aviso.textContent = 'Listo: el archivo se descargó.';
  } catch (e) {
    aviso.textContent = 'No se pudo generar el informe: ' + e.message;
  }
}

// Operador de una maquina un dia (foto diaria de la pagina Operacion,
// datos/operadores.json; pedido del usuario 26-oct-2026). Exacto el dia de una
// lectura; entre dos lecturas con el mismo operador, ese operador con "≈".
var OPERADORES_DIAS = typeof OPERADORES_DIAS !== 'undefined' ? OPERADORES_DIAS : {};
function operadorDe(maquina, fecha) {
  const dias = OPERADORES_DIAS || {};
  const exacto = dias[fecha] && dias[fecha][maquina];
  if (exacto) return exacto.operador || '';
  const fechas = Object.keys(dias).sort();
  const antes = fechas.filter(f => f < fecha).pop(), despues = fechas.find(f => f > fecha);
  const a = antes && dias[antes][maquina], b = despues && dias[despues][maquina];
  return a && b && a.operador && a.operador === b.operador ? a.operador + ' ≈' : '';
}
