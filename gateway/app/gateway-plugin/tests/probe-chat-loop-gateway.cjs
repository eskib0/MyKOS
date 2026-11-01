// Uso: node probe-chat-loop-gateway.cjs <puertoGateway> [puertoOllamaFalso]
//
// Fase 3, tramo 5: el bucle de chat del Gateway (chat-loop.js) contra un Gateway desechable con el server.py REAL y un
// Ollama FALSO que sigue un guion. Variables: BACKEND_PORT, PROJECT_DIR, TAG, CONTROL_TOKEN (= MYKOS_CONTROL_TOKEN del
// Gateway de prueba), OLLAMA_URL (= http://127.0.0.1:<puertoOllamaFalso>, lo lee tanto el Gateway como el trabajador) y
// EXPECT=on|off (por defecto on).
//   on : chatLoop.enabled=true → el bucle lo ejecuta el Gateway. Prueba la operación directa /mykos-control/loop, un chat
//        completo por /api/chat con herramienta de lectura, una acción sensible con aprobación y su continuación, un
//        permiso de sesión que se reutiliza, los errores del modelo y las peticiones falsificadas.
//   off: chatLoop.enabled=false → el bucle sigue siendo el de Python: la operación devuelve 409 y /api/chat funciona igual.
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");

const gw = Number(process.argv[2] || 18795);
const fakePort = Number(process.argv[3] || 3301);
const token = String(process.env.CONTROL_TOKEN || "");
const tag = process.env.TAG || "CL";
const projectDir = process.env.PROJECT_DIR || "";
const expectOn = String(process.env.EXPECT || "on").toLowerCase() !== "off";
const journalFile = process.env.CONTROL_AUDIT_FILE || path.join(os.homedir(), "mykos-gateway-test", `state-${tag}`, "mykos", "control-journal.jsonl");
const own = { Origin: `http://127.0.0.1:${gw}` };

const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ───────────── Ollama falso con guion ─────────────
const fake = { script: [], received: [], tagsCalls: 0 };
const reply = (message, extra = {}) => ({ message: { role: "assistant", ...message }, done_reason: "stop", done: true, ...extra });
const say = (content) => reply({ content });
const useTool = (name, args, content = "") => reply({ content, tool_calls: [{ function: { name, arguments: args } }] });
const fakeServer = http.createServer((req, res) => {
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => {
    const send = (status, body) => {
      const data = JSON.stringify(body);
      res.writeHead(status, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data), Connection: "close" });
      res.end(data);
    };
    if (req.url.startsWith("/api/tags")) {
      fake.tagsCalls += 1;
      return send(200, { models: [{ name: "fake:1", model: "fake:1", size: 1, capabilities: ["completion", "tools"], details: { parameter_size: "1B", family: "fake" } }] });
    }
    if (req.url.startsWith("/api/chat")) {
      let body = {};
      try {
        body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      } catch {}
      fake.received.push(body);
      const next = fake.script.shift();
      if (next === undefined) return send(500, { error: "guion agotado" });
      return send(next.__status || 200, next.__status ? { error: next.error } : next);
    }
    return send(404, { error: "no existe" });
  });
});

function request({ method = "GET", path: p, headers = {}, body, timeoutMs = 120000 }) {
  return new Promise((resolve) => {
    const h = { ...headers };
    let data = null;
    if (body !== undefined) {
      data = Buffer.from(typeof body === "string" ? body : JSON.stringify(body), "utf8");
      h["Content-Type"] = "application/json";
      h["Content-Length"] = data.length;
    }
    const chunks = [];
    const r = http.request({ host: "127.0.0.1", port: gw, method, path: p, headers: h, agent: false }, (res) => {
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => {
        const text = Buffer.concat(chunks).toString("utf8");
        let json = null;
        try {
          json = JSON.parse(text);
        } catch {}
        resolve({ status: res.statusCode, json, text });
      });
    });
    r.setTimeout(timeoutMs, () => {
      r.destroy();
      resolve({ status: "timeout", json: null, text: "" });
    });
    r.on("error", (e) => resolve({ status: `error:${e.code || e.message}`, json: null, text: "" }));
    r.end(data);
  });
}
const control = (op, body, headers = { "X-MyKOS-Control-Token": token }) => request({ method: "POST", path: `/mykos-control/${op}`, headers: { ...headers }, body });
const api = (method, p, body) => request({ method, path: p, headers: own, body });
const health = async () => (await request({ path: "/mykos-health", timeoutMs: 8000 })).json;
const journal = () => (fs.existsSync(journalFile)
  ? fs.readFileSync(journalFile, "utf8").split("\n").filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return {}; } })
  : []);
const newConversation = async () => (await api("POST", "/api/conversations/new", {})).json?.conversation?.id;
const conversationMessages = async (id) => (await api("GET", `/api/conversation?id=${id}`)).json?.conversation?.messages ?? [];

(async () => {
  await new Promise((resolve) => fakeServer.listen(fakePort, "127.0.0.1", resolve));
  const end = Date.now() + 150000;
  let up0 = null;
  while (Date.now() < end) {
    const h = await health();
    if (h?.ok && h.backend?.up && h.backend.phase === "up" && h.store?.active) {
      up0 = h;
      break;
    }
    await sleep(400);
  }
  if (!up0) {
    check("el Gateway arrancó con el backend «up» y el almacén activo", false, JSON.stringify(await health()).slice(0, 300));
    return finish();
  }
  // La versión no es parte del contrato del bucle: esta prueba debe detectar
  // que el plugin se ha cargado y que respeta el interruptor, no quedar rota
  // cada vez que se publica una revisión de MyKOS.
  check("Gateway con el plugin y el bucle de chat " + (expectOn ? "encendido" : "apagado"), typeof up0.version === "string" && up0.version.length > 0 && up0.chatLoop?.enabled === expectOn, `plugin ${up0.version}; chatLoop=${JSON.stringify(up0.chatLoop)}`);
  check("la prueba conoce el token del Gateway y el Ollama falso responde", token.length >= 16 && fake.tagsCalls >= 0, `${token.length} caracteres`);

  const convA = await newConversation();
  check("se crea una conversación de prueba", Boolean(convA), String(convA));
  const audit0 = journal().length;

  // ───── petición falsificada ─────
  const noTok = await control("loop", { model: "fake:1", messages: [{ role: "user", content: "x" }] }, {});
  const badTok = await control("loop", { model: "fake:1", messages: [{ role: "user", content: "x" }] }, { "X-MyKOS-Control-Token": "x".repeat(token.length) });
  check("la operación loop sin token o con token erróneo responde 403", noTok.status === 403 && badTok.status === 403, `HTTP ${noTok.status}/${badTok.status}`);

  if (!expectOn) {
    const off = await control("loop", { model: "fake:1", messages: [{ role: "user", content: "x" }], conversation_id: convA });
    check("con el bucle apagado, la operación loop responde 409 y no llama al modelo", off.status === 409 && fake.received.length === 0, `HTTP ${off.status}`);
    // El camino de Python sigue funcionando igual: respuesta directa y herramienta de lectura
    fake.script = [use("list_allowed_roots", {}), say("Camino de Python")];
    const chat = await api("POST", "/api/chat", { message: "hola", model: "fake:1", conversation_id: convA });
    check("con el bucle apagado, /api/chat responde por el bucle de Python con su herramienta", chat.status === 200 && chat.json?.message?.content === "Camino de Python" && (chat.json.tools_used || []).includes("list_allowed_roots"), `HTTP ${chat.status} ${chat.text.slice(0, 160)}`);
    check("y no pasa por el bucle del Gateway (ningún evento loop_tool)", !journal().slice(audit0).some((e) => e.event === "loop_tool"));
    // Aprobación y continuación por el camino de Python (el contexto de la aprobación tiene que llegar al trabajador)
    const convP = await newConversation();
    const offTarget = path.join(projectDir, "prueba-loop-off.txt");
    fs.rmSync(offTarget, { force: true });
    fake.script = [useTool("write_project_file", { root: "mykos", path: "prueba-loop-off.txt", content: "por python" }, "Propongo escribir")];
    const pend = await api("POST", "/api/chat", { message: "escribe", model: "fake:1", conversation_id: convP });
    fake.script = [say("Escrito por el camino de Python")];
    const ok = await api("POST", `/api/approvals/${pend.json?.pending_action?.id}/approve`, { permission_mode: "once" });
    check("con el bucle apagado, aprobar ejecuta la acción y el turno continúa (contexto de la aprobación intacto)", pend.json?.needs_approval === true && ok.status === 200 && ok.json?.message?.content === "Escrito por el camino de Python" && !ok.json?.continuation_failed && fs.existsSync(offTarget), `HTTP ${ok.status} ${ok.text.slice(-300)}`);
    for (const id of [convA, convP]) await api("DELETE", `/api/conversations?id=${id}`);
    fs.rmSync(offTarget, { force: true });
    return finishWith(up0);
  }

  // ───── operación directa /mykos-control/loop ─────
  const remote = await control("loop", { model: "openrouter/algo", messages: [{ role: "user", content: "x" }], conversation_id: convA });
  const noMsgs = await control("loop", { model: "fake:1", conversation_id: convA });
  check("un modelo remoto o un cuerpo sin contexto se rechaza con 400", remote.status === 400 && noMsgs.status === 400, `HTTP ${remote.status}/${noMsgs.status}`);

  fake.script = [useTool("list_allowed_roots", {}), say("Listo")];
  fake.received.length = 0;
  const direct = await control("loop", {
    model: "fake:1",
    messages: [{ role: "system", content: "sistema" }, { role: "user", content: "hola" }],
    conversation_id: convA,
    generation: { options: { num_ctx: 4096 }, think: false },
    activity_id: "act-directa",
  });
  check("loop directo: responde 200 con el texto final, la herramienta usada y el id del mensaje guardado", direct.status === 200 && direct.json?.message?.content === "Listo" && direct.json.tools_used?.join() === "list_allowed_roots" && Boolean(direct.json.message?.message_id), `HTTP ${direct.status} ${direct.text.slice(0, 200)}`);
  const stored = await conversationMessages(convA);
  check("la respuesta quedó guardada en la conversación (por el trabajador, con su id)", stored.some((m) => m.role === "assistant" && m.content === "Listo" && m.message_id === direct.json?.message?.message_id), `${stored.length} mensajes`);
  check("el Ollama falso recibió 2 llamadas; la primera ya lleva el catálogo real de herramientas (con las sensibles)", fake.received.length === 2 && fake.received[0].tools?.some((t) => t.function?.name === "write_project_file") && fake.received[0].tools?.some((t) => t.function?.name === "list_allowed_roots") && fake.received[0].stream === false, `${fake.received.length} llamadas; ${fake.received[0]?.tools?.length} herramientas`);
  const toolMsg = fake.received[1]?.messages?.find((m) => m.role === "tool");
  check("la segunda llamada lleva el resultado real de la herramienta ejecutada por Python", /mykos/.test(toolMsg?.content ?? "") && /"ok":true/.test(toolMsg?.content ?? ""), (toolMsg?.content ?? "").slice(0, 120));
  check("devuelve el contexto final y la ventana ajustada para el medidor", Array.isArray(direct.json?._messages) && direct.json._messages.length >= 4 && direct.json._generation?.options?.num_ctx === 4096, JSON.stringify(direct.json?._generation));
  const events = journal().slice(audit0);
  check("el diario anota la petición del bucle, la herramienta usada y el resultado, sin cuerpos", events.some((e) => e.event === "loop_tool" && e.tool === "list_allowed_roots" && e.ok === true) && events.some((e) => e.event === "control_result" && e.operation === "loop" && e.ok === true) && !events.some((e) => JSON.stringify(e).includes("hola")), `${events.length} eventos`);

  // ───── chat completo por /api/chat (Python arma el contexto y delega el bucle) ─────
  const convB = await newConversation();
  fake.script = [useTool("list_allowed_roots", {}), say("Hola por /api/chat")];
  fake.received.length = 0;
  const chat = await api("POST", "/api/chat", { message: "hola mykos", model: "fake:1", conversation_id: convB });
  check("/api/chat completo: 200, texto del modelo, herramienta usada y medidor de contexto", chat.status === 200 && chat.json?.message?.content === "Hola por /api/chat" && chat.json.tools_used?.includes("list_allowed_roots") && Number(chat.json.context?.estimated_tokens) > 0, `HTTP ${chat.status} ${chat.text.slice(0, 200)}`);
  check("el mensaje del usuario y la respuesta están en la conversación, en orden", (await conversationMessages(convB)).map((m) => m.role).join() === "user,assistant");
  check("la primera llamada al modelo lleva el prompt de sistema y el mensaje del usuario", fake.received[0]?.messages?.[0]?.role === "system" && fake.received[0].messages.some((m) => m.role === "user" && /hola mykos/.test(m.content)));

  // ───── acción sensible: aprobación y continuación ─────
  const convC = await newConversation();
  const target = "prueba-loop.txt";
  const targetPath = path.join(projectDir, target);
  fs.rmSync(targetPath, { force: true });
  fake.script = [useTool("write_project_file", { root: "mykos", path: target, content: "hola loop" }, "Propongo escribir el fichero")];
  const pendingChat = await api("POST", "/api/chat", { message: "escribe un fichero", model: "fake:1", conversation_id: convC });
  const approval = pendingChat.json?.pending_action;
  check("acción sensible: /api/chat devuelve la aprobación pendiente con la propuesta del modelo y NO escribe nada", pendingChat.status === 200 && pendingChat.json?.needs_approval === true && Boolean(approval?.id) && /Propongo escribir/.test(pendingChat.json.message?.content ?? "") && !fs.existsSync(targetPath), `HTTP ${pendingChat.status} ${pendingChat.text.slice(0, 160)}`);
  const listed = (await api("GET", `/api/approvals?conversation_id=${convC}`)).json?.approvals ?? [];
  check("la aprobación está en la cola del Gateway", listed.length === 1 && listed[0].id === approval?.id, `${listed.length} pendientes`);
  fake.script = [say("Fichero escrito")];
  const approved = await api("POST", `/api/approvals/${approval?.id}/approve`, { permission_mode: "session" });
  check("aprobar (permiso de sesión): el Gateway ejecuta por el trabajador, el bucle continúa y el modelo cierra", approved.status === 200 && approved.json?.message?.content === "Fichero escrito", `HTTP ${approved.status} ${approved.text.slice(-500)}`);
  check("el fichero existe con el contenido aprobado", fs.existsSync(targetPath) && fs.readFileSync(targetPath, "utf8") === "hola loop", fs.existsSync(targetPath) ? fs.readFileSync(targetPath, "utf8") : "no existe");
  const resumed = fake.received.at(-1);
  check("al continuar tras la aprobación, el modelo recibe la petición, su llamada y el resultado de la herramienta", resumed?.messages?.some((m) => m.role === "assistant" && m.tool_calls) && resumed.messages.some((m) => m.role === "tool" && /ok/.test(m.content)), `${resumed?.messages?.length} mensajes`);
  check("la cola de aprobaciones queda vacía", ((await api("GET", `/api/approvals?conversation_id=${convC}`)).json?.approvals ?? []).length === 0);

  // ───── permiso de sesión ya concedido: se ejecuta sin volver a preguntar ─────
  // El permiso de sesión cubre exactamente ese fichero (y overwrite=false): se borra y se vuelve a pedir el mismo.
  const target2 = target;
  const target2Path = targetPath;
  fs.rmSync(target2Path, { force: true });
  fake.script = [useTool("write_project_file", { root: "mykos", path: target2, content: "segundo" }), say("Segundo escrito")];
  const before = journal().length;
  const second = await api("POST", "/api/chat", { message: "otro más", model: "fake:1", conversation_id: convC });
  check("con el permiso de sesión ya concedido: se ejecuta sin pedir aprobación y responde el modelo", second.status === 200 && !second.json?.needs_approval && second.json?.message?.content === "Segundo escrito" && fs.existsSync(target2Path) && fs.readFileSync(target2Path, "utf8") === "segundo", `HTTP ${second.status} ${second.text.slice(0, 200)}`);
  const audit = (await api("GET", `/api/audit?conversation_id=${convC}&limit=50`)).json?.audit ?? [];
  check("la auditoría del Gateway anota la creación, la aprobación y el uso del permiso", ["approval_created", "permission_granted", "permission_used"].every((ev) => audit.some((a) => a.event === ev)), audit.map((a) => a.event).join(","));
  check("el diario anota la acción ejecutada por el bucle (loop_action) sin contenido", journal().slice(before).some((e) => e.event === "loop_action" && e.action === "write_file" && e.ok === true) && !journal().slice(before).some((e) => JSON.stringify(e).includes("segundo")));
  // Otra conversación no hereda el permiso de sesión
  const convD = await newConversation();
  fake.script = [useTool("write_project_file", { root: "mykos", path: "prueba-loop-3.txt", content: "tercero" }, "Otro")];
  const isolated = await api("POST", "/api/chat", { message: "y aquí", model: "fake:1", conversation_id: convD });
  check("otra conversación NO hereda el permiso de sesión: vuelve a pedir aprobación", isolated.json?.needs_approval === true && !fs.existsSync(path.join(projectDir, "prueba-loop-3.txt")), `HTTP ${isolated.status}`);

  // ───── errores del modelo ─────
  const convE = await newConversation();
  fake.script = [say(""), say("")];
  const empty = await api("POST", "/api/chat", { message: "di algo", model: "fake:1", conversation_id: convE });
  check("el modelo devuelve vacío dos veces: error claro del bucle (sin «HTTP 502» ni JSON envuelto)", empty.status >= 400 && /terminó sin devolver texto/.test(empty.json?.error ?? "") && !/plano de control|HTTP 5/.test(empty.json?.error ?? ""), `HTTP ${empty.status} ${empty.text.slice(0, 200)}`);
  fake.script = [{ __status: 500, error: "fallo interno del motor" }];
  const down = await api("POST", "/api/chat", { message: "otra", model: "fake:1", conversation_id: convE });
  check("el motor devuelve un error: llega al usuario con su mensaje", down.status >= 400 && /fallo interno del motor/.test(down.json?.error ?? ""), `HTTP ${down.status} ${down.text.slice(0, 200)}`);

  // ───── integridad ─────
  await api("DELETE", `/api/conversations?id=${convA}`);
  for (const id of [convB, convC, convD, convE]) await api("DELETE", `/api/conversations?id=${id}`);
  for (const f of [targetPath, target2Path, path.join(projectDir, "prueba-loop-3.txt")]) fs.rmSync(f, { force: true });
  return finishWith(up0);
})().catch((error) => {
  check("la batería terminó sin excepciones", false, String(error && error.stack ? error.stack : error));
  finish();
});

function use(name, args) {
  return useTool(name, args);
}

async function finishWith(up0) {
  const h = await health();
  check("al final: mismo Gateway y mismo backend, sin reinicios", h?.ok && h.pid === up0.pid && h.backend?.pid === up0.backend.pid && h.backend.restarts === up0.backend.restarts, `Gateway ${h?.pid}, backend ${h?.backend?.pid}, reinicios ${h?.backend?.restarts}`);
  finish();
}

function finish() {
  try {
    fakeServer.close();
  } catch {}
  const width = Math.min(150, Math.max(...results.map((r) => r.name.length)));
  let bad = 0;
  for (const r of results) {
    if (!r.ok) bad += 1;
    console.log(`${r.ok ? "OK   " : "FALLA"}  ${r.name.padEnd(width)}  ${r.detail}`);
  }
  console.log(bad ? `\n==> ${bad} de ${results.length} comprobaciones FALLARON` : `\n==> ${results.length}/${results.length} comprobaciones correctas`);
  process.exit(bad ? 1 : 0);
}
