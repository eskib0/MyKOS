// Backend falso para la prueba 5.4. Solo escucha en el puerto de la prueba y no toca el MyKOS real.
const http = require("http");
const os = require("os");
const path = require("path");
const fs = require("fs");

const port = Number(process.env.VOICE_BACKEND_PORT || 3299);
const gatewayPort = Number(process.env.VOICE_GATEWAY_PORT || 18798);
const tag = String(process.env.VOICE_TAG || "V54");
const tokenFile = path.join(os.homedir(), "mykos-gateway-test", "state-" + tag, "mykos", ".token");
const stats = { transcribe: 0, remoteModel: 0, tts: 0, geminiLiveTokens: 0, geminiTools: [], geminiPrepares: [], lastTranscriptBytes: 0, lastRemoteMessage: "", ttsPhrases: [] };

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

function send(res, status, body, headers = {}) {
  const raw = Buffer.from(JSON.stringify(body), "utf8");
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Content-Length": raw.length, Connection: "close", ...headers });
  res.end(raw);
}

function storeRequest(method, pathname, body) {
  return new Promise((resolve, reject) => {
    let token = "";
    try { token = fs.readFileSync(tokenFile, "utf8").trim(); } catch {}
    const raw = body === undefined ? null : Buffer.from(JSON.stringify(body), "utf8");
    const req = http.request({ hostname: "127.0.0.1", port: gatewayPort, method, path: pathname, headers: {
      Host: "127.0.0.1:" + gatewayPort,
      "X-MyKOS-Store-Token": token,
      ...(raw ? { "Content-Type": "application/json", "Content-Length": raw.length } : {}),
    }}, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        let json = null; try { json = JSON.parse(Buffer.concat(chunks).toString("utf8")); } catch {}
        resolve({ status: res.statusCode, json });
      });
    });
    req.on("error", reject);
    if (raw) req.end(raw); else req.end();
  });
}

async function conversations() {
  const result = await storeRequest("GET", "/mykos-store/conversations");
  if (result.status === 404) return { revision: 0, data: { conversations: [] } };
  if (result.status !== 200 || !result.json?.data?.conversations) throw new Error("no se pudo leer el almacén de conversaciones");
  return result.json;
}

async function putConversations(doc, data) {
  const result = await storeRequest("PUT", "/mykos-store/conversations", {
    data,
    expectedRevision: doc.revision || undefined,
    source: "fake-voice-backend",
    allowShrink: true,
  });
  if (result.status >= 300) throw new Error("fallo de escritura del almacén: " + result.status);
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url || "/", "http://127.0.0.1:" + port);
    if (req.method === "GET" && url.pathname === "/api/health") {
      send(res, 200, { service: "mykos-backend", pid: process.pid, ok: true });
      return;
    }
    if (req.method === "GET" && url.pathname === "/__voice-stats") {
      send(res, 200, { ...stats, ttsPhrases: [...stats.ttsPhrases] });
      return;
    }
    if (req.method === "POST" && url.pathname === "/api/conversations/new") {
      await readBody(req);
      const doc = await conversations();
      const id = "synthetic-voice-" + Date.now();
      const conversation = { id, title: "Prueba de voz sintética", messages: [] };
      await putConversations(doc, { ...doc.data, conversations: [...doc.data.conversations, conversation] });
      send(res, 200, { ok: true, conversation_id: id, conversation });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/conversations") {
      const doc = await conversations();
      send(res, 200, doc.data);
      return;
    }
    if (req.method === "DELETE" && url.pathname === "/api/conversations") {
      await readBody(req);
      const id = url.searchParams.get("id");
      const doc = await conversations();
      const before = doc.data.conversations.length;
      const rows = id ? doc.data.conversations.filter((item) => item.id !== id) : [];
      await putConversations(doc, { ...doc.data, conversations: rows });
      send(res, 200, { ok: true, deleted: rows.length !== before, id });
      return;
    }
    if (req.method === "POST" && url.pathname === "/mykos-control/transcribe") {
      const body = await readBody(req);
      stats.transcribe += 1;
      stats.lastTranscriptBytes = body.length;
      send(res, 200, { ok: true, text: "Hola desde audio sintético", engine: "fake-whisper" });
      return;
    }
    if (req.method === "POST" && url.pathname === "/mykos-control/remote-model") {
      const body = JSON.parse((await readBody(req)).toString("utf8") || "{}");
      const last = body.messages?.at(-1)?.content || "";
      stats.remoteModel += 1;
      stats.lastRemoteMessage = String(last);
      if (last === "interrumpe") await new Promise((resolve) => setTimeout(resolve, 600));
      send(res, 200, { ok: true, message: { role: "assistant", content: "Respuesta de Luna. Segunda frase." } });
      return;
    }
    if (req.method === "POST" && url.pathname === "/mykos-control/tts") {
      const body = JSON.parse((await readBody(req)).toString("utf8") || "{}");
      const phrase = String(body.text || "");
      stats.tts += 1;
      stats.ttsPhrases.push(phrase);
      send(res, 200, { ok: true, audio: Buffer.from("fake-wav:" + phrase, "utf8").toString("base64"), content_type: "audio/wav", engine: "fake-kokoro" });
      return;
    }
    if (req.method === "POST" && url.pathname === "/mykos-control/gemini-live/status") {
      await readBody(req);
      send(res, 200, { ok: true, available: true, error: "" });
      return;
    }
    if (req.method === "POST" && url.pathname === "/mykos-control/gemini-live/token") {
      const body = JSON.parse((await readBody(req)).toString("utf8") || "{}");
      if (body.model !== "gemini-3.8-live" || body.voice !== "Puck") {
        send(res, 400, { ok: false, error: "configuración Gemini Live inesperada" });
        return;
      }
      stats.geminiLiveTokens += 1;
      send(res, 200, { ok: true, token: "auth_tokens/test-ephemeral-token", expires_at: "2099-01-01T00:00:00Z", model: body.model, voice: body.voice });
      return;
    }
    if (req.method === "POST" && url.pathname === "/mykos-control/tool") {
      const body = JSON.parse((await readBody(req)).toString("utf8") || "{}");
      stats.geminiTools.push({ name: body.tool_name, arguments: body.arguments || {} });
      if (body.tool_name === "get_local_status") send(res, 200, { ok: true, machine: "fake-mykos", gpu: "fake-gpu" });
      else if (body.tool_name === "search_memory") send(res, 200, { ok: true, entries: [{ id: "memory-1", text: `resultado: ${body.arguments?.query || ""}` }] });
      else if (body.tool_name === "list_automations") send(res, 200, { ok: true, automations: [] });
      else send(res, 400, { ok: false, error: "herramienta de prueba no permitida" });
      return;
    }
    if (req.method === "POST" && url.pathname === "/mykos-control/prepare") {
      const body = JSON.parse((await readBody(req)).toString("utf8") || "{}");
      stats.geminiPrepares.push({ name: body.tool_name, arguments: body.arguments || {} });
      if (body.tool_name === "create_reminder") send(res, 200, { ok: true, action: { kind: "create_reminder", ...body.arguments } });
      else send(res, 400, { ok: false, error: "acción de prueba no permitida" });
      return;
    }
    send(res, 404, { ok: false, error: "not_found" });
  } catch (error) {
    send(res, 500, { ok: false, error: String(error?.message || error) });
  }
});
server.listen(port, "127.0.0.1", () => console.log("fake voice backend listening on " + port));
process.on("SIGTERM", () => server.close(() => process.exit(0)));
