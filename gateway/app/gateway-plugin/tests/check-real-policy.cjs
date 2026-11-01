// Uso: node check-real-policy.cjs [puerto]        (SOBRE EL GATEWAY REAL, por defecto 3210)
//
// Comprobación del cuarto corte de la fase 3 en el servicio real: el Gateway decide los servicios auxiliares.
// No cambia nada: solo hace peticiones que la política rechaza (no llegan a Python) y un latido de nodo con un token
// inventado, que Python rechaza por su cuenta. No toca credenciales, ni modelos, ni conversaciones, ni subidas.
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");

const port = Number(process.argv[2] || 3210);
const journalFile = path.join(os.homedir(), ".mykos", "gateway-state", "mykos", "control-journal.jsonl");
const workerLog = path.resolve(__dirname, "..", "..", "data", "mykos-backend.log");

const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });

function request({ method = "GET", path: p, headers = {}, body, port: target = port, timeoutMs = 20000 }) {
  return new Promise((resolve) => {
    const h = {};
    for (const [k, v] of Object.entries(headers)) h[k.toLowerCase()] = v;
    if (body !== undefined && h["content-length"] === undefined) h["content-length"] = Buffer.byteLength(body);
    const chunks = [];
    const r = http.request({ host: "127.0.0.1", port: target, method, path: p, headers: h, agent: false }, (res) => {
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, text: Buffer.concat(chunks).toString("utf8") }));
    });
    r.setTimeout(timeoutMs, () => {
      r.destroy();
      resolve({ status: "timeout", text: "" });
    });
    r.on("error", (e) => resolve({ status: "error:" + (e.code || e.message), text: "" }));
    r.end(body);
  });
}
const asJson = (r) => {
  try {
    return JSON.parse(r.text);
  } catch {
    return null;
  }
};
const own = { Origin: `http://127.0.0.1:${port}` };
const via = (method, p, payload, extra = {}) => request({
  method, path: p,
  headers: { ...own, ...(payload !== undefined ? { "Content-Type": "application/json" } : {}), ...extra },
  ...(payload !== undefined ? { body: typeof payload === "string" ? payload : JSON.stringify(payload) } : {}),
});
const journalTail = (lines = 400) => {
  if (!fs.existsSync(journalFile)) return [];
  const all = fs.readFileSync(journalFile, "utf8").split("\n").filter(Boolean);
  return all.slice(-lines).map((l) => { try { return JSON.parse(l); } catch { return { broken: l }; } });
};

(async () => {
  const health = asJson(await request({ path: "/mykos-health" }));
  check("el MyKOS real responde con el plugin 0.7.x, política activa (16 rutas gobernadas), backend y almacén en marcha",
    health?.ok && /^0\.[78]\./.test(String(health.version)) && health.policy?.strict === true && health.policy.governed === 16 && health.backend?.up && health.store?.active,
    `plugin ${health?.version}; policy=${JSON.stringify(health?.policy?.strict)}/${health?.policy?.governed}; backend=${health?.backend?.up}; almacén=${health?.store?.active}`);

  const logBefore = fs.existsSync(workerLog) ? fs.readFileSync(workerLog, "utf8").length : 0;
  const denials = [
    ["medición con un campo inventado", () => via("POST", "/api/benchmark", { model: "qwen3:14b", prompt: "hola" }), 400],
    ["medición sin modelo", () => via("POST", "/api/benchmark", {}), 400],
    ["descarga de modelo con un nombre con espacios y punto y coma", () => via("POST", "/api/ollama/pull-request", { model: "modelo; rm -rf" }), 400],
    ["clave de NVIDIA ausente (no toca las credenciales)", () => via("POST", "/api/providers/nvidia/connect", { provider: "nvidia_api" }), 400],
    ["OAuth de Claude con el proveedor de otra ruta", () => via("POST", "/api/oauth/claude/start", { provider: "openrouter" }), 400],
    ["subida que no es un formulario de archivos", () => via("POST", "/api/uploads", { files: "x" }), 415],
    ["latido de nodo sin token de nodo", () => via("POST", "/api/nodes/heartbeat", { node_id: "comprobacion" }), 403],
    ["retorno de OAuth con un código larguísimo", () => via("GET", `/api/oauth/openrouter/callback?code=${"a".repeat(900)}`), 400],
  ];
  for (const [label, run, expected] of denials) {
    const response = await run();
    const json = asJson(response);
    check(`el Gateway rechaza en el MyKOS real: ${label} (${expected})`, response.status === expected && typeof json?.error === "string", `HTTP ${response.status} · ${String(json?.error || response.text).slice(0, 90)}`);
  }
  const logAfter = fs.existsSync(workerLog) ? fs.readFileSync(workerLog, "utf8").slice(logBefore) : "";
  const leaked = ["/api/benchmark", "/api/ollama/pull-request", "/api/providers/nvidia/connect", "/api/oauth/claude/start", "/api/uploads"].filter((route) => logAfter.includes(route));
  check("ninguna de esas peticiones llegó al trabajador Python (su registro no las menciona)", leaked.length === 0, leaked.join(" | ") || "ninguna");

  const heartbeat = await via("POST", "/api/nodes/heartbeat", { node_id: "comprobacion-politica" }, { "X-MyKOS-Node-Token": "c".repeat(40) });
  const heartbeatJson = asJson(heartbeat);
  check("un latido con la forma correcta atraviesa la política y lo resuelve Python (nodo inválido → 400)", heartbeat.status === 400 && /nodo|token/i.test(String(heartbeatJson?.error || "")), `HTTP ${heartbeat.status} · ${String(heartbeatJson?.error || "").slice(0, 80)}`);

  const worker = await request({ port: 3211, method: "POST", path: "/api/benchmark", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: "qwen3:14b" }) });
  check("el trabajador interno (3211) sigue rechazando una medición directa (403)", worker.status === 403, `HTTP ${worker.status}`);

  const tail = journalTail(600);
  const denied = tail.filter((e) => e.event === "api_denied" && e.policy);
  const decided = tail.filter((e) => e.event === "api_decision");
  check(`el diario real anota los rechazos de política con su motivo (${denied.length} recientes)`, denied.length >= denials.length, denied.slice(-3).map((e) => `${e.path}:${e.reason}`).join(" | "));
  check("el diario real anota la decisión «allow» del latido permitido", decided.some((e) => e.path === "/api/nodes/heartbeat" && e.decision === "allow" && e.body_bound === true), `${decided.length} decisiones`);
  const text = tail.map((e) => JSON.stringify(e)).join("\n");
  check("el diario real no guarda claves, cuerpos ni tokens", !text.includes("nvapi-") && !text.includes("comprobacion-politica") && !text.includes("c".repeat(40)) && !/api_key/.test(text), "");
  check("ninguna línea reciente del diario está rota", !tail.some((e) => e.broken), "");

  const after = asJson(await request({ path: "/mykos-health" }));
  check("tras la comprobación, MyKOS sigue sano (backend arriba, almacén activo, misma versión)", after?.ok && after.backend?.up && after.store?.active && after.version === health?.version, `backend=${after?.backend?.up}; almacén=${after?.store?.active}`);
  finish();
})().catch((error) => {
  check("la comprobación terminó sin excepciones", false, String(error && error.stack ? error.stack : error));
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
