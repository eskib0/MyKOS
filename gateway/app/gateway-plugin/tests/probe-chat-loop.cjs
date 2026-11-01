// Uso: node probe-chat-loop.cjs
//
// Fase 3, tramo 5: pruebas unitarias del bucle de chat del Gateway (chat-loop.js), SIN Gateway ni Python: el modelo, la
// autoridad de permisos y el trabajador son falsos y registran lo que se les pide. Comprueba que el bucle hace lo mismo
// que la rama «modelo local» de run_model_until_result() de server.py.
const path = require("path");
const { pathToFileURL } = require("url");

const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });

const SCHEMAS = [
  { type: "function", function: { name: "read_project_file", parameters: {} } },
  { type: "function", function: { name: "web_search", parameters: {} } },
  { type: "function", function: { name: "web_fetch", parameters: {} } },
  { type: "function", function: { name: "run_powershell", parameters: {} } },
  { type: "function", function: { name: "save_research_note", parameters: {} } },
];
const SENSITIVE = ["run_powershell", "save_research_note", "write_project_file"];
const call = (name, args, id) => ({ ...(id ? { id } : {}), function: { name, arguments: args } });
const ollamaText = (content, extra = {}) => ({ message: { role: "assistant", content }, done_reason: "stop", done: true, ...extra });
const ollamaCalls = (calls, content = "") => ({ message: { role: "assistant", content, tool_calls: calls }, done_reason: "stop", done: true });
const llamaText = (content) => ({ choices: [{ message: { role: "assistant", content }, finish_reason: "stop" }] });
const llamaCalls = (calls) => ({ choices: [{ message: { role: "assistant", content: "", tool_calls: calls }, finish_reason: "tool_calls" }] });

/** Entorno falso. `script` = respuestas del modelo en orden (o funciones). */
function harness({ script, grants = new Set(), toolResults = {}, prepareFails = false, activityFails = false } = {}) {
  const log = { model: [], tools: [], prepared: [], actions: [], approvals: [], audits: [], saved: [], activity: [] };
  let turn = 0;
  const deps = {
    now: () => "2026-09-26T13:00:00+00:00",
    model: {
      async request(provider, payload) {
        log.model.push({ provider, payload: JSON.parse(JSON.stringify(payload)) });
        const next = script[Math.min(turn, script.length - 1)];
        turn += 1;
        if (next instanceof Error) throw next;
        return typeof next === "function" ? next(provider, payload) : next;
      },
    },
    authority: {
      descriptor: (tool, action) => ({ category: "test", operation: tool, scope_key: `${tool}:${JSON.stringify(action)}` }),
      authorize(tool, action) {
        const descriptor = deps.authority.descriptor(tool, action);
        return grants.has(tool)
          ? { ok: true, decision: "granted", descriptor, grant: { id: "g1", mode: "session" }, authorization: { permission_id: "g1", scope_key: descriptor.scope_key } }
          : { ok: true, decision: "approval_required", descriptor };
      },
      createApproval(input) {
        log.approvals.push(JSON.parse(JSON.stringify(input)));
        return { ok: true, approval: { id: `ap${log.approvals.length}`, tool_name: input.tool_name } };
      },
      audit: (event, descriptor, extra) => log.audits.push({ event, descriptor, extra }),
    },
    worker: {
      async catalog() {
        return { schemas: SCHEMAS, sensitive: SENSITIVE };
      },
      async tool(name, args) {
        log.tools.push({ name, args });
        const r = toolResults[name];
        return typeof r === "function" ? r(args) : r ?? { ok: true, action: name, content: `resultado de ${name}` };
      },
      async prepare(name, args) {
        log.prepared.push({ name, args });
        return prepareFails ? { ok: false, error: "no se puede preparar" } : { ok: true, action: { kind: name, args } };
      },
      async action(action, sid, authorization) {
        log.actions.push({ action, sid, authorization });
        return { ok: true, output: "ejecutado" };
      },
      async activity(id, update) {
        log.activity.push({ id, ...update });
        if (activityFails) throw new Error("el trabajador no responde");
      },
      async saveMessage(sid, message) {
        log.saved.push({ sid, message: JSON.parse(JSON.stringify(message)) });
        return { ...message, message_id: `m${log.saved.length}` };
      },
    },
  };
  return { deps, log };
}
const input = (over = {}) => ({
  model: "qwen3:8b",
  messages: [{ role: "system", content: "sistema" }, { role: "user", content: "hola" }],
  conversation_id: "c1",
  supports_vision: false,
  generation: { options: { num_ctx: 8192 }, think: false },
  activity_id: "a1",
  ...over,
});

(async () => {
  const mod = await import(pathToFileURL(path.join(__dirname, "..", "mykos-ui", "chat-loop.js")).href);
  const { runChatLoop, MAX_TOOL_ROUNDS } = mod;

  // 1. Respuesta directa con Ollama
  {
    const { deps, log } = harness({ script: [ollamaText("Hola, Usuario")] });
    const r = await runChatLoop(input(), deps);
    check("Ollama, respuesta directa: devuelve el mensaje guardado con su id", r.message?.content === "Hola, Usuario" && r.message.message_id === "m1" && r.done === true, JSON.stringify(r.message));
    check("se guarda una sola vez, en la conversación correcta, con fecha", log.saved.length === 1 && log.saved[0].sid === "c1" && log.saved[0].message.created_at === "2026-09-26T13:00:00+00:00", JSON.stringify(log.saved[0]));
    check("va al proveedor «ollama» con herramientas, sin streaming y con keep_alive", log.model[0].provider === "ollama" && log.model[0].payload.stream === false && log.model[0].payload.keep_alive === -1 && log.model[0].payload.tools.length === SCHEMAS.length, log.model[0].provider);
    check("sin herramientas: tools_used vacío y sources vacío", r.tools_used.length === 0 && r.sources.length === 0);
    check("devuelve el contexto final (_messages/_generation) para el medidor", Array.isArray(r._messages) && r._generation?.options?.num_ctx === 8192);
  }

  // 2. Ollama no recibe metadatos internos
  {
    const { deps, log } = harness({ script: [ollamaText("ok")] });
    await runChatLoop(input({ messages: [{ role: "user", content: "x", sources: [{ url: "u" }], created_at: "hoy", images: ["AAA"], image_mime_type: "image/png" }] }), deps);
    const sent = log.model[0].payload.messages[0];
    check("a Ollama solo van role/content/images/tool_calls/image_mime_type (nada de sources ni fechas)", sent.sources === undefined && sent.created_at === undefined && sent.images?.[0] === "AAA" && sent.image_mime_type === "image/png", JSON.stringify(sent));
  }

  // 3. llama.cpp: formato OpenAI, ids de llamada y herramienta de solo lectura
  {
    const { deps, log } = harness({ script: [llamaCalls([call("read_project_file", { path: "a.txt" })]), llamaText("Listo")] });
    const r = await runChatLoop(input({ model: "mykos-cuda", generation: { options: { num_ctx: 8192, num_predict: 300, temperature: 0.2 }, effort: "off" } }), deps);
    const first = log.model[0].payload;
    check("llama.cpp: proveedor llama_cpp, tool_choice auto, max_tokens, temperatura y reasoning_effort none", log.model[0].provider === "llama_cpp" && first.tool_choice === "auto" && first.max_tokens === 300 && first.temperature === 0.2 && first.reasoning_effort === "none" && first.user === "mykos-web-c1", JSON.stringify({ ...first, tools: undefined, messages: undefined }));
    const second = log.model[1].payload.messages;
    const assistantCall = second.find((m) => m.role === "assistant" && m.tool_calls);
    const toolMsg = second.find((m) => m.role === "tool");
    check("las llamadas sin id reciben call_<ronda>_<n> y el mensaje de herramienta lo lleva", assistantCall.tool_calls[0].id === "call_0_0" && assistantCall.tool_calls[0].type === "function" && toolMsg.tool_call_id === "call_0_0", JSON.stringify(toolMsg));
    check("la herramienta de lectura la ejecuta el trabajador y se anota en tools_used", log.tools.length === 1 && log.tools[0].name === "read_project_file" && r.tools_used.join() === "read_project_file" && r.message.content === "Listo");
  }

  // 4. Acción sensible sin permiso: aprobación pendiente, nada se ejecuta
  {
    const { deps, log } = harness({ script: [ollamaCalls([call("run_powershell", { command: "dir" })], "Propongo listar")] });
    const r = await runChatLoop(input(), deps);
    check("sensible sin permiso: devuelve pending_action y la propuesta del modelo", r.pending_action?.id === "ap1" && r.proposal === "Propongo listar" && r.done === false, JSON.stringify(r).slice(0, 200));
    check("no se ejecuta nada ni se guarda mensaje; la aprobación lleva conversación, modelo y contexto", log.actions.length === 0 && log.tools.length === 0 && log.saved.length === 0 && log.approvals[0].conversation_id === "c1" && log.approvals[0].model === "qwen3:8b" && log.approvals[0].messages.length >= 3, JSON.stringify(log.approvals[0]).slice(0, 160));
    check("la actividad pasa por «Esperando tu aprobación…»", log.activity.some((a) => a.status === "waiting" && a.phase === "approval"));
  }

  // 5. Acción sensible con permiso ya concedido: la ejecuta el trabajador con la autorización del Gateway
  {
    const { deps, log } = harness({ script: [ollamaCalls([call("run_powershell", { command: "dir" })]), ollamaText("Hecho")], grants: new Set(["run_powershell"]) });
    const r = await runChatLoop(input(), deps);
    check("con permiso concedido: se ejecuta por el trabajador con permission_id y sin pedir aprobación", log.actions.length === 1 && log.actions[0].authorization?.permission_id === "g1" && log.actions[0].sid === "c1" && log.approvals.length === 0 && r.message.content === "Hecho", JSON.stringify(log.actions[0]));
    check("queda auditado «permission_used» con el permiso usado", log.audits.length === 1 && log.audits[0].event === "permission_used" && log.audits[0].extra.permission_id === "g1" && log.audits[0].extra.status === "ok" && log.audits[0].extra.session_id === "c1");
  }

  // 6. Si la acción no se puede preparar, no se ejecuta ni se pide aprobación: el modelo recibe el error
  {
    const { deps, log } = harness({ script: [ollamaCalls([call("run_powershell", { command: "x" })]), ollamaText("no pude")], prepareFails: true });
    const r = await runChatLoop(input(), deps);
    const toolMsg = log.model[1].payload.messages.filter((m) => m.role === "tool").at(-1);
    check("acción no preparable: sin ejecución; el modelo recibe el error y sigue", log.actions.length === 0 && log.approvals.length === 0 && /no se puede preparar/.test(toolMsg?.content ?? "") && r.message.content === "no pude", toolMsg?.content);
  }

  // 7. Dos acciones sensibles a la vez
  {
    const { deps, log } = harness({ script: [ollamaCalls([call("run_powershell", { command: "a" }), call("write_project_file", { path: "b" })]), ollamaText("vale")] });
    const r = await runChatLoop(input(), deps);
    const errs = log.model[1].payload.messages.filter((m) => m.role === "tool");
    check("dos acciones sensibles en una ronda: ninguna se aprueba y el modelo recibe un error por cada una", log.approvals.length === 0 && errs.length === 2 && errs.every((m) => /Solo se permite una acción sensible/.test(m.content)) && r.tools_used.length === 2, JSON.stringify(r.tools_used));
  }

  // 8. Límites de búsqueda web y recorte de resultados
  {
    const search = (n) => ollamaCalls([call("web_search", { query: `q${n}`, max_results: 50 })]);
    const { deps, log } = harness({
      script: [search(1), search(2), search(3), ollamaText("fin")],
      toolResults: { web_search: { ok: true, action: "web_search", searched_at: "t", results: [{ title: "T", url: "https://a.example/x", snippet: "s" }] } },
    });
    const r = await runChatLoop(input(), deps);
    const last = log.model.at(-1).payload.messages.filter((m) => m.role === "tool").at(-1);
    check("web_search: a lo sumo 2 búsquedas por petición y max_results recortado a 5", log.tools.filter((t) => t.name === "web_search").length === 2 && log.tools.every((t) => t.args.max_results === 5) && /suficientes búsquedas/.test(last.content), last.content.slice(0, 90));
    check("las fuentes se acumulan sin duplicados y viajan en el mensaje final", r.sources.length === 1 && r.message.sources?.[0]?.url === "https://a.example/x" && log.saved[0].message.sources.length === 1);
    check("tras una herramienta web la ventana de contexto sube a 16384", r._generation.options.num_ctx === 16384, String(r._generation.options.num_ctx));
  }
  {
    const fetches = Array.from({ length: 7 }, (_, i) => ollamaCalls([call("web_fetch", { url: `https://e.example/${i}` })]));
    const { deps, log } = harness({ script: [...fetches, ollamaText("fin")] });
    await runChatLoop(input(), deps);
    check("web_fetch: a lo sumo 6 lecturas por petición", log.tools.filter((t) => t.name === "web_fetch").length === 6);
  }

  // 9. Respuesta vacía: un reintento y luego error claro
  {
    const { deps, log } = harness({ script: [ollamaText(""), ollamaText("ahora sí")] });
    const r = await runChatLoop(input(), deps);
    const retry = log.model[1].payload.messages.at(-1);
    check("respuesta vacía: un reintento con el aviso al modelo y ventana ampliada", r.message.content === "ahora sí" && retry.role === "user" && /llegó vacía/.test(retry.content) && log.model[1].payload.options.num_ctx === 16384, retry.content.slice(0, 40));
  }
  {
    const { deps } = harness({ script: [ollamaText(""), ollamaText("")] });
    let error = "";
    try {
      await runChatLoop(input(), deps);
    } catch (e) {
      error = e.message;
    }
    check("vacía dos veces y sin fuentes: error claro con el motivo", /terminó sin devolver texto \(motivo: stop\)/.test(error), error);
  }

  // 10. Ficha de investigación
  {
    const findings = { ok: true, action: "web_search", searched_at: "t", results: [{ title: "A", url: "https://a.example/", snippet: "s" }] };
    const bad = call("save_research_note", { title: "t", sources: [{ url: "https://inventada.example" }] });
    const good = call("save_research_note", { title: "t", sources: [{ url: "https://a.example" }] });
    const { deps, log } = harness({ script: [ollamaCalls([call("web_search", { query: "x" })]), ollamaCalls([bad]), ollamaCalls([good], "Ficha lista")], toolResults: { web_search: findings } });
    const r = await runChatLoop(input(), deps);
    const rejected = log.model[2].payload.messages.filter((m) => m.role === "tool").at(-1);
    check("una ficha con URLs no consultadas se rechaza sin pedir aprobación", /No se puede preparar la ficha todavía/.test(rejected.content) && log.approvals.length === 1, rejected.content.slice(0, 60));
    check("una ficha con URLs verificadas (aunque sin barra final) pasa a aprobación", r.pending_action?.id === "ap1" && r.proposal === "Ficha lista" && log.approvals[0].tool_name === "save_research_note");
  }

  // 11. Límite de rondas: se cierra con la ficha (solo esa herramienta) o falla
  {
    const findings = { ok: true, action: "web_search", searched_at: "t", results: [{ title: "A", url: "https://a.example/", snippet: "s" }] };
    const loop = (provider, payload) => (payload.tools?.length === 1 ? ollamaCalls([call("save_research_note", { title: "t", sources: [{ url: "https://a.example" }] })]) : ollamaCalls([call("read_project_file", { path: "x" })]));
    const { deps, log } = harness({ script: [ollamaCalls([call("web_search", { query: "x" })]), loop], toolResults: { web_search: findings, read_project_file: { ok: true } } });
    const r = await runChatLoop(input(), deps);
    const finalCall = log.model.at(-1).payload;
    check("al agotar las rondas: llamada final solo con save_research_note, sin la transcripción, y aprobación", finalCall.tools.length === 1 && finalCall.tools[0].function.name === "save_research_note" && finalCall.think === false && finalCall.options.num_predict >= 1536 && finalCall.messages.length === 3 && r.pending_action?.id === "ap1", `${log.model.length} llamadas`);
    check("el bucle se detiene en MAX_TOOL_ROUNDS + 1 llamadas al modelo (+ la de cierre)", log.model.length === MAX_TOOL_ROUNDS + 2, `${log.model.length}`);
  }
  {
    const { deps } = harness({ script: [() => ollamaCalls([call("read_project_file", { path: "x" })])] });
    let error = "";
    try {
      await runChatLoop(input(), deps);
    } catch (e) {
      error = e.message;
    }
    check("al agotar las rondas sin fuentes: falla con el error de cierre (no hay ficha que preparar)", /fuentes|cerrar|ficha|límite/i.test(error), error);
  }

  // 12. Robustez
  {
    const { deps } = harness({ script: [new Error("el motor no responde")] });
    let error = "";
    try {
      await runChatLoop(input(), deps);
    } catch (e) {
      error = e.message;
    }
    check("un fallo del modelo se propaga con su mensaje", error === "el motor no responde", error);
  }
  {
    const { deps, log } = harness({ script: [ollamaText("sigue")], activityFails: true });
    const r = await runChatLoop(input(), deps);
    check("si el aviso de actividad falla, el chat sigue y responde", r.message.content === "sigue" && log.activity.length > 0);
  }
  {
    const { deps, log } = harness({ script: [ollamaCalls([call("read_project_file", "{\"path\":\"a.txt\"}")]), ollamaText("ok")] });
    await runChatLoop(input(), deps);
    check("los argumentos como texto JSON se interpretan; los rotos se toman como vacíos", JSON.stringify(log.tools[0].args) === "{\"path\":\"a.txt\"}");
  }
  {
    const { deps, log } = harness({ script: [ollamaCalls([call("read_project_file", "{roto")]), ollamaText("ok")] });
    await runChatLoop(input(), deps);
    check("argumentos rotos: la herramienta se llama con {} y el bucle sigue", JSON.stringify(log.tools[0].args) === "{}");
  }
  {
    const { deps, log } = harness({
      script: [ollamaCalls([call("read_project_file", {})]), ollamaText("veo")],
      toolResults: { read_project_file: { ok: true, _image_base64: "IMG", _image_mime_type: "image/png" } },
    });
    await runChatLoop(input({ supports_vision: true }), deps);
    const t = log.model[1].payload.messages.find((m) => m.role === "tool");
    check("con visión: la imagen va adjunta al mensaje de herramienta y no en su texto", t.images?.[0] === "IMG" && t.image_mime_type === "image/png" && !/IMG/.test(t.content) && /"image_attached":true/.test(t.content));
  }
  {
    const { deps, log } = harness({
      script: [ollamaCalls([call("read_project_file", {})]), ollamaText("sin ver")],
      toolResults: { read_project_file: { ok: true, _image_base64: "IMG" } },
    });
    await runChatLoop(input({ supports_vision: false }), deps);
    const t = log.model[1].payload.messages.find((m) => m.role === "tool");
    check("sin visión: no se adjunta la imagen y se avisa en el resultado", t.images === undefined && /"image_attached":false/.test(t.content) && /no admite visión/.test(t.content));
  }
  {
    const { deps } = harness({ script: [ollamaText("hola")] });
    const original = input();
    const before = JSON.stringify(original.messages);
    await runChatLoop(original, deps);
    check("la entrada del contexto original no se corrompe (solo se le añade lo del bucle)", JSON.stringify(original.messages) === before);
  }
  {
    const { deps, log } = harness({ script: [ollamaText("sin auto")] });
    await runChatLoop(input({ auto_approve: true }), deps);
    check("auto_approve se ignora (el Gateway no acepta autorizaciones automáticas)", log.approvals.length === 0 && log.actions.length === 0);
  }

  finish();
})().catch((error) => {
  check("la prueba terminó sin excepciones", false, String(error && error.stack ? error.stack : error));
  finish();
});

function finish() {
  const width = Math.min(150, Math.max(...results.map((r) => r.name.length)));
  let bad = 0;
  for (const r of results) {
    if (!r.ok) bad += 1;
    console.log(`${r.ok ? "OK   " : "FALLA"}  ${r.name.padEnd(width)}  ${r.detail}`);
  }
  console.log(bad ? `\n==> ${bad} de ${results.length} comprobaciones FALLARON` : `\n==> ${results.length}/${results.length} comprobaciones correctas`);
  process.exit(bad ? 1 : 0);
}
