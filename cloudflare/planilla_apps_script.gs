/**
 * Planilla "Operación CYH" <-> app Flota C&H (sincronizada en los dos sentidos).
 * Pedido del usuario 4-nov-2026 (vista rehecha el mismo día, con las columnas de la
 * planilla antigua). Reglas en CLAUDE.md ("Planilla de Google Operación CYH").
 *
 *  - Pestaña Operación: Máquina · Implemento · Operador · Campo · Ubicación ·
 *    Fecha término · Destino · Calza GPS, en dos grupos con título:
 *      🟢 EN OPERACIÓN (fuera de CYH): campo anotado distinto de Taller.
 *      ⚪ RESTO (Taller / CYH): todas las demás.
 *    En cada grupo: tractores, shakers, shakers de suelo, recogedoras y podadora,
 *    y al final barredoras. Al cambiar el campo la fila sube o baja sola.
 *    Ubicación, Fecha término (de la Agenda) y Calza GPS son de solo lectura (gris,
 *    protegidas con aviso); si se editan, se vuelve a dibujar la hoja.
 *  - Pestaña Registro: la última modificación de cada máquina (fecha, hora y si
 *    fue App o Planilla). El historial completo queda en la app (D1).
 *  - Planilla -> App: al editar Implemento, Operador, Campo o Destino (o la pestaña
 *    Campos) se manda al Worker de Cloudflare al momento, con el PIN guardado en las
 *    Propiedades del script (nunca a la vista). Cambiar el campo deja el "Desde" de
 *    la app en automático (igual que en la app).
 *  - App -> Planilla: el Worker manda cada guardado de la app a esta misma planilla
 *    (doPost, "Aplicación web"), con una clave al azar que este script genera y
 *    registra en el Worker (con el PIN) al ejecutar "instalar".
 *  - Cada 5 minutos se trae todo desde la app (por si algo no llegó), el GPS y las
 *    listas desplegables.
 *  - Operador y Campo (10-nov-2026): un nombre igual a uno de la lista salvo mayúsculas,
 *    tildes o espacios se cambia solo al de la lista; uno parecido queda en amarillo con
 *    la nota "¿Es X?"; uno nuevo queda en la lista para las próximas veces.
 *  - Gana el último cambio; si el mismo dato se cambió en los dos lados en menos de
 *    2 min, la app muestra un aviso. El historial guarda el origen (App/Planilla).
 *
 * Propiedades del script (Configuración del proyecto -> Propiedades del script):
 *   PIN      el PIN de edición de la app (lo escribe el usuario; nunca va en el código)
 *   URL_WEB  la dirección de la "Aplicación web" (termina en /exec)
 *   CLAVE    la crea sola "instalar" (no tocar)
 */

const WORKER = 'https://disparador-reporte.dawn-band-fd6c.workers.dev';
const DATOS = 'https://jpfernandez428.github.io/reporte-hectareas/datos/';
const HOJA_OP = 'Operación', HOJA_CAMPOS = 'Campos', HOJA_LISTAS = 'Listas', HOJA_REGISTRO = 'Registro';
const ENCABEZADO_OP = ['Máquina', 'Implemento', 'Operador', 'Campo', 'Ubicación', 'Fecha término', 'Destino', 'Calza GPS'];
const ENCABEZADO_CAMPOS = ['Campo', 'Labor', 'Ha aprox.', 'Última modificación'];
const ENCABEZADO_REGISTRO = ['Máquina', 'Última modificación'];
// Columna (1 = A) -> dato de la app. A, E, F y H las escribe la app.
const COLUMNAS = { 2: 'implemento', 3: 'operador', 4: 'campo', 7: 'destino' };
const SOLO_LECTURA_OP = [1, 5, 6, 8];
const NCOL = ENCABEZADO_OP.length;
const TZ_CHILE = 'America/Santiago';
// Orden de los tipos dentro de cada grupo (pedido del usuario).
const ORDEN_TIPOS = ['Tractores', 'Shacker SBS', 'Shaker Orchard Rite', 'Shacker de Suelo', 'Recogedoras', 'Podadora', 'Barredoras'];
const TITULO_OP = '🟢 EN OPERACIÓN (fuera de CYH)', TITULO_RESTO = '⚪ RESTO (Taller / CYH)';
const COLOR = {
  encabezado: '#1f4d2b', tituloOp: '#b7e1cd', tituloResto: '#d9d9d9', soloLectura: '#eeeeee', textoGris: '#5f6368',
  bien: '#137333', ojo: '#b06000', mal: '#c5221f',
};
const CACHE_SEG = 21600;  // 6 h (se renueva cada 5 min)

// ---------------------------------------------------------------------------
// Menú e instalación
// ---------------------------------------------------------------------------
function onOpen() {
  SpreadsheetApp.getUi().createMenu('Operación CYH')
    .addItem('Traer todo desde la app', 'sincronizar')
    .addItem('Reintentar envíos pendientes', 'reintentarPendientes')
    .addSeparator()
    .addItem('Instalar / reinstalar', 'instalar')
    .addToUi();
}

function instalar() {
  const p = PropertiesService.getScriptProperties();
  if (!p.getProperty('PIN')) return mensaje('Falta la propiedad PIN (Configuración del proyecto → Propiedades del script).');
  const url = (p.getProperty('URL_WEB') || '').trim();
  if (!/^https:\/\/script\.google\.com\/macros\/s\/[\w-]+\/exec$/.test(url)) {
    return mensaje('Falta la propiedad URL_WEB: la dirección de la Aplicación web (Implementar → Gestionar implementaciones), que termina en /exec.');
  }
  // Activadores: al editar (instalable, puede llamar a internet) y cada 5 minutos.
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  const ss = SpreadsheetApp.getActive();
  ScriptApp.newTrigger('alEditar').forSpreadsheet(ss).onEdit().create();
  ScriptApp.newTrigger('sincronizar').timeBased().everyMinutes(5).create();
  // Clave al azar para que solo el Worker pueda escribir aquí (App -> Planilla).
  let clave = p.getProperty('CLAVE');
  if (!clave) {
    clave = (Utilities.getUuid() + Utilities.getUuid()).replace(/-/g, '');
    p.setProperty('CLAVE', clave);
  }
  const r = llamarWorker({ tipo: 'registrar', url: url, clave: clave });
  if (!r.ok) return mensaje('No se pudo conectar con la app: ' + r.error + '. Revisa el PIN y que el Worker nuevo y la base D1 estén listos en Cloudflare, y vuelve a ejecutar "instalar".');
  p.deleteProperty('VISTA');
  preparar();
  sincronizar();
  mensaje('Listo: la planilla quedó conectada con la app. Los cambios van y vienen en segundos.');
}

// Formato fijo, listas desplegables y protección (con aviso) de las columnas que escribe la app.
function preparar() {
  const op = hoja(HOJA_OP, ENCABEZADO_OP), campos = hoja(HOJA_CAMPOS, ENCABEZADO_CAMPOS);
  const listas = hoja(HOJA_LISTAS, ['Operadores', 'Campos']), registro = hoja(HOJA_REGISTRO, ENCABEZADO_REGISTRO);
  // La vista anterior (Desde, Próximo destino, GPS, Última modificación) se reemplaza entera.
  op.getRange(1, 1, 1, Math.max(op.getMaxColumns(), NCOL)).clearContent();
  op.getRange(1, 1, 1, NCOL).setValues([ENCABEZADO_OP]);
  if (op.getMaxColumns() > NCOL) op.getRange(1, NCOL + 1, op.getMaxRows(), op.getMaxColumns() - NCOL).clear();
  actualizarListas();
  listas.hideSheet();
  [op, campos, registro].forEach(h => {
    h.setFrozenRows(1);
    h.getRange(1, 1, 1, h.getLastColumn()).setFontWeight('bold').setBackground(COLOR.encabezado).setFontColor('#ffffff');
  });
  op.setFrozenColumns(0);  // los títulos de grupo van combinados de A a H (Sheets no combina con una columna fija)
  campos.getRange(2, 1, 1000, 1).setDataValidation(regla(listas, 2));
  campos.getRange(2, 3, 1000, 1).setNumberFormat('0.##');
  campos.getRange(2, 4, 1000, 1).setFontColor('#666666').setBackground('#f3f3f3');
  registro.getRange(2, 1, 1000, 2).setFontColor(COLOR.textoGris).setBackground(COLOR.soloLectura);
  [[1, 230], [2, 150], [3, 150], [4, 170], [5, 150], [6, 110], [7, 150], [8, 190]].forEach(([c, w]) => op.setColumnWidth(c, w));
  campos.setColumnWidth(1, 200); campos.setColumnWidth(2, 160); campos.setColumnWidth(4, 160);
  registro.setColumnWidth(1, 230); registro.setColumnWidth(2, 200);
  // Protección: Máquina, Ubicación, Fecha término y Calza GPS (y la pestaña Registro) muestran
  // un aviso antes de editarlas; si igual se editan, la hoja se vuelve a dibujar.
  [op, campos, registro].forEach(h => h.getProtections(SpreadsheetApp.ProtectionType.RANGE)
    .filter(x => x.getDescription() === 'Lo escribe la app').forEach(x => x.remove()));
  [op.getRange('A:A'), op.getRange('E:F'), op.getRange('H:H'), registro.getRange('A:B')]
    .forEach(r => r.protect().setDescription('Lo escribe la app').setWarningOnly(true));
  const pr = campos.getRange('D:D').protect().setDescription('Lo escribe la app');
  pr.removeEditors(pr.getEditors());
  if (pr.canDomainEdit()) pr.setDomainEdit(false);
}

// Operador y Campo: lista desplegable, pero se acepta un nombre nuevo (la app pregunta si se parece a uno existente).
function regla(listas, col) {
  return SpreadsheetApp.newDataValidation().requireValueInRange(listas.getRange(2, col, 600, 1), true).setAllowInvalid(true).build();
}

// ---------------------------------------------------------------------------
// Planilla -> App (al editar)
// ---------------------------------------------------------------------------
function alEditar(e) {
  if (!e || !e.range) return;
  const h = e.range.getSheet(), nombre = h.getName();
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) return aviso('La planilla está ocupada: vuelve a editar la celda en unos segundos.');
  try {
    if (nombre === HOJA_CAMPOS) { if (e.range.getRow() >= 2) enviarCampos(e); return; }
    if (nombre === HOJA_REGISTRO) {
      if (e.range.getNumRows() === 1 && e.range.getNumColumns() === 1) e.range.setValue(e.oldValue === undefined ? '' : e.oldValue);
      return aviso('La pestaña Registro la escribe la app.');
    }
    if (nombre !== HOJA_OP) return;
    const est = estadoGuardado();
    if (!est) { traerDesdeApp(); return aviso('No se pudo leer la app: se volvió a traer todo. Si el cambio no quedó, edítalo de nuevo.'); }
    const r0 = e.range.getRow(), c0 = e.range.getColumn(), nr = e.range.getNumRows(), nc = e.range.getNumColumns();
    const maquinas = h.getRange(r0, 1, nr, 1).getValues().map(x => String(x[0] || '').trim());
    const filaDeMaquina = maquinas.map(m => !!est.maquinas[m]);
    // Encabezado, títulos de grupo y columnas de solo lectura: se vuelve a dibujar (se deshace lo editado).
    if (r0 < 2 || filaDeMaquina.some(x => !x) || SOLO_LECTURA_OP.some(c => c >= c0 && c < c0 + nc)) {
      dibujar(est);
      return aviso('Máquina, Ubicación, Fecha término, Calza GPS y los títulos los escribe la app: no se cambió nada.');
    }
    const valores = e.range.getValues();
    const cambios = [], avisos = [];
    const sug = sugerencias(), listas = listasDeLaHoja();
    for (let i = 0; i < nr; i++) {
      const m = maquinas[i];
      for (let j = 0; j < nc; j++) {
        const k = COLUMNAS[c0 + j];
        if (!k) continue;
        let v = String(valores[i][j] == null ? '' : valores[i][j]).trim();
        if (k === 'operador' || k === 'campo') v = revisarNombre(m, k, v, listas[k], sug, avisos);
        cambios.push({ maquina: m, k: k, valor: v });
        // Cambiar de campo deja el "Desde" en automático (llegada al campo según el GPS), como en la app.
        if (k === 'campo' && v !== String(est.maquinas[m].campo || '').trim()) cambios.push({ maquina: m, k: 'desde', valor: '' });
      }
    }
    guardarSugerencias(sug);
    const ok = cambios.length ? enviarOperacion(cambios, !avisos.length, est) : true;
    if (avisos.length && ok) aviso(avisos.join(' · ') + ' · Guardado en la app ✓', 15);
  } finally { lock.releaseLock(); }
}

// ---------------------------------------------------------------------------
// Nombres de campo y operador escritos en la planilla (pedido del usuario 10-nov-2026)
//  (a) igual a uno de la lista salvo mayúsculas, tildes o espacios -> se usa el de la lista;
//  (b) parecido a uno de la lista -> se guarda tal cual, la celda queda amarilla con una nota
//      "¿Es X?" (si se vuelve a escribir lo mismo, es un nombre nuevo y se quita el amarillo);
//  (c) nuevo -> se guarda y queda en la lista desplegable (la lista suma todo lo anotado).
// ---------------------------------------------------------------------------
function revisarNombre(m, k, v, lista, sug, avisos) {
  const id = m + '|' + k;
  if (!v || esTaller(v)) { delete sug[id]; return v; }
  const igual = lista.find(x => clave(x) === clave(v));
  if (igual) {
    delete sug[id];
    if (igual !== v) avisos.push(`Se usó «${igual}» (ya existía)`);
    return igual;
  }
  if (sug[id] && clave(sug[id].valor) === clave(v)) { delete sug[id]; avisos.push(`«${v}» quedó como ${k === 'campo' ? 'campo' : 'operador'} nuevo`); return v; }
  const mejor = lista.map(x => ({ x: x, p: Math.max(parecido(v, x), k === 'operador' && mismoPrimerNombre(v, x) ? 0.8 : 0) }))
    .filter(o => o.p >= 0.75).sort((a, b) => b.p - a.p)[0];
  if (mejor) {
    sug[id] = { valor: v, sugerido: mejor.x, ts: Date.now() };
    avisos.push(`¿«${v}» es «${mejor.x}»? Quedó en amarillo: si es el mismo, elígelo de la lista; si es nuevo, vuelve a escribir «${v}»`);
  } else delete sug[id];
  return v;
}
function listasDeLaHoja() {
  const h = hoja(HOJA_LISTAS, ['Operadores', 'Campos']);
  const n = Math.max(h.getLastRow() - 1, 0);
  const vals = n ? h.getRange(2, 1, n, 2).getValues() : [];
  return { operador: vals.map(r => String(r[0]).trim()).filter(Boolean), campo: vals.map(r => String(r[1]).trim()).filter(Boolean) };
}
function sugerencias() { return JSON.parse(PropertiesService.getScriptProperties().getProperty('SUGERENCIAS') || '{}'); }
function guardarSugerencias(sug) {
  // Se olvidan solas a los 7 días.
  Object.keys(sug).forEach(id => { if (Date.now() - (sug[id].ts || 0) > 7 * 86400000) delete sug[id]; });
  PropertiesService.getScriptProperties().setProperty('SUGERENCIAS', JSON.stringify(sug));
}
function parecido(a, b) {
  a = clave(a); b = clave(b);
  if (!a || !b) return 0;
  if (a === b) return 1;
  if (a.indexOf(b) >= 0 || b.indexOf(a) >= 0) return 0.9;
  const d = [];
  for (let i = 0; i <= a.length; i++) { d[i] = [i]; }
  for (let j = 1; j <= b.length; j++) d[0][j] = j;
  for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
    d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
  return 1 - d[a.length][b.length] / Math.max(a.length, b.length);
}
function mismoPrimerNombre(a, b) {
  const ta = sinT(a).split(/\s+/), tb = sinT(b).split(/\s+/);
  return !!ta[0] && ta[0] === tb[0] && (ta.length === 1 || tb.length === 1 || (ta[1] || '')[0] === (tb[1] || '')[0]);
}

function enviarOperacion(cambios, avisar, est) {
  est = est || estadoGuardado();
  const r = llamarWorker({ tipo: 'operacion', cambios: cambios, id: nuevoId() });
  if (r.ok) {
    const d = r.datos;
    const nuevo = d.maquinas ? { maquinas: d.maquinas, agenda: d.agenda || (est && est.agenda) || [] }
                             : unirFilas(est, Object.values(d.filas || {}));
    guardarEstado(nuevo);
    dibujar(nuevo);
    const ultima = {};
    Object.keys(d.filas || {}).forEach(m => { ultima[m] = d.ultima || ''; });
    escribirRegistro(ultima);
    if (avisar) aviso(d.conflictos_nuevos ? 'Guardado. Ojo: ese dato también se cambió en la app hace menos de 2 min (aviso en la app).' : 'Guardado en la app ✓');
    return true;
  }
  if (r.pin || r.estado === 400) {
    aviso(r.pin ? 'PIN incorrecto: no se guardó (revisa la propiedad PIN).' : 'No se guardó: ' + r.error);
    if (est) dibujar(est); else traerDesdeApp();
    return false;
  }
  // Sin conexión: queda pendiente (se ve en la hoja) y se reintenta solo cada 5 minutos.
  const p = PropertiesService.getScriptProperties();
  const pend = JSON.parse(p.getProperty('PENDIENTES') || '[]').concat(cambios).slice(-300);
  p.setProperty('PENDIENTES', JSON.stringify(pend));
  if (est) dibujar(conPendientes(est));
  if (avisar) aviso('Sin conexión con la app: el cambio se enviará solo.');
  return false;
}

function reintentarPendientes() {
  const p = PropertiesService.getScriptProperties();
  const pend = JSON.parse(p.getProperty('PENDIENTES') || '[]');
  if (!pend.length) return;
  p.deleteProperty('PENDIENTES');
  enviarOperacion(pend, false);
}

// Pestaña Campos: se manda completa (campo + labor + ha aprox.).
function enviarCampos(e) {
  const h = SpreadsheetApp.getActive().getSheetByName(HOJA_CAMPOS);
  if (e && e.range.getColumn() + e.range.getNumColumns() - 1 >= 4 && e.range.getColumn() <= 4) {
    if (e.range.getNumRows() === 1 && e.range.getNumColumns() === 1) e.range.setValue(e.oldValue === undefined ? '' : e.oldValue);
    aviso('Esa columna la escribe la app.');
    return;
  }
  const filas = [];
  const vals = h.getLastRow() > 1 ? h.getRange(2, 1, h.getLastRow() - 1, 3).getValues() : [];
  for (const [campo, labor, ha] of vals) {
    if (!String(campo).trim()) continue;
    const t = ha === '' || ha == null ? '' : String(Math.round(Number(String(ha).replace(',', '.')) * 100) / 100);
    if (t === 'NaN') { aviso(`Ha aprox. no válida en ${campo}: escribe solo el número.`); return; }
    filas.push({ campo: String(campo).trim(), labor: String(labor || '').trim(), ha: t });
  }
  const r = llamarWorker({ tipo: 'ha', filas: filas, id: nuevoId() });
  if (r.ok) {
    if (e) h.getRange(e.range.getRow(), 4, e.range.getNumRows(), 1).setValue(r.datos.ultima || '');
    aviso('Ha aprox. guardadas en la app ✓');
  } else aviso('No se guardaron las ha aprox.: ' + r.error + ' (vuelve a editar la celda para reintentar).');
}

// ---------------------------------------------------------------------------
// App -> Planilla (el Worker llama aquí con la clave)
// ---------------------------------------------------------------------------
function doPost(e) {
  let d;
  try { d = JSON.parse(e.postData.contents); } catch (x) { return json({ ok: false, error: 'json' }); }
  const clave = PropertiesService.getScriptProperties().getProperty('CLAVE') || '';
  if (!clave || !igual(String(d.clave || ''), clave)) return json({ ok: false, error: 'clave' });
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) return json({ ok: false, error: 'ocupado' });
  try {
    const filas = (Array.isArray(d.filas) ? d.filas : []).filter(f => f && f.maquina);
    const est = estadoGuardado();
    if (est) {
      const nuevo = unirFilas(est, filas);
      guardarEstado(nuevo);
      dibujar(conPendientes(nuevo));
    } else traerDesdeApp();
    const ultima = {};
    filas.forEach(f => { ultima[f.maquina] = String(d.ultima || ''); });
    escribirRegistro(ultima);
  } finally { lock.releaseLock(); }
  return json({ ok: true });
}

function doGet() { return json({ ok: true, planilla: 'Operación CYH' }); }

// ---------------------------------------------------------------------------
// Cada 5 minutos: pendientes, todo desde la app, GPS y listas
// ---------------------------------------------------------------------------
function sincronizar() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return;
  try {
    reintentarPendientes();
    traerDesdeApp(true);
    actualizarListas();
  } finally { lock.releaseLock(); }
}

// Lee la app (D1 o lo publicado), arma el GPS de cada máquina y dibuja todo.
let ESTADO_LEIDO = null;  // lo último leído de la app en esta ejecución (cambios y nombres quitados)
function traerDesdeApp(conGps) {
  const estado = leerJson(WORKER + '/estado');
  let est, ha = null, cambios = [];
  if (estado && estado.d1) {
    ESTADO_LEIDO = estado;
    est = { maquinas: estado.maquinas, agenda: estado.agenda || [] };
    ha = estado.ha_aprox; cambios = estado.cambios || [];
  } else {
    const op = leerJson(DATOS + 'operacion.json');
    if (!op) return;
    est = { maquinas: op.maquinas, agenda: Object.values((leerJson(DATOS + 'agenda.json') || {}).trabajos || {}) };
    ha = Object.values(op.ha_aprox || {});
  }
  guardarEstado(est);
  if (conGps || !infoGuardada()) construirInfo();
  dibujar(conPendientes(est));
  // Registro: lo más reciente del historial de la app por máquina.
  const ultima = {};
  for (const c of cambios) if (!ultima[c.maquina]) ultima[c.maquina] = `${horaChile(c.ts)} · ${c.origen || 'App'}`;
  escribirRegistro(ultima, Object.keys(est.maquinas));
  if (ha) escribirCampos(ha, est.maquinas, (leerJson(DATOS + 'reporte_v2.json') || {}).v2 || {});
}

// GPS, orden y nombres de los campos (se guarda 6 h en la caché del script; se renueva cada 5 min).
function construirInfo() {
  const v2 = (leerJson(DATOS + 'reporte_v2.json') || {}).v2 || {};
  const campos = leerJson(DATOS + 'campos.json') || {};
  const vivo = leerJson(WORKER + '/gps?guardado=1');
  const patio = vivo && vivo.maquinas ? (leerJson(DATOS + 'flota.json') || {}).patio : null;
  const info = infoDesde(v2, campos, vivo, patio, Date.now());
  CacheService.getScriptCache().put('INFO', JSON.stringify(info), CACHE_SEG);
  return info;
}

// Dibuja la pestaña Operación (solo si cambió algo desde la última vez).
function dibujar(est) {
  const info = infoGuardada() || construirInfo();
  const v = armarVista(est.maquinas, est.agenda || [], info, hoyChile());
  const notas = marcarSugerencias(v);
  const h = hoja(HOJA_OP, ENCABEZADO_OP);
  const p = PropertiesService.getScriptProperties();
  const firma = Utilities.base64Encode(Utilities.computeDigest(Utilities.DigestAlgorithm.MD5, JSON.stringify([v.valores, v.tipos, notas]), Utilities.Charset.UTF_8));
  const n = v.valores.length, total = Math.max(h.getMaxRows() - 1, n);
  if (p.getProperty('VISTA') === firma && h.getLastRow() === n + 1 && sinCambiosAMano(h, v)) return;
  if (h.getMaxRows() < n + 1) h.insertRowsAfter(h.getMaxRows(), n + 1 - h.getMaxRows());
  const todo = h.getRange(2, 1, total, NCOL);
  todo.breakApart();
  todo.clearContent().clearDataValidations().clearNote().setBackground(null).setFontWeight('normal').setFontColor(null).setFontSize(10);
  const r = h.getRange(2, 1, n, NCOL);
  r.setNumberFormat('@');  // texto tal cual (que Sheets no convierta fechas ni números)
  r.setValues(v.valores).setBackgrounds(v.fondos).setFontColors(v.colores).setFontWeights(v.negritas);
  h.getRange(2, 3, n, 2).setNotes(notas);
  const listas = hoja(HOJA_LISTAS, ['Operadores', 'Campos']);
  const rOp = regla(listas, 1), rCampo = regla(listas, 2);
  h.getRange(2, 3, n, 2).setDataValidations(v.tipos.map(t => t === 'maquina' ? [rOp, rCampo] : [null, null]));
  v.tipos.forEach((t, i) => {
    if (t !== 'tituloOp' && t !== 'tituloResto') return;
    h.getRange(i + 2, 1, 1, NCOL).merge().setFontSize(11).setVerticalAlignment('middle');
    h.setRowHeight(i + 2, 28);
  });
  p.setProperty('VISTA', firma);
}

// Celdas de Operador/Campo con un nombre parecido a uno de la lista: amarillo y nota "¿Es X?".
function marcarSugerencias(v) {
  const sug = sugerencias();
  const vistas = {};
  const notas = v.valores.map((f, i) => [3, 4].map(c => {
    if (v.tipos[i] !== 'maquina') return '';
    const k = c === 3 ? 'operador' : 'campo', id = f[0] + '|' + k, s = sug[id];
    if (!s || clave(s.valor) !== clave(f[c - 1])) return '';
    vistas[id] = true;
    v.fondos[i][c - 1] = '#fff2cc';
    return `¿Es «${s.sugerido}»? Si es el mismo, elígelo de la lista. Si es ${k === 'campo' ? 'un campo nuevo' : 'un operador nuevo'}, vuelve a escribir «${s.valor}» y se quita el amarillo.`;
  }));
  // Las que ya no calzan (se cambió el valor desde la app o la planilla) se olvidan.
  if (Object.keys(sug).some(id => !vistas[id])) { Object.keys(sug).forEach(id => { if (!vistas[id]) delete sug[id]; }); guardarSugerencias(sug); }
  return notas;
}

// Si alguien escribió a mano en la hoja (columna Máquina distinta), se vuelve a dibujar aunque la firma calce.
function sinCambiosAMano(h, v) {
  const a = h.getRange(2, 1, v.valores.length, 1).getValues();
  return v.valores.every((f, i) => String(a[i][0]) === String(f[0]));
}

function escribirCampos(ha, maquinas, v2) {
  const h = hoja(HOJA_CAMPOS, ENCABEZADO_CAMPOS);
  const n = Math.max(h.getLastRow() - 1, 0);
  const actual = n ? h.getRange(2, 1, n, 4).getValues() : [];
  const clave = (c, l) => String(c).trim().toLowerCase() + '|' + String(l).trim().toLowerCase();
  const idx = {};
  actual.forEach((r, i) => { idx[clave(r[0], r[1])] = i; });
  for (const x of ha) {
    const k = clave(x.campo, x.labor);
    if (idx[k] === undefined) { idx[k] = actual.length; actual.push([x.campo, x.labor, '', '']); }
    const r = actual[idx[k]];
    r[2] = x.ha === '' ? '' : Number(x.ha);
    if (x.ts) r[3] = `${horaChile(x.ts)} · ${x.origen || 'Planilla'}`;
  }
  // Campo + labor de las maquinas que estan en un campo (para anotar sus ha aprox.).
  const labor = {};
  (v2.unidades || []).forEach(u => { labor[u.maquina] = u.labor; });
  Object.keys(maquinas).forEach(m => {
    const c = String(maquinas[m].campo || '').trim();
    if (!c || /^(taller|cyh)/i.test(c) || !labor[m]) return;
    const k = clave(c, labor[m]);
    if (idx[k] === undefined) { idx[k] = actual.length; actual.push([c, labor[m], '', '']); }
  });
  const antes = n ? h.getRange(2, 1, n, 4).getValues() : [];
  if (actual.length !== antes.length || actual.some((r, i) => r.some((v, j) => String(v) !== String(antes[i][j])))) {
    h.getRange(2, 1, actual.length, 4).setValues(actual);
  }
}

// Pestaña Registro: Máquina | Última modificación (fecha y hora · App o Planilla).
function escribirRegistro(ultima, todas) {
  const h = hoja(HOJA_REGISTRO, ENCABEZADO_REGISTRO);
  const n = Math.max(h.getLastRow() - 1, 0);
  const actual = n ? h.getRange(2, 1, n, 2).getValues().map(r => [String(r[0]), String(r[1])]) : [];
  const idx = {};
  actual.forEach((r, i) => { idx[r[0]] = i; });
  (todas || []).concat(Object.keys(ultima)).forEach(m => {
    if (idx[m] === undefined) { idx[m] = actual.length; actual.push([m, '']); }
    if (ultima[m]) actual[idx[m]][1] = ultima[m];
  });
  if (!actual.length) return;
  const antes = n ? h.getRange(2, 1, n, 2).getDisplayValues() : [];
  if (actual.length !== antes.length || actual.some((r, i) => r[0] !== antes[i][0] || r[1] !== antes[i][1])) {
    h.getRange(2, 1, actual.length, 2).setNumberFormat('@').setValues(actual);
  }
}

// Listas desplegables (10-nov-2026): los campos de Wialon y sus equivalencias, los operadores
// conocidos, y todo lo anotado alguna vez en Operación (un nombre nuevo queda en la lista),
// menos los nombres quitados desde la app (🗑, con PIN).
function actualizarListas() {
  const v2 = (leerJson(DATOS + 'reporte_v2.json') || {}).v2 || {};
  const campos = leerJson(DATOS + 'campos.json') || {};
  const usados = nombresUsados();
  const q = quitadosDeLaApp();
  const ops = [];
  ((v2.operadores || {}).lista || []).forEach(o => { ops.push(o.operador); (o.otros_nombres || []).forEach(x => ops.push(x)); });
  const nl = campos.nombres_lista || {};
  const wialon = (campos.campos || []).filter(c => nl[c]);
  const manuales = Object.keys(campos.equivalencias || {}).concat(usados.campo);
  // Un nombre igual a otro salvo mayúsculas o tildes aparece una sola vez (gana el primero: Wialon, luego lo más usado).
  const unico = l => {
    const vistos = {}, salida = [];
    l.forEach(x => { x = String(x || '').trim(); const k = clave(x); if (k && !vistos[k] && !esTaller(x)) { vistos[k] = true; salida.push(x); } });
    return salida.sort((a, b) => a.localeCompare(b, 'es'));
  };
  const a = unico(ops.concat(usados.operador).filter(x => !q.operador[clave(x)]));
  const b = ['Taller'].concat(unico(wialon.concat(manuales.filter(x => !q.campo[clave(x)]))));
  if (!a.length && b.length < 2) return;  // sin datos publicados: se deja lo anterior
  const h = hoja(HOJA_LISTAS, ['Operadores', 'Campos']);
  const filas = Math.max(a.length, b.length);
  h.getRange(2, 1, Math.max(h.getMaxRows() - 1, 1), 2).clearContent();
  h.getRange(2, 1, filas, 2).setValues(Array.from({ length: filas }, (_, i) => [a[i] || '', b[i] || '']));
}

// Nombres anotados alguna vez en Operación (foto diaria, historial y hoy), el más usado primero.
function nombresUsados() {
  const cuenta = { operador: {}, campo: {} };
  const sumar = (k, v, peso) => { v = String(v || '').trim(); if (v && v.length <= 80) cuenta[k][v] = (cuenta[k][v] || 0) + peso; };
  const foto = (leerJson(DATOS + 'operadores.json') || {}).dias || {};
  Object.keys(foto).forEach(d => Object.keys(foto[d]).forEach(m => { sumar('operador', foto[d][m].operador, 1); sumar('campo', foto[d][m].campo, 1); }));
  const cambios = (leerJson(DATOS + 'operacion_cambios.json') || []).concat((ESTADO_LEIDO && ESTADO_LEIDO.cambios) || []);
  cambios.forEach(c => { const k = c.cambio === 'Operador' ? 'operador' : c.cambio === 'Campo' ? 'campo' : ''; if (k) { sumar(k, c.antes, 1); sumar(k, c.despues, 1); } });
  const est = ESTADO_LEIDO || {};
  Object.keys(est.maquinas || {}).forEach(m => { sumar('operador', est.maquinas[m].operador, 3); sumar('campo', est.maquinas[m].campo, 3); });
  const orden = k => Object.keys(cuenta[k]).sort((a, b) => cuenta[k][b] - cuenta[k][a]);
  return { operador: orden('operador'), campo: orden('campo') };
}
// Nombres quitados de la lista desde la app: lo publicado + lo guardado al instante en Cloudflare.
function quitadosDeLaApp() {
  const q = { operador: {}, campo: {} };
  const pub = leerJson(DATOS + 'nombres_quitados.json') || {};
  ['operador', 'campo'].forEach(t => (pub[t] || []).forEach(x => { q[t][clave(x.nombre)] = true; }));
  const acc = ((ESTADO_LEIDO && ESTADO_LEIDO.acciones) || []).filter(a => a.tipo === 'equivalencia' || a.tipo === 'borrar_equivalencia')
    .sort((a, b) => a.ts - b.ts);
  acc.forEach(a => {
    let d = {}; try { d = typeof a.datos === 'string' ? JSON.parse(a.datos) : (a.datos || {}); } catch (x) { return; }
    ['operador', 'campo'].forEach(t => {
      if (clave(d.planilla) !== clave('lista-quitar: ' + t)) return;
      if (a.tipo === 'equivalencia') q[t][clave(d.campo)] = true; else delete q[t][clave(d.campo)];
    });
  });
  return q;
}

// ---------------------------------------------------------------------------
// Estado guardado (caché del script)
// ---------------------------------------------------------------------------
function estadoGuardado() {
  const t = CacheService.getScriptCache().get('ESTADO');
  if (t) return JSON.parse(t);
  traerDesdeApp();
  const u = CacheService.getScriptCache().get('ESTADO');
  return u ? JSON.parse(u) : null;
}
function guardarEstado(est) { CacheService.getScriptCache().put('ESTADO', JSON.stringify(est), CACHE_SEG); }
function infoGuardada() {
  const t = CacheService.getScriptCache().get('INFO');
  return t ? JSON.parse(t) : null;
}
function unirFilas(est, filas) {
  const maquinas = Object.assign({}, (est && est.maquinas) || {});
  filas.forEach(f => {
    const m = f.maquina;
    maquinas[m] = Object.assign({}, maquinas[m] || {}, { implemento: f.implemento || '', operador: f.operador || '',
      campo: f.campo || '', desde: f.desde || '', destino: f.destino || '' });
  });
  return { maquinas: maquinas, agenda: (est && est.agenda) || [] };
}
// Lo que se editó sin conexión se ve en la hoja mientras se reintenta.
function conPendientes(est) {
  const pend = JSON.parse(PropertiesService.getScriptProperties().getProperty('PENDIENTES') || '[]');
  if (!pend.length) return est;
  const maquinas = JSON.parse(JSON.stringify(est.maquinas));
  pend.forEach(c => { if (maquinas[c.maquina]) maquinas[c.maquina][c.k] = c.valor; });
  return { maquinas: maquinas, agenda: est.agenda };
}

// ---------------------------------------------------------------------------
// Armado de la vista (sin llamadas a Google: se puede probar aparte)
// ---------------------------------------------------------------------------
// info: {orden: [[maquina, tipo]], gps: {maquina: {lugar, comuna, dias, cercano: [campo, km]}},
//        nombres: {campo interno: nombre para mostrar}, eq: {nombre: [campos de Wialon]}}
function infoDesde(v2, campos, vivo, patio, ahora) {
  const gps = {};
  Object.entries(v2.gps_maquinas || {}).forEach(([m, g]) => {
    const c = (g.cercanos || [])[0];
    gps[m] = { lugar: g.lugar || '', comuna: g.comuna || '', dias: g.dias_sin_senal == null ? null : g.dias_sin_senal,
               cercano: c ? [c.campo, c.km] : null, lat: g.lat, lon: g.lon };
  });
  // GPS al momento (lo último que consultó la app, sin volver a preguntar a Wialon): días sin señal y CYH.
  Object.entries((vivo && vivo.maquinas) || {}).forEach(([m, x]) => {
    if (!x || !x.t) return;
    const g = gps[m] || (gps[m] = { lugar: '', comuna: '', dias: null, cercano: null });
    g.dias = Math.floor((ahora / 1000 - x.t) / 86400);
    const lejos = g.lat == null || distanciaM(x.lat, x.lon, g.lat, g.lon) > 2000;
    if (patio && dentro(x.lon, x.lat, patio)) Object.assign(g, { lugar: 'CYH', comuna: '' });
    else if ((patio && g.lugar === 'CYH') || (lejos && g.lugar === 'fuera de geocercas')) Object.assign(g, { lugar: 'fuera de geocercas', comuna: comunaDe(x.dir) || g.comuna, cercano: null });
    else if (lejos && comunaDe(x.dir)) g.comuna = comunaDe(x.dir);
    delete g.lat; delete g.lon;
  });
  Object.values(gps).forEach(g => { delete g.lat; delete g.lon; });
  return { orden: (v2.unidades || []).map(u => [u.maquina, u.grupo]), gps: gps,
           nombres: campos.nombres_lista || {}, eq: campos.equivalencias || {} };
}

// Devuelve las filas de la hoja (desde la fila 2) con sus colores y el tipo de cada fila.
function armarVista(maquinas, agenda, info, hoy) {
  const tipoDe = {};
  info.orden.forEach(([m, t], i) => { tipoDe[m] = [t, i]; });
  const lista = Object.keys(maquinas).sort((a, b) => {
    const [ta, ia] = tipoDe[a] || ['', 1e6], [tb, ib] = tipoDe[b] || ['', 1e6];
    const oa = ORDEN_TIPOS.indexOf(ta), ob = ORDEN_TIPOS.indexOf(tb);
    return ((oa < 0 ? 99 : oa) - (ob < 0 ? 99 : ob)) || (ia - ib) || a.localeCompare(b, 'es', { numeric: true });
  });
  const enOperacion = m => { const c = String(maquinas[m].campo || '').trim(); return !!c && !esTaller(c); };
  const op = lista.filter(enOperacion), resto = lista.filter(m => !enOperacion(m));
  const v = { valores: [], fondos: [], colores: [], negritas: [], tipos: [] };
  const fila = (valores, fondos, colores, negritas, tipo) => {
    v.valores.push(valores); v.fondos.push(fondos); v.colores.push(colores); v.negritas.push(negritas); v.tipos.push(tipo);
  };
  const titulo = (texto, tipo, color) => fila([texto].concat(Array(NCOL - 1).fill('')), Array(NCOL).fill(color),
    Array(NCOL).fill('#1f1f1f'), Array(NCOL).fill('bold'), tipo);
  const maquina = m => {
    const d = maquinas[m], g = info.gps[m];
    const calza = calzaGps(d.campo, g, info);
    const valores = [m, d.implemento || '', d.operador || '', d.campo || '', ubicacion(g, info),
                     fechaChile(terminoAgenda(d.campo, agenda, info, hoy)), d.destino || '', calza];
    const fondos = valores.map((_, j) => SOLO_LECTURA_OP.indexOf(j + 1) >= 0 ? COLOR.soloLectura : '#ffffff');
    const colores = valores.map((_, j) => j === 7 ? colorCalza(calza) : SOLO_LECTURA_OP.indexOf(j + 1) >= 0 && j ? COLOR.textoGris : '#1f1f1f');
    const negritas = valores.map((_, j) => j === 0 ? 'bold' : 'normal');
    fila(valores, fondos, colores, negritas, 'maquina');
  };
  titulo(`${TITULO_OP} · ${op.length} máquinas`, 'tituloOp', COLOR.tituloOp);
  op.forEach(maquina);
  fila(Array(NCOL).fill(''), Array(NCOL).fill('#ffffff'), Array(NCOL).fill('#1f1f1f'), Array(NCOL).fill('normal'), 'vacio');
  titulo(`${TITULO_RESTO} · ${resto.length} máquinas`, 'tituloResto', COLOR.tituloResto);
  resto.forEach(maquina);
  return v;
}

// "✅ calza", "⚠ sin geocerca", "⚠ sin señal X días", "❌ GPS en CYH", "❌ GPS afuera", "❌ GPS en <campo>".
function calzaGps(campo, g, info) {
  if (!g || (!g.lugar && g.dias == null)) return '⚠ sin GPS';
  const enCampo = !!String(campo || '').trim() && !esTaller(campo);
  if (g.lugar === 'CYH') return enCampo ? '❌ GPS en CYH' : '✅ calza';
  if (g.dias != null && g.dias >= 2) return `⚠ sin señal ${g.dias} días`;
  if (!enCampo) return '❌ GPS afuera';
  if (g.lugar && g.lugar !== 'fuera de geocercas') return calzaCampo(campo, g.lugar, info) ? '✅ calza' : '❌ GPS en ' + nombreCampo(g.lugar, info);
  if (g.cercano && g.cercano[1] < 2 && calzaCampo(campo, g.cercano[0], info)) return '✅ calza';
  return '⚠ sin geocerca';
}
const colorCalza = t => /^✅/.test(t) ? COLOR.bien : /^❌/.test(t) ? COLOR.mal : COLOR.ojo;

// Comuna o lugar según el GPS: "CYH", el campo (si está dentro de una geocerca) o la comuna.
function ubicacion(g, info) {
  if (!g || !g.lugar) return (g && g.comuna) || '';
  if (g.lugar === 'CYH') return 'CYH';
  if (g.lugar !== 'fuera de geocercas') return nombreCampo(g.lugar, info);
  return g.comuna || 'sin geocerca';
}

// Término del trabajo de la Agenda en ese campo (a mano, o el que calculó la Agenda al guardar).
function terminoAgenda(campo, agenda, info, hoy) {
  if (!campo || esTaller(campo)) return '';
  const ts = (agenda || []).filter(t => t && t.estado !== 'terminado' && (calzaCampo(campo, t.campo, info) || calzaCampo(t.campo, campo, info)));
  if (!ts.length) return '';
  const actuales = ts.filter(t => (t.inicio || '') <= hoy);
  const t = actuales.length ? actuales.sort((a, b) => b.inicio.localeCompare(a.inicio))[0]
                            : ts.sort((a, b) => (a.inicio || '').localeCompare(b.inicio || ''))[0];
  return t.termino || t.termino_previsto || '';
}

function calzaCampo(anotado, lugar, info) {
  if (!anotado || !lugar) return false;
  if (clave(anotado) === clave(lugar)) return true;
  const eq = Object.entries(info.eq || {}).find(([k]) => clave(k) === clave(anotado));
  return !!(eq && eq[1].some(c => clave(c) === clave(lugar)));
}
const nombreCampo = (c, info) => (info.nombres || {})[c] || c;
const esTaller = c => /^(taller|cyh)/i.test(String(c || '').trim());
const sinT = t => String(t || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();
const clave = t => sinT(t).replace(/[^a-z0-9]/g, '');

// Comuna de una dirección de Wialon (igual que la app): sin país, región ni calle.
const REGIONES = ['region', 'región', 'metropolitana', 'libertador', 'maule', 'valparaiso', 'valparaíso', 'biobio', 'biobío', 'nuble', 'ñuble', 'araucania', 'araucanía', 'coquimbo', 'los lagos', 'los rios', 'los ríos'];
function comunaDe(texto) {
  let p = String(texto || '').split(',').map(x => x.trim()).filter(x => x && x.toLowerCase() !== 'chile' && !REGIONES.some(r => x.toLowerCase().startsWith(r)));
  if (p.length >= 2) p = p.slice(1);
  p = p.filter(x => !/\d/.test(x));
  return p.length ? p[p.length - 1] : '';
}
function dentro(x, y, pol) {
  let si = false;
  for (let i = 0, j = pol.length - 1; i < pol.length; j = i++) {
    const [xi, yi] = pol[i], [xj, yj] = pol[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) si = !si;
  }
  return si;
}
function distanciaM(lat1, lon1, lat2, lon2) {
  const k = Math.PI / 180, dx = (lon2 - lon1) * k * Math.cos((lat1 + lat2) / 2 * k), dy = (lat2 - lat1) * k;
  return Math.hypot(dx, dy) * 6371000;
}

// ---------------------------------------------------------------------------
// Ayudas
// ---------------------------------------------------------------------------
function llamarWorker(cuerpo) {
  const pin = PropertiesService.getScriptProperties().getProperty('PIN');
  if (!pin) return { ok: false, error: 'falta la propiedad PIN' };
  try {
    const r = UrlFetchApp.fetch(WORKER + '/hoja', { method: 'post', contentType: 'application/json',
      payload: JSON.stringify(Object.assign({}, cuerpo, { pin: pin })), muteHttpExceptions: true });
    const estado = r.getResponseCode();
    let d = {};
    try { d = JSON.parse(r.getContentText()); } catch (x) { /* respuesta no JSON */ }
    if (estado === 200 && d.ok !== false) return { ok: true, datos: d };
    return { ok: false, estado: estado, pin: estado === 403 && d.error === 'pin', error: d.error || ('respuesta ' + estado) };
  } catch (x) {
    return { ok: false, estado: 0, error: 'sin conexión' };
  }
}

const LEIDOS = {};  // cada archivo se lee una vez por ejecucion
function leerJson(url) {
  if (url.indexOf(DATOS) === 0 && LEIDOS[url]) return LEIDOS[url];
  try {
    const r = UrlFetchApp.fetch(url + (url.indexOf('?') < 0 ? '?' : '&') + 'x=' + Date.now(), { muteHttpExceptions: true });
    const d = r.getResponseCode() === 200 ? JSON.parse(r.getContentText()) : null;
    if (d && url.indexOf(DATOS) === 0) LEIDOS[url] = d;
    return d;
  } catch (x) { return null; }
}

function hoja(nombre, encabezado) {
  const ss = SpreadsheetApp.getActive();
  let h = ss.getSheetByName(nombre);
  if (!h) h = ss.insertSheet(nombre);
  if (String(h.getRange(1, 1).getValue()) !== encabezado[0] || String(h.getRange(1, encabezado.length).getValue()) !== encabezado[encabezado.length - 1]) {
    h.getRange(1, 1, 1, encabezado.length).setValues([encabezado]);
  }
  return h;
}

const fechaChile = iso => iso ? `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}` : '';
const horaChile = ms => Utilities.formatDate(new Date(ms), TZ_CHILE, 'dd-MM-yyyy HH:mm');
const hoyChile = () => Utilities.formatDate(new Date(), TZ_CHILE, 'yyyy-MM-dd');
function igual(a, b) {
  let d = a.length ^ b.length;
  for (let i = 0; i < b.length; i++) d |= (a.charCodeAt(i) || 0) ^ b.charCodeAt(i);
  return d === 0;
}
const nuevoId = () => ('p' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8)).toLowerCase();
const json = o => ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
function aviso(t, seg) { try { SpreadsheetApp.getActive().toast(t, 'Operación CYH', seg || 6); } catch (x) { console.log(t); } }
// Mensaje que NO espera respuesta (10-nov-2026): con alert() "instalar" quedaba esperando
// que alguien apretara Aceptar en la planilla y Google lo cortaba a los 6 minutos.
function mensaje(t) { console.log(t); try { SpreadsheetApp.getActive().toast(t, 'Operación CYH', 30); } catch (x) { /* sin planilla abierta */ } }
