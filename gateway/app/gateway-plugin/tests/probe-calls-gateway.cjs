// Integración del contrato de llamadas contra un Gateway desechable con el backend real y almacén de prueba.
const http = require("http");
const port = Number(process.argv[2] || 18795);
let passed = 0;
let failed = 0;
function check(label, value, detail = "") { if (value) { passed += 1; console.log(`OK     ${label}${detail ? `  ${detail}` : ""}`); } else { failed += 1; console.log(`FALLA  ${label}${detail ? `  ${detail}` : ""}`); } }
function request(method, pathname, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const data = body === undefined ? null : Buffer.from(typeof body === "string" ? body : JSON.stringify(body), "utf8");
    const req = http.request({ hostname: "127.0.0.1", port, method, path: pathname, headers: {
      Host: `127.0.0.1:${port}`,
      ...(data ? { "Content-Type": "application/json", "Content-Length": data.length } : {}), ...headers,
    }}, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        const text = Buffer.concat(chunks).toString("utf8");
        let json = null; try { json = JSON.parse(text); } catch {}
        resolve({ status: res.statusCode, headers: res.headers, json, text });
      });
    });
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}
// Para el modo streaming: no se espera a 'end', se van recogiendo las líneas NDJSON
// a medida que llegan (cada res.write() del servidor debe verse como un chunk aparte).
function requestStreamingLines(method, pathname, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const data = body === undefined ? null : Buffer.from(typeof body === "string" ? body : JSON.stringify(body), "utf8");
    const req = http.request({ hostname: "127.0.0.1", port, method, path: pathname, headers: {
      Host: `127.0.0.1:${port}`,
      ...(data ? { "Content-Type": "application/json", "Content-Length": data.length } : {}), ...headers,
    }}, (res) => {
      let buffer = "";
      const lines = [];
      res.on("data", (chunk) => {
        buffer += chunk.toString("utf8");
        let idx;
        while ((idx = buffer.indexOf("\n")) >= 0) {
          const raw = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 1);
          if (!raw.trim()) continue;
          try { lines.push(JSON.parse(raw)); } catch { lines.push({ _parse_error: raw }); }
        }
      });
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, lines }));
    });
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

(async () => {
  let created = await request("POST", "/api/conversations/new", {});
  for (let attempt = 0; attempt < 20 && created.status === 503; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 500));
    created = await request("POST", "/api/conversations/new", {});
  }
  const sessionId = created.json?.conversation_id || created.json?.conversation?.id || created.json?.id;
  check("crea una sesión de prueba", created.status === 200 && typeof sessionId === "string" && sessionId.length > 0, `HTTP ${created.status}`);
  if (!sessionId) throw new Error("el backend no devolvió sessionId");

  const start = await request("POST", `/api/sessions/${encodeURIComponent(sessionId)}/calls`, { model: "openai-codex-oauth/gpt-5.6-luna" });
  check("POST calls lo resuelve el Gateway", start.status === 201 && start.json?.ok === true, `HTTP ${start.status}`);
  const callId = start.json?.callId;
  check("devuelve callId y sessionId", typeof callId === "string" && start.json?.sessionId === sessionId);
  check("la llamada empieza en connecting y sin audio", start.json?.state === "connecting" && start.json?.connection?.audio === false);
  check("elige GPT-5.6-Luna", start.json?.model === "openai-codex-oauth/gpt-5.6-luna" && start.json?.provider === "openai_codex_oauth");

  const status = await request("GET", `/api/calls/${encodeURIComponent(callId)}`);
  check("GET callId devuelve el estado", status.status === 200 && status.json?.callId === callId && status.json?.state === "connecting");
  const emptyTurn = await request("POST", `/api/calls/${encodeURIComponent(callId)}/turn`, { turnId: "empty", transcript: "" });
  check("un turno sin transcripción se rechaza sin llamar al modelo", emptyTurn.status === 400 && emptyTurn.json?.error === "empty_transcript");

  // Modo streaming (opt-in con stream:true): sin modelo real disponible en esta prueba
  // desechable, se comprueba que el error llega como línea NDJSON "type":"error" en
  // vez de romper el contrato clásico; el camino sin stream de arriba queda intacto.
  const emptyTurnStream = await requestStreamingLines("POST", `/api/calls/${encodeURIComponent(callId)}/turn`, { turnId: "empty-stream", transcript: "", stream: true });
  check(
    "el modo streaming responde NDJSON y manda el error como línea, no como 400",
    emptyTurnStream.status === 200
      && String(emptyTurnStream.headers["content-type"] || "").includes("application/x-ndjson")
      && emptyTurnStream.lines.length === 1
      && emptyTurnStream.lines[0].type === "error"
      && emptyTurnStream.lines[0].error === "empty_transcript",
  );
  const interrupted = await request("POST", `/api/calls/${encodeURIComponent(callId)}/interrupt`, {});
  check("POST interrupt lo resuelve el Gateway", interrupted.status === 200 && interrupted.json?.state === "interrupted");
  const duplicate = await request("POST", `/api/sessions/${encodeURIComponent(sessionId)}/calls`, {});
  check("impide dos llamadas activas en una sesión", duplicate.status === 409 && duplicate.json?.error === "call_exists");
  const missingSession = await request("POST", "/api/sessions/no-existe/calls", {});
  check("rechaza una sesión inexistente", missingSession.status === 404 && missingSession.json?.error === "session_not_found");
  const oversized = await request("POST", `/api/sessions/${encodeURIComponent(sessionId)}/calls`, JSON.stringify({ model: "x".repeat(17000) }));
  check("limita un cuerpo de llamada grande", oversized.status === 413);

  const ended = await request("DELETE", `/api/calls/${encodeURIComponent(callId)}`);
  check("DELETE callId cuelga y cierra transporte", ended.status === 200 && ended.json?.state === "ended" && ended.json?.connection?.transport === "closed");
  const endedAgain = await request("DELETE", `/api/calls/${encodeURIComponent(callId)}`);
  check("colgar repetido es idempotente", endedAgain.status === 200 && endedAgain.json?.state === "ended");
  const after = await request("GET", `/api/calls/${encodeURIComponent(callId)}`);
  check("el estado final permanece consultable", after.status === 200 && after.json?.state === "ended");
  const unknown = await request("GET", "/api/calls/call_missing");
  check("callId desconocido da 404 limpio", unknown.status === 404 && unknown.json?.error === "call_not_found");

  const conversations = await request("GET", "/api/conversations");
  check("la sesión temporal queda en el almacén", conversations.status === 200 && conversations.json?.conversations?.some((item) => item.id === sessionId));
  const deleted = await request("DELETE", `/api/conversations?id=${encodeURIComponent(sessionId)}`);
  check("borra la sesión temporal de la prueba", deleted.status === 200 && deleted.json?.deleted === true);

  console.log(`\n==> ${passed}/${passed + failed} comprobaciones correctas`);
  process.exitCode = failed ? 1 : 0;
})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
