/**
 * Planilla "Operación CYH" <-> app Flota C&H (sincronizada en los dos sentidos).
 * Pedido del usuario 4-nov-2026. Reglas en CLAUDE.md ("Planilla de Google Operación CYH").
 *
 *  - Planilla -> App: al editar una celda (Implemento, Operador, Campo, Desde,
 *    Próximo destino, o la pestaña Campos) se manda al Worker de Cloudflare al
 *    momento, con el PIN guardado en las Propiedades del script (nunca a la vista).
 *  - App -> Planilla: el Worker manda cada guardado de la app a esta misma
 *    planilla (doPost, "Aplicación web"), con una clave al azar que este script
 *    genera y registra en el Worker (con el PIN) al ejecutar "instalar".
 *  - Cada 5 minutos se trae todo desde la app (por si algo no llegó) y se
 *    actualiza la columna GPS y las listas desplegables.
 *  - Gana el último cambio; si el mismo dato se cambió en los dos lados en menos
 *    de 2 min, la app muestra un aviso. El historial guarda el origen (App/Planilla).
 *
 * Propiedades del script (Configuración del proyecto -> Propiedades del script):
 *   PIN      el PIN de edición de la app (lo escribe el usuario; nunca va en el código)
 *   URL_WEB  la dirección de la "Aplicación web" (termina en /exec)
 *   CLAVE    la crea sola "instalar" (no tocar)
 */

const WORKER = 'https://disparador-reporte.dawn-band-fd6c.workers.dev';
const DATOS = 'https://jpfernandez428.github.io/reporte-hectareas/datos/';
const HOJA_OP = 'Operación', HOJA_CAMPOS = 'Campos', HOJA_LISTAS = 'Listas';
const ENCABEZADO_OP = ['Máquina', 'Implemento', 'Operador', 'Campo', 'Desde', 'Próximo destino', 'GPS (solo lectura)', 'Última modificación'];
const ENCABEZADO_CAMPOS = ['Campo', 'Labor', 'Ha aprox.', 'Última modificación'];
// Columna (1 = A) -> dato de la app. A, G y H las escribe la app.
const COLUMNAS = { 2: 'implemento', 3: 'operador', 4: 'campo', 5: 'desde', 6: 'destino' };
const SOLO_LECTURA_OP = [1, 7, 8];
const TZ_CHILE = 'America/Santiago';

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
  preparar();
  sincronizar();
  mensaje('Listo: la planilla quedó conectada con la app. Los cambios van y vienen en segundos.');
}

// Formato, listas desplegables y protección de las columnas que escribe la app.
function preparar() {
  const ss = SpreadsheetApp.getActive();
  const op = hoja(HOJA_OP, ENCABEZADO_OP), campos = hoja(HOJA_CAMPOS, ENCABEZADO_CAMPOS), listas = hoja(HOJA_LISTAS, ['Operadores', 'Campos']);
  actualizarListas();
  listas.hideSheet();
  [op, campos].forEach(h => {
    h.setFrozenRows(1);
    h.getRange(1, 1, 1, h.getLastColumn()).setFontWeight('bold').setBackground('#1f4d2b').setFontColor('#ffffff');
  });
  op.setFrozenColumns(1);
  const n = 1000;
  // Operador y Campo: lista desplegable, pero se acepta un nombre nuevo (la app pregunta si se parece a uno existente).
  const regla = col => SpreadsheetApp.newDataValidation().requireValueInRange(listas.getRange(2, col, 600, 1), true).setAllowInvalid(true).build();
  op.getRange(2, 3, n, 1).setDataValidation(regla(1));
  op.getRange(2, 4, n, 1).setDataValidation(regla(2));
  op.getRange(2, 5, n, 1).setNumberFormat('dd-mm-yyyy');
  campos.getRange(2, 1, n, 1).setDataValidation(regla(2));
  campos.getRange(2, 3, n, 1).setNumberFormat('0.##');
  op.getRange(2, 7, n, 2).setFontColor('#666666').setBackground('#f3f3f3');
  campos.getRange(2, 4, n, 1).setFontColor('#666666').setBackground('#f3f3f3');
  op.setColumnWidth(1, 230); op.setColumnWidth(3, 150); op.setColumnWidth(4, 180); op.setColumnWidth(6, 150); op.setColumnWidth(7, 380); op.setColumnWidth(8, 160);
  campos.setColumnWidth(1, 200); campos.setColumnWidth(2, 160); campos.setColumnWidth(4, 160);
  // Protección: la columna Máquina, GPS y Última modificación solo las escribe la app.
  [op, campos].forEach(h => h.getProtections(SpreadsheetApp.ProtectionType.RANGE).filter(x => x.getDescription() === 'Lo escribe la app').forEach(x => x.remove()));
  [op.getRange('A:A'), op.getRange('G:H'), campos.getRange('D:D')].forEach(r => {
    const pr = r.protect().setDescription('Lo escribe la app');
    pr.removeEditors(pr.getEditors());
    if (pr.canDomainEdit()) pr.setDomainEdit(false);
  });
}

// ---------------------------------------------------------------------------
// Planilla -> App (al editar)
// ---------------------------------------------------------------------------
function alEditar(e) {
  if (!e || !e.range) return;
  const h = e.range.getSheet(), nombre = h.getName();
  if (e.range.getRow() < 2) return;
  if (nombre === HOJA_CAMPOS) return enviarCampos(e);
  if (nombre !== HOJA_OP) return;
  const r0 = e.range.getRow(), c0 = e.range.getColumn(), nr = e.range.getNumRows(), nc = e.range.getNumColumns();
  // Columnas que escribe la app (Máquina, GPS, Última modificación): se deshace lo editado
  // (si se pegó un bloque que las toca, se deshace todo el bloque).
  if (SOLO_LECTURA_OP.some(c => c >= c0 && c < c0 + nc)) {
    if (nr === 1 && nc === 1) e.range.setValue(e.oldValue === undefined ? '' : e.oldValue);
    else traerDesdeApp();
    aviso('Las columnas Máquina, GPS y Última modificación las escribe la app: no se cambió nada.');
    return;
  }
  const tz = SpreadsheetApp.getActive().getSpreadsheetTimeZone();
  const maquinas = h.getRange(r0, 1, nr, 1).getValues();
  const valores = e.range.getValues();
  const cambios = [];
  for (let i = 0; i < nr; i++) {
    const maquina = String(maquinas[i][0] || '').trim();
    if (!maquina) continue;
    for (let j = 0; j < nc; j++) {
      const k = COLUMNAS[c0 + j];
      if (!k) continue;
      let v = valores[i][j];
      if (k === 'desde') {
        v = fechaIso(v, tz);
        if (v === null) { aviso(`Fecha no válida en ${maquina}: usa día-mes-año (ej. 05-11-2026).`); continue; }
      }
      cambios.push({ maquina: maquina, k: k, valor: String(v == null ? '' : v).trim() });
    }
  }
  if (!cambios.length) return;
  enviarOperacion(cambios, true);
}

function enviarOperacion(cambios, avisar) {
  const r = llamarWorker({ tipo: 'operacion', cambios: cambios, id: nuevoId() });
  if (r.ok) {
    escribirFilas(Object.values(r.datos.filas || {}), r.datos.ultima || '');
    if (avisar) aviso(r.datos.conflictos_nuevos ? 'Guardado. Ojo: ese dato también se cambió en la app hace menos de 2 min (aviso en la app).' : 'Guardado en la app ✓');
    return true;
  }
  if (r.pin || r.estado === 400) {
    aviso(r.pin ? 'PIN incorrecto: no se guardó (revisa la propiedad PIN).' : 'No se guardó: ' + r.error);
    traerDesdeApp();
    return false;
  }
  // Sin conexión: queda pendiente y se reintenta solo cada 5 minutos.
  const p = PropertiesService.getScriptProperties();
  const pend = JSON.parse(p.getProperty('PENDIENTES') || '[]').concat(cambios).slice(-300);
  p.setProperty('PENDIENTES', JSON.stringify(pend));
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
    escribirFilas(Array.isArray(d.filas) ? d.filas : [], String(d.ultima || ''));
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
    traerDesdeApp();
    actualizarListas();
  } finally { lock.releaseLock(); }
}

function traerDesdeApp() {
  const estado = leerJson(WORKER + '/estado');
  let maquinas, ha = null, cambios = [];
  if (estado && estado.d1) { maquinas = estado.maquinas; ha = estado.ha_aprox; cambios = estado.cambios || []; }
  else {
    const op = leerJson(DATOS + 'operacion.json');
    if (!op) return;
    maquinas = op.maquinas;
    ha = Object.values(op.ha_aprox || {});
  }
  const v2 = (leerJson(DATOS + 'reporte_v2.json') || {}).v2 || {};
  const vivo = leerJson(WORKER + '/gps?guardado=1');
  // Ultima modificacion por maquina (lo mas reciente del historial de la app).
  const ultima = {};
  for (const c of cambios) if (!ultima[c.maquina]) ultima[c.maquina] = `${horaChile(c.ts)} · ${c.origen || 'App'}`;
  const orden = (v2.unidades || []).map(u => u.maquina).filter(m => maquinas[m]);
  Object.keys(maquinas).forEach(m => { if (orden.indexOf(m) < 0) orden.push(m); });
  const pend = new Set(JSON.parse(PropertiesService.getScriptProperties().getProperty('PENDIENTES') || '[]').map(x => x.maquina));
  const filas = orden.filter(m => !pend.has(m)).map(m => Object.assign({ maquina: m }, maquinas[m]));
  escribirFilas(filas, '', ultima, v2, vivo);
  if (ha) escribirCampos(ha, maquinas, v2);
}

// filas: [{maquina, implemento, operador, campo, desde, destino}]; ultima: texto para la columna H
// (o mapa por maquina); v2/vivo: para la columna GPS y la nota de "Desde" automatico.
function escribirFilas(filas, ultima, ultimaPorMaquina, v2, vivo) {
  const h = hoja(HOJA_OP, ENCABEZADO_OP);
  const tz = SpreadsheetApp.getActive().getSpreadsheetTimeZone();
  const n = Math.max(h.getLastRow() - 1, 0);
  const actual = n ? h.getRange(2, 1, n, 8).getValues() : [];
  const fila = {};
  actual.forEach((r, i) => { fila[String(r[0]).trim()] = i; });
  const nuevas = [];
  for (const f of filas) {
    if (!f || !f.maquina) continue;
    let i = fila[f.maquina];
    if (i === undefined) { i = actual.length; actual.push([f.maquina, '', '', '', '', '', '', '']); fila[f.maquina] = i; nuevas.push(i); }
    const r = actual[i];
    r[1] = f.implemento || ''; r[2] = f.operador || ''; r[3] = f.campo || '';
    r[4] = f.desde ? Utilities.parseDate(f.desde + ' 12:00', tz, 'yyyy-MM-dd HH:mm') : '';
    r[5] = f.destino || '';
    if (v2) r[6] = textoGps(f.maquina, v2, vivo);
    const u = ultima || (ultimaPorMaquina && ultimaPorMaquina[f.maquina]);
    if (u) r[7] = u;
  }
  if (!actual.length) return;
  // Se escribe solo si algo cambio (asi no se pisa nada sin necesidad).
  const antes = n ? h.getRange(2, 1, n, 8).getDisplayValues() : [];
  const distinto = actual.some((r, i) => !antes[i] || r.some((v, j) => texto(v, tz) !== antes[i][j]));
  if (distinto) h.getRange(2, 1, actual.length, 8).setValues(actual);
  // Nota en "Desde" vacio: la fecha automatica (llegada al campo segun el GPS).
  if (v2 && v2.desde_auto) {
    const notas = actual.map(r => [!r[4] && v2.desde_auto[r[0]] && r[3] && !/^taller/i.test(r[3]) ? 'Automática (GPS): ' + fechaChile(v2.desde_auto[r[0]]) : '']);
    h.getRange(2, 5, notas.length, 1).setNotes(notas);
  }
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

function actualizarListas() {
  const v2 = (leerJson(DATOS + 'reporte_v2.json') || {}).v2 || {};
  const campos = leerJson(DATOS + 'campos.json') || {};
  const ops = [];
  ((v2.operadores || {}).lista || []).forEach(o => { ops.push(o.operador); (o.otros_nombres || []).forEach(x => ops.push(x)); });
  const nl = campos.nombres_lista || {};
  const cs = ['Taller'].concat((campos.campos || []).filter(c => nl[c]), Object.keys(campos.equivalencias || {}));
  const unico = l => Array.from(new Set(l.filter(Boolean))).sort((a, b) => a.localeCompare(b, 'es'));
  const a = unico(ops), b = ['Taller'].concat(unico(cs.slice(1)));
  if (!a.length && b.length < 2) return;  // sin datos publicados: se deja lo anterior
  const h = hoja(HOJA_LISTAS, ['Operadores', 'Campos']);
  const filas = Math.max(a.length, b.length);
  h.getRange(2, 1, Math.max(h.getMaxRows() - 1, 1), 2).clearContent();
  h.getRange(2, 1, filas, 2).setValues(Array.from({ length: filas }, (_, i) => [a[i] || '', b[i] || '']));
}

// ---------------------------------------------------------------------------
// Ayudas
// ---------------------------------------------------------------------------
function textoGps(m, v2, vivo) {
  const g = (v2.gps_maquinas || {})[m] || {};
  const partes = [[g.texto, g.gps].filter(Boolean).join(' · ')];
  const x = vivo && vivo.maquinas && vivo.maquinas[m];
  if (x && x.t) {
    const estado = x.traslado ? `en traslado (${Math.round(Math.max(x.v || 0, x.vmax || 0))} km/h)` : (x.v || 0) > 1 ? 'en movimiento' : 'detenido';
    partes.push(`Al momento: ${estado}${x.dir ? ' · ' + String(x.dir).split(',').slice(-3).join(',').trim() : ''} · posición de las ${horaChile(x.t * 1000).slice(11)}`);
  }
  return partes.filter(Boolean).join(' | ');
}

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
  if (String(h.getRange(1, 1).getValue()) !== encabezado[0]) h.getRange(1, 1, 1, encabezado.length).setValues([encabezado]);
  return h;
}

// Fecha de la celda -> 'yyyy-mm-dd' ('' si esta vacia, null si no se entiende).
function fechaIso(v, tz) {
  if (v === '' || v == null) return '';
  if (Object.prototype.toString.call(v) === '[object Date]') return Utilities.formatDate(v, tz, 'yyyy-MM-dd');
  const t = String(v).trim();
  let m = t.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (m) return t;
  m = t.match(/^(\d{1,2})[-\/.](\d{1,2})[-\/.](\d{4})$/);
  if (m) return `${m[3]}-${('0' + m[2]).slice(-2)}-${('0' + m[1]).slice(-2)}`;
  return null;
}
const fechaChile = iso => iso ? `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}` : '';
const horaChile = ms => Utilities.formatDate(new Date(ms), TZ_CHILE, 'dd-MM-yyyy HH:mm');
function texto(v, tz) {
  return Object.prototype.toString.call(v) === '[object Date]' ? Utilities.formatDate(v, tz, 'dd-MM-yyyy') : String(v);
}
function igual(a, b) {
  let d = a.length ^ b.length;
  for (let i = 0; i < b.length; i++) d |= (a.charCodeAt(i) || 0) ^ b.charCodeAt(i);
  return d === 0;
}
const nuevoId = () => ('p' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8)).toLowerCase();
const json = o => ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
function aviso(t) { try { SpreadsheetApp.getActive().toast(t, 'Operación CYH', 6); } catch (x) { console.log(t); } }
function mensaje(t) { try { SpreadsheetApp.getUi().alert(t); } catch (x) { console.log(t); } }
