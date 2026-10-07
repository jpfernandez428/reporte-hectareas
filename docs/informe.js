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
const numeroCuartel = n => { const m = n.match(/(\d+)\s*$/); return m ? parseInt(m[1], 10) : 0; };
const ordenCuartel = (a, b) => raizCampo(a).localeCompare(raizCampo(b)) || numeroCuartel(a) - numeroCuartel(b) || a.localeCompare(b);
const fechaCl = iso => iso ? iso.split('-').reverse().join('-') : '';
const hoyIso = () => new Date().toLocaleDateString('en-CA', { timeZone: 'America/Santiago' });
const n2 = v => Number(v).toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const p1 = v => (v * 100).toLocaleString('es-CL', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '%';

// Campos disponibles (con trabajo en el historial).
function camposDisponibles() {
  const campos = {};
  for (const d of datos) {
    const raiz = raizCampo(d.cuartel);
    if (!campos[raiz]) campos[raiz] = nombreCampo(d.cuartel);
  }
  return Object.entries(campos).sort((a, b) => a[1].localeCompare(b[1], 'es')).map(([raiz, nombre]) => ({ raiz, nombre }));
}

// Datos del informe: filas del periodo y avance por cuartel (estado al "hasta").
function datosInforme(raices, desde, hasta) {
  const pedidos = new Set(raices);
  const filas = datos.filter(d => pedidos.has(raizCampo(d.cuartel)) && d.fecha >= desde && d.fecha <= hasta && d.area_trabajada_ha > 0);
  const area = {};
  for (const d of datos) area[d.cuartel] = Math.max(area[d.cuartel] || 0, d.area_total_ha);
  // Fecha en que cada cuartel + labor llego al 95 % (todas las maquinas).
  const completos = {};
  const acumulado = {};
  for (const d of [...datos].sort((a, b) => a.fecha.localeCompare(b.fecha))) {
    if (d.labor === 'Barrido') continue;
    const k = d.cuartel + '||' + d.labor;
    acumulado[k] = (acumulado[k] || 0) + d.area_trabajada_ha;
    if (!completos[k] && acumulado[k] >= INF_UMBRAL * area[d.cuartel] - 1e-6) completos[k] = d.fecha;
  }
  const claves = [...new Set(filas.map(d => d.cuartel + '||' + d.labor))];
  const cuarteles = claves.map(k => {
    const [cuartel, labor] = k.split('||');
    const del = datos.filter(d => d.cuartel === cuartel && d.labor === labor);
    const ha = filas.filter(d => d.cuartel === cuartel && d.labor === labor).reduce((t, d) => t + d.area_trabajada_ha, 0);
    const hastaFecha = del.filter(d => d.fecha <= hasta).reduce((t, d) => t + d.area_trabajada_ha, 0);
    const c = { campo: nombreCampo(cuartel), raiz: raizCampo(cuartel), cuartel, labor, area: area[cuartel], ha };
    if (labor === 'Barrido') {
      const info = avanceCuarteles && avanceCuarteles.cuarteles[cuartel] && avanceCuarteles.cuarteles[cuartel].labores.Barrido;
      const cierres = ((info && info.cierres) || []).filter(f => f <= hasta);
      const enPeriodo = cierres.filter(f => f >= desde);
      c.pasadas = enPeriodo.length;
      const enCurso = Math.max(0, hastaFecha - cierres.length * c.area) / c.area;
      c.completo = enPeriodo.length > 0;
      c.pct = c.completo && enCurso < 0.01 ? 1 : Math.min(1, enCurso);
      c.fechaCompleto = enPeriodo[0] || null;
    } else {
      const fc = completos[k];
      c.completo = !!(fc && fc <= hasta);
      c.pct = c.completo ? 1 : Math.min(1, hastaFecha / c.area);
      c.fechaCompleto = c.completo ? fc : null;
    }
    return c;
  }).sort((a, b) => ordenCuartel(a.cuartel, b.cuartel) || a.labor.localeCompare(b.labor));
  return { filas, cuarteles };
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
async function informeExcel(campos, desde, hasta) {
  await cargarScript(LIBS_INFORME.exceljs);
  const { filas, cuarteles } = datosInforme(campos.map(c => c.raiz), desde, hasta);
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
    [['Campo(s)', camposTxt], ['Período', `${fechaCl(desde)} al ${fechaCl(hasta)}`], ['Labores', r.labores.join(', ')], ['Fecha de emisión', fechaCl(hoyIso())]]
      .forEach(([k, v], i) => { ws.getCell(2 + i, 1).value = k; ws.getCell(2 + i, 1).font = { bold: true, size: 10, color: { argb: 'FF555555' } }; ws.getCell(2 + i, 2).value = v; });
    ws.getCell(7, 1).value = 'Indicadores principales'; ws.getCell(7, 1).font = { size: 12, bold: true, color: { argb: 'FF' + INF_VERDE } };
    [['Hectáreas trabajadas', r.total, NUM], ['Cuarteles completos', r.completos, '0'], ['Cuarteles en proceso', cs.length - r.completos, '0'],
     ['Días trabajados', r.dias, '0'], ['Máquinas utilizadas', r.maquinas, '0']].forEach(([k, v, f], j) => {
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
      [...(conCampo ? [null] : []), 'Total', null, cs.reduce((t, c) => t + c.area, 0), cs.reduce((t, c) => t + c.ha, 0), null, `${r.completos} completos`, null, ...(r.hayBarrido ? [null] : [])],
      columnas.indexOf('Estado') + 1);
    [18, 16, 14, 14, 14, 12, 13, 14, 12].forEach((w, j) => { ws.getColumn(j + 1).width = w; });
  }

  const camposTxt = campos.map(c => c.nombre).join(', ');
  hojaResumen('Resumen', camposTxt, filas, cuarteles, campos.length > 1);
  if (campos.length > 1) {
    for (const c of campos) {
      hojaResumen(('Resumen ' + c.nombre).slice(0, 31), c.nombre, filas.filter(d => raizCampo(d.cuartel) === c.raiz),
                  cuarteles.filter(x => x.raiz === c.raiz), false);
    }
  }
  // Por maquina
  let ws = wb.addWorksheet('Por máquina', { views: [{ state: 'frozen', ySplit: 4, showGridLines: false }],
    pageSetup: { orientation: 'landscape', fitToPage: true, fitToWidth: 1, fitToHeight: 0 } });
  ws.getCell('A1').value = 'Hectáreas por máquina y por día'; ws.getCell('A1').font = { size: 16, bold: true, color: { argb: 'FF' + INF_VERDE } };
  ws.getCell('A2').value = `${camposTxt} · ${fechaCl(desde)} al ${fechaCl(hasta)}`; ws.getCell('A2').font = { color: { argb: 'FF555555' } };
  ['Máquina', 'Fecha', 'Labor', 'Cuarteles trabajados', 'Hectáreas'].forEach((c, j) => { Object.assign(ws.getCell(4, j + 1), encabezado, { value: c }); });
  const porMaq = {};
  for (const d of filas) {
    const k = d.maquina + '||' + d.fecha;
    porMaq[k] = porMaq[k] || { maquina: d.maquina, fecha: d.fecha, ha: 0, labores: new Set(), cuarteles: new Set() };
    porMaq[k].ha += d.area_trabajada_ha; porMaq[k].labores.add(d.labor); porMaq[k].cuarteles.add(d.cuartel);
  }
  let r = 5;
  const maquinas = [...new Set(filas.map(d => d.maquina))].sort((a, b) => a.localeCompare(b, 'es', { numeric: true }));
  for (const m of maquinas) {
    const filasM = Object.values(porMaq).filter(x => x.maquina === m).sort((a, b) => a.fecha.localeCompare(b.fecha));
    filasM.forEach((x, i) => {
      const fila = ws.getRow(r++);
      [m, aFecha(x.fecha), [...x.labores].sort().join(', '), [...x.cuarteles].sort(ordenCuartel).join(', '), x.ha].forEach((v, j) => {
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
  [32, 12, 14, 60, 13].forEach((w, j) => { ws.getColumn(j + 1).width = w; });
  // Detalle
  ws = wb.addWorksheet('Detalle', { views: [{ state: 'frozen', ySplit: 4, showGridLines: false }],
    pageSetup: { orientation: 'landscape', fitToPage: true, fitToWidth: 1, fitToHeight: 0 } });
  ws.getCell('A1').value = 'Detalle por cuartel, día y máquina'; ws.getCell('A1').font = { size: 16, bold: true, color: { argb: 'FF' + INF_VERDE } };
  ws.getCell('A2').value = `${camposTxt} · ${fechaCl(desde)} al ${fechaCl(hasta)}`; ws.getCell('A2').font = { color: { argb: 'FF555555' } };
  const det = [...filas].sort((a, b) => ordenCuartel(a.cuartel, b.cuartel) || a.fecha.localeCompare(b.fecha) || a.maquina.localeCompare(b.maquina));
  r = tabla(ws, 4, ['Campo', 'Cuartel', 'Fecha', 'Labor', 'Máquina', 'Hectáreas'],
    det.map(d => [nombreCampo(d.cuartel), d.cuartel, aFecha(d.fecha), d.labor, d.maquina, d.area_trabajada_ha]),
    [null, null, FEC, null, null, NUM], ['Total', null, null, null, null, det.reduce((t, d) => t + d.area_trabajada_ha, 0)]);
  ws.autoFilter = { from: 'A4', to: `F${4 + det.length}` };
  [14, 16, 12, 12, 32, 12].forEach((w, j) => { ws.getColumn(j + 1).width = w; });
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

function dibujarMapa(nombres, contornos, estado, ancho, alto) {
  const lienzo = document.createElement('canvas');
  lienzo.width = ancho; lienzo.height = alto;
  const ctx = lienzo.getContext('2d');
  ctx.fillStyle = '#FFFFFF'; ctx.fillRect(0, 0, ancho, alto);
  const lat0 = contornos[nombres[0]][0][1], k = Math.cos(lat0 * Math.PI / 180);
  const pts = nombres.flatMap(n => contornos[n]);
  const xs = pts.map(p => p[0] * k), ys = pts.map(p => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const margen = 30, abajo = 50;
  const esc = Math.min((ancho - 2 * margen) / (x1 - x0 || 1e-9), (alto - 2 * margen - abajo) / (y1 - y0 || 1e-9));
  const ox = (ancho - (x1 - x0) * esc) / 2, oy = margen + (alto - 2 * margen - abajo - (y1 - y0) * esc) / 2;
  const T = p => [ox + (p[0] * k - x0) * esc, oy + (y1 - p[1]) * esc];
  for (const n of nombres) {
    const c = estado[n];
    const [relleno, borde] = c && c.completo ? ['#7BC68E', '#2F6F3E'] : c ? ['#F6D365', '#A07800'] : ['#E4E7E5', '#9AA19C'];
    ctx.beginPath();
    contornos[n].forEach((p, i) => { const [x, y] = T(p); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.closePath(); ctx.fillStyle = relleno; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = borde; ctx.stroke();
  }
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = '#1B201C';
  for (const n of nombres) {
    const c = estado[n];
    const centro = contornos[n].reduce((s, p) => [s[0] + p[0] / contornos[n].length, s[1] + p[1] / contornos[n].length], [0, 0]);
    const [x, y] = T(centro);
    const etiqueta = (n.match(/(\d+)\s*$/) || [null, n])[1];
    ctx.font = 'bold 22px Helvetica, Arial, sans-serif';
    ctx.fillText(etiqueta, x, c && !c.completo ? y - 12 : y);
    if (c && !c.completo) { ctx.font = '20px Helvetica, Arial, sans-serif'; ctx.fillText(Math.round(c.pct * 100) + '%', x, y + 12); }
  }
  // Leyenda
  ctx.textAlign = 'left'; ctx.font = '20px Helvetica, Arial, sans-serif';
  let lx = margen;
  for (const [relleno, borde, texto] of [['#7BC68E', '#2F6F3E', 'Completo'], ['#F6D365', '#A07800', 'En proceso (% de avance)'], ['#E4E7E5', '#9AA19C', 'Sin trabajo en el período']]) {
    ctx.fillStyle = relleno; ctx.strokeStyle = borde; ctx.lineWidth = 2;
    ctx.fillRect(lx, alto - 36, 30, 20); ctx.strokeRect(lx, alto - 36, 30, 20);
    ctx.fillStyle = '#1B201C'; ctx.fillText(texto, lx + 40, alto - 25);
    lx += 40 + ctx.measureText(texto).width + 40;
  }
  return lienzo.toDataURL('image/jpeg', 0.88);
}

// ---------------- PDF ----------------
async function informePdf(campos, desde, hasta) {
  await cargarScript(LIBS_INFORME.jspdf);
  await cargarScript(LIBS_INFORME.autotable);
  if (!geocercasInforme) {
    const r = await fetch('datos/geocercas.json?_=' + Date.now());
    geocercasInforme = r.ok ? await r.json() : {};
  }
  const { filas, cuarteles } = datosInforme(campos.map(c => c.raiz), desde, hasta);
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });
  const VERDE = [47, 111, 62], GRIS = [85, 85, 85];

  function bloque(titulo, camposTxt, fs, cs, conCampo) {
    const r = resumenDe(fs, cs);
    doc.setFont('helvetica', 'bold'); doc.setFontSize(16); doc.setTextColor(...VERDE);
    doc.text(titulo, 12, 15);
    doc.setFont('helvetica', 'normal'); doc.setFontSize(9); doc.setTextColor(...GRIS);
    doc.text(`Campo(s): ${camposTxt}    Período: ${fechaCl(desde)} al ${fechaCl(hasta)}    Labores: ${r.labores.join(', ')}    Emisión: ${fechaCl(hoyIso())}`, 12, 21);
    const kpis = [['Hectáreas trabajadas', n2(r.total)], ['Cuarteles completos', String(r.completos)], ['Cuarteles en proceso', String(cs.length - r.completos)],
                  ['Días trabajados', String(r.dias)], ['Máquinas utilizadas', String(r.maquinas)]];
    const anchoK = (297 - 24 - 4 * 3) / 5;
    kpis.forEach(([k, v], i) => {
      const x = 12 + i * (anchoK + 3);
      doc.setFillColor(238, 244, 239); doc.rect(x, 25, anchoK, 18, 'F');
      doc.setFont('helvetica', 'bold'); doc.setFontSize(8); doc.setTextColor(...GRIS); doc.text(k, x + anchoK / 2, 30, { align: 'center' });
      doc.setFontSize(16); doc.setTextColor(...VERDE); doc.text(v, x + anchoK / 2, 39, { align: 'center' });
    });
    const dias = Object.keys(r.porDia).sort();
    const estiloTabla = { theme: 'grid', styles: { fontSize: 7.5, cellPadding: 1.2, lineColor: [208, 215, 209], lineWidth: 0.1 },
                          headStyles: { fillColor: VERDE, textColor: 255, halign: 'center', fontStyle: 'bold' },
                          alternateRowStyles: { fillColor: [242, 245, 242] }, footStyles: { fillColor: [221, 230, 222], textColor: 20, fontStyle: 'bold' },
                          margin: { left: 12, right: 12, bottom: 14 }, showFoot: 'lastPage' };
    doc.setFont('helvetica', 'bold'); doc.setFontSize(11); doc.setTextColor(...VERDE);
    doc.text('Trabajo por día (ha)', 12, 51);
    doc.autoTable({ ...estiloTabla, startY: 53, tableWidth: 30 + 28 * (r.labores.length + 1),
      head: [['Fecha', ...r.labores, 'Total del día']],
      body: dias.map(d => [fechaCl(d), ...r.labores.map(l => r.porDia[d][l] ? n2(r.porDia[d][l]) : ''), n2(Object.values(r.porDia[d]).reduce((t, v) => t + v, 0))]),
      foot: [['Total', ...r.labores.map(l => n2(dias.reduce((t, d) => t + (r.porDia[d][l] || 0), 0))), n2(r.total)]],
      columnStyles: Object.fromEntries([...Array(r.labores.length + 1).keys()].map(i => [i + 1, { halign: 'right' }])) });
    let y = doc.lastAutoTable.finalY + 8;
    if (y > 180) { doc.addPage(); y = 15; }
    doc.setFont('helvetica', 'bold'); doc.setFontSize(11); doc.setTextColor(...VERDE);
    doc.text(`Avance por cuartel (estado al ${fechaCl(hasta)})`, 12, y);
    const enc = [...(conCampo ? ['Campo'] : []), 'Cuartel', 'Labor', 'Área (ha)', 'Ha en el período', '% avance', 'Estado', 'Completado', ...(r.hayBarrido ? ['Pasadas'] : [])];
    const colEstado = enc.indexOf('Estado');
    doc.autoTable({ ...estiloTabla, startY: y + 2,
      head: [enc],
      body: cs.map(c => [...(conCampo ? [c.campo] : []), c.cuartel, c.labor, n2(c.area), n2(c.ha), p1(c.pct), c.completo ? 'Completo' : 'En proceso',
                          fechaCl(c.fechaCompleto), ...(r.hayBarrido ? [c.labor === 'Barrido' ? String(c.pasadas) : ''] : [])]),
      foot: [[...(conCampo ? [''] : []), 'Total', '', n2(cs.reduce((t, c) => t + c.area, 0)), n2(cs.reduce((t, c) => t + c.ha, 0)), '', `${r.completos} completos`, '', ...(r.hayBarrido ? [''] : [])]],
      columnStyles: Object.fromEntries(enc.map((c, i) => [i, { halign: ['Área (ha)', 'Ha en el período', '% avance', 'Pasadas'].includes(c) ? 'right' : (c === 'Estado' || c === 'Completado' ? 'center' : 'left') }])),
      didParseCell: h => {
        if (h.section === 'body' && h.column.index === colEstado) {
          const ok = h.cell.raw === 'Completo';
          h.cell.styles.fillColor = ok ? [214, 239, 217] : [255, 243, 196];
          h.cell.styles.textColor = ok ? [31, 107, 52] : [138, 106, 0]; h.cell.styles.fontStyle = 'bold';
        }
      } });
  }

  function mapas(campo, cs) {
    const contornos = Object.fromEntries(Object.entries(geocercasInforme).filter(([n]) => raizCampo(n) === campo.raiz).map(([n, g]) => [n, g.contorno]));
    if (!Object.keys(contornos).length) return;
    const estado = Object.fromEntries(cs.map(c => [c.cuartel, c]));
    const grupos = gruposDeCuarteles(contornos);
    grupos.forEach((g, i) => {
      doc.addPage();
      doc.setFont('helvetica', 'bold'); doc.setFontSize(14); doc.setTextColor(...VERDE);
      const rango = g.length > 1 ? ` (cuarteles ${(g[0].match(/(\d+)\s*$/) || ['', g[0]])[1]} a ${(g[g.length - 1].match(/(\d+)\s*$/) || ['', g[g.length - 1]])[1]})` : '';
      doc.text(`Mapa de avance - campo ${campo.nombre}${grupos.length > 1 ? `, grupo ${i + 1} de ${grupos.length}` : ''}${grupos.length > 1 ? rango : ''} (al ${fechaCl(hasta)})`, 12, 15);
      const imagen = dibujarMapa(g, contornos, estado, 1800, 1128);
      doc.addImage(imagen, 'JPEG', 12, 20, 273, 171, undefined, 'FAST');
    });
  }

  const camposTxt = campos.map(c => c.nombre).join(', ');
  bloque('C&H Maquinaria - Informe de hectáreas trabajadas', camposTxt, filas, cuarteles, campos.length > 1);
  if (campos.length === 1) {
    mapas(campos[0], cuarteles);
  } else {
    for (const c of campos) {
      doc.addPage();
      const cs = cuarteles.filter(x => x.raiz === c.raiz);
      bloque(`Campo ${c.nombre}`, c.nombre, filas.filter(d => raizCampo(d.cuartel) === c.raiz), cs, false);
      mapas(c, cs);
    }
  }
  const paginas = doc.getNumberOfPages();
  for (let i = 1; i <= paginas; i++) {
    doc.setPage(i);
    doc.setFont('helvetica', 'normal'); doc.setFontSize(7); doc.setTextColor(...GRIS);
    doc.text('C&H Maquinaria · Hectáreas medidas con GPS dentro de cada cuartel · Cuartel completo al llegar al 95 % (se cuenta su área total)', 12, 203);
    doc.text(`Página ${i} de ${paginas}`, 285, 203, { align: 'right' });
  }
  descargarArchivo(doc.output('blob'), nombreArchivo(campos, desde, hasta) + '.pdf');
}

// ---------------- Panel en la pagina ----------------
function abrirInforme() {
  const panel = document.getElementById('panelInforme');
  panel.hidden = !panel.hidden;
  if (panel.hidden) return;
  const lista = document.getElementById('informeCampos');
  if (!lista.childElementCount) {
    lista.innerHTML = camposDisponibles().map((c, i) =>
      `<label class="campo-informe" data-nombre="${escaparXml(c.nombre.toLowerCase())}"><input type="checkbox" id="campoInf${i}" value="${escaparXml(c.raiz)}" data-nombre="${escaparXml(c.nombre)}"> ${escaparXml(c.nombre)}</label>`).join('');
  }
  const ultimo = datos.map(d => d.fecha).sort().pop() || hoyIso();
  if (!document.getElementById('informeHasta').value) document.getElementById('informeHasta').value = ultimo;
  if (!document.getElementById('informeDesde').value) document.getElementById('informeDesde').value = ultimo.slice(0, 8) + '01';
}
function filtrarCamposInforme() {
  const texto = document.getElementById('buscarCampoInforme').value.trim().toLowerCase();
  document.querySelectorAll('#informeCampos .campo-informe').forEach(l => { l.hidden = !!texto && !l.dataset.nombre.includes(texto); });
}
async function generarInforme(tipo) {
  const campos = [...document.querySelectorAll('#informeCampos input:checked')].map(i => ({ raiz: i.value, nombre: i.dataset.nombre }));
  const desde = document.getElementById('informeDesde').value, hasta = document.getElementById('informeHasta').value;
  const aviso = document.getElementById('informeAviso');
  if (!campos.length) { aviso.textContent = 'Elige al menos un campo.'; return; }
  if (!desde || !hasta || desde > hasta) { aviso.textContent = 'Revisa las fechas: "desde" debe ser anterior o igual a "hasta".'; return; }
  const { filas } = datosInforme(campos.map(c => c.raiz), desde, hasta);
  if (!filas.length) { aviso.textContent = 'No hay trabajo registrado en esos campos y fechas.'; return; }
  aviso.textContent = `Generando ${tipo === 'pdf' ? 'PDF' : 'Excel'}…`;
  try {
    if (tipo === 'pdf') await informePdf(campos, desde, hasta); else await informeExcel(campos, desde, hasta);
    aviso.textContent = 'Listo: el archivo se descargó.';
  } catch (e) {
    aviso.textContent = 'No se pudo generar el informe: ' + e.message;
  }
}
