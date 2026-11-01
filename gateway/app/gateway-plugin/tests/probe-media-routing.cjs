// Prueba del enrutamiento de voz: la interfaz usa /api/* pero el Gateway
// reenvía al endpoint interno autenticado del trabajador.
const http = require("http");
const port = Number(process.argv[2] || 18795);
const workerPort = 3304;
let passed = 0;
let failed = 0;
function check(label, value, detail = "") { if (value) { passed += 1; console.log(`OK     ${label}${detail ? `  ${detail}` : ""}`); } else { failed += 1; console.log(`FALLA  ${label}${detail ? `  ${detail}` : ""}`); } }
function request(method, targetPort, pathname, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const data = body === undefined ? null : Buffer.from(typeof body === "string" ? body : JSON.stringify(body), "utf8");
    const req = http.request({ hostname: "127.0.0.1", port: targetPort, method, path: pathname, headers: {
      Host: `127.0.0.1:${targetPort}`,
      ...(data ? { "Content-Type": "application/json", "Content-Length": data.length } : {}), ...headers,
    }}, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => { const text = Buffer.concat(chunks).toString("utf8"); let json; try { json = JSON.parse(text); } catch { json = null; } resolve({ status: res.statusCode, json }); });
    });
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

(async () => {
  const seen = [];
  const worker = http.createServer((req, res) => {
    seen.push({ path: req.url, token: Boolean(req.headers["x-mykos-control-token"]) });
    const body = JSON.stringify({ ok: true, audio: "ZmFrZQ==", content_type: "audio/wav", engine: "fake" });
    res.writeHead(200, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) });
    res.end(body);
  });
  await new Promise((resolve) => worker.listen(workerPort, "127.0.0.1", resolve));
  try {
    const result = await request("POST", port, "/api/tts", { text: "hola", voice: "em_alex" });
    check("la interfaz puede pedir voz a través del Gateway", result.status === 200 && result.json?.content_type === "audio/wav", `HTTP ${result.status}`);
    check("el Gateway usa la ruta privada y el token", seen.some((item) => item.path === "/mykos-control/tts" && item.token));
  } finally {
    await new Promise((resolve) => worker.close(resolve));
  }
  console.log(`\n==> ${passed}/${passed + failed} comprobaciones correctas`);
  process.exitCode = failed ? 1 : 0;
})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });

