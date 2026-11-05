// Uso: node probe-policy.cjs        (no necesita Gateway ni Python)
//
// Fase 3, cuarto corte: unitarias de la política de servicios auxiliares (gateway-plugin/mykos-ui/policy.js).
//   1. Cuerpos válidos e inválidos de cada dominio (benchmark, modelos de Ollama, credenciales, subidas, nodos).
//   2. Consulta del retorno de OAuth.
//   3. Cabeceras obligatorias, tipo de contenido y tamaño declarado.
//   4. Límites de carga: cuántas a la vez, cuántas por minuto, liberación del hueco y grupos compartidos.
//   5. Firma de la decisión: liga método, ruta, cuerpo y caducidad; cambiar cualquiera de los cuatro la invalida.
//   6. Ningún mensaje de error devuelve el valor de un campo secreto (la clave de NVIDIA).
const os = require("os");
const path = require("path");
const crypto = require("crypto");
const { pathToFileURL } = require("url");

const repo = path.resolve(__dirname, "..", "..");
const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });

(async () => {
  const policy = await import(pathToFileURL(path.join(repo, "gateway-plugin", "mykos-ui", "policy.js")).href);
  const { POLICY_TABLE, policyFor, checkJsonBody, checkQuery, checkHeaders, PolicyLimiter, decide, decisionHeaderValue, bodyHashOf, DECISION_HEADER } = policy;

  const body = (value) => Buffer.from(typeof value === "string" ? value : JSON.stringify(value), "utf8");
  const entryOf = (method, p) => {
    const found = policyFor(method, p);
    if (!found) throw new Error(`sin política: ${method} ${p}`);
    return found;
  };
  const jsonVerdict = (method, p, value) => checkJsonBody(entryOf(method, p), body(value));
  const okBody = (method, p, value) => jsonVerdict(method, p, value) === null;
  const reasonOf = (verdict) => (verdict === null ? "(aceptado)" : `${verdict.status}/${verdict.reason}`);

  check(`la tabla de política cubre ${POLICY_TABLE.length} rutas de servicios auxiliares`, POLICY_TABLE.length === 42, `${POLICY_TABLE.length}`);

  // 1. Benchmark
  check("benchmark: modelo y perfiles válidos se aceptan", okBody("POST", "/api/benchmark", { model: "qwen3:14b", profiles: ["fast", "deep"] }), reasonOf(jsonVerdict("POST", "/api/benchmark", { model: "qwen3:14b", profiles: ["fast", "deep"] })));
  check("benchmark: solo el modelo (sin perfiles) se acepta", okBody("POST", "/api/benchmark", { model: "llama3.1:8b-instruct-q4_K_M" }), "");
  const benchDenials = [
    ["sin modelo", {}, "missing_field"],
    ["modelo vacío", { model: "" }, "bad_format"],
    ["modelo con espacios y comillas", { model: 'qwen3 "; rm -rf' }, "bad_format"],
    ["modelo que no es texto", { model: 12 }, "bad_type"],
    ["perfil inventado", { model: "a", profiles: ["turbo"] }, "bad_value"],
    ["cinco perfiles", { model: "a", profiles: ["fast", "deep", "balanced", "fast", "deep"] }, "too_many"],
    ["perfiles que no son lista", { model: "a", profiles: "fast" }, "bad_type"],
    ["campo desconocido", { model: "a", prompt: "hola" }, "unknown_field"],
    ["cuerpo que es una lista", [{ model: "a" }], "bad_json"],
    ["cuerpo que no es JSON", "{modelo:", "bad_json"],
    ["cuerpo vacío", "", "empty_body"],
  ];
  for (const [label, value, reason] of benchDenials) {
    const verdict = jsonVerdict("POST", "/api/benchmark", value);
    check(`benchmark rechaza: ${label}`, verdict !== null && verdict.reason === reason, reasonOf(verdict));
  }
  const bigBody = jsonVerdict("POST", "/api/benchmark", { model: "a".repeat(5000) });
  check("benchmark rechaza un cuerpo mayor que su límite (413)", bigBody?.status === 413 || bigBody?.reason === "too_long", reasonOf(bigBody));

  // 2. Modelos de Ollama
  check("pull de modelo: modelo y conversación válidos se aceptan", okBody("POST", "/api/ollama/pull-request", { model: "gemma3:4b", conversation_id: "abc-123_XY" }), "");
  check("borrado de modelo rechaza una conversación con caracteres raros", jsonVerdict("POST", "/api/ollama/delete-request", { model: "a", conversation_id: "../../x" })?.reason === "bad_format", "");
  check("pull de modelo rechaza un campo de más (insecure_registry)", jsonVerdict("POST", "/api/ollama/pull-request", { model: "a", insecure_registry: true })?.reason === "unknown_field", "");

  // 3. Credenciales
  check("OAuth de Claude acepta su propio proveedor (segmento o identificador canónico)", okBody("POST", "/api/oauth/claude/start", { provider: "claude" }) && okBody("POST", "/api/oauth/claude/start", { provider: "anthropic_oauth" }), "");
  check("OAuth de Claude rechaza el proveedor de otra ruta", jsonVerdict("POST", "/api/oauth/claude/start", { provider: "openrouter" })?.reason === "bad_value", "");
  check("OAuth admite un cuerpo mínimo «{}» (el proveedor es opcional)", okBody("POST", "/api/oauth/openrouter/logout", {}), "");
  check("NVIDIA: clave válida aceptada", okBody("POST", "/api/providers/nvidia/connect", { provider: "nvidia_api", api_key: "nvapi-" + "K".repeat(40) }), "");
  const nvidiaDenials = [
    ["sin clave", { provider: "nvidia_api" }, "missing_field"],
    ["clave demasiado corta", { api_key: "corta" }, "bad_format"],
    ["clave con espacios", { api_key: "nvapi con espacio dentro y mas texto" }, "bad_format"],
    ["clave con salto de línea", { api_key: "nvapi-1234567890123456\nGET /x" }, "bad_format"],
    ["clave que no es texto", { api_key: 123456 }, "bad_type"],
  ];
  for (const [label, value, reason] of nvidiaDenials) {
    const verdict = jsonVerdict("POST", "/api/providers/nvidia/connect", value);
    check(`NVIDIA rechaza: ${label}`, verdict !== null && verdict.reason === reason, reasonOf(verdict));
  }
  const secret = "nvapi-" + "S".repeat(50) + "\n";
  const secretVerdict = jsonVerdict("POST", "/api/providers/nvidia/connect", { api_key: secret });
  check("el mensaje de error de una clave no válida NO contiene la clave", secretVerdict !== null && !secretVerdict.message.includes("SSSS"), secretVerdict?.message || "");

  // 4. Retorno de OAuth (consulta)
  const callback = entryOf("GET", "/api/oauth/openrouter/callback");
  const query = (search) => checkQuery(callback, new URLSearchParams(search));
  check("retorno de OAuth: código y estado normales se aceptan", query("code=abc123DEF&state=xyz789") === null, reasonOf(query("code=abc123DEF&state=xyz789")));
  check("retorno de OAuth: se admite un parámetro desconocido pero acotado", query("code=abc&nuevo=1") === null, "");
  check("retorno de OAuth: rechaza un código larguísimo", query(`code=${"a".repeat(900)}`)?.reason === "param_too_long", "");
  check("retorno de OAuth: rechaza caracteres de control en un parámetro", query("code=abc%00def")?.reason === "bad_param", reasonOf(query("code=abc%00def")));
  check("retorno de OAuth: rechaza demasiados parámetros", query(Array.from({ length: 14 }, (_, i) => `p${i}=1`).join("&"))?.reason === "too_many_params", "");
  check("retorno de OAuth: admite un error largo en error_description", query("error=access_denied&error_description=" + encodeURIComponent("motivo ".repeat(40))) === null, "");

  // 5. Cabeceras: subidas y latido de nodo
  const uploads = entryOf("POST", "/api/uploads");
  check("subidas: multipart con tamaño correcto pasa", checkHeaders(uploads, { "content-type": "multipart/form-data; boundary=x", "content-length": "1024" }) === null, "");
  check("subidas: rechaza JSON en vez de formulario (415)", checkHeaders(uploads, { "content-type": "application/json", "content-length": "10" })?.status === 415, "");
  check("subidas: rechaza sin Content-Length (411)", checkHeaders(uploads, { "content-type": "multipart/form-data; boundary=x" })?.status === 411, "");
  check("subidas: rechaza 33 MB declarados (413)", checkHeaders(uploads, { "content-type": "multipart/form-data; boundary=x", "content-length": String(33 * 1024 * 1024) })?.status === 413, "");
  check("subidas: rechaza tamaño 0 o no numérico", checkHeaders(uploads, { "content-type": "multipart/form-data; boundary=x", "content-length": "0" })?.reason === "bad_length" && checkHeaders(uploads, { "content-type": "multipart/form-data; boundary=x", "content-length": "abc" })?.reason === "bad_length", "");
  const nodes = entryOf("POST", "/api/nodes/heartbeat");
  check("latido de nodo: con token de nodo con forma válida pasa la comprobación de cabeceras", checkHeaders(nodes, { "x-mykos-node-token": "n".repeat(40) }) === null, "");
  check("latido de nodo: sin token de nodo, 403 en el Gateway (no llega a Python)", checkHeaders(nodes, {})?.status === 403, "");
  check("latido de nodo: token demasiado corto, 403", checkHeaders(nodes, { "x-mykos-node-token": "corto" })?.status === 403, "");
  check("latido de nodo: cuerpo con node_id y capacidades acotadas se acepta", okBody("POST", "/api/nodes/heartbeat", { node_id: "nodo1", capabilities: ["camera", "shell"] }), "");
  check("latido de nodo: rechaza 40 capacidades", jsonVerdict("POST", "/api/nodes/heartbeat", { node_id: "n", capabilities: Array.from({ length: 40 }, () => "x") })?.reason === "too_many", "");

  // 6. Límites de carga
  {
    let clock = 1_000_000;
    const limiter = new PolicyLimiter(() => clock);
    const bench = entryOf("POST", "/api/benchmark");
    const first = limiter.acquire(bench);
    const second = limiter.acquire(bench);
    check("benchmark: una medición a la vez (la segunda recibe 429 «ocupado» con Retry-After)", first.ok && !second.ok && second.status === 429 && second.reason === "busy" && second.retryAfter > 0, `${second.status}/${second.reason}`);
    first.release();
    const third = limiter.acquire(bench);
    check("al terminar la medición se libera el hueco", third.ok === true, "");
    third.release();
    check("release() dos veces no regala huecos", (() => { third.release(); const a = limiter.acquire(bench); const b = limiter.acquire(bench); const ok = a.ok && !b.ok; a.release(); return ok; })(), "");
    // Ritmo por minuto (benchmark: 12)
    for (let i = 0; i < 11; i += 1) limiter.acquire(bench).release?.();
    const rate = limiter.acquire(bench);
    check("benchmark: la 13.ª medición del mismo minuto recibe 429 «demasiadas»", !rate.ok && rate.reason === "rate_limited", `${rate.status}/${rate.reason}`);
    clock += 61_000;
    const later = limiter.acquire(bench);
    check("un minuto después vuelve a admitir mediciones", later.ok === true, "");
    later.release();
    // Grupo compartido: pull y delete de modelos comparten contador
    const pull = entryOf("POST", "/api/ollama/pull-request");
    const del = entryOf("POST", "/api/ollama/delete-request");
    const leases = [limiter.acquire(pull), limiter.acquire(del), limiter.acquire(pull)];
    const blocked = limiter.acquire(del);
    check("pull y delete de modelos comparten el mismo límite (3 a la vez)", leases.every((l) => l.ok) && !blocked.ok && blocked.reason === "busy", `${blocked.status}/${blocked.reason}`);
    for (const lease of leases) lease.release();
    const snapshot = limiter.snapshot();
    // Un rechazo por «ocupado» no gasta ritmo: solo cuentan las 3 admitidas; benchmark lleva 1 desde que avanzó el reloj.
    check("el resumen de carga cuenta acciones en marcha y del último minuto", snapshot["ollama-models"]?.running === 0 && snapshot["ollama-models"]?.lastMinute === 3 && snapshot.benchmark?.running === 0 && snapshot.benchmark?.lastMinute === 1, JSON.stringify(snapshot));
  }

  // 7. decide(): orden de comprobaciones y no reservar hueco si deniega
  {
    const limiter = new PolicyLimiter();
    const bench = entryOf("POST", "/api/benchmark");
    for (let i = 0; i < 5; i += 1) {
      const bad = decide(bench, { method: "POST", pathname: "/api/benchmark", headers: {}, body: body({ model: "" }), searchParams: new URLSearchParams() }, limiter);
      check(`una petición inválida no consume hueco ni ritmo (intento ${i + 1})`, bad.ok === false && bad.reason === "bad_format", `${bad.status}/${bad.reason}`);
    }
    const good = decide(bench, { method: "POST", pathname: "/api/benchmark", headers: {}, body: body({ model: "qwen3:14b" }), searchParams: new URLSearchParams() }, limiter);
    check("tras cinco rechazos, una petición válida sigue pasando", good.ok === true && typeof good.release === "function" && /^[0-9a-f]{64}$/.test(good.bodyHash), good.bodyHash || "");
    good.release();
    const stream = decide(entryOf("POST", "/api/uploads"), { method: "POST", pathname: "/api/uploads", headers: { "content-type": "multipart/form-data; boundary=b", "content-length": "500" }, body: null, searchParams: new URLSearchParams() }, limiter);
    check("en una subida el Gateway no lee el cuerpo: la decisión no lo liga («-»)", stream.ok === true && stream.bodyHash === "-", stream.bodyHash);
    stream.release();
  }

  // 8. Firma de la decisión
  {
    const token = "t".repeat(64);
    const raw = body({ model: "qwen3:14b" });
    const header = decisionHeaderValue(token, "POST", "/api/benchmark", raw);
    const [version, expires, hash, signature] = header.split(".");
    const expected = (method, p, bodyHash, exp, key = token) => crypto.createHmac("sha256", key).update(`gateway-decision|${method} ${p}|${bodyHash}|${exp}`, "utf8").digest("hex");
    check("la cabecera de decisión tiene versión, caducidad, hash del cuerpo y firma", version === "v1" && Number(expires) > Math.floor(Date.now() / 1000) && hash === bodyHashOf(raw) && /^[0-9a-f]{64}$/.test(signature), header.slice(0, 40) + "…");
    check("la cabecera de decisión se llama X-MyKOS-Gateway-Decision", DECISION_HEADER === "x-mykos-gateway-decision", DECISION_HEADER);
    check("la firma corresponde a método, ruta, cuerpo y caducidad", signature === expected("POST", "/api/benchmark", hash, expires), "");
    check("la misma decisión para otra ruta no vale", signature !== expected("POST", "/api/uploads", hash, expires), "");
    check("la misma decisión para otro método no vale", signature !== expected("GET", "/api/benchmark", hash, expires), "");
    check("la misma decisión para otro cuerpo no vale", signature !== expected("POST", "/api/benchmark", bodyHashOf(body({ model: "otro" })), expires), "");
    check("la misma decisión con otra caducidad no vale", signature !== expected("POST", "/api/benchmark", hash, String(Number(expires) + 1)), "");
    check("con otro token del Gateway la firma no coincide", signature !== expected("POST", "/api/benchmark", hash, expires, "x".repeat(64)), "");
    check("la caducidad por defecto es de 120 s como máximo", Number(expires) - Math.floor(Date.now() / 1000) <= 120, `${Number(expires) - Math.floor(Date.now() / 1000)} s`);
    check("sin cuerpo leído el hash es «-» y la firma también lo cubre", (() => {
      const h = decisionHeaderValue(token, "POST", "/api/uploads", null);
      const [, exp, bodyHash, sig] = h.split(".");
      return bodyHash === "-" && sig === expected("POST", "/api/uploads", "-", exp);
    })(), "");
  }
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
