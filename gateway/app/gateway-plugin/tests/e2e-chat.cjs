// Uso: node e2e-chat.cjs [mensaje]
//   Variables: MYKOS_URL (por defecto http://127.0.0.1:3210), MYKOS_MODEL (por defecto mykos-cuda), TIMEOUT_S (420)
//
// Prueba de EXTREMO A EXTREMO sobre el MyKOS REAL, con el modelo local:
//   navegador (esta petición) -> Gateway :3210 -> proxy /api/* -> backend Python :3211 -> arranca llama.cpp si hace falta
//   -> Python llama al Gateway (/v1/chat/completions) -> agente -> llama.cpp -> respuesta de vuelta por el mismo camino.
// Crea una conversación temporal, chatea y la BORRA al terminar, para no dejar rastro en los datos de Usuario.
const http = require("http");

const base = new URL(process.env.MYKOS_URL || "http://127.0.0.1:3210");
const model = process.env.MYKOS_MODEL || "mykos-cuda";
const timeoutMs = Number(process.env.TIMEOUT_S || 420) * 1000;
const message = process.argv[2] || "Responde únicamente con la palabra OK.";

function request(method, path, body, timeout = 30000) {
  return new Promise((resolve) => {
    const payload = body === undefined ? undefined : JSON.stringify(body);
    const headers = payload ? { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) } : {};
    const chunks = [];
    const t0 = Date.now();
    const done = (status, extra = {}) => {
      let json = null;
      try {
        json = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      } catch {}
      resolve({ status, json, ms: Date.now() - t0, ...extra });
    };
    const r = http.request({ host: base.hostname, port: base.port, method, path, headers, agent: false }, (res) => {
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => done(res.statusCode));
      res.on("error", (e) => done("error:" + (e.code || e.message)));
    });
    r.setTimeout(timeout, () => {
      r.destroy();
      done("timeout");
    });
    r.on("error", (e) => done("error:" + (e.code || e.message)));
    r.end(payload);
  });
}

(async () => {
  const before = (await request("GET", "/api/conversations")).json?.conversations?.length;
  console.log(`conversaciones antes: ${before}`);
  const created = await request("POST", "/api/conversations/new", {});
  const id = created.json?.conversation?.id;
  console.log(`conversación temporal: ${id} (HTTP ${created.status})`);
  if (!id) process.exit(2);
  let ok = false;
  try {
    console.log(`enviando «${message}» al modelo ${model}... (la primera vez carga el modelo en la GPU; puede tardar minutos)`);
    const chat = await request("POST", "/api/chat", { model, conversation_id: id, message, auto_approve: false }, timeoutMs);
    const text = chat.json?.message?.content ?? chat.json?.message ?? JSON.stringify(chat.json).slice(0, 300);
    console.log(`HTTP ${chat.status} en ${(chat.ms / 1000).toFixed(1)} s`);
    console.log(`claves de la respuesta: ${Object.keys(chat.json || {}).join(", ")}`);
    console.log(`respuesta del modelo: ${String(typeof text === "string" ? text : JSON.stringify(text)).slice(0, 400)}`);
    ok = chat.status === 200 && Boolean(text);
  } finally {
    const del = await request("DELETE", `/api/conversations?id=${encodeURIComponent(id)}`);
    const after = (await request("GET", "/api/conversations")).json?.conversations?.length;
    console.log(`conversación temporal borrada: HTTP ${del.status} ${JSON.stringify(del.json)}; conversaciones ahora: ${after} (antes ${before})`);
    if (after !== before) console.log("ATENCIÓN: el número de conversaciones no coincide con el de antes");
  }
  console.log(ok ? "==> EXTREMO A EXTREMO CORRECTO" : "==> EXTREMO A EXTREMO FALLÓ");
  process.exit(ok ? 0 : 1);
})();
