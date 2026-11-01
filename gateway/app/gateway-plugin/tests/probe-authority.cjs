// Prueba aislada de la autoridad de permisos/aprobaciones del Gateway.
const http = require("http");
const port = Number(process.argv[2] || 18795);
const token = String(process.env.CONTROL_TOKEN || "");
let passed = 0;
let failed = 0;

function check(label, condition, detail = "") {
  if (condition) { passed += 1; console.log(`OK     ${label}${detail ? `  ${detail}` : ""}`); }
  else { failed += 1; console.log(`FALLA  ${label}${detail ? `  ${detail}` : ""}`); }
}

function request(method, pathname, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const data = body === undefined ? null : Buffer.from(JSON.stringify(body), "utf8");
    const req = http.request({
      hostname: "127.0.0.1", port, method, path: pathname,
      headers: { Host: `127.0.0.1:${port}`, ...(data ? { "Content-Type": "application/json", "Content-Length": data.length } : {}), ...headers },
    }, (res) => {
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

(async () => {
  const auth = { "X-MyKOS-Control-Token": token };
  const action = { kind: "run_powershell", command: "Write-Output authority-test", cwd_root: "mykos", cwd_path: ".", timeout_seconds: 5 };
  check("se proporciona el token", token.length >= 16, `longitud=${token.length}`);

  const denied = await request("POST", "/mykos-control/authorize", { tool_name: action.kind, action, conversation_id: "authority-test" });
  check("la autorización sin token se rechaza", denied.status === 403, `HTTP ${denied.status}`);

  const needs = await request("POST", "/mykos-control/authorize", { tool_name: action.kind, action, conversation_id: "authority-test" }, auth);
  check("el Gateway decide que la acción necesita aprobación", needs.status === 200 && needs.json?.decision === "approval_required", `HTTP ${needs.status}`);

  const created = await request("POST", "/mykos-control/approval", {
    operation: "create", conversation_id: "authority-test", model: "test-model", tool_name: action.kind,
    action, messages: [{ role: "user", content: "prueba" }], generation: {}, supports_vision: false,
  }, auth);
  const approvalId = created.json?.approval?.id;
  check("la aprobación se guarda en el Gateway", created.status === 200 && Boolean(approvalId), `HTTP ${created.status}`);

  const listed = await request("POST", "/mykos-control/approval", { operation: "list", conversation_id: "authority-test" }, auth);
  check("la cola de aprobación se consulta desde el Gateway", listed.status === 200 && listed.json?.approvals?.some((item) => item.id === approvalId), `HTTP ${listed.status}`);

  const rejected = await request("POST", "/mykos-control/approval", { operation: "resolve", approval_id: approvalId, decision: "reject", permission_mode: "once" }, auth);
  check("el Gateway resuelve y audita el rechazo", rejected.status === 200 && rejected.json?.rejected === true, `HTTP ${rejected.status}`);

  const empty = await request("POST", "/mykos-control/approval", { operation: "list", conversation_id: "authority-test" }, auth);
  check("una aprobación resuelta desaparece de la cola", empty.status === 200 && empty.json?.approvals?.length === 0, `HTTP ${empty.status}`);

  const publicPermissions = await request("GET", "/api/permissions?conversation_id=authority-test");
  const publicApprovals = await request("GET", "/api/approvals?conversation_id=authority-test");
  check("la interfaz lee permisos desde el Gateway", publicPermissions.status === 200 && Array.isArray(publicPermissions.json?.permissions), `HTTP ${publicPermissions.status}`);
  check("la interfaz lee aprobaciones desde el Gateway", publicApprovals.status === 200 && Array.isArray(publicApprovals.json?.approvals), `HTTP ${publicApprovals.status}`);

  const context = await request("POST", "/mykos-control/context", {
    system_prompt: "Sistema de prueba",
    context: Array.from({ length: 30 }, (_, index) => ({ role: index % 2 ? "assistant" : "user", content: "x".repeat(400) })),
    generation: { options: { num_ctx: 2048, num_predict: 256 } },
  }, auth);
  check("la compactación del contexto la hace el Gateway", context.status === 200 && Array.isArray(context.json?.messages) && context.json?.context?.compacted === true, `HTTP ${context.status}`);

  console.log(`\n==> ${passed}/${passed + failed} comprobaciones correctas`);
  process.exitCode = failed ? 1 : 0;
})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
