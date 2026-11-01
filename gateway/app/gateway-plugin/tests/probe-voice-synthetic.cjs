// Integración 5.4: audio sintético por el Gateway, Luna/TTS falsos y cierre de llamada.
const http = require("http");

const port = Number(process.argv[2] || 18798);
const backendPort = Number(process.env.VOICE_BACKEND_PORT || 3299);
let passed = 0;
let failed = 0;
function check(label, value, detail = "") {
  if (value) { passed += 1; console.log("OK     " + label + (detail ? "  " + detail : "")); }
  else { failed += 1; console.log("FALLA  " + label + (detail ? "  " + detail : "")); }
}
function wait(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
function requestTo(targetPort, method, pathname, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const data = body === undefined ? null : Buffer.isBuffer(body) ? body : Buffer.from(typeof body === "string" ? body : JSON.stringify(body), "utf8");
    const req = http.request({ hostname: "127.0.0.1", port: targetPort, method, path: pathname, headers: {
      Host: "127.0.0.1:" + targetPort,
      ...(data && !headers["Content-Type"] ? { "Content-Type": "application/json" } : {}),
      ...(data ? { "Content-Length": data.length } : {}), ...headers,
    }}, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        const raw = Buffer.concat(chunks);
        let json = null; try { json = JSON.parse(raw.toString("utf8")); } catch {}
        resolve({ status: res.statusCode, headers: res.headers, json, raw });
      });
    });
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}
const request = (method, pathname, body, headers) => requestTo(port, method, pathname, body, headers);

(async () => {
  const created = await request("POST", "/api/conversations/new", {});
  const sessionId = created.json?.conversation_id;
  check("crea sesión temporal por el Gateway", created.status === 200 && typeof sessionId === "string");
  if (!sessionId) throw new Error("no se creó la sesión sintética");

  const started = await request("POST", "/api/sessions/" + encodeURIComponent(sessionId) + "/calls", { model: "openai-codex-oauth/gpt-5.6-luna" });
  const callId = started.json?.callId;
  check("crea la llamada en el Gateway", started.status === 201 && typeof callId === "string");

  const wav = Buffer.from("RIFFsynthetic-wav", "ascii");
  const transcription = await request("POST", "/api/transcribe", wav, { "Content-Type": "audio/wav" });
  check("el audio sintético atraviesa la frontera de transcripción", transcription.status === 200 && transcription.json?.engine === "fake-whisper" && transcription.json?.text === "Hola desde audio sintético");

  const turn = await request("POST", "/api/calls/" + encodeURIComponent(callId) + "/turn", { turnId: "synthetic-1", transcript: transcription.json.text });
  check("el turno usa la transcripción y responde", turn.status === 200 && turn.json?.text === "Respuesta de Luna. Segunda frase.");
  check("devuelve dos fragmentos de audio TTS", turn.json?.audio?.length === 2 && turn.json.audio.every((item) => item.engine === "fake-kokoro"));

  const stats = await requestTo(backendPort, "GET", "/__voice-stats");
  check("el backend falso recibió Whisper, Luna y Kokoro", stats.status === 200 && stats.json?.transcribe === 1 && stats.json?.remoteModel === 1 && stats.json?.tts === 2 && stats.json?.lastRemoteMessage === "Hola desde audio sintético");

  const interruptionPromise = request("POST", "/api/calls/" + encodeURIComponent(callId) + "/turn", { turnId: "synthetic-interrupt", transcript: "interrumpe" });
  await wait(60);
  const interrupted = await request("POST", "/api/calls/" + encodeURIComponent(callId) + "/interrupt", {});
  const interruptedTurn = await interruptionPromise;
  check("interrumpir cancela el modelo pendiente", interrupted.status === 200 && interrupted.json?.state === "interrupted" && interruptedTurn.status === 409 && interruptedTurn.json?.error === "turn_interrupted");

  const ended = await request("DELETE", "/api/calls/" + encodeURIComponent(callId));
  check("colgar cierra la llamada y el transporte", ended.status === 200 && ended.json?.state === "ended" && ended.json?.connection?.transport === "closed");
  const listed = await request("GET", "/api/conversations");
  const row = listed.json?.conversations?.find((item) => item.id === sessionId);
  check("la conversación conserva el turno completado y el intento interrumpido", row?.messages?.map((item) => item.role).join(",") === "user,assistant,user");
  const deleted = await request("DELETE", "/api/conversations?id=" + encodeURIComponent(sessionId));
  check("elimina la sesión temporal", deleted.status === 200 && deleted.json?.deleted === true);

  console.log("\n==> " + passed + "/" + (passed + failed) + " comprobaciones correctas");
  process.exitCode = failed ? 1 : 0;
})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
