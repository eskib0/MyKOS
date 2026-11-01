// Uso: node probe-activity.cjs
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

(async () => {
  let now = Date.parse("2026-09-27T18:00:00.000Z");
  const mod = await import(pathToFileURL(path.join(__dirname, "..", "mykos-ui", "activity.js")).href);
  const registry = new mod.ActivityRegistry({ now: () => now, staleMs: 1000 });
  assert.deepEqual(registry.view(), { ok: true, active: false, status: "idle" });
  assert.equal(registry.start({ id: "a1", conversationId: "c1", model: "modelo", modelLabel: "Modelo local" }), "a1");
  assert.equal(registry.view({ conversationId: "c1" }).phase, "preparing");
  now += 250;
  assert.equal(registry.update("a1", { status: "waiting", phase: "approval", label: "Esperando tu aprobación…" }), true);
  const active = registry.view({ activityId: "a1" });
  assert.equal(active.active, true);
  assert.equal(active.status, "waiting");
  assert.equal(active.phase, "approval");
  assert.equal(active.elapsed_seconds, 0.25);
  assert.equal(active.heartbeat_age_seconds, 0);
  assert.equal(registry.finish("a1"), true);
  assert.equal(registry.view().active, false);
  registry.start({ id: "a2" });
  now += 1001;
  assert.equal(registry.view({ activityId: "a2" }).active, false);
  console.log("OK  activity registry 10/10");
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
