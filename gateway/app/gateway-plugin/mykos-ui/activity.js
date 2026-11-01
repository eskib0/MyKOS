// Registro efímero de actividad de MyKOS, propiedad del Gateway.
// No se persiste: describe una operación que está en curso y se descarta al
// terminar o tras un tiempo sin latido.

const STALE_MS = 30 * 60 * 1000;

export class ActivityRegistry {
  constructor({ now = () => Date.now(), staleMs = STALE_MS } = {}) {
    this.now = now;
    this.staleMs = staleMs;
    this.items = new Map();
  }

  purge() {
    const now = this.now();
    for (const [id, item] of this.items) {
      if (now - item.updatedAtEpoch > this.staleMs) this.items.delete(id);
    }
  }

  start({ id, conversationId = "", model = "", modelLabel = "Modelo", providerLabel = "Ollama local", remote = false, location = remote ? "remoto" : "local" } = {}) {
    if (typeof id !== "string" || !id.trim()) throw new Error("activity_id inválido");
    this.purge();
    const now = this.now();
    const item = {
      id: id.trim(), conversation_id: String(conversationId || ""), model: String(model || ""), model_label: String(modelLabel || "Modelo"),
      provider_label: String(providerLabel || "Ollama local"), remote: Boolean(remote), location: String(location || "local"),
      status: "working", phase: "preparing", label: "Preparando petición…",
      detail: `${modelLabel || "Modelo"} · ${location || "local"}`,
      started_at: new Date(now).toISOString(), updated_at: new Date(now).toISOString(),
      startedAtEpoch: now, updatedAtEpoch: now,
    };
    this.items.set(item.id, item);
    return item.id;
  }

  update(id, changes = {}) {
    const item = this.items.get(String(id || ""));
    if (!item) return false;
    for (const key of ["status", "phase", "label", "detail", "model", "model_label", "provider_label", "location"]) {
      if (typeof changes[key] === "string") item[key] = changes[key];
    }
    if (typeof changes.remote === "boolean") item.remote = changes.remote;
    const now = this.now();
    item.updated_at = new Date(now).toISOString();
    item.updatedAtEpoch = now;
    return true;
  }

  finish(id) { return this.items.delete(String(id || "")); }

  view({ activityId = "", conversationId = "" } = {}) {
    this.purge();
    let item = activityId ? this.items.get(String(activityId)) : null;
    if (!item && conversationId) item = [...this.items.values()].find((value) => value.conversation_id === String(conversationId));
    if (!item) return { ok: true, active: false, status: "idle" };
    const { startedAtEpoch, updatedAtEpoch, ...publicItem } = item;
    const now = this.now();
    return { ok: true, ...publicItem, active: true, elapsed_seconds: Math.max(0, (now - startedAtEpoch) / 1000), heartbeat_age_seconds: Math.max(0, (now - updatedAtEpoch) / 1000) };
  }
}
