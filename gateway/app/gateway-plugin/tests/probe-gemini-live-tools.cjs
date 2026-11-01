// Unitarias del puente Gemini Live -> Gateway. No abre WebSocket ni llama a Google.
const assert = require("assert");
const os = require("os");
const path = require("path");
const { pathToFileURL } = require("url");

let passed = 0;
function check(label, fn) {
  try { fn(); passed += 1; console.log(`OK     ${label}`); }
  catch (error) { console.error(`FALLA  ${label}\n${error.stack || error}`); process.exitCode = 1; }
}

(async () => {
  const repo = path.resolve(__dirname, "..", "..");
  const { GEMINI_LIVE_FUNCTION_DECLARATIONS, runGeminiLiveFunctionCalls } = await import(pathToFileURL(path.join(repo, "gateway-plugin", "mykos-ui", "gemini-live-tools.js")).href);
  const calls = [];
  const prepared = [];
  const approvals = [];
  const activeCall = { sessionId: "conversation-test", model: "gemini/gemini-3.8-live", provider: "gemini_api", state: "active" };
  const deps = {
    registry: { getInternal: (id) => id === "call-ok" ? activeCall : null },
    worker: {
      tool: async (name, args) => { calls.push({ name, args }); return { ok: true, name, args }; },
      prepare: async (name, args) => { prepared.push({ name, args }); return { ok: true, action: { kind: name, ...args } }; },
    },
    authority: { createApproval: (input) => { approvals.push(input); return { ok: true, approval: { id: "approval-1", expires_at: "2099-01-01T00:00:00Z" } }; } },
  };

  check("declara exactamente el lote limitado de cuatro herramientas", () => assert.deepEqual(GEMINI_LIVE_FUNCTION_DECLARATIONS.map((x) => x.name), ["get_local_status", "search_memory", "list_automations", "create_reminder"]));
  const read = await runGeminiLiveFunctionCalls("call-ok", [{ id: "status-1", name: "get_local_status", args: {} }, { id: "memory-1", name: "search_memory", args: { query: "notas", max_results: 6 } }], deps);
  check("ejecuta solo lecturas permitidas y responde con el protocolo de Gemini", () => {
    assert.equal(read.functionResponses.length, 2);
    assert.equal(read.functionResponses[0].response.result.ok, true);
    assert.deepEqual(calls, [{ name: "get_local_status", args: {} }, { name: "search_memory", args: { query: "notas", max_results: 6 } }]);
  });
  const invalid = await runGeminiLiveFunctionCalls("call-ok", [{ id: "bad-1", name: "run_powershell", args: { command: "whoami" } }], deps);
  check("rechaza herramientas fuera de la lista blanca sin ejecutarlas", () => assert.equal(invalid.functionResponses[0].response.result.ok, false));
  const reminder = await runGeminiLiveFunctionCalls("call-ok", [{ id: "rem-1", name: "create_reminder", args: { title: "Pan", run_at: "2099-01-01T10:00:00+01:00" } }], deps);
  check("un recordatorio crea una aprobación y no ejecuta la acción", () => {
    assert.equal(prepared.length, 1);
    assert.equal(approvals.length, 1);
    assert.equal(approvals[0].conversation_id, "conversation-test");
    assert.equal(reminder.functionResponses[0].response.result.pending_approval, true);
  });
  await assert.rejects(() => runGeminiLiveFunctionCalls("call-missing", [{ id: "status-2", name: "get_local_status", args: {} }], deps));
  check("no acepta llamadas que no estén activas y vinculadas a Gemini", () => {});
  console.log(`\n==> ${passed}/5 comprobaciones correctas`);
})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
