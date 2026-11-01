// Uso: CONTROL_TOKEN=<token> node probe-model-control.cjs <puertoGateway>
const fs = require("fs");
const http = require("http");

const port = Number(process.argv[2] || 18795);
const token = String(process.env.CONTROL_TOKEN || "");
const auditFile = process.env.CONTROL_AUDIT_FILE || "";
let passed = 0;
let failed = 0;

function check(label, condition, detail = "") {
  if (condition) { passed += 1; console.log(`OK     ${label}${detail ? `  ${detail}` : ""}`); }
  else { failed += 1; console.log(`FALLA  ${label}${detail ? `  ${detail}` : ""}`); }
}

function request(method, pathname, body) {
  return new Promise((resolve, reject) => {
    const data = body === undefined ? null : Buffer.from(JSON.stringify(body), "utf8");
    const req = http.request({
      hostname: "127.0.0.1", port, method, path: pathname,
      headers: { Host: `127.0.0.1:${port}`, "X-MyKOS-Control-Token": token, ...(data ? { "Content-Type": "application/json", "Content-Length": data.length } : {}) },
    }, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        const text = Buffer.concat(chunks).toString("utf8");
        let json;
        try { json = JSON.parse(text); } catch { json = null; }
        resolve({ status: res.statusCode, json, text });
      });
    });
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

(async () => {
  let health;
  const deadline = Date.now() + 60_000;
  do {
    health = await request("GET", "/mykos-health");
    if (health.status === 200) break;
    await new Promise((resolve) => setTimeout(resolve, 500));
  } while (Date.now() < deadline);
  check("Gateway y backend de prueba están listos", health.status === 200, `HTTP ${health.status}`);

  const response = await request("POST", "/mykos-control/model", {
    provider: "llama_cpp",
    payload: { model: "mykos-cuda", messages: [{ role: "user", content: "prueba" }], stream: false },
  });
  const message = response.json?.choices?.[0]?.message;
  check("el Gateway selecciona el proveedor llama.cpp y devuelve su respuesta", response.status === 200 && message?.content === "modelo-controlado:mykos-cuda", `HTTP ${response.status}`);
  check("el Gateway no arranca un proceso llama.cpp falso si ya hay motor sano", health.json?.control?.llamaProcess === null, JSON.stringify(health.json?.control || {}));

  if (auditFile && fs.existsSync(auditFile)) {
    const rows = fs.readFileSync(auditFile, "utf8").trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
    check("el diario registra la petición y el resultado del modelo", rows.some((row) => row.event === "control_request" && row.operation === "model" && row.provider === "llama_cpp") && rows.some((row) => row.event === "control_result" && row.operation === "model" && row.ok === true));
  } else check("el diario del modelo está disponible", false, auditFile || "sin ruta");

  console.log(`\n==> ${passed}/${passed + failed} comprobaciones correctas`);
  process.exitCode = failed ? 1 : 0;
})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
