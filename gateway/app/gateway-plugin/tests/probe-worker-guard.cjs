// Uso: node probe-worker-guard.cjs <puertoGateway>
//
// Fase 3, tercer corte: el trabajador Python (:3211) ya no contesta a nadie que no sea el Gateway, y el Gateway solo
// reenvía las rutas de su tabla (routes.js).
//
// Variables de entorno (las fija el que lanza la prueba):
//   BACKEND_PORT   puerto interno del backend (3299)
//   PROJECT_DIR    copia de prueba del proyecto (make-project.cjs)
//   PYTHON_EXE     intérprete de Python
//   TAG            etiqueta del estado de prueba (W): <test>/state-<TAG>/mykos/control-journal.jsonl es el diario
//   CONTROL_TOKEN  el mismo valor que MYKOS_CONTROL_TOKEN del Gateway de prueba (así la prueba conoce el token)
//
// El Gateway de prueba lleva el plugin con backend.spawn=true (server.py REAL sobre una copia de datos vacía).
const http = require("http");
const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");

const gw = Number(process.argv[2] || 18795);
const be = Number(process.env.BACKEND_PORT || 3299);
const project = process.env.PROJECT_DIR;
const python = process.env.PYTHON_EXE || "python3";
const tag = process.env.TAG || "W18";
const token = String(process.env.CONTROL_TOKEN || "");
if (!project) throw new Error("falta la variable PROJECT_DIR");
const testRoot = path.join(os.homedir(), "mykos-gateway-test");
const journalFile = path.join(testRoot, `state-${tag}`, "mykos", "control-journal.jsonl");
const workerLog = path.join(project, "data", "mykos-backend.log");

const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });
const info = (name, detail) => results.push({ name, ok: true, info: true, detail });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function request({ method = "GET", path: p, headers = {}, body, port = gw, host, timeoutMs = 30000 }) {
  return new Promise((resolve) => {
    const h = {};
    for (const [k, v] of Object.entries(headers)) h[k.toLowerCase()] = v;
    if (host !== undefined) h.host = host;
    if (body !== undefined && h["content-length"] === undefined) h["content-length"] = Buffer.byteLength(body);
    const chunks = [];
    const fail = (why) => resolve({ status: why, headers: {}, body: Buffer.concat(chunks), text: Buffer.concat(chunks).toString("utf8") });
    const r = http.request({ host: "127.0.0.1", port, method, path: p, headers: h, agent: false }, (res) => {
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks), text: Buffer.concat(chunks).toString("utf8") }));
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
const health = async () => {
  const r = await request({ path: "/mykos-health", timeoutMs: 8000 });
  return { status: r.status, json: asJson(r) };
};
const portOpen = (port) =>
  new Promise((resolve) => {
    const s = net.connect({ host: "127.0.0.1", port }, () => {
      s.destroy();
      resolve(true);
    });
    s.on("error", () => resolve(false));
  });
const own = { Origin: `http://127.0.0.1:${gw}` };
const viaGateway = (method, p, payload, extra = {}) => request({ method, path: p, headers: { ...own, ...(payload !== undefined ? { "Content-Type": "application/json" } : {}), ...extra }, ...(payload !== undefined ? { body: JSON.stringify(payload) } : {}) });
const direct = (method, p, { body, headers = {}, host } = {}) => request({ method, path: p, port: be, host, headers, ...(body !== undefined ? { body } : {}) });
const journal = () => (fs.existsSync(journalFile) ? fs.readFileSync(journalFile, "utf8").split("\n").filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return { broken: l }; } }) : []);
const workerLogText = () => (fs.existsSync(workerLog) ? fs.readFileSync(workerLog, "utf8") : "");
const conversationIds = async () => (asJson(await viaGateway("GET", "/api/conversations"))?.conversations ?? []).map((c) => c.id).sort();

(async () => {
  // A. Arranque
  const up = await waitFor(async () => {
    const h = await health();
    return h.status === 200 && h.json?.backend?.up && h.json.backend.phase === "up" ? h.json : null;
  }, 150000);
  if (!up) {
    check("el Gateway arrancó con el backend «up»", false, JSON.stringify((await health()).json).slice(0, 500));
    return finish();
  }
  check("el Gateway arrancó con el backend «up», tabla de rutas estricta y 62 rutas conocidas", up.routes?.strict === true && up.routes.known === 62 && /^0\.(8|9|1[0-3])\./.test(String(up.version)), `plugin ${up.version}; routes=${JSON.stringify(up.routes)}`);
  check("la prueba conoce el token del Gateway (CONTROL_TOKEN)", token.length >= 16, `${token.length} caracteres`);
  const baseline = await conversationIds();
  const memoryBefore = asJson(await viaGateway("GET", "/api/memory"))?.count;

  // B. Al trabajador, directo y sin token: 403 en TODAS las rutas /api/* salvo /api/health
  {
    const attempts = [
      ["GET", "/api/memory"], ["GET", "/api/conversations"], ["GET", "/api/permissions"], ["GET", "/api/oauth/status"], ["GET", "/api/management"],
      ["GET", "/api/status"], ["GET", "/api/library/list"], ["GET", "/api/oauth/openrouter/callback?error=x"],
      ["POST", "/api/conversations/new", "{}"], ["POST", "/api/chat", "{}"], ["POST", "/api/oauth/openrouter/logout", "{}"],
      ["POST", "/api/providers/nvidia/logout", "{}"], ["POST", "/api/providers/nvidia/connect", "{}"], ["POST", "/api/providers/kimi/connect", "{}"], ["POST", "/api/ollama/pull-request", "{}"], ["POST", "/api/ollama/delete-request", "{}"], ["POST", "/api/uploads", "x"], ["POST", "/api/benchmark", "{}"],
      ["POST", "/api/nodes/heartbeat", "{}", { "X-MyKOS-Node-Token": "n".repeat(32) }],
      ["DELETE", "/api/conversations?id=nada"], ["DELETE", "/api/conversations/messages?conversation_id=a&message_id=b"],
      ["POST", "/api/nada", "{}"], ["GET", "/api/nada"],
    ];
    const outcomes = [];
    for (const [method, p, body, extra] of attempts) {
      const r = await direct(method, p, { body, headers: { "Content-Type": "text/plain", ...(extra || {}) } });
      outcomes.push({ method, p, status: r.status, ok: r.status === 403 && /solo acepta peticiones del Gateway/.test(r.text) });
    }
    const failedOnes = outcomes.filter((o) => !o.ok);
    check(`al trabajador directo y sin token: ${attempts.length} rutas (GET, POST y DELETE, incluidas rutas que no existen) responden 403`, failedOnes.length === 0, failedOnes.map((o) => `${o.method} ${o.p} -> ${o.status}`).join(" | ") || `${attempts.length} de ${attempts.length} rechazadas`);

    // Petición «de otra web» (POST simple text/plain, sin preflight) y con Host de rebinding
    const evilPost = await direct("POST", "/api/conversations/new", { body: "{}", headers: { "Content-Type": "text/plain", Origin: "http://evil.example" }, host: "evil.example" });
    const evilGet = await direct("GET", "/api/memory", { headers: { Origin: "http://evil.example" }, host: "evil.example:3211" });
    check("POST simple desde otra web y GET con Host de «rebinding» directos al trabajador: 403", evilPost.status === 403 && evilGet.status === 403, `HTTP ${evilPost.status}/${evilGet.status}`);

    // Tokens erróneos
    const variants = [["vacío", ""], ["corto", "abc"], ["misma longitud", "x".repeat(token.length)], ["el verdadero con un carácter más", `${token}0`], ["el verdadero al revés", token.split("").reverse().join("")]];
    const wrong = [];
    for (const [label, value] of variants) {
      const r = await direct("GET", "/api/memory", { headers: { "X-MyKOS-Control-Token": value } });
      if (r.status !== 403) wrong.push(`${label}: ${r.status}`);
    }
    check("token vacío, corto, de la misma longitud, con un carácter más o al revés: 403", wrong.length === 0, wrong.join(" | ") || "5 variantes rechazadas");

    const h = await direct("GET", "/api/health");
    const root = await direct("GET", "/");
    const staticFile = await direct("GET", "/static/app.js");
    check("/api/health sigue abierto (lo usa la supervisión) y las rutas que no son /api/ no cambian (404 en modo backend)", h.status === 200 && root.status === 404 && staticFile.status === 404, `HTTP ${h.status}/${root.status}/${staticFile.status}`);
    const control = await direct("POST", "/mykos-control/tool", { body: "{}", headers: { "Content-Type": "application/json" } });
    check("las rutas internas /mykos-control/* siguen exigiendo su token (403)", control.status === 403, `HTTP ${control.status}`);

    const after = await conversationIds();
    const memoryAfter = asJson(await viaGateway("GET", "/api/memory"))?.count;
    check("ninguno de esos intentos cambió nada: mismas conversaciones y misma memoria", JSON.stringify(after) === JSON.stringify(baseline) && memoryAfter === memoryBefore, `${after.length} conversaciones, ${memoryAfter} recuerdos`);
    const log = workerLogText();
    check("el registro del trabajador muestra los 403 (llegaron a Python y allí se rechazaron)", (log.match(/" 403 -/g) || []).length >= attempts.length, `${(log.match(/" 403 -/g) || []).length} líneas 403`);
  }

  // C. Con el token verdadero SÍ contesta: el token es lo que abre la puerta
  {
    const oauth = await direct("POST", "/mykos-control/oauth-status", { body: "{}", headers: { "Content-Type": "application/json", "X-MyKOS-Control-Token": token } });
    check("con el token verdadero, el trabajador responde su plano interno OAuth (200): el token sigue siendo válido", oauth.status === 200, `HTTP ${oauth.status}`);
  }

  // D. Por el Gateway: lo permitido funciona, lo desconocido no llega a Python
  {
    const mem = await viaGateway("GET", "/api/memory");
    const created = await viaGateway("POST", "/api/conversations/new", { title: "guardián" });
    const id = asJson(created)?.conversation?.id;
    const del = await viaGateway("DELETE", `/api/conversations?id=${id}`);
    check("por el Gateway todo sigue funcionando: leer memoria, crear y borrar una conversación", mem.status === 200 && created.status === 200 && id && del.status === 200, `HTTP ${mem.status}/${created.status}/${del.status}`);
    const forged = await viaGateway("GET", "/api/memory", undefined, { "X-MyKOS-Control-Token": "falsificado" });
    check("un token falsificado por el navegador no estropea nada: el Gateway pone el suyo (200)", forged.status === 200, `HTTP ${forged.status}`);

    const logBefore = workerLogText().length;
    const unknown = [["GET", "/api/nada"], ["POST", "/api/chat/otra"], ["GET", "/api/memory/"], ["GET", "/api/conversations/"], ["POST", "/api/conversations/new/"], ["GET", "/api/Memory"], ["GET", "/api/conversations%2Fnew"], ["POST", "/api/approvals/x/borrar"]];
    const unknownOutcomes = [];
    for (const [m, p] of unknown) {
      const r = await viaGateway(m, p, m === "POST" ? {} : undefined);
      unknownOutcomes.push({ m, p, status: r.status, err: asJson(r)?.error });
    }
    check(`${unknown.length} rutas inexistentes (barra final, mayúsculas, %2F, decisión inventada): el Gateway responde 404 y no llegan al trabajador`, unknownOutcomes.every((o) => o.status === 404) && !/\/api\/(nada|chat\/otra|Memory|conversations%2Fnew|approvals\/x\/borrar)|\/ HTTP\/1/.test(workerLogText().slice(logBefore)), unknownOutcomes.filter((o) => o.status !== 404).map((o) => `${o.m} ${o.p} -> ${o.status}`).join(" | ") || "404 en todas");
    const encodedDots = await request({ path: "/api/%2e%2e/health", headers: {} });
    check("«%2e%2e» se trata como «..»: no se devuelve nada del trabajador ni llega a Python", (encodedDots.status === 404 || encodedDots.status === 200) && !/\/api\/%2e|\/api\/\.\./i.test(workerLogText().slice(logBefore)) && !/"count"|"entries"/.test(encodedDots.text), `HTTP ${encodedDots.status}`);

    const put = await viaGateway("PUT", "/api/memory", {});
    const getNew = await viaGateway("GET", "/api/conversations/new");
    const delHealth = await viaGateway("DELETE", "/api/health");
    const patch = await viaGateway("PATCH", "/api/conversations", {});
    check("método no permitido: 405 con la cabecera «Allow» correcta (PUT memoria, GET nueva conversación, DELETE health, PATCH)", put.status === 405 && put.headers.allow === "GET" && getNew.status === 405 && getNew.headers.allow === "POST" && delHealth.status === 405 && patch.status === 405 && patch.headers.allow === "DELETE, GET", `HTTP ${put.status}/${getNew.status}/${delHealth.status}/${patch.status}; Allow: ${put.headers.allow} | ${getNew.headers.allow} | ${patch.headers.allow}`);

    // Cabecera Host/Origin ajenos: siguen bloqueados en el Gateway
    const evil = await request({ method: "POST", path: "/api/conversations/new", headers: { "Content-Type": "application/json", Origin: "http://evil.example" }, body: "{}" });
    const evilHost = await request({ method: "GET", path: "/api/memory", host: "evil.example" });
    check("por el Gateway, una web ajena (Origin) o un Host ajeno siguen recibiendo 403", evil.status === 403 && evilHost.status === 403, `HTTP ${evil.status}/${evilHost.status}`);

    // Ruta con «..» sin codificar: se normaliza y se reenvía la ruta normalizada
    const dots = await request({ path: "/api/../api/memory", headers: {} });
    const dotsLog = workerLogText().slice(logBefore);
    check("una ruta con «..» se clasifica ya normalizada y a Python solo llega la ruta normalizada", (dots.status === 200 || dots.status === 404 || dots.status === 403) && !/\/api\/\.\./.test(dotsLog), `HTTP ${dots.status}`);

    // Rutas con sus propios credenciales y rutas del navegador que deben atravesar el Gateway con el token
    const heartbeat = await viaGateway("POST", "/api/nodes/heartbeat", { node_id: "no-existe" }, { "X-MyKOS-Node-Token": "n".repeat(32) });
    check("latido de un nodo por el Gateway: llega a Python con su token de nodo y responde el error de nodo, no el 403 del guardián", heartbeat.status === 400 && /nodo/i.test(asJson(heartbeat)?.error ?? ""), `HTTP ${heartbeat.status}: ${asJson(heartbeat)?.error}`);
    const callback = await request({ path: "/api/oauth/openrouter/callback?error=denegado", headers: {} });
    check("retorno de OAuth (navegación GET sin Origin) llega a Python por el Gateway (ni 403 del guardián ni 404 del Gateway)", callback.status !== 403 && !/Ruta no encontrada/.test(callback.text), `HTTP ${callback.status}`);
    const approval = await viaGateway("POST", "/api/approvals/inexistente/approve", {});
    check("aprobación por el Gateway: Python responde por su cuenta (no 403 del guardián, no 404 de ruta desconocida)", approval.status !== 403 && !/Ruta no encontrada/.test(approval.text), `HTTP ${approval.status}: ${String(asJson(approval)?.error ?? approval.text).slice(0, 80)}`);
  }

  // E. Diario del Gateway: dice QUÉ se hizo (dominio, acción, riesgo) y no guarda cuerpos ni el token
  {
    const j = journal();
    const create = j.findLast((e) => e.event === "api_request" && e.method === "POST" && e.path === "/api/conversations/new");
    const createResult = j.findLast((e) => e.event === "api_result" && e.method === "POST" && e.path === "/api/conversations/new");
    const del = j.findLast((e) => e.event === "api_request" && e.method === "DELETE" && e.path === "/api/conversations");
    const oauth = j.findLast((e) => e.event === "api_request" && e.path === "/api/oauth/openrouter/callback");
    const approve = j.findLast((e) => e.event === "api_request" && /^\/api\/approvals\/.+\/approve$/.test(e.path ?? ""));
    check("api_request de «crear conversación»: dominio conversations, acción create, riesgo write, propietario gateway", create?.domain === "conversations" && create.action === "create" && create.risk === "write" && create.route_owner === "gateway", JSON.stringify(create));
    check("api_result lleva los mismos datos más el estado", createResult?.domain === "conversations" && createResult.status === 200 && createResult.ok === true, JSON.stringify(createResult));
    check("borrar conversación, retorno de OAuth y aprobar quedan clasificados (delete/write, callback/sensitive, decide/sensitive)", del?.action === "delete" && del.risk === "write" && oauth?.domain === "oauth" && oauth.risk === "sensitive" && approve?.domain === "approvals" && approve.risk === "sensitive", `${del?.action}/${oauth?.action}/${approve?.action}`);
    const denied = j.filter((e) => e.event === "api_denied");
    check("cada rechazo del Gateway queda en el diario (api_denied): rutas desconocidas (404) y métodos no permitidos (405)", denied.filter((e) => e.reason === "unknown_route" && e.status === 404).length >= 8 && denied.filter((e) => e.reason === "method_not_allowed" && e.status === 405).length >= 4, `${denied.length} rechazos: ${denied.filter((e) => e.reason === "unknown_route").length} desconocidas, ${denied.filter((e) => e.reason === "method_not_allowed").length} de método`);
    const text = fs.existsSync(journalFile) ? fs.readFileSync(journalFile, "utf8") : "";
    check("el diario no contiene el token del Gateway ni cuerpos de peticiones", !text.includes(token) && !text.includes("falsificado") && !text.includes("no-existe"), `${j.length} anotaciones`);
    check("ninguna línea del diario está rota", !j.some((e) => e.broken), "");
  }

  // F. Caída del backend: el relanzado sigue con el guardián y con el mismo token
  {
    const before = (await health()).json.backend.pid;
    process.kill(before);
    const back = await waitFor(async () => {
      const h = await health();
      return h.status === 200 && h.json?.backend?.up && h.json.backend.pid !== before ? h.json : null;
    }, 90000, 500);
    check("tras caer Python, el plugin lo relanza con otro PID", back, back ? `PID ${before} -> ${back.backend.pid}` : "no se recuperó");
    if (back) {
      const noTok = await direct("GET", "/api/memory");
      const withTok = await direct("POST", "/mykos-control/oauth-status", { body: "{}", headers: { "Content-Type": "application/json", "X-MyKOS-Control-Token": token } });
      const gate = await viaGateway("GET", "/api/memory");
      check("el trabajador relanzado sigue rechazando sin token (403), acepta el token en su plano interno OAuth (200) y por el Gateway funciona", noTok.status === 403 && withTok.status === 200 && gate.status === 200, `HTTP ${noTok.status}/${withTok.status}/${gate.status}`);
    }
  }

  // G. Modos de arranque manual del propio server.py (sin Gateway): falla cerrado en modo backend, antiguo sin token
  {
    const start = async (port, env) => {
      const child = spawn(python, [path.join(project, "server.py")], { cwd: project, env: { ...process.env, PYTHONUTF8: "1", PYTHONUNBUFFERED: "1", MYKOS_PORT: String(port), MYKOS_STORE_MODE: "file", MYKOS_PUBLIC_PORT: String(port), MYKOS_CONTROL_TOKEN: "", MYKOS_BACKEND_ONLY: "", MYKOS_PARENT_PID: "", ...env }, stdio: "ignore", windowsHide: true });
      const ok = await waitFor(async () => (await portOpen(port)), 60000, 300);
      return { child, ok };
    };
    const stop = (child) => {
      try {
        child.kill();
      } catch {}
    };
    const closed = await start(3297, { MYKOS_BACKEND_ONLY: "1", MYKOS_WORKER_GUARD: "1" });
    if (closed.ok) {
      const api = await request({ port: 3297, path: "/api/memory" });
      const post = await request({ port: 3297, method: "POST", path: "/api/conversations/new", headers: { "Content-Type": "application/json" }, body: "{}" });
      const hh = await request({ port: 3297, path: "/api/health" });
      check("server.py con la puerta activada y SIN token (mal arrancado): falla cerrado, todo /api/* menos /api/health da 403", api.status === 403 && post.status === 403 && hh.status === 200, `HTTP ${api.status}/${post.status}/${hh.status}`);
    } else check("server.py con la puerta activada y sin token arranca", false, "no llegó a escuchar");
    stop(closed.child);
    const legacy = await start(3296, { MYKOS_BACKEND_ONLY: "1" });
    if (legacy.ok) {
      const api = await request({ port: 3296, path: "/api/health" });
      check("server.py sin la variable de la puerta (Gateway anterior al plugin 0.6.0 o arranque manual): la salud pública conserva el comportamiento antiguo (200)", api.status === 200, `HTTP ${api.status}`);
    } else check("server.py sin la puerta arranca", false, "no llegó a escuchar");
    stop(legacy.child);
    await sleep(500);
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
    console.log(`${r.info ? "INFO " : r.ok ? "OK   " : "FALLA"}  ${r.name.padEnd(width)}  ${r.detail}`);
  }
  const counted = results.filter((r) => !r.info).length;
  console.log(failures ? `\n==> ${failures} de ${counted} comprobaciones FALLARON` : `\n==> ${counted}/${counted} comprobaciones correctas`);
  process.exit(failures ? 1 : 0);
}
