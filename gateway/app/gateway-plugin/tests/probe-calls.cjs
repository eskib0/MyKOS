// Prueba unitaria del contrato de llamadas de voz (fase 5.1), sin Gateway ni audio.
const os = require("os");
const path = require("path");
const { pathToFileURL } = require("url");

const repo = path.resolve(__dirname, "..", "..");

let passed = 0;
let failed = 0;
function check(label, value, detail = "") {
  if (value) { passed += 1; console.log(`OK     ${label}${detail ? `  ${detail}` : ""}`); }
  else { failed += 1; console.log(`FALLA  ${label}${detail ? `  ${detail}` : ""}`); }
}
(async () => {
  const { CallError, CallRegistry } = await import(pathToFileURL(path.join(repo, "gateway-plugin", "mykos-ui", "calls.js")).href);
  function expectError(fn, status, code) {
    try { fn(); return false; }
    catch (error) { return error.status === status && error.code === code; }
  }
  const doc = { revision: 1, data: { conversations: [{ id: "session-1", title: "Prueba", messages: [] }] } };
  const store = {
    get(name) { return name === "conversations" ? doc : null; },
    put(name, data, options) {
      if (name !== "conversations" || options.expectedRevision !== doc.revision) throw new Error("revisión inesperada");
      doc.revision += 1;
      doc.data = data;
      return { revision: doc.revision };
    },
  };
  const registry = new CallRegistry({ store, isActive: () => true });
  const created = registry.create({ sessionId: "session-1" });
  check("crea callId propio y sesión compartida", /^call_[0-9a-f-]{36}$/.test(created.callId) && created.sessionId === "session-1");
  check("el estado inicial es connecting sin audio", created.state === "connecting" && created.connection.audio === false && created.connection.realtime === false);
  check("elige GPT-5.6-Luna por defecto", created.model === "openai-codex-oauth/gpt-5.6-luna" && created.provider === "openai_codex_oauth");
  check("guarda el ciclo de vida en la conversación", doc.data.conversations[0].voice_calls?.[0]?.call_id === created.callId && doc.data.conversations[0].voice_calls[0].state === "connecting");
  check("GET devuelve el mismo estado", registry.get(created.callId).callId === created.callId && registry.get(created.callId).state === "connecting");
  check("impide dos llamadas activas en la misma sesión", expectError(() => registry.create({ sessionId: "session-1" }), 409, "call_exists"));
  check("rechaza una sesión que no existe", expectError(() => registry.create({ sessionId: "missing" }), 404, "session_not_found"));
  check("rechaza un motor con salto de línea", expectError(() => registry.create({ sessionId: "session-1", model: "x\ny" }), 400, "bad_model"));

  const active = registry.setState(created.callId, "active", { connection: { transport: "control", realtime: false } });
  check("puede pasar a active sin fingir que hay audio", active.state === "active" && active.connection.transport === "control" && active.connection.audio === false);
  check("persiste el cambio a active", doc.data.conversations[0].voice_calls[0].state === "active");
  const ended = registry.end(created.callId);
  check("colgar cierra transporte y marca ended", ended.state === "ended" && ended.connection.transport === "closed" && ended.connection.audio === false && Boolean(ended.endedAt));
  check("colgar repetido es idempotente", registry.end(created.callId).state === "ended");
  check("persiste el cierre", doc.data.conversations[0].voice_calls[0].state === "ended" && Boolean(doc.data.conversations[0].voice_calls[0].ended_at));
  check("permite una nueva llamada tras cerrar la anterior", registry.create({ sessionId: "session-1", model: "openrouter/test-model" }).provider === "openrouter");
  check("GET de call desconocida da 404 limpio", expectError(() => registry.get("call_missing"), 404, "call_not_found"));

  console.log(`\n==> ${passed}/${passed + failed} comprobaciones correctas`);
  process.exitCode = failed ? 1 : 0;
})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
