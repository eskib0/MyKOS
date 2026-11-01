// Motor falso para probar el controlador de modelos sin cargar CUDA ni Ollama.
const http = require("http");
const port = Number(process.argv[2] || 8092);

const json = (res, status, body) => {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Content-Length": Buffer.byteLength(payload), Connection: "close" });
  res.end(payload);
};

const server = http.createServer((req, res) => {
  if (req.url === "/health") return json(res, 200, { status: "ok" });
  if (req.method !== "POST" || req.url !== "/v1/chat/completions") return json(res, 404, { error: "not_found" });
  const chunks = [];
  req.on("data", (chunk) => chunks.push(chunk));
  req.on("end", () => {
    let body = {};
    try { body = JSON.parse(Buffer.concat(chunks).toString("utf8")); } catch {}
    json(res, 200, {
      id: "fake-model-response",
      object: "chat.completion",
      choices: [{ index: 0, message: { role: "assistant", content: `modelo-controlado:${body.model || "sin-modelo"}` }, finish_reason: "stop" }],
      usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
    });
  });
});

server.listen(port, "127.0.0.1", () => {
  if (process.send) process.send({ ready: true, port });
  else console.log(`fake model escuchando en ${port}`);
});
process.on("disconnect", () => server.close(() => process.exit(0)));
