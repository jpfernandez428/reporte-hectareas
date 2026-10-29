// Worker de Cloudflare "disparador-reporte": lanza a la hora exacta los
// workflows de GitHub (los horarios propios de GitHub se atrasan horas), y
// recibe las confirmaciones de campo de la pagina (POST /confirmar).
// Instrucciones y reglas en CLAUDE.md ("Reporte diario por correo").
//
// Cloudflare programa en UTC; Chile cambia de horario, por eso cada horario
// esta dos veces (verano UTC-3 e invierno UTC-4) y el Worker lanza solo el
// que calza con la hora real de Chile.
//
// Secretos del Worker (los carga el usuario en Cloudflare; nunca en este archivo,
// el repositorio ni el chat):
//   GITHUB_TOKEN  token fine-grained solo del repositorio reporte-hectareas,
//                 permiso Actions: Read and write.
//   PIN_EDICION   PIN unico para guardar desde las paginas (26-oct-2026): todos
//                 los guardados (confirmar, equivalencias, actualizar, Operacion,
//                 Agenda) lo piden; sin el PIN correcto no se guarda nada.

const REPO = 'jpfernandez428/reporte-hectareas';

// Hora de Chile (HH:MM) -> workflow que se lanza. Cron Triggers del Worker:
//   30 3,4 * * *    (00:30 de Chile: corrida de la noche)
//   30 10,11 * * *  (07:30: correo; se arma y sale a las 07:45)
//   0 12,13 * * *   (09:00: aviso de atraso)
// (La revision de la planilla del Drive cada 30 min quedo apagada el 26-oct-2026:
//  la pagina Operacion es la fuente. Si el Cron "*/30 * * * *" sigue en
//  Cloudflare, no hace nada; se puede borrar.)
const TAREAS = {
  '00:30': { workflow: 'diario.yml', inputs: {} },               // corrida de la noche
  '07:30': { workflow: 'correo.yml', inputs: { modo: 'diario' } }, // arma el correo y lo envia a las 07:45
  '09:00': { workflow: 'correo.yml', inputs: { modo: 'diario' } }, // aviso si la corrida viene atrasada
};

const CRON_PLANILLA = '*/30 * * * *';  // apagado (26-oct-2026): no lanza nada

function horaChile(fecha) {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'America/Santiago', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(fecha);
}

async function lanzar(env, tarea) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${tarea.workflow}/dispatches`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'disparador-reporte',
    },
    body: JSON.stringify({ ref: 'main', inputs: tarea.inputs }),
  });
  if (r.status !== 204) {
    throw new Error(`GitHub respondio ${r.status} al lanzar ${tarea.workflow}: ${await r.text()}`);
  }
}

// Confirmaciones de la pagina (trabajo sin geocerca): la pagina hace POST a
// /confirmar y el Worker lanza confirmar.yml. Abierto, sin clave (regla del
// usuario, 21-oct-2026): solo se validan los datos. Solo acepta llamadas desde
// la pagina publicada.
const ORIGEN_PAGINA = 'https://jpfernandez428.github.io';
const CORS = {
  'Access-Control-Allow-Origin': ORIGEN_PAGINA,
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

// PIN de edicion: comparacion en tiempo constante; con PIN incorrecto se
// espera 1 s antes de responder (frena intentos seguidos).
async function revisarPin(datos, env) {
  if (!env.PIN_EDICION) return responder(500, { error: 'falta configurar el PIN en Cloudflare' });
  const a = new TextEncoder().encode(String((datos && datos.pin) || ''));
  const b = new TextEncoder().encode(String(env.PIN_EDICION));
  let distinto = a.length !== b.length ? 1 : 0;
  for (let i = 0; i < b.length; i++) distinto |= (a[i] || 0) ^ b[i];
  if (distinto) {
    await new Promise(r => setTimeout(r, 1000));
    return responder(403, { error: 'pin' });
  }
  return null;
}

async function leerCuerpo(peticion) {
  try { return await peticion.json(); } catch { return null; }
}

function responder(estado, cuerpo) {
  return new Response(JSON.stringify(cuerpo), { status: estado, headers: { ...CORS, 'Content-Type': 'application/json' } });
}

async function confirmar(datos, env, ctx) {
  const accion = String(datos.accion || '');
  const inputs = { accion };
  if (accion === 'campo' || accion === 'ninguno') {
    const lat = Number(datos.lat), lon = Number(datos.lon);
    if (!(lat > -56 && lat < -17 && lon > -76 && lon < -66)) return responder(400, { error: 'coordenadas' });
    inputs.lat = lat.toFixed(6); inputs.lon = lon.toFixed(6);
    if (accion === 'campo') {
      const campo = String(datos.campo || '').trim();
      if (!campo || campo.length > 80) return responder(400, { error: 'campo' });
      inputs.campo = campo;
      if (datos.planilla) inputs.planilla = String(datos.planilla).slice(0, 80);  // equivalencia sola
    }
  } else if (accion === 'maquina' || accion === 'deshacer_maquina') {
    const maquina = String(datos.maquina || '').trim();
    if (!maquina || maquina.length > 80) return responder(400, { error: 'maquina' });
    inputs.maquina = maquina;
    if (accion === 'maquina') {
      const valor = String(datos.valor || '').trim();
      if (!(valor === 'cyh' || valor.startsWith('campo'))) return responder(400, { error: 'valor' });
      inputs.campo = valor.slice(0, 90);
      inputs.planilla = String(datos.planilla || '').slice(0, 80);
    }
  } else if (accion === 'equivalencia' || accion === 'borrar_equivalencia') {
    const nombre = String(datos.planilla || '').trim(), campo = String(datos.campo || '').trim();
    if (!nombre || nombre.length > 80 || campo.length > 80 || (accion === 'equivalencia' && !campo)) return responder(400, { error: 'equivalencia' });
    inputs.planilla = nombre; inputs.campo = campo;
  } else if (accion === 'deshacer') {
    const id = String(datos.id || '');
    if (!/^\d{14}$/.test(id)) return responder(400, { error: 'id' });
    inputs.id = id;
  } else {
    return responder(400, { error: 'accion' });
  }
  let db = null;
  try { db = await base(env); } catch (e) { db = null; }
  if (!db) {
    await lanzar(env, { workflow: 'confirmar.yml', inputs });
    return responder(200, { ok: true, d1: false });
  }
  // Queda registrado al instante en D1 (las paginas lo muestran) y se copia a GitHub desde la cola.
  const id = 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  await db.batch([
    db.prepare('INSERT INTO acciones (id, ts, tipo, datos) VALUES (?, ?, ?, ?)').bind(id, Date.now(), accion, JSON.stringify(inputs)),
    db.prepare('INSERT OR REPLACE INTO copias (id, ts, workflow, inputs) VALUES (?, ?, ?, ?)').bind(id, Date.now(), 'confirmar.yml', JSON.stringify(inputs)),
    db.prepare("UPDATE meta SET v = CAST(CAST(v AS INTEGER) + 1 AS TEXT) WHERE k = 'version'"),
  ]);
  ctx.waitUntil(copiarPendientes(env, db, id).catch(() => {}));  // copia a GitHub al tiro
  return responder(200, { ok: true, d1: true, id, copia: id });
}

// ---------------------------------------------------------------------------
// Base de datos D1 (binding "DB", pedido del usuario 27-oct-2026): guardar al
// INSTANTE. D1 tiene una sola copia principal: lo guardado se ve al tiro en la
// siguiente lectura desde cualquier celular (KV puede tardar hasta 1 min).
// Las tablas se crean solas; la primera vez se carga la operacion publicada.
// Cada guardado se copia a GitHub (operacion.yml / confirmar.yml) desde una
// cola que se reintenta sola si GitHub falla. Sin DB, todo sigue como antes
// (solo GitHub).
// ---------------------------------------------------------------------------
const URL_OPERACION_PUBLICADA = 'https://jpfernandez428.github.io/reporte-hectareas/datos/operacion.json';
const CAMPOS_FILA = ['implemento', 'operador', 'campo', 'desde', 'destino'];
const NOMBRES_CAMPO = { implemento: 'Implemento', operador: 'Operador', campo: 'Campo', desde: 'Desde', destino: 'Próximo destino' };
let BASE_LISTA = false;

async function base(env) {
  if (!env.DB) return null;
  if (!BASE_LISTA) {
    await env.DB.batch([
      env.DB.prepare('CREATE TABLE IF NOT EXISTS operacion (maquina TEXT PRIMARY KEY, implemento TEXT, operador TEXT, campo TEXT, desde TEXT, destino TEXT)'),
      env.DB.prepare('CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)'),
      env.DB.prepare('CREATE TABLE IF NOT EXISTS cambios (n INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, guardado TEXT, maquina TEXT, cambio TEXT, antes TEXT, despues TEXT)'),
      env.DB.prepare('CREATE TABLE IF NOT EXISTS copias (id TEXT PRIMARY KEY, ts INTEGER, workflow TEXT, inputs TEXT, intentos INTEGER DEFAULT 0, ok INTEGER DEFAULT 0, error TEXT)'),
      env.DB.prepare('CREATE TABLE IF NOT EXISTS acciones (id TEXT PRIMARY KEY, ts INTEGER, tipo TEXT, datos TEXT)'),
      env.DB.prepare('CREATE TABLE IF NOT EXISTS agenda (id TEXT PRIMARY KEY, datos TEXT, ts INTEGER)'),
      env.DB.prepare('CREATE TABLE IF NOT EXISTS agenda_cambios (n INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, guardado TEXT, trabajo TEXT, cambio TEXT, antes TEXT, despues TEXT)'),
    ]);
    const sembrado = await env.DB.prepare("SELECT v FROM meta WHERE k = 'sembrado'").first();
    if (!sembrado) {
      // Primera vez: la operacion publicada en GitHub pasa a la base.
      const r = await fetch(URL_OPERACION_PUBLICADA + '?x=' + Date.now(), { cf: { cacheTtl: 0 } });
      if (!r.ok) throw new Error('no se pudo leer la operacion publicada');
      const op = await r.json();
      const filas = Object.entries(op.maquinas || {}).map(([m, x]) => env.DB.prepare(
        'INSERT OR REPLACE INTO operacion (maquina, implemento, operador, campo, desde, destino) VALUES (?, ?, ?, ?, ?, ?)')
        .bind(m, x.implemento || '', x.operador || '', x.campo || '', x.desde || '', x.destino || ''));
      await env.DB.batch([...filas,
        env.DB.prepare("INSERT OR REPLACE INTO meta (k, v) VALUES ('version', '1')"),
        env.DB.prepare("INSERT OR REPLACE INTO meta (k, v) VALUES ('actualizado', ?)").bind(op.actualizado || ''),
        env.DB.prepare("INSERT OR REPLACE INTO meta (k, v) VALUES ('sembrado', ?)").bind(String(Date.now()))]);
    }
    const agendaSembrada = await env.DB.prepare("SELECT v FROM meta WHERE k = 'agenda_sembrada'").first();
    if (!agendaSembrada) {
      // Primera vez con la Agenda: los trabajos publicados en GitHub pasan a la base.
      const r = await fetch(URL_AGENDA_PUBLICADA + '?x=' + Date.now(), { cf: { cacheTtl: 0 } });
      const ag = r.ok ? await r.json() : { trabajos: {} };
      const filas = Object.values(ag.trabajos || {}).map(t => env.DB.prepare('INSERT OR REPLACE INTO agenda (id, datos, ts) VALUES (?, ?, ?)')
        .bind(t.id, JSON.stringify(t), Date.now()));
      await env.DB.batch([...filas, env.DB.prepare("INSERT OR REPLACE INTO meta (k, v) VALUES ('agenda_sembrada', ?)").bind(String(Date.now()))]);
    }
    BASE_LISTA = true;
  }
  return env.DB;
}

const horaChileLarga = t => new Intl.DateTimeFormat('es-CL', { timeZone: 'America/Santiago', day: '2-digit', month: '2-digit', year: 'numeric',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(t)).replace(/\//g, '-').replace(',', '');

async function estadoBase(db) {
  const [filas, v, act, cambios, pend, agenda, agendaCambios] = await Promise.all([
    db.prepare('SELECT * FROM operacion').all(),
    db.prepare("SELECT v FROM meta WHERE k = 'version'").first(),
    db.prepare("SELECT v FROM meta WHERE k = 'actualizado'").first(),
    db.prepare('SELECT ts, guardado, maquina, cambio, antes, despues FROM cambios ORDER BY n DESC LIMIT 100').all(),
    db.prepare('SELECT COUNT(*) AS n FROM copias WHERE ok = 0').first(),
    db.prepare('SELECT datos FROM agenda').all(),
    db.prepare('SELECT ts, guardado, trabajo, cambio, antes, despues FROM agenda_cambios ORDER BY n DESC LIMIT 100').all(),
  ]);
  const maquinas = {};
  for (const f of filas.results) maquinas[f.maquina] = Object.fromEntries(CAMPOS_FILA.map(k => [k, f[k] || '']));
  return { ok: true, d1: true, version: Number((v && v.v) || 0), actualizado: (act && act.v) || '', maquinas,
           cambios: cambios.results, copias_pendientes: (pend && pend.n) || 0,
           agenda: agenda.results.map(r => JSON.parse(r.datos)), agenda_cambios: agendaCambios.results };
}

// Copias a GitHub pendientes (se reintentan en cada consulta, como maximo 1 por minuto cada una).
async function copiarPendientes(env, db, soloId) {
  const lista = soloId
    ? (await db.prepare('SELECT * FROM copias WHERE id = ?').bind(soloId).all()).results
    : (await db.prepare('SELECT * FROM copias WHERE ok = 0 AND ts < ? ORDER BY ts LIMIT 5').bind(Date.now() - 60000).all()).results;
  for (const c of lista) {
    try {
      await lanzar(env, { workflow: c.workflow, inputs: JSON.parse(c.inputs) });
      await db.prepare('UPDATE copias SET ok = 1, intentos = intentos + 1, error = NULL WHERE id = ?').bind(c.id).run();
    } catch (e) {
      await db.prepare('UPDATE copias SET intentos = intentos + 1, ts = ?, error = ? WHERE id = ?').bind(Date.now(), String(e.message || e).slice(0, 300), c.id).run();
    }
  }
}

// Pagina Operacion: "Guardar" manda las filas (completas) que cambiaron.
async function guardarOperacion(datos, env, ctx) {
  const cambios = Array.isArray(datos.cambios) ? datos.cambios : null;
  if (!cambios || !cambios.length || cambios.length > 150) return responder(400, { error: 'cambios' });
  const limpio = [];
  for (const c of cambios) {
    const fila = {};
    for (const k of ['maquina', ...CAMPOS_FILA]) {
      const v = String((c && c[k]) || '').trim();
      if (v.length > 80) return responder(400, { error: k });
      fila[k] = v;
    }
    if (!fila.maquina) return responder(400, { error: 'maquina' });
    if (fila.desde && !/^\d{4}-\d{2}-\d{2}$/.test(fila.desde)) return responder(400, { error: 'desde' });
    limpio.push(fila);
  }
  const texto = JSON.stringify(limpio);
  if (texto.length > 60000) return responder(400, { error: 'demasiados cambios' });
  const id = /^[a-z0-9]{8,40}$/.test(String(datos.id || '')) ? String(datos.id) : 'w' + Date.now().toString(36);
  const recibido = Date.now();
  const copia = { workflow: 'operacion.yml', inputs: { cambios: texto, id, recibido: String(recibido) } };
  let db = null;
  try { db = await base(env); } catch (e) { db = null; }
  if (!db) {
    // Sin base de datos: como antes (solo GitHub, 1 a 3 minutos).
    await lanzar(env, copia);
    return responder(200, { ok: true, d1: false });
  }
  // 1) Guardar al instante en D1 (con el historial de cambios).
  const actuales = {};
  for (const r of (await db.prepare(`SELECT * FROM operacion WHERE maquina IN (${limpio.map(() => '?').join(',')})`).bind(...limpio.map(f => f.maquina)).all()).results) actuales[r.maquina] = r;
  const sentencias = [];
  for (const f of limpio) {
    const antes = actuales[f.maquina] || {};
    if (f.campo !== (antes.campo || '') && f.desde === (antes.desde || '')) f.desde = '';  // cambio de campo: Desde automatico
    for (const k of CAMPOS_FILA) {
      const a = antes[k] || '', d = f[k] || '';
      if (a !== d) sentencias.push(db.prepare('INSERT INTO cambios (ts, guardado, maquina, cambio, antes, despues) VALUES (?, ?, ?, ?, ?, ?)')
        .bind(recibido, id, f.maquina, NOMBRES_CAMPO[k], k === 'desde' ? (a || 'automática') : a, k === 'desde' ? (d || 'automática') : d));
    }
    sentencias.push(db.prepare('INSERT OR REPLACE INTO operacion (maquina, implemento, operador, campo, desde, destino) VALUES (?, ?, ?, ?, ?, ?)')
      .bind(f.maquina, f.implemento, f.operador, f.campo, f.desde, f.destino));
  }
  sentencias.push(db.prepare("UPDATE meta SET v = CAST(CAST(v AS INTEGER) + 1 AS TEXT) WHERE k = 'version'"));
  sentencias.push(db.prepare("INSERT OR REPLACE INTO meta (k, v) VALUES ('actualizado', ?)").bind(horaChileLarga(recibido)));
  sentencias.push(db.prepare('INSERT OR REPLACE INTO copias (id, ts, workflow, inputs) VALUES (?, ?, ?, ?)')
    .bind(id, recibido, copia.workflow, JSON.stringify({ ...copia.inputs, cambios: JSON.stringify(limpio) })));
  await db.batch(sentencias);
  // 2) Copia a GitHub (historial, reportes, correo) sin hacer esperar a la pagina.
  ctx.waitUntil(copiarPendientes(env, db, id));
  return responder(200, { ...(await estadoBase(db)), id });
}

// ---------------------------------------------------------------------------
// Agenda de trabajos (pedido del usuario 29-oct-2026): la pagina manda el
// trabajo completo (crear o editar) o {borrar: id}. Con D1 queda al instante,
// con su historial de cambios; la copia a GitHub va por agenda.yml (agenda.py).
// ---------------------------------------------------------------------------
const URL_AGENDA_PUBLICADA = 'https://jpfernandez428.github.io/reporte-hectareas/datos/agenda.json';
const ESTADOS_AGENDA = ['por_confirmar', 'confirmado', 'en_curso', 'terminado'];
const NOMBRES_AGENDA = { campo: 'Campo', labor: 'Labor', inicio: 'Inicio', termino: 'Término (a mano)', ha: 'Hectáreas',
  cuarteles: 'Cuarteles', necesita: 'Qué se necesita', estado: 'Estado', notas: 'Notas', maquinas: 'Máquinas', operadores: 'Operadores' };
const textoCorto = (v, largo) => String(v ?? '').replace(/\s+/g, ' ').trim().slice(0, largo);
const fechaOk = v => !v || /^\d{4}-\d{2}-\d{2}$/.test(v);
// Trabajo limpio (mismas reglas que agenda.py) o null si no sirve.
function limpiarTrabajo(t) {
  if (!t || typeof t !== 'object' || !/^[a-z0-9]{6,30}$/.test(String(t.id || ''))) return null;
  const lista = (v, largo) => (Array.isArray(v) ? v : []).slice(0, 30).map(x => textoCorto(x, largo)).filter(Boolean);
  const r = {
    id: String(t.id), campo: textoCorto(t.campo, 80), labor: textoCorto(t.labor, 60),
    inicio: textoCorto(t.inicio, 10), termino: textoCorto(t.termino, 10), termino_previsto: textoCorto(t.termino_previsto, 10),
    ha: textoCorto(t.ha, 10), cuarteles: lista(t.cuarteles, 80),
    necesita: (Array.isArray(t.necesita) ? t.necesita : []).slice(0, 10).map(x => ({ tipo: textoCorto(x && x.tipo, 40), cantidad: Math.max(1, Math.min(50, parseInt(x && x.cantidad, 10) || 1)) })).filter(x => x.tipo),
    estado: ESTADOS_AGENDA.includes(t.estado) ? t.estado : 'por_confirmar', notas: textoCorto(t.notas, 1000),
    maquinas: lista(t.maquinas, 80), operadores: lista(t.operadores, 80), creado: textoCorto(t.creado, 20),
  };
  if (!r.campo || !r.inicio || !fechaOk(r.inicio) || !fechaOk(r.termino) || !fechaOk(r.termino_previsto)) return null;
  if (r.ha && !/^\d{1,5}([.,]\d{1,2})?$/.test(r.ha)) return null;
  return r;
}
const textoAgenda = (k, v) => Array.isArray(v) ? (k === 'necesita' ? v.map(x => `${x.cantidad} ${x.tipo}`).join(', ') : v.join(', ')) : String(v || '');

async function guardarAgenda(datos, env, ctx) {
  const id = /^[a-z0-9]{8,40}$/.test(String(datos.id || '')) ? String(datos.id) : 'a' + Date.now().toString(36);
  const borrar = datos.borrar ? String(datos.borrar) : '';
  const trabajo = borrar ? null : limpiarTrabajo(datos.trabajo);
  if (borrar ? !/^[a-z0-9]{6,30}$/.test(borrar) : !trabajo) return responder(400, { error: 'trabajo' });
  const recibido = Date.now();
  const copia = { workflow: 'agenda.yml', inputs: { trabajo: borrar ? JSON.stringify({ borrar }) : JSON.stringify(trabajo), id, recibido: String(recibido) } };
  let db = null;
  try { db = await base(env); } catch (e) { db = null; }
  if (!db) {
    await lanzar(env, copia);
    return responder(200, { ok: true, d1: false });
  }
  const tid = borrar || trabajo.id;
  const fila = await db.prepare('SELECT datos FROM agenda WHERE id = ?').bind(tid).first();
  const antes = fila ? JSON.parse(fila.datos) : null;
  const nombre = t => `${t.campo} · ${t.labor || 'sin labor'}`;
  const sentencias = [];
  const anotar = (cambio, a, d) => sentencias.push(db.prepare('INSERT INTO agenda_cambios (ts, guardado, trabajo, cambio, antes, despues) VALUES (?, ?, ?, ?, ?, ?)')
    .bind(recibido, id, nombre(trabajo || antes || { campo: tid }), cambio, a, d));
  if (borrar) {
    if (antes) { anotar('Borrado', nombre(antes), ''); sentencias.push(db.prepare('DELETE FROM agenda WHERE id = ?').bind(tid)); }
  } else {
    if (!antes) anotar('Creado', '', `${trabajo.inicio}${trabajo.ha ? ' · ' + trabajo.ha + ' ha' : ''}`);
    else for (const k of Object.keys(NOMBRES_AGENDA)) {
      const a = textoAgenda(k, antes[k]), d = textoAgenda(k, trabajo[k]);
      if (a !== d) anotar(NOMBRES_AGENDA[k], a, d);
    }
    sentencias.push(db.prepare('INSERT OR REPLACE INTO agenda (id, datos, ts) VALUES (?, ?, ?)').bind(trabajo.id, JSON.stringify(trabajo), recibido));
  }
  sentencias.push(db.prepare("UPDATE meta SET v = CAST(CAST(v AS INTEGER) + 1 AS TEXT) WHERE k = 'version'"));
  sentencias.push(db.prepare('INSERT OR REPLACE INTO copias (id, ts, workflow, inputs) VALUES (?, ?, ?, ?)').bind(id, recibido, copia.workflow, JSON.stringify(copia.inputs)));
  await db.batch(sentencias);
  ctx.waitUntil(copiarPendientes(env, db, id));
  return responder(200, { ...(await estadoBase(db)), id });
}

export default {
  async fetch(peticion, env, ctx) {
    const url = new URL(peticion.url);
    if (peticion.method === 'OPTIONS') return new Response(null, { headers: CORS });
    // Lecturas de la base (abiertas, como los datos publicados): version (cada 3 s) y estado completo.
    if (peticion.method === 'GET' && (url.pathname === '/version' || url.pathname === '/estado')) {
      try {
        const db = await base(env);
        if (!db) return responder(200, { ok: true, d1: false });
        if (url.pathname === '/version') {
          const v = await db.prepare("SELECT v FROM meta WHERE k = 'version'").first();
          return responder(200, { ok: true, d1: true, version: Number((v && v.v) || 0) });
        }
        ctx.waitUntil(copiarPendientes(env, db).catch(() => {}));  // reintenta copias a GitHub atrasadas
        const e = await estadoBase(db);
        e.acciones = (await db.prepare('SELECT a.id, a.ts, a.tipo, a.datos, c.ok AS copiado FROM acciones a LEFT JOIN copias c ON c.id = a.id ORDER BY a.ts DESC LIMIT 50').all()).results;
        return responder(200, e);
      } catch (e) { return responder(503, { ok: false, error: 'base de datos: ' + String(e.message || e) }); }
    }
    // Prueba a mano (GET /probar?hora=00:30 | 07:30 | 09:00 | planilla): lanza esa tarea al
    // tiro y muestra la respuesta de GitHub. Es inofensivo: la corrida no
    // repite un dia ya procesado y el correo no sale dos veces el mismo dia.
    if (url.pathname === '/probar') {
      const hora = url.searchParams.get('hora') || '';
      // /probar?hora=planilla lanza la revision de la planilla (como el Cron).
      const tarea = hora === 'planilla' ? { workflow: 'planilla.yml', inputs: { origen: 'cron' } } : TAREAS[hora];
      if (!tarea) return new Response(`Horas validas: ${Object.keys(TAREAS).join(', ')}, planilla`, { status: 400 });
      const token = env.GITHUB_TOKEN ? `token cargado (${String(env.GITHUB_TOKEN).length} caracteres)` : 'FALTA el secreto GITHUB_TOKEN';
      try {
        await lanzar(env, tarea);
        return new Response(`OK: GitHub acepto lanzar ${tarea.workflow} (${hora}). ${token}. Hora de Chile ahora: ${horaChile(new Date())}.`);
      } catch (e) {
        return new Response(`ERROR: ${e.message}. ${token}.`, { status: 502 });
      }
    }
    // Guardados desde las paginas: solo desde la pagina publicada y con el PIN.
    if (peticion.method === 'POST' && ['/confirmar', '/planilla', '/operacion', '/agenda'].includes(url.pathname)) {
      if ((peticion.headers.get('Origin') || '') !== ORIGEN_PAGINA) return responder(403, { error: 'origen' });
      const datos = await leerCuerpo(peticion);
      if (!datos) return responder(400, { error: 'JSON invalido' });
      const sinPin = await revisarPin(datos, env);
      if (sinPin) return sinPin;
      try {
        if (url.pathname === '/confirmar') return await confirmar(datos, env, ctx);
        if (url.pathname === '/operacion') return await guardarOperacion(datos, env, ctx);
        if (url.pathname === '/agenda') return await guardarAgenda(datos, env, ctx);
        // Boton "Actualizar" de reporte2.html: rearma con la pagina Operacion.
        await lanzar(env, { workflow: 'planilla.yml', inputs: { origen: 'boton' } });
        return responder(200, { ok: true });
      } catch (e) { return responder(502, { error: String(e.message || e) }); }
    }
    return new Response('No encontrado', { status: 404 });
  },

  async scheduled(evento, env) {
    const hora = horaChile(new Date(evento.scheduledTime));
    if (evento.cron === CRON_PLANILLA) return;  // revision de la planilla apagada (26-oct-2026)
    const tarea = TAREAS[hora];
    if (!tarea) {
      console.log(`${hora} de Chile: no corresponde (es el horario del otro cambio de hora).`);
      return;
    }
    try {
      await lanzar(env, tarea);
      console.log(`${hora} de Chile: lanzado ${tarea.workflow}`);
    } catch (e) {
      console.log(`${hora} de Chile: ERROR al lanzar ${tarea.workflow}: ${e.message}`);
      throw e;  // queda como error en los registros de Cloudflare
    }
  },
};
