// Prueba aislada del controlador Realtime de MyKOS: jamás usa red ni credenciales reales.
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { pathToFileURL } = require("url");

let passed = 0;
function ok(label, condition) { assert.ok(condition, label); passed += 1; console.log(`OK     ${label}`); }

(async () => {
  const repo = path.resolve(__dirname, "..", "..");
  const { MyKOSRealtimeController, RealtimeError, validateSdp, finishAnswerSdp, usageLimitMessage } = await import(pathToFileURL(path.join(repo, "gateway-plugin", "mykos-ui", "realtime.js")).href);
  const { CallRegistry } = await import(pathToFileURL(path.join(repo, "gateway-plugin", "mykos-ui", "calls.js")).href);
  const sdp = "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=MyKOS test\r\nt=0 0\r\n";
  ok("acepta una oferta SDP mínima sin perder su terminador de línea", validateSdp(sdp) === sdp && validateSdp(sdp).endsWith("\r\n"));
  assert.throws(() => validateSdp("texto"), (error) => error instanceof RealtimeError && error.code === "bad_sdp");
  ok("rechaza SDP inválido", true);

  const calls = new Map();
  const registry = {
    create({ sessionId, model }) { const call = { callId: "call-test", sessionId, model, state: "connecting" }; calls.set(call.callId, call); return call; },
    setState(id, state, extra = {}) { const call = calls.get(id); Object.assign(call, { state, ...extra }); return call; },
  };
  const fixtureDir = fs.mkdtempSync(path.join(os.tmpdir(), "mykos-realtime-"));
  const oauthFile = path.join(fixtureDir, "auth.json");
  fs.writeFileSync(oauthFile, JSON.stringify({
    auth_mode: "chatgpt",
    tokens: { access_token: "test-mykos-oauth-token", account_id: "account-mykos-test" },
  }));
  const requests = [];
  const controller = new MyKOSRealtimeController({
    registry,
    config: { enabled: true, apiBase: "https://example.invalid", model: "gpt-live-1-codex", voice: "cove", oauthFile, safetyIdentifier: "mykos-test", timeoutMs: 5000 },
    fetchImpl: async (url, init) => {
      requests.push({ url, init });
      return new Response("v=0\r\nanswer\r\na=ice-pwd:abc\r\n", { status: 201, headers: { "openai-session-id": "live_test" } });
    },
  });
  const result = await controller.create({ sessionId: "session-test", sdp });
  ok("crea gpt-live-1-codex por el contrato OAuth independiente de MyKOS", requests[0].url.startsWith("https://chatgpt.com/backend-api/codex/realtime/calls?"));
  const requestPayload = JSON.parse(requests[0].init.body);
  ok("envía el contrato GPT-Live/Codex y no filtra el OAuth", requestPayload.sdp === sdp && requestPayload.session.model === "gpt-live-1-codex" && requestPayload.session.delegation?.type === "client" && requestPayload.session.audio?.output?.voice === "cove" && !requests[0].init.body.includes("test-mykos-oauth-token") && requests[0].init.headers["OpenAI-Alpha"] === "quicksilver=v2");
  ok("devuelve solo SDP de respuesta y sesión", result.transport.sdp === "v=0\r\nanswer\r\na=ice-pwd:abc\r\n" && result.session.id === "live_test");
  ok("la respuesta SDP conserva el CRLF final tras a=ice-pwd (Chrome la rechaza sin él)", result.transport.sdp.endsWith("a=ice-pwd:abc\r\n"));
  ok("finishAnswerSdp añade un único CRLF si falta y rechaza vacío", finishAnswerSdp("v=0\r\na=ice-pwd:x") === "v=0\r\na=ice-pwd:x\r\n" && finishAnswerSdp("v=0\r\na=ice-pwd:x\r\n\r\n") === "v=0\r\na=ice-pwd:x\r\n" && finishAnswerSdp("  \r\n") === "" && finishAnswerSdp(undefined) === "");
  ok("marca la llamada de MyKOS como WebRTC activa", result.call.state === "active" && result.call.connection.realtime === true);

  process.env.MYKOS_REALTIME_API_KEY = "test-only-key";
  const apiRequests = [];
  const publicApi = new MyKOSRealtimeController({
    registry,
    config: { enabled: true, apiBase: "https://example.invalid", model: "gpt-live-1", voice: "marin", credentialFile: "", safetyIdentifier: "mykos-test", timeoutMs: 5000 },
    fetchImpl: async (url, init) => {
      apiRequests.push({ url, init });
      return new Response(JSON.stringify({ session: { id: "live_public" }, transport: { type: "webrtc", sdp: "v=0\r\npublic-answer\r\na=ice-pwd:abc\r\n" } }), { status: 201, headers: { "Content-Type": "application/json" } });
    },
  });
  const publicResult = await publicApi.create({ sessionId: "session-public", sdp });
  const publicPayload = JSON.parse(apiRequests[0].init.body);
  ok("mantiene el contrato Platform separado para gpt-live-1", apiRequests[0].url === "https://example.invalid/v1/live/sessions" && publicPayload.transport?.type === "webrtc" && publicPayload.session.model === "gpt-live-1" && !apiRequests[0].init.body.includes("test-only-key") && publicResult.session.id === "live_public" && publicResult.transport.sdp.endsWith("a=ice-pwd:abc\r\n"));

  // Cuota de suscripción agotada: 429 usage_limit_reached con hora de restablecimiento.
  const limitBody = JSON.stringify({ error: { type: "usage_limit_reached", message: "The usage limit has been reached", plan_type: "plus", resets_at: 1790462270, resets_in_seconds: 10781 } });
  const limited = new MyKOSRealtimeController({
    registry,
    config: { enabled: true, apiBase: "https://example.invalid", model: "gpt-live-1-codex", voice: "cove", oauthFile, safetyIdentifier: "mykos-test", timeoutMs: 5000 },
    fetchImpl: async () => new Response(limitBody, { status: 429, headers: { "content-type": "application/json" } }),
  });
  await assert.rejects(() => limited.create({ sessionId: "session-limit", sdp }), (error) => error instanceof RealtimeError && error.status === 429 && error.code === "realtime_usage_limit" && /Se restablece (el 27\/09 )?a las 00:37\.$/.test(error.message) && !error.message.includes("plus") && !error.message.includes("The usage limit"));
  ok("cuota agotada: 429 realtime_usage_limit con la hora de restablecimiento, sin el cuerpo del proveedor", true);
  const noon = Date.UTC(2026, 8, 27, 9, 0, 0);
  ok("mismo día: omite la fecha y sin hora usa un texto genérico", usageLimitMessage(429, JSON.stringify({ error: { resets_at: Math.floor(noon / 1000) + 3600 } }), noon) === "Límite de uso de ChatGPT alcanzado. Se restablece a las 12:00." && usageLimitMessage(429, "no json") === "Límite de uso de ChatGPT alcanzado. Inténtalo más tarde." && usageLimitMessage(500, "{}") === "");

  const disabled = new MyKOSRealtimeController({ registry, config: { enabled: false }, fetchImpl: async () => { throw new Error("no debe llamar"); } });
  await assert.rejects(() => disabled.create({ sessionId: "x", sdp }), (error) => error instanceof RealtimeError && error.code === "realtime_disabled");
  ok("permanece apagado por defecto", true);

  const document = { revision: 1, data: { conversations: [{ id: "session-transcript", messages: [] }] } };
  const store = { get: () => document, put: (_name, data, options) => { assert.equal(options.expectedRevision, document.revision); document.revision += 1; document.data = data; } };
  const transcripts = new CallRegistry({ store, isActive: () => true });
  const transcriptCall = transcripts.create({ sessionId: "session-transcript" });
  const firstTranscript = transcripts.appendTranscript(transcriptCall.callId, { role: "user", text: "Hola", entryId: "evt_1" });
  const duplicateTranscript = transcripts.appendTranscript(transcriptCall.callId, { role: "user", text: "Hola", entryId: "evt_1" });
  ok("persiste transcripciones Realtime en la conversación de MyKOS", firstTranscript.saved && document.data.conversations[0].messages[0].content === "Hola");
  ok("no duplica eventos Realtime repetidos", duplicateTranscript.duplicate && document.data.conversations[0].messages.length === 1);
  delete process.env.MYKOS_REALTIME_API_KEY;
  fs.rmSync(fixtureDir, { recursive: true, force: true });
  console.log(`\n==> ${passed} comprobaciones correctas`);
})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
