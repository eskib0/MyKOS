// Prueba de que los proveedores remotos atraviesan el plano de modelo del Gateway.
const http = require("http");
const port = Number(process.argv[2] || 18795);
const workerPort = 3303;
const token = String(process.env.CONTROL_TOKEN || "");
let passed = 0;
let failed = 0;
function check(label, value, detail = "") { if (value) { passed += 1; console.log(`OK     ${label}${detail ? `  ${detail}` : ""}`); } else { failed += 1; console.log(`FALLA  ${label}${detail ? `  ${detail}` : ""}`); } }
function request(method, targetPort, pathname, body) {
  return new Promise((resolve, reject) => {
    const data = body === undefined ? null : Buffer.from(JSON.stringify(body), "utf8");
    const req = http.request({ hostname: "127.0.0.1", port: targetPort, method, path: pathname, headers: {
      Host: `127.0.0.1:${targetPort}`,
      ...(data ? { "Content-Type": "application/json", "Content-Length": data.length } : {}),
      ...(targetPort === port ? { "X-MyKOS-Control-Token": token } : {}),
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
  const worker = http.createServer((req, res) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      const payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      const response = { ok: true, done: true, tools_used: [], message: { role: "assistant", content: `fake:${payload.model}` } };
      const body = JSON.stringify(response);
      res.writeHead(200, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) });
      res.end(body);
    });
  });
  await new Promise((resolve) => worker.listen(workerPort, "127.0.0.1", resolve));
  try {
    const accepted = await request("POST", port, "/mykos-control/remote-model", {
      model: "openrouter/test-model", messages: [{ role: "user", content: "hola" }], conversation_id: "remote-test", generation: {},
    });
    check("el Gateway admite un proveedor remoto permitido", accepted.status === 200 && accepted.json?.message?.content === "fake:openrouter/test-model", `HTTP ${accepted.status}`);
    const blocked = await request("POST", port, "/mykos-control/remote-model", {
      model: "http://servidor-no-permitido", messages: [], conversation_id: "remote-test", generation: {},
    });
    check("el Gateway bloquea un proveedor remoto arbitrario", blocked.status === 400, `HTTP ${blocked.status}`);
  } finally {
    await new Promise((resolve) => worker.close(resolve));
  }
  console.log(`\n==> ${passed}/${passed + failed} comprobaciones correctas`);
  process.exitCode = failed ? 1 : 0;
})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });

