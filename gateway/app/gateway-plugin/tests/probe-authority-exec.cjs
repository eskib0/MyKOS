// Prueba aislada del recorrido aprobación -> Gateway -> trabajador Python.
const http = require("http");
const port = Number(process.argv[2] || 18795);
const token = String(process.env.CONTROL_TOKEN || "");

function request(method, pathname, body) {
  return new Promise((resolve, reject) => {
    const data = body === undefined ? null : Buffer.from(JSON.stringify(body), "utf8");
    const req = http.request({ hostname: "127.0.0.1", port, method, path: pathname, headers: {
      Host: `127.0.0.1:${port}`, ...(data ? { "Content-Type": "application/json", "Content-Length": data.length } : {}),
      "X-MyKOS-Control-Token": token,
    }}, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        const text = Buffer.concat(chunks).toString("utf8");
        let json; try { json = JSON.parse(text); } catch { json = null; }
        resolve({ status: res.statusCode, json, text });
      });
    });
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

let passed = 0;
let failed = 0;
function check(label, value, detail = "") {
  if (value) { passed += 1; console.log(`OK     ${label}${detail ? `  ${detail}` : ""}`); }
  else { failed += 1; console.log(`FALLA  ${label}${detail ? `  ${detail}` : ""}`); }
}

(async () => {
  const deadline = Date.now() + 60_000;
  let health;
  do {
    health = await request("GET", "/mykos-health");
    if (health.status === 200 && health.json?.backend?.up) break;
    await new Promise((resolve) => setTimeout(resolve, 500));
  } while (Date.now() < deadline);
  if (!(health?.status === 200 && health.json?.backend?.up)) {
    console.log(`FALLA  el backend supervisado está listo  HTTP ${health?.status || 0}`);
    process.exitCode = 1;
    return;
  }
  const action = { kind: "run_powershell", command: "Write-Output phase3-gateway-execution", cwd_root: "mykos", cwd_path: ".", timeout_seconds: 10 };
  const created = await request("POST", "/mykos-control/approval", {
    operation: "create", conversation_id: "authority-exec-test", model: "test-model", tool_name: action.kind,
    action, messages: [{ role: "user", content: "ejecuta la prueba" }], generation: {}, supports_vision: false,
  });
  const id = created.json?.approval?.id;
  check("se crea una aprobación para el trabajador", created.status === 200 && Boolean(id), `HTTP ${created.status}`);

  const resolved = await request("POST", "/mykos-control/approval", { operation: "resolve", approval_id: id, decision: "approve", permission_mode: "once" });
  check("el Gateway resuelve la aprobación", resolved.status === 200 && resolved.json?.approved === true, `HTTP ${resolved.status}`);
  check("el trabajador solo ejecuta después de la decisión del Gateway", resolved.json?.action_result?.ok === true && String(resolved.json?.action_result?.stdout || "").includes("phase3-gateway-execution"));

  const audit = await request("POST", "/mykos-control/permissions", { operation: "audit", conversation_id: "authority-exec-test", limit: 20 });
  const events = Array.isArray(audit.json?.audit) ? audit.json.audit.map((entry) => entry.event) : [];
  check("el Gateway conserva la auditoría del ciclo", audit.status === 200 && events.includes("approval_approved") && events.includes("execution_succeeded"));

  console.log(`\n==> ${passed}/${passed + failed} comprobaciones correctas`);
  process.exitCode = failed ? 1 : 0;
})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
