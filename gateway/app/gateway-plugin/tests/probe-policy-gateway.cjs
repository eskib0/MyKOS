// Uso: node probe-policy-gateway.cjs <puertoGateway>
//
// Fase 3, cuarto corte: el Gateway DECIDE los servicios auxiliares (benchmark, modelos de Ollama, credenciales,
// subidas y latidos de nodos) antes de reenviar, y el trabajador Python exige su decisión firmada.
//
// Se ejecuta con un Gateway desechable que lanza el server.py REAL sobre una copia de datos vacía:
//   BACKEND_PORT   puerto interno del backend (3299)
//   PROJECT_DIR    copia de prueba del proyecto (make-project.cjs)
//   PYTHON_EXE     intérprete de Python (para el arranque manual, si se usa)
//   TAG            etiqueta del estado de prueba: <test>/state-<TAG>/mykos/control-journal.jsonl es el diario
//   CONTROL_TOKEN  el mismo valor que MYKOS_CONTROL_TOKEN del Gateway de prueba
//
// Qué comprueba
//   A. Estado: plugin 0.7.x, política activa y 16 rutas gobernadas.
//   B. El Gateway rechaza peticiones mal formadas de estos dominios y NO llegan a Python (se comprueba en su registro).
//   C. Lo que cumple la política sí llega a Python (latido con token inventado → 400 del propio Python; subida real).
//   D. Límites de carga: la 13.ª acción de modelos del minuto recibe 429, y otros dominios siguen funcionando.
//   E. El trabajador, directo y con el token del Gateway, exige la decisión firmada: sin ella, manipulada, caducada,
//      de otra ruta o con otro cuerpo → 403/400; con la correcta → pasa. Una ruta sin política sigue funcionando.
//   F. El diario clasifica cada decisión (dominio, acción, riesgo, política) y no guarda cuerpos, tokens ni claves.
const http = require("http");
const net = require("net");
const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");

const gw = Number(process.argv[2] || 18795);
const be = Number(process.env.BACKEND_PORT || 3299);
const project = process.env.PROJECT_DIR;
const tag = process.env.TAG || "Y";
const token = String(process.env.CONTROL_TOKEN || "");
if (!project) throw new Error("falta la variable PROJECT_DIR");
const testRoot = path.join(os.homedir(), "mykos-gateway-test");
const journalFile = path.join(testRoot, `state-${tag}`, "mykos", "control-journal.jsonl");
const workerLog = path.join(project, "data", "mykos-backend.log");

const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function request({ method = "GET", path: p, headers = {}, body, port = gw, timeoutMs = 30000 }) {
  return new Promise((resolve) => {
    const h = {};
    for (const [k, v] of Object.entries(headers)) h[k.toLowerCase()] = v;
    if (body !== undefined && h["content-length"] === undefined) h["content-length"] = Buffer.byteLength(body);
    const chunks = [];
    const fail = (why) => resolve({ status: why, headers: {}, text: Buffer.concat(chunks).toString("utf8") });
    const r = http.request({ host: "127.0.0.1", port, method, path: p, headers: h, agent: false }, (res) => {
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, text: Buffer.concat(chunks).toString("utf8") }));
      res.on("error", (e) => fail("error:" + (e.code || e.message)));
    });
    r.setTimeout(timeoutMs, () => {
      r.destroy();
      fail("timeout");
    });
    r.on("error", (e) => fail("error:" + (e.code || e.message)));
    r.end(body);
  });
}

/** Petición a pelo por socket: permite declarar un Content-Length que no se corresponde con lo enviado. */
function rawRequest({ port = gw, method = "POST", path: p, headers = {}, body = "" }) {
  return new Promise((resolve) => {
    const lines = [`${method} ${p} HTTP/1.1`, `Host: 127.0.0.1:${port}`, "Connection: close"];
    for (const [k, v] of Object.entries(headers)) lines.push(`${k}: ${v}`);
    const socket = net.connect({ host: "127.0.0.1", port }, () => {
      socket.write(`${lines.join("\r\n")}\r\n\r\n${body}`);
    });
    let text = "";
    const done = (why) => resolve({ status: why ?? Number(/^HTTP\/1\.[01] (\d{3})/.exec(text)?.[1] || 0), text });
    socket.setTimeout(15000, () => {
      socket.destroy();
      done("timeout");
    });
    socket.on("data", (c) => {
      text += c.toString("utf8");
      if (/\r\n\r\n/.test(text) && text.length > 0) {
        // basta con la cabecera y el principio del cuerpo
        setTimeout(() => {
          socket.destroy();
          done();
        }, 120);
      }
    });
    socket.on("error", () => done("error"));
    socket.on("end", () => done());
  });
}

const asJson = (r) => {
  try {
    return JSON.parse(r.text);
  } catch {
    return null;
  }
};
async function waitFor(fn, ms, step = 250) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const v = await fn();
    if (v) return v;
    await sleep(step);
  }
  return null;
}
const health = async () => asJson(await request({ path: "/mykos-health", timeoutMs: 8000 }));
const own = { Origin: `http://127.0.0.1:${gw}` };
const viaGateway = (method, p, payload, extra = {}) => request({
  method, path: p,
  headers: { ...own, ...(payload !== undefined ? { "Content-Type": "application/json" } : {}), ...extra },
  ...(payload !== undefined ? { body: typeof payload === "string" ? payload : JSON.stringify(payload) } : {}),
});
const direct = (method, p, { body, headers = {} } = {}) => request({ method, path: p, port: be, headers, ...(body !== undefined ? { body } : {}) });
const journal = () => (fs.existsSync(journalFile)
  ? fs.readFileSync(journalFile, "utf8").split("\n").filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return { broken: l }; } })
  : []);
const workerLogText = () => (fs.existsSync(workerLog) ? fs.readFileSync(workerLog, "utf8") : "");

/** Decisión firmada como la que emite el Gateway (la prueba conoce su token). */
function decision(method, p, rawBody, { deltaSeconds = 90, tamper = false, hash } = {}) {
  const expires = Math.floor(Date.now() / 1000) + deltaSeconds;
  const bodyHash = hash ?? (rawBody === null ? "-" : crypto.createHash("sha256").update(rawBody, "utf8").digest("hex"));
  const payload = `gateway-decision|${method} ${p}|${bodyHash}|${expires}`;
  let signature = crypto.createHmac("sha256", token).update(payload, "utf8").digest("hex");
  if (tamper) signature = `${signature.slice(0, -1)}${signature.endsWith("a") ? "b" : "a"}`;
  return `v1.${expires}.${bodyHash}.${signature}`;
}
const multipart = (() => {
  const boundary = "----mykosPolicyProbe";
  // El trabajador solo admite PDF e imágenes (mira la extensión), así que el archivo de prueba es un .png mínimo.
  const body = `--${boundary}\r\nContent-Disposition: form-data; name="files"; filename="nota-de-prueba.png"\r\nContent-Type: image/png\r\n\r\nPNG de prueba de politica\r\n--${boundary}--\r\n`;
  return { boundary, body, contentType: `multipart/form-data; boundary=${boundary}` };
})();

(async () => {
  // A. Arranque
  const up = await waitFor(async () => {
    const h = await health();
    return h?.ok && h.backend?.up && h.backend.phase === "up" ? h : null;
  }, 150000);
  if (!up) {
    check("el Gateway arrancó con el backend «up»", false, JSON.stringify(await health()).slice(0, 400));
    return finish();
  }
  check("Gateway con el plugin 0.7.x, política activa y 16 rutas gobernadas", /^0\.[78]\./.test(String(up.version)) && up.policy?.strict === true && up.policy.governed === 16, `plugin ${up.version}; policy=${JSON.stringify(up.policy)}`);
  check("la prueba conoce el token del Gateway (CONTROL_TOKEN)", token.length >= 16, `${token.length} caracteres`);

  // B. El Gateway rechaza lo que no cumple la política, y no molesta a Python
  const logBefore = workerLogText().length;
  const denials = [
    ["benchmark sin modelo", () => viaGateway("POST", "/api/benchmark", {}), 400],
    ["benchmark con modelo raro", () => viaGateway("POST", "/api/benchmark", { model: "qwen3; rm -rf /" }), 400],
    ["benchmark con campo inventado", () => viaGateway("POST", "/api/benchmark", { model: "qwen3:14b", prompt: "hola" }), 400],
    ["benchmark con perfil inventado", () => viaGateway("POST", "/api/benchmark", { model: "qwen3:14b", profiles: ["turbo"] }), 400],
    ["benchmark con cuerpo enorme", () => viaGateway("POST", "/api/benchmark", JSON.stringify({ model: "a".repeat(20000) })), 413],
    ["benchmark con JSON roto", () => viaGateway("POST", "/api/benchmark", "{modelo:"), 400],
    ["descarga de modelo sin modelo", () => viaGateway("POST", "/api/ollama/pull-request", { conversation_id: "abc" }), 400],
    ["borrado de modelo con conversación con «..»", () => viaGateway("POST", "/api/ollama/delete-request", { model: "x", conversation_id: "../../etc" }), 400],
    ["OAuth de Claude con el proveedor de otra ruta", () => viaGateway("POST", "/api/oauth/claude/start", { provider: "openrouter" }), 400],
    ["OAuth de OpenAI con campo inventado", () => viaGateway("POST", "/api/oauth/openai/logout", { provider: "openai", force: true }), 400],
    ["NVIDIA sin clave", () => viaGateway("POST", "/api/providers/nvidia/connect", { provider: "nvidia_api" }), 400],
    ["NVIDIA con clave con salto de línea", () => viaGateway("POST", "/api/providers/nvidia/connect", { api_key: "nvapi-1234567890123456\nGET /otra" }), 400],
    ["subida que no es un formulario", () => viaGateway("POST", "/api/uploads", { files: "x" }), 415],
    ["latido de nodo sin token de nodo", () => viaGateway("POST", "/api/nodes/heartbeat", { node_id: "n1" }), 403],
    ["latido de nodo con token corto", () => viaGateway("POST", "/api/nodes/heartbeat", { node_id: "n1" }, { "X-MyKOS-Node-Token": "corto" }), 403],
    ["latido de nodo con campo inventado", () => viaGateway("POST", "/api/nodes/heartbeat", { node_id: "n1", command: "shutdown" }, { "X-MyKOS-Node-Token": "n".repeat(40) }), 400],
    ["retorno de OAuth con código larguísimo", () => viaGateway("GET", `/api/oauth/openrouter/callback?code=${"a".repeat(900)}`), 400],
    ["retorno de OAuth con carácter de control", () => viaGateway("GET", "/api/oauth/openrouter/callback?code=abc%00def"), 400],
  ];
  for (const [label, run, expected] of denials) {
    const response = await run();
    const json = asJson(response);
    check(`el Gateway rechaza: ${label} (${expected})`, response.status === expected && typeof json?.error === "string" && json.error.length > 5, `HTTP ${response.status} · ${String(json?.error || response.text).slice(0, 90)}`);
  }
  const bigDeclared = await rawRequest({
    path: "/api/uploads",
    headers: { Origin: `http://127.0.0.1:${gw}`, "Content-Type": multipart.contentType, "Content-Length": String(40 * 1024 * 1024) },
    body: multipart.body,
  });
  check("el Gateway rechaza una subida que declara 40 MB (413) sin leerla", bigDeclared.status === 413, `HTTP ${bigDeclared.status}`);
  const noLength = await rawRequest({ path: "/api/uploads", headers: { Origin: `http://127.0.0.1:${gw}`, "Content-Type": multipart.contentType, "Transfer-Encoding": "chunked" }, body: "0\r\n\r\n" });
  check("el Gateway rechaza una subida sin Content-Length (411)", noLength.status === 411, `HTTP ${noLength.status}`);

  const logAfterDenials = workerLogText().slice(logBefore);
  const reachedPython = ["/api/benchmark", "/api/ollama/pull-request", "/api/ollama/delete-request", "/api/oauth/claude/start", "/api/providers/nvidia/connect", "/api/uploads"]
    .filter((route) => logAfterDenials.includes(route));
  check("ninguna de esas peticiones llegó al trabajador Python (su registro no las menciona)", reachedPython.length === 0, reachedPython.join(" | ") || "ninguna");

  const denialEvents = journal().filter((e) => e.event === "api_denied" && e.policy);
  check(`el diario anota cada rechazo con su política y su motivo (${denialEvents.length})`, denialEvents.length >= denials.length, `${denialEvents.length} entradas api_denied con política`);
  const reasons = new Set(denialEvents.map((e) => e.reason));
  check("los motivos del diario son concretos (campo desconocido, formato, cabecera, tamaño…)", ["unknown_field", "bad_format", "missing_field", "missing_header", "bad_content_type"].every((r) => reasons.has(r)), [...reasons].join(", "));
  check("los rechazos del diario llevan dominio, acción y riesgo", denialEvents.every((e) => e.domain && e.action && e.risk), "");

  // C. Lo que cumple la política pasa y llega a Python
  const heartbeat = await viaGateway("POST", "/api/nodes/heartbeat", { node_id: "nodo-de-prueba" }, { "X-MyKOS-Node-Token": "n".repeat(40) });
  const heartbeatJson = asJson(heartbeat);
  check("un latido con la forma correcta pasa la política y lo resuelve Python (nodo inválido → 400)", heartbeat.status === 400 && /nodo|token/i.test(String(heartbeatJson?.error || "")), `HTTP ${heartbeat.status} · ${String(heartbeatJson?.error || "").slice(0, 80)}`);
  check("el registro del trabajador confirma que el latido sí llegó", workerLogText().includes("/api/nodes/heartbeat"), "");
  const upload = await viaGateway("POST", "/api/uploads", multipart.body, { "Content-Type": multipart.contentType });
  const uploadJson = asJson(upload);
  check("una subida real de un archivo pequeño atraviesa la política y el trabajador la registra", upload.status === 200 && Array.isArray(uploadJson?.attachments) && uploadJson.attachments.length === 1, `HTTP ${upload.status} · ${String(upload.text).slice(0, 90)}`);
  const decisionEvents = journal().filter((e) => e.event === "api_decision");
  check("el diario anota la decisión «allow» de las permitidas, con su política", decisionEvents.length >= 2 && decisionEvents.every((e) => e.decision === "allow" && e.policy && e.domain), `${decisionEvents.length} entradas api_decision`);
  check("la decisión anota si queda ligada al cuerpo exacto (JSON sí, subida no)", decisionEvents.some((e) => e.path === "/api/nodes/heartbeat" && e.body_bound === true) && decisionEvents.some((e) => e.path === "/api/uploads" && e.body_bound === false), "");

  // D. Límites de carga
  const rate = [];
  for (let i = 0; i < 13; i += 1) {
    const response = await viaGateway("POST", "/api/ollama/delete-request", { model: `modelo-inventado-${i}` });
    rate.push(response.status);
  }
  check("las 12 primeras acciones de modelos del minuto no se limitan", rate.slice(0, 12).every((status) => status !== 429), rate.slice(0, 12).join(","));
  const limited = rate[12];
  check("la 13.ª acción de modelos del mismo minuto recibe 429", limited === 429, `HTTP ${limited}`);
  const limitedEvent = journal().reverse().find((e) => e.event === "api_denied" && e.reason === "rate_limited");
  check("el diario anota el límite por ritmo con su grupo de política", limitedEvent?.policy === "ollama-models", JSON.stringify(limitedEvent || {}).slice(0, 120));
  const otherDomain = await viaGateway("POST", "/api/nodes/heartbeat", { node_id: "nodo-de-prueba" }, { "X-MyKOS-Node-Token": "n".repeat(40) });
  check("el límite es por dominio: los latidos de nodo siguen funcionando", otherDomain.status === 400, `HTTP ${otherDomain.status}`);

  // E. El trabajador exige la decisión firmada (pruebas directas con el token del Gateway)
  const heartbeatBody = JSON.stringify({ node_id: "nodo-de-prueba" });
  const nodeHeaders = { "Content-Type": "application/json", "X-MyKOS-Control-Token": token, "X-MyKOS-Node-Token": "n".repeat(40) };
  const attempts = [
    ["sin decisión firmada", {}, 403],
    ["con la firma manipulada", { "X-MyKOS-Gateway-Decision": decision("POST", "/api/nodes/heartbeat", heartbeatBody, { tamper: true }) }, 403],
    ["con una decisión caducada", { "X-MyKOS-Gateway-Decision": decision("POST", "/api/nodes/heartbeat", heartbeatBody, { deltaSeconds: -30 }) }, 403],
    ["con una caducidad inventada a una hora", { "X-MyKOS-Gateway-Decision": decision("POST", "/api/nodes/heartbeat", heartbeatBody, { deltaSeconds: 3600 }) }, 403],
    ["con una decisión de otra ruta", { "X-MyKOS-Gateway-Decision": decision("POST", "/api/benchmark", heartbeatBody) }, 403],
    ["con una decisión de otro método", { "X-MyKOS-Gateway-Decision": decision("GET", "/api/nodes/heartbeat", heartbeatBody) }, 403],
    ["con un formato de decisión desconocido", { "X-MyKOS-Gateway-Decision": "v2.1.2.3" }, 403],
    ["con la decisión sin ligar al cuerpo («-») en una ruta JSON", { "X-MyKOS-Gateway-Decision": decision("POST", "/api/nodes/heartbeat", null) }, 403],
    ["con una decisión válida para OTRO cuerpo", { "X-MyKOS-Gateway-Decision": decision("POST", "/api/nodes/heartbeat", JSON.stringify({ node_id: "otro" })) }, 400],
  ];
  for (const [label, extra, expected] of attempts) {
    const response = await direct("POST", "/api/nodes/heartbeat", { body: heartbeatBody, headers: { ...nodeHeaders, ...extra } });
    const json = asJson(response);
    const mentionsDecision = /decisión/i.test(String(json?.error || ""));
    check(`el trabajador rechaza la llamada directa ${label} (${expected})`, response.status === expected && mentionsDecision, `HTTP ${response.status} · ${String(json?.error || response.text).slice(0, 80)}`);
  }
  {
    const response = await direct("POST", "/api/nodes/heartbeat", {
      body: heartbeatBody,
      headers: { ...nodeHeaders, "X-MyKOS-Gateway-Decision": decision("POST", "/api/nodes/heartbeat", heartbeatBody) },
    });
    const json = asJson(response);
    check("con la decisión correcta (ruta, método y cuerpo) el trabajador la atiende", response.status === 400 && /nodo|token/i.test(String(json?.error || "")), `HTTP ${response.status} · ${String(json?.error || "").slice(0, 80)}`);
  }
  {
    const response = await direct("POST", "/api/uploads", {
      body: multipart.body,
      headers: { "Content-Type": multipart.contentType, "X-MyKOS-Control-Token": token, "X-MyKOS-Gateway-Decision": decision("POST", "/api/uploads", null) },
    });
    check("en una subida vale la decisión sin ligar al cuerpo («-»), que es la que emite el Gateway", response.status === 200, `HTTP ${response.status} · ${String(response.text).slice(0, 80)}`);
  }
  {
    const response = await direct("GET", "/api/health", { headers: { "X-MyKOS-Control-Token": token } });
    check("una ruta sin política sigue funcionando con solo el token (sin regresión)", response.status === 200, `HTTP ${response.status}`);
  }
  {
    const response = await direct("POST", "/api/benchmark", { body: JSON.stringify({ model: "qwen3:14b" }), headers: { "Content-Type": "application/json" } });
    check("sin token del Gateway sigue siendo 403 antes de mirar la decisión", response.status === 403, `HTTP ${response.status}`);
  }

  // F. Higiene del diario
  const text = fs.existsSync(journalFile) ? fs.readFileSync(journalFile, "utf8") : "";
  check("el diario no contiene el token del Gateway", token.length > 0 && !text.includes(token), "");
  check("el diario no contiene claves, cuerpos ni tokens de nodo", !text.includes("nvapi-") && !text.includes("nodo-de-prueba") && !text.includes("n".repeat(40)) && !/api_key/.test(text), "");
  const policyEvents = journal().filter((e) => e.policy);
  check(`todas las entradas con política llevan método, ruta y estado (${policyEvents.length})`, policyEvents.length > 0 && policyEvents.every((e) => e.method && e.path && (e.status || e.decision)), "");
  const load = (await health())?.policy?.load;
  check("/mykos-health informa de la carga por grupo de política", load && typeof load === "object", JSON.stringify(load || {}).slice(0, 120));
  finish();
})().catch((error) => {
  check("la batería terminó sin excepciones", false, String(error && error.stack ? error.stack : error));
  finish();
});

function finish() {
  const width = Math.min(150, Math.max(...results.map((r) => r.name.length)));
  let failures = 0;
  for (const r of results) {
    if (!r.ok) failures += 1;
    console.log(`${r.ok ? "OK   " : "FALLA"}  ${r.name.padEnd(width)}  ${r.detail}`);
  }
  console.log(failures ? `\n==> ${failures} de ${results.length} comprobaciones FALLARON` : `\n==> ${results.length}/${results.length} comprobaciones correctas`);
  process.exit(failures ? 1 : 0);
}
