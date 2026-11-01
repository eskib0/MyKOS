// Prueba del plano interno de control de fase 3.
// Uso: CONTROL_TOKEN=<token> node probe-control.cjs <puertoGateway>

const fs = require("fs");
const http = require("http");
const path = require("path");

const port = Number(process.argv[2] || 18795);
const token = String(process.env.CONTROL_TOKEN || "");
const auditFile = process.env.CONTROL_AUDIT_FILE || "";
let passed = 0;
let failed = 0;

function check(label, condition, detail = "") {
  if (condition) {
    passed += 1;
    console.log(`OK     ${label}${detail ? `  ${detail}` : ""}`);
  } else {
    failed += 1;
    console.log(`FALLA  ${label}${detail ? `  ${detail}` : ""}`);
  }
}

function request(method, pathname, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const data = body === undefined ? null : Buffer.from(JSON.stringify(body), "utf8");
    const req = http.request({
      hostname: "127.0.0.1",
      port,
      method,
      path: pathname,
      headers: {
        Host: `127.0.0.1:${port}`,
        ...(data ? { "Content-Type": "application/json", "Content-Length": data.length } : {}),
        ...headers,
      },
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
  check("se proporciona el token de prueba", token.length >= 16, `longitud=${token.length}`);
  let health;
  const healthDeadline = Date.now() + 60_000;
  do {
    health = await request("GET", "/mykos-health");
    if (health.status === 200) break;
    await new Promise((resolve) => setTimeout(resolve, 500));
  } while (Date.now() < healthDeadline);
  check("/mykos-health declara el controlador del Gateway", health.status === 200 && health.json?.control?.owner === "mykos-gateway", `HTTP ${health.status}`);

  const denied = await request("GET", "/mykos-control/status");
  check("el plano de control rechaza una petición sin token", denied.status === 403, `HTTP ${denied.status}`);

  const status = await request("GET", "/mykos-control/status", undefined, { "X-MyKOS-Control-Token": token });
  check("el token correcto permite consultar el controlador", status.status === 200 && status.json?.control === "mykos-gateway", `HTTP ${status.status}`);

  const tool = await request("POST", "/mykos-control/tool", {
    tool_name: "list_allowed_roots",
    arguments: {},
  }, { "X-MyKOS-Control-Token": token });
  check("una herramienta de lectura atraviesa el Gateway y devuelve raíces", tool.status === 200 && tool.json?.ok === true && Array.isArray(tool.json?.roots), `HTTP ${tool.status}`);

  const action = await request("POST", "/mykos-control/action", {
    conversation_id: "phase3-control-test",
    authorization: {},
    action: {
      kind: "run_powershell",
      command: "Write-Output phase3-control-test",
      cwd_root: "mykos",
      cwd_path: "",
      timeout_seconds: 5,
    },
  }, { "X-MyKOS-Control-Token": token });
  check("una acción de shell sin autorización no atraviesa el Gateway", action.status === 403 && action.json?.error === "action_not_authorized", `HTTP ${action.status}`);

  if (auditFile && fs.existsSync(auditFile)) {
    const lines = fs.readFileSync(auditFile, "utf8").trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
    check("el diario del Gateway registra solicitud y resultado de herramienta", lines.some((row) => row.event === "control_request" && row.operation === "tool") && lines.some((row) => row.event === "control_result" && row.operation === "tool" && row.ok === true));
    check("el diario del Gateway registra solicitud y rechazo de acción", lines.some((row) => row.event === "control_request" && row.operation === "action") && lines.some((row) => row.event === "permission_denied" && row.action === "run_powershell" && row.ok === false));
  } else {
    check("el diario del Gateway está disponible para la prueba", false, auditFile || "sin ruta");
  }

  console.log(`\n==> ${passed}/${passed + failed} comprobaciones correctas`);
  process.exitCode = failed ? 1 : 0;
})().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
