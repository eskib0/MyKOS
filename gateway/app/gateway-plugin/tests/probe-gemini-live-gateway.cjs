// Integración de Gemini Live sin red externa: el backend falso entrega solo un
// token efímero y comprobamos que el Gateway no expone ninguna API key.
const http = require("http");

const port = Number(process.argv[2] || 18803);
const backendPort = Number(process.env.VOICE_BACKEND_PORT || 3303);
let passed = 0;
let failed = 0;
function check(label, value, detail = "") {
  if (value) { passed += 1; console.log(`OK     ${label}${detail ? `  ${detail}` : ""}`); }
  else { failed += 1; console.log(`FALLA  ${label}${detail ? `  ${detail}` : ""}`); }
}
function request(targetPort, method, pathname, body) {
  return new Promise((resolve, reject) => {
    const raw = body === undefined ? null : Buffer.from(JSON.stringify(body), "utf8");
    const req = http.request({ hostname: "127.0.0.1", port: targetPort, method, path: pathname, headers: {
      Host: `127.0.0.1:${targetPort}`,
      ...(raw ? { "Content-Type": "application/json", "Content-Length": String(raw.length) } : {}),
    }}, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        const text = Buffer.concat(chunks).toString("utf8");
        let json = null; try { json = JSON.parse(text); } catch {}
        resolve({ status: res.statusCode, text, json });
      });
    });
    req.on("error", reject);
    req.end(raw);
  });
}

(async () => {
  const mode = await request(port, "GET", "/api/voice/mode");
  check("informa que Gemini Live está disponible sin abrir sesión", mode.status === 200 && mode.json?.gemini?.available === true, JSON.stringify(mode.json?.gemini));

  const selected = await request(port, "POST", "/api/voice/mode", { mode: "gemini" });
  check("selecciona Gemini sin generar token", selected.status === 200 && selected.json?.mode === "gemini", JSON.stringify(selected.json));

  const conversation = await request(port, "POST", "/api/conversations/new", {});
  const sessionId = conversation.json?.conversation_id;
  check("crea una conversación temporal", conversation.status === 200 && typeof sessionId === "string");
  if (!sessionId) throw new Error("No se creó la conversación de prueba.");

  const prepared = await request(port, "POST", `/api/sessions/${encodeURIComponent(sessionId)}/gemini-live`, {});
  const callId = prepared.json?.call?.callId;
  const token = prepared.json?.transport?.token || "";
  check("prepara una llamada WebSocket Gemini", prepared.status === 201 && prepared.json?.transport?.type === "websocket" && prepared.json?.call?.provider === "gemini_api", JSON.stringify(prepared.json));
  check("solo devuelve token efímero, nunca una API key", token === "auth_tokens/test-ephemeral-token" && !/AIza[A-Za-z0-9_-]{20,}/.test(prepared.text));
  check("usa el endpoint WebSocket oficial v1beta", String(prepared.json?.transport?.endpoint || "").includes("v1beta.GenerativeService.BidiGenerateContentConstrained"));

  const tool = callId ? await request(port, "POST", `/api/calls/${encodeURIComponent(callId)}/gemini-tools`, {
    functionCalls: [{ id: "status-1", name: "get_local_status", args: {} }],
  }) : { status: 0 };
  check("el Gateway ejecuta una herramienta Gemini permitida en el backend privado", tool.status === 200 && tool.json?.functionResponses?.[0]?.response?.result?.machine === "fake-mykos", JSON.stringify(tool.json));

  const reminder = callId ? await request(port, "POST", `/api/calls/${encodeURIComponent(callId)}/gemini-tools`, {
    functionCalls: [{ id: "reminder-1", name: "create_reminder", args: { title: "Prueba", run_at: "2099-01-01T10:00:00+01:00" } }],
  }) : { status: 0 };
  check("un recordatorio de Gemini queda pendiente de aprobación", reminder.status === 200 && reminder.json?.functionResponses?.[0]?.response?.result?.pending_approval === true, JSON.stringify(reminder.json));

  const forbidden = callId ? await request(port, "POST", `/api/calls/${encodeURIComponent(callId)}/gemini-tools`, {
    functionCalls: [{ id: "shell-1", name: "run_powershell", args: { command: "whoami" } }],
  }) : { status: 0 };
  check("rechaza una herramienta Gemini fuera de la lista blanca", forbidden.status === 200 && forbidden.json?.functionResponses?.[0]?.response?.result?.ok === false, JSON.stringify(forbidden.json));

  const stats = await request(backendPort, "GET", "/__voice-stats");
  check("el token lo genera el backend privado una sola vez", stats.json?.geminiLiveTokens === 1, JSON.stringify(stats.json));
  check("las lecturas pasan por el backend y el recordatorio solo se prepara", stats.json?.geminiTools?.length === 1 && stats.json?.geminiPrepares?.length === 1, JSON.stringify(stats.json));

  if (callId) await request(port, "DELETE", `/api/calls/${encodeURIComponent(callId)}`);
  await request(port, "DELETE", `/api/conversations?id=${encodeURIComponent(sessionId)}`);
  console.log(`\n==> ${passed}/${passed + failed} comprobaciones correctas`);
  process.exitCode = failed ? 1 : 0;
})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
