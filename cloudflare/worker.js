// Worker de Cloudflare "disparador-reporte": lanza a la hora exacta los
// workflows de GitHub (los horarios propios de GitHub se atrasan horas), y
// recibe las confirmaciones de campo de la pagina (POST /confirmar).
// Instrucciones y reglas en CLAUDE.md ("Reporte diario por correo").
//
// Cloudflare programa en UTC; Chile cambia de horario, por eso cada horario
// esta dos veces (verano UTC-3 e invierno UTC-4) y el Worker lanza solo el
// que calza con la hora real de Chile.
//
// Secreto del Worker: GITHUB_TOKEN (token fine-grained solo del repositorio
// reporte-hectareas, permiso Actions: Read and write). Nunca en este archivo.

const REPO = 'jpfernandez428/reporte-hectareas';

// Hora de Chile (HH:MM) -> workflow que se lanza. Cron Triggers del Worker:
//   30 3,4 * * *    (00:30 de Chile: corrida de la noche)
//   30 10,11 * * *  (07:30: correo; se arma y sale a las 07:45)
//   0 12,13 * * *   (09:00: aviso de atraso)
const TAREAS = {
  '00:30': { workflow: 'diario.yml', inputs: {} },               // corrida de la noche
  '07:30': { workflow: 'correo.yml', inputs: { modo: 'diario' } }, // arma el correo y lo envia a las 07:45
  '09:00': { workflow: 'correo.yml', inputs: { modo: 'diario' } }, // aviso si la corrida viene atrasada
};

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
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

function responder(estado, cuerpo) {
  return new Response(JSON.stringify(cuerpo), { status: estado, headers: { ...CORS, 'Content-Type': 'application/json' } });
}

async function confirmar(peticion, env) {
  let datos;
  try { datos = await peticion.json(); } catch { return responder(400, { error: 'JSON invalido' }); }
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
  } else if (accion === 'deshacer') {
    const id = String(datos.id || '');
    if (!/^\d{14}$/.test(id)) return responder(400, { error: 'id' });
    inputs.id = id;
  } else {
    return responder(400, { error: 'accion' });
  }
  await lanzar(env, { workflow: 'confirmar.yml', inputs });
  return responder(200, { ok: true });
}

export default {
  async fetch(peticion, env) {
    const url = new URL(peticion.url);
    if (peticion.method === 'OPTIONS') return new Response(null, { headers: CORS });
    // Prueba a mano (GET /probar?hora=00:30 | 07:30 | 09:00): lanza esa tarea al
    // tiro y muestra la respuesta de GitHub. Es inofensivo: la corrida no
    // repite un dia ya procesado y el correo no sale dos veces el mismo dia.
    if (url.pathname === '/probar') {
      const hora = url.searchParams.get('hora') || '';
      const tarea = TAREAS[hora];
      if (!tarea) return new Response(`Horas validas: ${Object.keys(TAREAS).join(', ')}`, { status: 400 });
      const token = env.GITHUB_TOKEN ? `token cargado (${String(env.GITHUB_TOKEN).length} caracteres)` : 'FALTA el secreto GITHUB_TOKEN';
      try {
        await lanzar(env, tarea);
        return new Response(`OK: GitHub acepto lanzar ${tarea.workflow} (${hora}). ${token}. Hora de Chile ahora: ${horaChile(new Date())}.`);
      } catch (e) {
        return new Response(`ERROR: ${e.message}. ${token}.`, { status: 502 });
      }
    }
    if (url.pathname === '/confirmar' && peticion.method === 'POST') {
      if ((peticion.headers.get('Origin') || '') !== ORIGEN_PAGINA) return responder(403, { error: 'origen' });
      try { return await confirmar(peticion, env); } catch (e) { return responder(502, { error: String(e.message || e) }); }
    }
    return new Response('No encontrado', { status: 404 });
  },

  async scheduled(evento, env) {
    const hora = horaChile(new Date(evento.scheduledTime));
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
