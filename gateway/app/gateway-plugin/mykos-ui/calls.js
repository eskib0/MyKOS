// Registro de llamadas de voz de MyKOS (fase 5.1).
//
// Este tramo solo reserva la llamada y guarda su ciclo de vida. No abre audio, WebRTC ni micrófono. Esos recursos
// llegarán en el tramo 5.2 y deberán colgarse a través de esta misma autoridad.

import { randomUUID } from "node:crypto";

export const CALL_STATES = new Set(["connecting", "active", "interrupted", "ended", "error"]);
const CALL_REGISTRY = Symbol.for("mykos.mykos-ui.call-registries");

const now = () => new Date().toISOString();
const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

function providerFor(model) {
  const value = String(model || "").trim();
  if (!value) return "unknown";
  if (value.startsWith("openai-codex-oauth/") || value === "gpt-live-1-codex") return "openai_codex_oauth";
  if (value.startsWith("openrouter/")) return "openrouter";
  if (value.startsWith("meta-ai/")) return "meta_ai_oauth";
  if (value.startsWith("nvidia/")) return "nvidia_api";
  if (value.startsWith("kimi/")) return "kimi_api";
  if (value.startsWith("gemini/")) return "gemini_api";
  if (value.startsWith("mistral/")) return "mistral_api";
  if (value.startsWith("grok/")) return "grok";
  if (value.startsWith("antigravity/")) return "antigravity";
  if (value.startsWith("qwen-cli/")) return "qwen_cli";
  if (value.startsWith("anthropic/") || value === "claude-sonnet-oauth") return "anthropic";
  if (value === "mykos-cuda" || value.startsWith("strata/")) return "strata";
  if (!value.includes("/")) return "ollama";
  return "unknown";
}

function publicCall(call) {
  return {
    callId: call.callId,
    sessionId: call.sessionId,
    state: call.state,
    model: call.model,
    provider: call.provider,
    connection: { ...call.connection },
    createdAt: call.createdAt,
    updatedAt: call.updatedAt,
    ...(call.endedAt ? { endedAt: call.endedAt } : {}),
    ...(call.error ? { error: call.error } : {}),
  };
}

export class CallError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export class CallRegistry {
  constructor({ store, isActive = () => true, defaultModel = "openai-codex-oauth/gpt-5.6-luna", logger } = {}) {
    this.store = store;
    this.isActive = isActive;
    this.defaultModel = defaultModel;
    this.logger = logger;
    this.calls = new Map();
  }

  configure({ store, isActive, defaultModel, logger } = {}) {
    if (store) this.store = store;
    if (isActive) this.isActive = isActive;
    if (defaultModel) this.defaultModel = defaultModel;
    if (logger) this.logger = logger;
    return this;
  }

  conversation(sessionId) {
    if (!this.store || !this.isActive()) {
      throw new CallError(503, "store_inactive", "El almacén de MyKOS no está activo.");
    }
    const doc = this.store.get("conversations");
    const conversations = doc?.data?.conversations;
    if (!doc || !Array.isArray(conversations)) {
      throw new CallError(503, "conversations_unavailable", "No se puede leer el almacén de conversaciones.");
    }
    const conversation = conversations.find((item) => item?.id === sessionId);
    if (!conversation) throw new CallError(404, "session_not_found", "La sesión de MyKOS no existe.");
    return { doc, conversations, conversation };
  }

  saveConversationCall(sessionId, call) {
    const { doc, conversations, conversation } = this.conversation(sessionId);
    const rows = Array.isArray(conversation.voice_calls) ? conversation.voice_calls.filter(isObject) : [];
    const entry = {
      call_id: call.callId,
      state: call.state,
      model: call.model,
      provider: call.provider,
      created_at: call.createdAt,
      updated_at: call.updatedAt,
      ...(call.endedAt ? { ended_at: call.endedAt } : {}),
      ...(call.error ? { error: call.error } : {}),
    };
    const index = rows.findIndex((item) => item.call_id === call.callId);
    if (index >= 0) rows[index] = entry;
    else rows.push(entry);
    conversation.voice_calls = rows.slice(-32);
    this.store.put("conversations", { ...doc.data, conversations }, {
      expectedRevision: doc.revision,
      source: `voice-call:${call.state}`,
    });
  }

  create({ sessionId, model, replace = false } = {}) {
    const cleanSessionId = String(sessionId || "").trim();
    if (!cleanSessionId || cleanSessionId.length > 160) throw new CallError(400, "bad_session", "La sesión indicada no es válida.");
    const selectedModel = String(model || this.defaultModel).trim();
    if (!selectedModel || selectedModel.length > 180 || /[\r\n\x00]/.test(selectedModel)) {
      throw new CallError(400, "bad_model", "El motor de voz indicado no es válido.");
    }
    this.conversation(cleanSessionId);
    for (const call of this.calls.values()) {
      if (call.sessionId === cleanSessionId && !["ended", "error"].includes(call.state)) {
        if (replace) {
          this.end(call.callId);
          continue;
        }
        throw new CallError(409, "call_exists", "Esta sesión ya tiene una llamada activa.");
      }
    }
    const timestamp = now();
    const call = {
      callId: `call_${randomUUID()}`,
      sessionId: cleanSessionId,
      state: "connecting",
      model: selectedModel,
      provider: providerFor(selectedModel),
      connection: {
        transport: "pending",
        audio: false,
        realtime: false,
      },
      createdAt: timestamp,
      updatedAt: timestamp,
    };
    this.saveConversationCall(cleanSessionId, call);
    this.calls.set(call.callId, call);
    return publicCall(call);
  }

  get(callId) {
    const call = this.calls.get(String(callId || "").trim());
    if (!call) throw new CallError(404, "call_not_found", "La llamada no existe.");
    return publicCall(call);
  }

  /** Uso interno del motor de voz; la API pública recibe siempre publicCall(). */
  getInternal(callId) {
    const call = this.calls.get(String(callId || "").trim());
    if (!call) throw new CallError(404, "call_not_found", "La llamada no existe.");
    return call;
  }

  end(callId) {
    const call = this.calls.get(String(callId || "").trim());
    if (!call) throw new CallError(404, "call_not_found", "La llamada no existe.");
    if (call.state === "ended") return publicCall(call);
    const timestamp = now();
    call.state = "ended";
    call.updatedAt = timestamp;
    call.endedAt = timestamp;
    call.connection = { ...call.connection, audio: false, realtime: false, transport: "closed" };
    this.saveConversationCall(call.sessionId, call);
    return publicCall(call);
  }

  setState(callId, state, extra = {}) {
    const call = this.calls.get(String(callId || "").trim());
    if (!call) throw new CallError(404, "call_not_found", "La llamada no existe.");
    if (!CALL_STATES.has(state)) throw new CallError(400, "bad_state", "El estado de llamada no es válido.");
    call.state = state;
    call.updatedAt = now();
    if (state === "ended") call.endedAt = call.updatedAt;
    if (isObject(extra.connection)) call.connection = { ...call.connection, ...extra.connection };
    if (extra.error) call.error = String(extra.error).slice(0, 300);
    this.saveConversationCall(call.sessionId, call);
    return publicCall(call);
  }

  /** Guarda un texto final de Realtime en la conversación de MyKOS, de forma idempotente. */
  appendTranscript(callId, { role, text, entryId } = {}) {
    const call = this.getInternal(callId);
    const cleanRole = role === "user" || role === "assistant" ? role : "";
    const cleanText = typeof text === "string" ? text.trim() : "";
    const cleanEntryId = String(entryId || "").trim().replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 128);
    if (!cleanRole || !cleanText || cleanText.length > 12_000 || !cleanEntryId) {
      throw new CallError(400, "bad_transcript", "La transcripción de voz no es válida.");
    }
    call.transcriptIds ??= new Set();
    if (call.transcriptIds.has(cleanEntryId)) return { saved: false, duplicate: true, call: publicCall(call) };
    const { doc, conversations, conversation } = this.conversation(call.sessionId);
    conversation.messages = Array.isArray(conversation.messages) ? conversation.messages : [];
    conversation.messages.push({
      id: `realtime_${call.callId}_${cleanEntryId}`,
      role: cleanRole,
      content: cleanText,
      created_at: now(),
      voice_call_id: call.callId,
      voice_provider: call.provider === "gemini_api" ? "gemini_live" : "openai_realtime",
    });
    conversation.updated_at = now();
    this.store.put("conversations", { ...doc.data, conversations }, {
      expectedRevision: doc.revision,
      source: call.provider === "gemini_api" ? "gemini-live-transcript" : "realtime-transcript",
    });
    call.transcriptIds.add(cleanEntryId);
    return { saved: true, duplicate: false, call: publicCall(call) };
  }
}

export function acquireCallRegistry(key, options = {}) {
  const registries = (globalThis[CALL_REGISTRY] ??= new Map());
  const registry = registries.get(key) ?? new CallRegistry(options);
  registry.configure(options);
  registries.set(key, registry);
  return registry;
}
