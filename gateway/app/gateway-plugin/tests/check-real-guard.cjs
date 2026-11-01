// Uso: node check-real-guard.cjs
//
// Comprobación SOBRE EL GATEWAY REAL tras activar el tercer corte de la fase 3 (plugin 0.6.0): puerta única.
//   - el trabajador (:3211) rechaza lo que no trae el token del Gateway, con cualquier Host/Origin (solo lecturas y un
//     POST que debe rechazarse: no puede cambiar nada);
//   - por el Gateway (:3210) todo sigue funcionando: lectura, alta y baja de una conversación temporal;
//   - rutas inexistentes / métodos no permitidos: 404 / 405 en el Gateway;
//   - la interfaz real cargada en un navegador no provoca ningún rechazo del Gateway (api_denied) ni 403/404 de la API;
//   - el diario del Gateway clasifica las peticiones.
// No usa credenciales ni el token: es un cliente más y no modifica nada salvo una conversación temporal (creada y borrada).
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

const PUB = 3210;
const BE = 3211;
const journalFile = path.join(os.homedir(), ".mykos", "gateway-state", "mykos", "control-journal.jsonl");
const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });
const info = (name, detail) => results.push({ name, ok: true, info: true, detail });

function request({ method = "GET", path: p, port = PUB, host, headers = {}, body }) {
  return new Promise((resolve) => {
    const h = {};
    for (const [k, v] of Object.entries(headers)) h[k.toLowerCase()] = v;
    if (host !== undefined) h.host = host;
    if (body !== undefined) h["content-length"] = Buffer.byteLength(body);
    const chunks = [];
    const r = http.request({ host: "127.0.0.1", port, method, path: p, headers: h, agent: false, timeout: 30000 }, (res) => {
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, text: Buffer.concat(chunks).toString("utf8") }));
    });
    r.on("error", () => resolve({ status: "error", headers: {}, text: "" }));
    r.on("timeout", () => {
      r.destroy();
      resolve({ status: "timeout", headers: {}, text: "" });
    });
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
const own = { Origin: `http://127.0.0.1:${PUB}` };
const journal = () => (fs.existsSync(journalFile) ? fs.readFileSync(journalFile, "utf8").split("\n").filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return {}; } }) : []);
const conversationIds = async () => (asJson(await request({ path: "/api/conversations" }))?.conversations ?? []).map((c) => c.id).sort();

(async () => {
  const health = asJson(await request({ path: "/mykos-health" }));
  check("Gateway con el plugin 0.7.x, tabla de rutas estricta (51 rutas), backend y almacén activos", health?.ok && /^0\.[78]\./.test(String(health.version)) && health.routes?.strict === true && health.routes.known === 51 && health.backend?.up && health.store?.active, `plugin ${health?.version}; routes=${JSON.stringify(health?.routes)}`);
  const before = await conversationIds();

  // Al trabajador, directo
  const attempts = [
    ["GET", "/api/memory", { host: "evil.example:3211", headers: { Origin: "http://evil.example" } }],
    ["GET", "/api/conversations", {}],
    ["GET", "/api/permissions", {}],
    ["GET", "/api/oauth/status", {}],
    ["POST", "/api/conversations/new", { headers: { "Content-Type": "text/plain", Origin: "http://evil.example" }, body: "{}" }],
  ];
  const outcomes = [];
  for (const [method, p, extra] of attempts) {
    const r = await request({ method, path: p, port: BE, ...extra });
    outcomes.push(`${method} ${p} -> ${r.status}`);
  }
  check("al trabajador directo (sin token, con Host/Origin ajenos y un POST simple): 403 en todo", outcomes.every((o) => o.endsWith("403")), outcomes.join(" | "));
  const h = await request({ path: "/api/health", port: BE });
  check("/api/health del trabajador sigue abierto (supervisión)", h.status === 200, `HTTP ${h.status}`);
  const after = await conversationIds();
  check("el POST directo rechazado no creó ninguna conversación", JSON.stringify(after) === JSON.stringify(before), `${before.length} antes, ${after.length} después`);

  // Por el Gateway
  const mem = await request({ path: "/api/memory" });
  check("por el Gateway: la memoria responde (200)", mem.status === 200 && typeof asJson(mem)?.count === "number", `HTTP ${mem.status}`);
  const created = await request({ method: "POST", path: "/api/conversations/new", headers: { ...own, "Content-Type": "application/json" }, body: JSON.stringify({ title: "prueba del guardián" }) });
  const id = asJson(created)?.conversation?.id;
  const during = await conversationIds();
  const del = await request({ method: "DELETE", path: `/api/conversations?id=${id}`, headers: own });
  const end = await conversationIds();
  check("por el Gateway: se crea y se borra una conversación temporal y todo queda como estaba", created.status === 200 && id && during.length === before.length + 1 && del.status === 200 && JSON.stringify(end) === JSON.stringify(before), `HTTP ${created.status}/${del.status}; ${before.length} → ${during.length} → ${end.length}`);
  const unknown = await request({ path: "/api/nada" });
  const method = await request({ method: "PUT", path: "/api/memory", headers: own, body: "{}" });
  check("ruta inexistente: 404; método no permitido: 405 con «Allow»", unknown.status === 404 && method.status === 405 && method.headers.allow === "GET", `HTTP ${unknown.status}/${method.status}; Allow: ${method.headers.allow}`);
  const evil = await request({ method: "POST", path: "/api/conversations/new", headers: { "Content-Type": "application/json", Origin: "http://evil.example" }, body: "{}" });
  check("por el Gateway, una web ajena (Origin) sigue recibiendo 403", evil.status === 403, `HTTP ${evil.status}`);

  // La interfaz real en un navegador: nada rechazado
  const edge = ["C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe", "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"].find((p) => fs.existsSync(p));
  if (edge) {
    const mark = new Date().toISOString();
    const titles = (asJson(await request({ path: "/api/conversations" }))?.conversations ?? []).map((c) => String(c.title || "")).filter((t) => t.length >= 4 && !/[<>&"'`]/.test(t));
    const profile = path.join(os.tmpdir(), "edge-profile-real-guard");
    const common = ["--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars", `--user-data-dir=${profile}`, "--window-size=1440,900", "--virtual-time-budget=12000"];
    let dom = "";
    try {
      dom = execFileSync(edge, [...common, "--dump-dom", `http://127.0.0.1:${PUB}/`], { encoding: "utf8", timeout: 120000, maxBuffer: 32 * 1024 * 1024, stdio: ["ignore", "pipe", "ignore"] });
    } catch (e) {
      dom = String(e.stdout || "");
    }
    const shown = titles.filter((t) => dom.includes(t));
    check("la interfaz real cargada en un navegador muestra los títulos de tus conversaciones", dom.length > 5000 && shown.length >= 1, `${shown.length} de ${titles.length} títulos visibles`);
    const since = journal().filter((e) => e.at >= mark);
    const requests = since.filter((e) => e.event === "api_request");
    const bad = since.filter((e) => e.event === "api_denied" || (e.event === "api_result" && (e.status === 403 || e.status === 404 || e.status === 405) && e.path !== "/api/nada" && e.path !== "/api/memory" && e.path !== "/api/conversations/new"));
    const routes = [...new Set(requests.map((e) => `${e.method} ${e.path}`))];
    check("la interfaz no provoca ningún rechazo (api_denied) ni 403/404/405 de la API", requests.length > 0 && bad.length === 0, `${requests.length} peticiones de la interfaz (${routes.length} rutas distintas)${bad.length ? "; rechazos: " + bad.map((e) => `${e.method} ${e.path} ${e.status ?? e.reason}`).join(", ") : ""}`);
    info("rutas que pidió la interfaz", routes.join("  "));
  } else info("Edge no encontrado: se omite la vista en el navegador", "");

  // Diario
  const j = journal();
  const create = [...j].reverse().find((e) => e.event === "api_request" && e.method === "POST" && e.path === "/api/conversations/new" && e.domain);
  const denied = [...j].reverse().find((e) => e.event === "api_denied" && e.path === "/api/nada");
  check("el diario del Gateway clasifica las peticiones (dominio/acción/riesgo) y anota los rechazos", create?.domain === "conversations" && create.action === "create" && create.risk === "write" && denied?.reason === "unknown_route" && denied.status === 404, JSON.stringify(create ?? {}).slice(0, 160));
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
    console.log(`${r.info ? "INFO " : r.ok ? "OK   " : "FALLA"}  ${r.name.padEnd(width)}  ${r.detail}`);
  }
  const counted = results.filter((r) => !r.info).length;
  console.log(failures ? `\n==> ${failures} de ${counted} comprobaciones FALLARON` : `\n==> ${counted}/${counted} comprobaciones correctas`);
  process.exit(failures ? 1 : 0);
}
