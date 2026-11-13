// Uso: node probe-routes.cjs        (no necesita Gateway)
//
// Tabla de rutas del Gateway (routes.js), fase 3 tercer corte:
//   1. Coincide EXACTAMENTE con las rutas /api/* que sirve server.py (método por método): una ruta nueva en Python sin
//      darla de alta en la tabla, o una entrada de la tabla que Python ya no sirve, hace fallar esta prueba.
//   2. classifyRoute() clasifica bien: rutas exactas, con parámetros, métodos, barras finales, mayúsculas y
//      codificaciones raras (lo desconocido no se clasifica).
//   3. Cada ruta tiene dominio, acción, riesgo y propietario válidos, y las de escritura/credenciales no se quedan en «read».
const fs = require("fs");
const os = require("os");
const path = require("path");
const { pathToFileURL } = require("url");

const repo = path.resolve(__dirname, "..", "..");
const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });

function pythonRoutes() {
  const src = fs.readFileSync(path.join(repo, "server.py"), "utf8");
  const found = new Set();
  const unknownPrefixes = [];
  for (const [method, fn] of [["GET", "do_GET"], ["POST", "do_POST"], ["DELETE", "do_DELETE"]]) {
    const start = src.indexOf(`    def ${fn}(self)`);
    if (start < 0) throw new Error(`no encuentro ${fn} en server.py`);
    const next = src.indexOf("\n    def ", start + 10);
    const body = src.slice(start, next < 0 ? undefined : next);
    for (const m of body.matchAll(/path\s*(?:==|!=)\s*"(\/api\/[^"]+)"/g)) found.add(`${method} ${m[1]}`);
    for (const m of body.matchAll(/path\s+in\s+\{([^}]*)\}/g)) for (const s of m[1].matchAll(/"(\/api\/[^"]+)"/g)) found.add(`${method} ${s[1]}`);
    for (const m of body.matchAll(/path\.startswith\("(\/api\/[^"]+)"\)/g)) {
      const prefix = m[1];
      if (method === "POST" && prefix === "/api/permissions/") found.add("POST /api/permissions/:id/revoke");
      else if (method === "POST" && prefix === "/api/approvals/") found.add("POST /api/approvals/:id/(approve|reject)");
      else unknownPrefixes.push(`${method} ${prefix}`);
    }
  }
  return { found, unknownPrefixes };
}

(async () => {
  const { ROUTE_TABLE, classifyRoute } = await import(pathToFileURL(path.join(repo, "gateway-plugin", "mykos-ui", "routes.js")).href);

  // 1. Coincidencia con server.py
  const { found, unknownPrefixes } = pythonRoutes();
  const registry = new Set(ROUTE_TABLE.map((r) => `${r.method} ${r.pattern}`));
  const gatewayOnly = new Set(ROUTE_TABLE.filter((r) => r.owner === "gateway").map((r) => `${r.method} ${r.pattern}`));
  const workerFound = new Set([...found].filter((r) => !gatewayOnly.has(r)));
  const workerRegistry = new Set([...registry].filter((r) => !gatewayOnly.has(r)));
  const duplicatedGatewayHandlers = [...found].filter((r) => gatewayOnly.has(r) && r !== "GET /api/health").sort();
  const missing = [...workerFound].filter((r) => !workerRegistry.has(r)).sort();
  const extra = [...workerRegistry].filter((r) => !workerFound.has(r)).sort();
  check(`server.py sirve ${found.size} rutas /api/* y la tabla tiene ${workerRegistry.size} rutas de trabajador más ${gatewayOnly.size} del Gateway`, workerFound.size === workerRegistry.size, `${found.size} en Python / ${workerFound.size} de trabajador / ${gatewayOnly.size} del Gateway`);
  check("todas las rutas de server.py están en la tabla del Gateway", missing.length === 0, missing.join(" | ") || "ninguna falta");
  check("todas las rutas de trabajador de la tabla existen en server.py", extra.length === 0, extra.join(" | ") || "ninguna sobra");
  check("server.py no conserva handlers HTTP de rutas ya propiedad del Gateway", duplicatedGatewayHandlers.length === 0, duplicatedGatewayHandlers.join(" | ") || "ninguno");
  check("server.py no usa prefijos /api/ desconocidos (rutas por prefijo sin clasificar)", unknownPrefixes.length === 0, unknownPrefixes.join(" | ") || "ninguno");
  check("no hay entradas duplicadas en la tabla", registry.size === ROUTE_TABLE.length, `${ROUTE_TABLE.length} entradas, ${registry.size} distintas`);

  // 2. Validez de cada entrada
  const RISKS = new Set(["read", "write", "sensitive"]);
  const OWNERS = new Set(["gateway", "worker"]);
  const bad = ROUTE_TABLE.filter((r) => !r.domain || !r.action || !RISKS.has(r.risk) || !OWNERS.has(r.owner) || !["GET", "POST", "DELETE"].includes(r.method) || !r.pattern.startsWith("/api/"));
  check("cada ruta tiene método, dominio, acción, riesgo y propietario válidos", bad.length === 0, bad.map((r) => `${r.method} ${r.pattern}`).join(", ") || `${ROUTE_TABLE.length} entradas correctas`);
  const getNotRead = ROUTE_TABLE.filter((r) => r.method === "GET" && r.risk !== "read").map((r) => r.pattern);
  check("las GET son «read»; solo el retorno de OAuth (cambia credenciales) es «sensitive»", getNotRead.length === 1 && getNotRead[0] === "/api/oauth/openrouter/callback", getNotRead.join(", "));
  const writesAsRead = ROUTE_TABLE.filter((r) => r.method !== "GET" && r.risk === "read").map((r) => `${r.method} ${r.pattern}`);
  check("ninguna ruta POST/DELETE está marcada como «read»", writesAsRead.length === 0, writesAsRead.join(", "));
  const credentialRoutes = ROUTE_TABLE.filter((r) => /^\/api\/(oauth|providers)\//.test(r.pattern) && r.method === "POST");
  check("todas las rutas de credenciales y proveedores (OAuth, Meta AI, Grok, NVIDIA, Kimi, Gemini, Mistral, Anthropic, Antigravity y Qwen) son «sensitive»", credentialRoutes.length === 37 && credentialRoutes.every((r) => r.risk === "sensitive"), `${credentialRoutes.length} rutas`);
  const sensitive = new Set(ROUTE_TABLE.filter((r) => r.risk === "sensitive").map((r) => `${r.method} ${r.pattern}`));
  check("chat, aprobaciones, benchmark, descargas de modelos, voz y transcripción son «sensitive»", ["POST /api/chat", "POST /api/approvals/:id/(approve|reject)", "POST /api/benchmark", "POST /api/ollama/pull-request", "POST /api/ollama/delete-request", "POST /api/tts", "POST /api/transcribe"].every((r) => sensitive.has(r)), "");
  const gatewayOwned = ROUTE_TABLE.filter((r) => r.owner === "gateway").map((r) => `${r.method} ${r.pattern}`).sort();
  check("propiedad del Gateway: conversaciones, memoria, biblioteca, cortex, modelos, Ollama, OAuth, proveedores, automatizaciones, subagentes, nodos, actividad, gestión, herramientas, permisos, aprobaciones, benchmark, llamadas, medios, Realtime, modo de voz, perfil de usuario y actualizaciones del sistema", gatewayOwned.length === 100 && ["POST /api/benchmark", "POST /api/approvals/:id/(approve|reject)", "POST /api/ollama/pull-request", "POST /api/ollama/delete-request", "POST /api/nodes/heartbeat", "GET /api/oauth/status", "GET /api/approvals", "GET /api/memory", "GET /api/cortex/graph", "GET /api/cortex/note", "POST /api/cortex/note", "GET /api/cortex/search", "POST /api/transcribe", "POST /api/tts", "POST /api/voice/mode", "POST /api/calls/:callid/gemini-tools", "GET /api/user-profile", "POST /api/user-profile", "GET /api/system/updates", "POST /api/system/update"].every((r) => gatewayOwned.includes(r)), gatewayOwned.join(", "));

  // 3. Clasificación
  const c = classifyRoute;
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  check("ruta exacta con su método: dominio, acción y riesgo", same(c("POST", "/api/conversations/new"), { known: true, methodAllowed: true, domain: "conversations", action: "create", risk: "write", owner: "gateway" }), JSON.stringify(c("POST", "/api/conversations/new")));
  check("la misma ruta con otro método: existe pero no se permite, con la lista «Allow»", same(c("GET", "/api/conversations/new"), { known: true, methodAllowed: false, allow: ["POST"] }) && same(c("PUT", "/api/memory"), { known: true, methodAllowed: false, allow: ["GET"] }) && same(c("DELETE", "/api/health"), { known: true, methodAllowed: false, allow: ["GET"] }), "");
  check("/api/conversations admite GET y DELETE (y solo eso)", c("GET", "/api/conversations").methodAllowed && c("DELETE", "/api/conversations").methodAllowed && same(c("POST", "/api/conversations"), { known: true, methodAllowed: false, allow: ["DELETE", "GET"] }), JSON.stringify(c("POST", "/api/conversations")));
  check("ruta con parámetro: /api/permissions/<id>/revoke y /api/approvals/<id>/approve|reject", c("POST", "/api/permissions/abc123/revoke").action === "revoke" && c("POST", "/api/approvals/xyz/approve").action === "decide" && c("POST", "/api/approvals/xyz/reject").action === "decide", "");
  const unknown = ["/api", "/api/", "/api/nada", "/api/memory/", "/api/Memory", "/API/memory", "/api/conversations/", "/api/conversations/new/", "/api/conversations%2Fnew", "/api/approvals/xyz/borrar", "/api/approvals//approve", "/api/permissions/a/b/revoke", "/api/permissions//revoke", "/api/oauth/openrouter/callback/x", "/mykos-control/tool", "/mykos-store/conversations", "/static/app.js", "/api/memory?x=1", "/api/memory%00", "/api/memory\\..\\x"];
  const leaked = unknown.filter((p) => ["GET", "POST", "DELETE"].some((m) => c(m, p).known));
  check(`${unknown.length} rutas parecidas pero inexistentes (barra final, mayúsculas, %2F, %00, prefijos internos...) no se reconocen`, leaked.length === 0, leaked.join(" | ") || "ninguna se cuela");
  check("un método que Python no implementa (HEAD, OPTIONS, PATCH) no está permitido en ninguna ruta", ROUTE_TABLE.every((r) => !c("HEAD", r.pattern.replace(/:[a-z]+/g, "x").replace("(approve|reject)", "approve")).methodAllowed && !c("OPTIONS", r.pattern.replace(/:[a-z]+/g, "x").replace("(approve|reject)", "approve")).methodAllowed && !c("PATCH", r.pattern.replace(/:[a-z]+/g, "x").replace("(approve|reject)", "approve")).methodAllowed), "");
  const everyOk = ROUTE_TABLE.every((r) => {
    const concrete = r.pattern.replace(/:[a-z]+/g, "id1").replace("(approve|reject)", "approve");
    const got = c(r.method, concrete);
    return got.known && got.methodAllowed && got.domain === r.domain && got.action === r.action && got.risk === r.risk && got.owner === r.owner;
  });
  check("cada entrada de la tabla se clasifica a sí misma con su propio método", everyOk, `${ROUTE_TABLE.length} comprobadas`);

  // 4. Política de servicios auxiliares (cuarto corte): tabla del Gateway ↔ lista de server.py
  const { POLICY_TABLE, policyFor, policyKeys } = await import(pathToFileURL(path.join(repo, "gateway-plugin", "mykos-ui", "policy.js")).href);
  const policyList = policyKeys();
  const inTable = policyList.filter((key) => registry.has(key));
  check(`las ${policyList.length} rutas con política existen en la tabla de rutas con su método`, inTable.length === policyList.length, policyList.filter((k) => !registry.has(k)).join(" | ") || "todas");
  const pythonDecisionRoutes = (() => {
    const src = fs.readFileSync(path.join(repo, "server.py"), "utf8");
    const block = src.slice(src.indexOf("GATEWAY_DECISION_ROUTES = {"), src.indexOf("GATEWAY_DECISION_UNBOUND_BODY"));
    return [...block.matchAll(/\("([A-Z]+)",\s*"(\/api\/[^"]+)"\)/g)].map((m) => `${m[1]} ${m[2]}`).sort();
  })();
  check("server.py exige decisión firmada en las mismas rutas que la política del Gateway",
    pythonDecisionRoutes.length === policyList.length && pythonDecisionRoutes.every((key, index) => key === policyList[index]),
    `${pythonDecisionRoutes.length} en Python / ${policyList.length} en la política`);
  const unboundInPython = (() => {
    const src = fs.readFileSync(path.join(repo, "server.py"), "utf8");
    const block = src.slice(src.indexOf("GATEWAY_DECISION_UNBOUND_BODY = {"), src.indexOf("GATEWAY_DECISION_HEADER"));
    return [...block.matchAll(/\("([A-Z]+)",\s*"(\/api\/[^"]+)"\)/g)].map((m) => `${m[1]} ${m[2]}`).sort();
  })();
  const unboundInPolicy = POLICY_TABLE.filter((entry) => entry.body !== "json").map((entry) => `${entry.method} ${entry.path}`).sort();
  check("las rutas cuya decisión no va ligada al cuerpo son las mismas en la política y en server.py",
    unboundInPython.length === unboundInPolicy.length && unboundInPython.every((key, index) => key === unboundInPolicy[index]),
    `Python: ${unboundInPython.join(", ")} / política: ${unboundInPolicy.join(", ")}`);
  const wellFormed = POLICY_TABLE.filter((entry) => (
    !entry.group || !["json", "stream", "none"].includes(entry.body) || !entry.limits
    || !(entry.limits.concurrent > 0) || !(entry.limits.perMinute > 0)
    || (entry.body === "json" && Object.keys(entry.fields || {}).length === 0)
  ));
  check("cada política tiene grupo, tipo de cuerpo, campos (si es JSON) y límites de carga", wellFormed.length === 0, wellFormed.map((e) => `${e.method} ${e.path}`).join(", ") || `${POLICY_TABLE.length} correctas`);
  // Toda acción auxiliar sensible o de escritura debe estar gobernada; las excepciones son explícitas y razonadas.
  const exempt = new Set([
    "POST /api/chat", // lo gobierna el bucle de chat y la autoridad de permisos
    "POST /api/approvals/:id/(approve|reject)", // decisión de aprobación: ya la resuelve el Gateway
    "POST /api/transcribe", "POST /api/tts", // frontera interna propia (/mykos-control)
    "POST /api/sessions/:sessionid/realtime", // MyKOS crea la sesión WebRTC con su propia clave; nunca se reenvía
    "POST /api/calls/:callid/transcript", // persistencia idempotente de eventos de Realtime en el almacén MyKOS
    "POST /api/sessions/:sessionid/calls", "GET /api/calls/:callid", "DELETE /api/calls/:callid", "POST /api/calls/:callid/turn", "POST /api/calls/:callid/interrupt", // ciclo de vida y turnos propiedad del Gateway
    "POST /api/calls/:callid/gemini-tools", // puente limitado: valida la llamada, lista blanca y aprobaciones en el Gateway
    "POST /api/sessions/:sessionid/gemini-live", // entrega solo un token efímero y crea el registro de la llamada
    "POST /api/session/diary", // diario de sesión resuelto por el Gateway
    "POST /api/permissions/:id/revoke", // lo ejecuta el Gateway, no llega al trabajador
    "POST /api/automations/clear-events", // limpia la bitácora de eventos ya disparados; lo ejecuta el Gateway, no llega al trabajador
    "GET /api/automations", // lectura directa del documento de automatizaciones del Gateway
    "GET /api/subagents", // lectura directa del documento de trabajos del Gateway
    "GET /api/nodes", // registro de nodos y ficha del escritorio local del Gateway
    "POST /api/voice/mode", // enciende/apaga Realtime en memoria y lo guarda en disco; lo decide el Gateway, no el trabajador
    "POST /api/user-profile", // guarda el perfil USER.md en el espacio de trabajo; lo ejecuta el Gateway
    "POST /api/system/update", // aplica actualizaciones del sistema y reinicia; lo ejecuta el Gateway
    "POST /api/conversations/new", "POST /api/conversations/compact", // datos de conversación, ya en el almacén del Gateway
    "DELETE /api/conversations", "DELETE /api/conversations/messages",
    "POST /api/cortex/note", // guarda nota Markdown en la bóveda Cortex vía plano de control interno (/mykos-control/cortex/save)
  ]);
  const ungoverned = ROUTE_TABLE
    .filter((r) => r.method !== "GET" && (r.risk === "sensitive" || r.risk === "write"))
    .map((r) => `${r.method} ${r.pattern}`)
    .filter((key) => !policyList.includes(key) && !exempt.has(key));
  check("ninguna ruta de escritura o sensible se reenvía sin política ni excepción razonada", ungoverned.length === 0, ungoverned.join(" | ") || "ninguna");
  check("policyFor solo responde a la ruta y el método exactos", !policyFor("GET", "/api/benchmark") && !policyFor("POST", "/api/benchmark/") && !policyFor("POST", "/api/Benchmark") && policyFor("POST", "/api/benchmark")?.group === "benchmark", "");
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
