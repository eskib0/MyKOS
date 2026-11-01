// Uso: node probe-payloads.cjs <puertoGateway>
//
// Fase 1 (cierre): pruebas de payload del contrato. Manda cargas MALFORMADAS o hostiles al Gateway y comprueba que
// responde con un error limpio (4xx, JSON, sin trazas ni «undefined»), que nada se cae y que no se escribe nada.
//   1. Plano de control interno (/mykos-control/*, con token): 11 operaciones × ~22 cuerpos (vacío, null, tipos
//      erróneos, JSON roto, profundidad enorme, __proto__, Unicode raro, cuerpo gigante...).
//   2. API pública (POST /api/*): las mismas cargas sobre todas las rutas de escritura seguras de probar.
//   3. API pública (GET /api/* con parámetros): consultas hostiles (%00, «..», rutas absolutas, UNC, %ff, CRLF, muy largas...)
//      incluida la biblioteca de ficheros (no puede salir de su raíz ni leer credenciales).
//   4. Integridad: Gateway y backend siguen vivos con el mismo PID, y las revisiones de memoria, índice, permisos y
//      aprobaciones no han cambiado.
//
// Variables: BACKEND_PORT (3299), PROJECT_DIR, TAG (estado <test>/state-<TAG>), CONTROL_TOKEN (= MYKOS_CONTROL_TOKEN del Gateway).
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");

const gw = Number(process.argv[2] || 18795);
const token = String(process.env.CONTROL_TOKEN || "");
const tag = process.env.TAG || "W";
const testRoot = path.join(os.homedir(), "mykos-gateway-test");
const tokenFile = path.join(testRoot, `state-${tag}`, "mykos", ".token");

const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });
const info = (name, detail) => results.push({ name, ok: true, info: true, detail });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function request({ method = "GET", path: p, headers = {}, body, port = gw, host, timeoutMs = 60000 }) {
  return new Promise((resolve) => {
    const h = {};
    for (const [k, v] of Object.entries(headers)) h[k.toLowerCase()] = v;
    if (host !== undefined) h.host = host;
    if (body !== undefined && h["content-length"] === undefined) h["content-length"] = Buffer.byteLength(body);
    const chunks = [];
    const done = (status) => resolve({ status, headers: {}, text: Buffer.concat(chunks).toString("utf8") });
    const r = http.request({ host: "127.0.0.1", port, method, path: p, headers: h, agent: false }, (res) => {
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, text: Buffer.concat(chunks).toString("utf8") }));
      res.on("error", (e) => done("error:" + (e.code || e.message)));
    });
    r.setTimeout(timeoutMs, () => {
      r.destroy();
      done("timeout");
    });
    r.on("error", (e) => done("error:" + (e.code || e.message)));
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
const health = async () => asJson(await request({ path: "/mykos-health", timeoutMs: 8000 }));

// Cuerpos malformados
const BIG = "x".repeat(3 * 1024 * 1024);
const BODIES = [
  ["vacío", ""],
  ["null", "null"],
  ["array vacío", "[]"],
  ["cadena", '"hola"'],
  ["número", "123"],
  ["booleano", "true"],
  ["objeto vacío", "{}"],
  ["JSON roto", "{"],
  ["JSON cortado", '{"operation":'],
  ["comillas simples", "{'a':1}"],
  ["BOM delante", "\ufeff{}"],
  ["profundidad 3000", "[".repeat(3000) + "]".repeat(3000)],
  ["objeto muy anidado", '{"a":'.repeat(2000) + "1" + "}".repeat(2000)],
  ["cadena de 3 MB", JSON.stringify({ tool_name: BIG })],
  ["__proto__", '{"__proto__":{"polluted":true},"operation":"list","tool_name":"x"}'],
  ["constructor.prototype", '{"constructor":{"prototype":{"polluted":true}},"operation":"list"}'],
  ["tipos erróneos", JSON.stringify({ operation: 5, tool_name: { a: 1 }, action: "x", conversation_id: [1], model: false, messages: "no", payload: 3, provider: {}, approval_id: {}, decision: [], context: "x", system_prompt: 7, generation: "g", limit: "abc", permission_id: null })],
  ["todo null", JSON.stringify({ operation: null, tool_name: null, action: null, conversation_id: null, model: null, messages: null, payload: null, provider: null, approval_id: null, decision: null, context: null, generation: null, system_prompt: null })],
  ["acción vacía", JSON.stringify({ action: {}, tool_name: "", conversation_id: "" })],
  ["acción con tipos raros", JSON.stringify({ action: { kind: { x: 1 }, command: ["a"], cwd_root: 5, cwd_path: null }, tool_name: 9, conversation_id: {} })],
  ["Unicode raro", JSON.stringify({ tool_name: "\u0000\ud800\u202e", conversation_id: "\u0000".repeat(50), operation: "\u0000" })],
  ["operación desconocida", '{"operation":"drop","decision":"nuke","provider":"../../etc"}'],
];
const CHAT_SAFE = new Set(["vacío", "null", "array vacío", "cadena", "número", "booleano", "JSON roto", "JSON cortado", "comillas simples", "BOM delante", "profundidad 3000", "objeto muy anidado", "cadena de 3 MB", "__proto__", "constructor.prototype"]);

const LEAK = /TypeError|ReferenceError|RangeError|SyntaxError|Cannot read|Cannot destructure|is not a function|is not iterable|undefined|Traceback|File ".*\.py"|\bat (async )?[A-Za-z_.<>]+ \(|node_modules|\.js:\d+:\d+|\.py", line \d+/;
const failures = [];
let total = 0;
const seenStatuses = new Map();
function judge(label, r, { allowReset = false, jsonExpected = true } = {}) {
  total += 1;
  seenStatuses.set(r.status, (seenStatuses.get(r.status) || 0) + 1);
  const status = r.status;
  if (typeof status !== "number") {
    if (allowReset && /ECONNRESET|EPIPE/.test(String(status))) return;
    failures.push(`${label}: sin respuesta (${status})`);
    return;
  }
  if (status >= 500) {
    failures.push(`${label}: HTTP ${status} ${r.text.slice(0, 110).replace(/\s+/g, " ")}`);
    return;
  }
  if (LEAK.test(r.text)) {
    failures.push(`${label}: la respuesta filtra un error interno: ${r.text.slice(0, 130).replace(/\s+/g, " ")}`);
    return;
  }
  if (jsonExpected && r.text && !asJson(r)) failures.push(`${label}: HTTP ${status} pero el cuerpo no es JSON: ${r.text.slice(0, 80).replace(/\s+/g, " ")}`);
}

const control = (op, body) => request({ method: "POST", path: `/mykos-control/${op}`, headers: { "Content-Type": "application/json", "X-MyKOS-Control-Token": token }, body });
const pub = (p, body, extraHeaders = {}) => request({ method: "POST", path: p, headers: { "Content-Type": "application/json", Origin: `http://127.0.0.1:${gw}`, ...extraHeaders }, body });
const revisions = async () => {
  const r = await request({ path: "/mykos-store/", headers: { "X-MyKOS-Store-Token": fs.readFileSync(tokenFile, "utf8").trim() } });
  return Object.fromEntries((asJson(r)?.docs ?? []).map((d) => [d.name, d.revision]));
};

(async () => {
  const up0 = await (async () => {
    const end = Date.now() + 150000;
    while (Date.now() < end) {
      const h = await health();
      if (h?.ok && h.backend?.up && h.backend.phase === "up" && h.store?.active) return h;
      await sleep(400);
    }
    return null;
  })();
  if (!up0) {
    check("el Gateway arrancó con el backend «up» y el almacén activo", false, JSON.stringify(await health()).slice(0, 400));
    return finish();
  }
  check("el Gateway arrancó con el backend «up» y el almacén activo", true, `Gateway PID ${up0.pid}, backend PID ${up0.backend.pid}`);
  check("la prueba conoce el token (CONTROL_TOKEN)", token.length >= 16, `${token.length} caracteres`);
  const revBefore = await revisions();
  const baselineConversations = (asJson(await request({ path: "/api/conversations" }))?.conversations ?? []).map((c) => c.id);

  // 1. Plano de control interno
  {
    const ops = ["authorize", "approval", "permissions", "context", "remote-model", "model", "tool", "action", "transcribe", "tts", "nada"];
    const before = failures.length;
    let n = 0;
    for (const op of ops) {
      for (const [name, body] of BODIES) {
        const r = await control(op, body);
        judge(`control/${op} · ${name}`, r, { allowReset: name === "cadena de 3 MB" });
        n += 1;
      }
    }
    check(`plano de control: ${n} cargas malformadas (11 operaciones × ${BODIES.length} cuerpos): siempre un 4xx limpio en JSON, sin trazas`, failures.length === before, failures.slice(before, before + 6).join(" | ") || `${n} de ${n} limpias`);
    const h = await health();
    check("tras el plano de control: mismo Gateway, mismo backend, todo «up»", h?.ok && h.pid === up0.pid && h.backend?.pid === up0.backend.pid, `Gateway ${h?.pid}, backend ${h?.backend?.pid}`);
    // GET a operaciones de solo POST y sin token
    const noTok = await request({ method: "POST", path: "/mykos-control/context", headers: { "Content-Type": "application/json" }, body: "{}" });
    const wrongTok = await request({ method: "POST", path: "/mykos-control/context", headers: { "Content-Type": "application/json", "X-MyKOS-Control-Token": "x".repeat(token.length) }, body: "{}" });
    check("sin token o con token erróneo el plano de control responde 403 (con cualquier cuerpo)", noTok.status === 403 && wrongTok.status === 403, `HTTP ${noTok.status}/${wrongTok.status}`);
  }

  // 2. API pública, POST
  {
    const routes = ["/api/conversations/new", "/api/conversations/compact", "/api/chat", "/api/approvals/x/approve", "/api/approvals/x/reject", "/api/permissions/x/revoke", "/api/oauth/openai/logout", "/api/oauth/claude/logout", "/api/oauth/openrouter/logout", "/api/providers/nvidia/connect", "/api/providers/nvidia/logout", "/api/ollama/pull-request", "/api/ollama/delete-request", "/api/nodes/heartbeat", "/api/transcribe", "/api/tts", "/api/uploads"];
    const before = failures.length;
    let n = 0;
    for (const route of routes) {
      for (const [name, body] of BODIES) {
        if (route === "/api/chat" && !CHAT_SAFE.has(name)) continue;
        const r = await pub(route, body, route === "/api/nodes/heartbeat" ? { "X-MyKOS-Node-Token": "n".repeat(32) } : {});
        judge(`POST ${route} · ${name}`, r, { allowReset: name === "cadena de 3 MB" });
        n += 1;
      }
    }
    // Subidas con tipos de contenido hostiles
    for (const [name, headers, body] of [
      ["multipart sin límite", { "Content-Type": "multipart/form-data" }, "x"],
      ["multipart con límite roto", { "Content-Type": "multipart/form-data; boundary=" }, "--\r\n"],
      ["multipart cortado", { "Content-Type": "multipart/form-data; boundary=abc" }, "--abc\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.txt\"\r\n\r\ndatos sin cierre"],
      ["nombre de fichero con ruta", { "Content-Type": "multipart/form-data; boundary=abc" }, "--abc\r\nContent-Disposition: form-data; name=\"file\"; filename=\"..\\..\\..\\evil.txt\"\r\nContent-Type: text/plain\r\n\r\nx\r\n--abc--\r\n"],
      ["nombre de dispositivo", { "Content-Type": "multipart/form-data; boundary=abc" }, "--abc\r\nContent-Disposition: form-data; name=\"file\"; filename=\"CON\"\r\nContent-Type: text/plain\r\n\r\nx\r\n--abc--\r\n"],
    ]) {
      const r = await request({ method: "POST", path: "/api/uploads", headers: { Origin: `http://127.0.0.1:${gw}`, ...headers }, body });
      judge(`POST /api/uploads · ${name}`, r);
      n += 1;
    }
    check(`API pública, POST: ${n} cargas malformadas sobre ${routes.length} rutas: siempre un error limpio en JSON, sin trazas`, failures.length === before, failures.slice(before, before + 6).join(" | ") || `${n} de ${n} limpias`);
    const h = await health();
    check("tras las cargas públicas: mismo Gateway y mismo backend (nada se cayó ni se relanzó)", h?.ok && h.pid === up0.pid && h.backend?.pid === up0.backend.pid && h.backend.restarts === up0.backend.restarts, `Gateway ${h?.pid}, backend ${h?.backend?.pid}, reinicios ${h?.backend?.restarts}`);
    // Se retiran las conversaciones que las cargas «válidas» hayan podido crear (POST /api/conversations/new con {} es legítimo)
    const now = (asJson(await request({ path: "/api/conversations" }))?.conversations ?? []).map((c) => c.id);
    const created = now.filter((id) => !baselineConversations.includes(id));
    for (const id of created) await request({ method: "DELETE", path: `/api/conversations?id=${id}`, headers: { Origin: `http://127.0.0.1:${gw}` } });
    info("conversaciones creadas por cuerpos que eran válidos (y retiradas)", `${created.length}`);
  }

  // 3. API pública, GET con parámetros hostiles
  {
    // El contenido del canario y el nombre/ruta del fichero deben ser cadenas DISTINTAS: si comparten subcadena, un
    // servidor que solo eco el valor recibido en un mensaje de error (rechazo normal, sin leer nada) ya haría saltar
    // la detección de fuga, como un falso positivo (confirmado a mano contra el MyKOS real: solo se eco la ruta).
    const canary = `canary-content-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const canaryFile = path.join(os.tmpdir(), `payload-marker-${Date.now()}.txt`);
    fs.writeFileSync(canaryFile, canary);
    const VALUES = [
      "", "%00", "%zz", "%ff%fe", "..", "../..", "..\\..\\..\\Windows\\win.ini", "..%2f..%2f..%2fWindows%2fwin.ini", "%2e%2e%2f%2e%2e%2f", "C:\\Windows\\win.ini", "C:/Windows/win.ini", `${canaryFile}`, "\\\\localhost\\c$\\Windows\\win.ini", "\\\\?\\C:\\Windows\\win.ini",
      "CON", "NUL", "a:stream", "x%0d%0aSet-Cookie:%20evil=1", "x\r\ny", "%E0%A4%A", "a".repeat(600), "a".repeat(12000), "[]", "{}", "1;2", "id[]=1", "\u202e", "%",
    ];
    const targets = [
      ["/api/conversation", ["id"]], ["/api/conversations/export", ["id"]], ["/api/context", ["conversation_id"]], ["/api/activity", ["activity_id", "conversation_id"]],
      ["/api/library/list", ["root", "path"]], ["/api/library/search", ["root", "path", "query"]], ["/api/library/preview", ["root", "path"]],
      ["/api/audit", ["limit", "conversation_id"]], ["/api/permissions", ["conversation_id"]], ["/api/approvals", ["conversation_id"]],
      ["/api/ollama/catalog", ["query"]], ["/api/ollama/jobs", ["id"]], ["/api/health", ["gateway"]],
    ];
    const before = failures.length;
    let n = 0;
    const leaks = [];
    for (const [route, params] of targets) {
      for (const value of VALUES) {
        for (const param of params) {
          // Node se niega a enviar un CR/LF sin escapar en la ruta (ERR_UNESCAPED_CHARACTERS, una excepción síncrona que
          // abortaba toda la batería): esos valores viajan escapados (%0D%0A); el CRLF real se prueba en las cabeceras.
          const raw = value.includes("%") ? value : encodeURIComponent(value);
          const r = await request({ path: `${route}?${param}=${raw}`, headers: {}, timeoutMs: 30000 });
          const label = `GET ${route}?${param}=${value.slice(0, 24).replace(/[\r\n]/g, "·")}`;
          // 431 (cabeceras demasiado grandes) es una respuesta válida del servidor HTTP del Gateway para las cadenas enormes
          if (r.status === 431 || r.status === 414 || r.status === 400 && !r.text) {
            n += 1;
            continue;
          }
          judge(label, r, { jsonExpected: true });
          n += 1;
          if (r.text.includes(canary)) leaks.push(`${label} devolvió el contenido de un fichero FUERA de la raíz`);
          if (/\[fonts\]|\[extensions\]|for 16-bit app support/i.test(r.text)) leaks.push(`${label} devolvió win.ini`);
        }
      }
    }
    check(`API pública, GET: ${n} consultas hostiles: siempre un error limpio en JSON, sin trazas`, failures.length === before, failures.slice(before, before + 6).join(" | ") || `${n} de ${n} limpias`);
    check("la biblioteca no sale de su raíz: ni un fichero fuera de ella, ni win.ini, ni rutas absolutas o UNC", leaks.length === 0, leaks.slice(0, 3).join(" | ") || "ninguna fuga");
    try {
      fs.rmSync(canaryFile, { force: true });
    } catch {}
    // Cabeceras hostiles
    const headerCases = [
      ["Host con inyección", { host: "127.0.0.1:" + gw + "\r\nX-A: b" }],
      ["Origin gigante", { origin: "http://" + "a".repeat(9000) + ".example" }],
      ["Content-Length negativo", { "content-length": "-5" }],
    ];
    let hs = 0;
    for (const [name, headers] of headerCases) {
      try {
        const r = await request({ method: "POST", path: "/api/conversations/new", headers: { "Content-Type": "application/json", ...headers }, body: "{}", timeoutMs: 15000 });
        judge(`cabecera · ${name}`, r, { jsonExpected: false });
        hs += 1;
      } catch {
        hs += 1; // Node se niega a enviar la cabecera: también es una defensa
      }
    }
    info("cabeceras hostiles (Host con CRLF, Origin gigante, Content-Length negativo) probadas", `${hs}`);
  }

  // 4. Integridad final
  {
    const h = await health();
    check("al final: Gateway y backend siguen vivos, con los mismos PID y sin reinicios", h?.ok && h.pid === up0.pid && h.backend?.pid === up0.backend.pid && h.backend.restarts === up0.backend.restarts, `Gateway ${h?.pid}, backend ${h?.backend?.pid}, reinicios ${h?.backend?.restarts}`);
    const revAfter = await revisions();
    const changed = ["memory", "memory-index", "permissions", "approvals"].filter((d) => revAfter[d] !== revBefore[d]);
    check("nada se escribió por el camino: memoria, índice, permisos y aprobaciones con la misma revisión", changed.length === 0, changed.map((d) => `${d}: r${revBefore[d]}→r${revAfter[d]}`).join(", ") || JSON.stringify(revAfter));
    const conv = (asJson(await request({ path: "/api/conversations" }))?.conversations ?? []).map((c) => c.id);
    check("las conversaciones han vuelto a las de antes de las pruebas", JSON.stringify([...conv].sort()) === JSON.stringify([...baselineConversations].sort()), `${conv.length} conversaciones`);
    const okAfter = await request({ path: "/api/memory" });
    check("la API sigue respondiendo con normalidad (memoria 200)", okAfter.status === 200, `HTTP ${okAfter.status}`);
    info("estados HTTP vistos durante toda la prueba", `${total} respuestas: ${[...seenStatuses.entries()].sort().map(([s, c]) => `${s}×${c}`).join(" ")}`);
    if (failures.length) info("primeros fallos", failures.slice(0, 12).join("\n      "));
  }
  finish();
})().catch((error) => {
  check("la batería terminó sin excepciones", false, String(error && error.stack ? error.stack : error));
  finish();
});

function finish() {
  const width = Math.min(150, Math.max(...results.map((r) => r.name.length)));
  let bad = 0;
  for (const r of results) {
    if (!r.ok) bad += 1;
    console.log(`${r.info ? "INFO " : r.ok ? "OK   " : "FALLA"}  ${r.name.padEnd(width)}  ${r.detail}`);
  }
  const counted = results.filter((r) => !r.info).length;
  console.log(bad ? `\n==> ${bad} de ${counted} comprobaciones FALLARON` : `\n==> ${counted}/${counted} comprobaciones correctas`);
  process.exit(bad ? 1 : 0);
}
