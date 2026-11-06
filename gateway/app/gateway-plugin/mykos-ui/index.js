// Plugin "mykos-ui" de MyKOS Gateway (v0.3)
//
// Qué hace
//   1. Sirve la interfaz MyKOS (carpeta static/ del proyecto) en  GET/HEAD /  y  /static/*
//   2. Reenvía /api/* al backend Python de MyKOS (proxy inverso por streaming, sin cargar cuerpos en memoria)
//   3. Arranca y supervisa ese backend como servicio del Gateway: si el Gateway se detiene, el backend también
//   4. Publica /mykos-health con el estado de todo lo anterior
//   5. (opcional, config.store.enabled) Es el DUEÑO de los datos de MyKOS: guarda las conversaciones y la memoria en
//      su propio almacén (store.js) y el backend Python los pide por HTTP interno (/mykos-store/, con token)
//
// REGLAS DE ESTE FICHERO (aprendidas en pruebas; detalle en AUDITORIA_FASE_0_2026-09-25.md)
//   1. NO importa nada del SDK ni de dist/ por ruta relativa: hacía que el Gateway tardase ~105 s en arrancar
//      (frente a ~6 s) y dejaba /health sin responder. La entrada nativa es un objeto plano con register(api).
//   2. NO usa import.meta.url para localizar ficheros: el Gateway carga el plugin desde una COPIA temporal
//      (<estado>/tmp/plugin-captures/...). Las rutas salen de la configuración del plugin.
//   3. register(api) se ejecuta más de una vez por arranque (registro temprano y runtime completo): sin efectos
//      secundarios al registrar. Los procesos solo se lanzan desde el servicio, que se registra en modo "full".

import { appendFileSync, chmodSync, closeSync, copyFileSync, cpSync, existsSync, mkdirSync, openSync, readFileSync, readdirSync, renameSync, statSync, writeFileSync, createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createHmac, randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import http from "node:http";
import https from "node:https";
import path from "node:path";
import { exec, spawn, spawnSync } from "node:child_process";
import { pipeline } from "node:stream";
import os from "node:os";
import { DocumentStore, StoreError } from "./store.js";
import { PermissionAuthority } from "./permissions.js";
import { prepareContext } from "./context.js";
import { acquireCallRegistry, CallError } from "./calls.js";
import { acquireVoiceEngine, VoiceEngineError } from "./voice-engine.js";
import { MyKOSRealtimeController, RealtimeError } from "./realtime.js";
import { runGeminiLiveFunctionCalls } from "./gemini-live-tools.js";
import { ROUTE_TABLE, classifyRoute } from "./routes.js";
import { runChatLoop, stripFakeLedgerTags, toolMessageForResult, utcNow } from "./chat-loop.js";
import { ActivityRegistry } from "./activity.js";
import { DECISION_HEADER, POLICY_TABLE, PolicyLimiter, decide, decisionHeaderValue, policyFor } from "./policy.js";
import {
  BASE_HEADERS,
  HOP_BY_HOP,
  MAX_CHUNKED_BODY_BYTES,
  MIME,
  PROBE_TIMEOUT_MS,
  actionRouteSignature,
  compactedConversationSummary,
  controlAudit,
  conversationById,
  conversationMarkdown,
  conversationSummary,
  conversationSummaryExcerpt,
  executionGrant,
  isObject,
  isOwnRequest,
  jsonRequest,
  mediaLibrary,
  onlyGetHead,
  probeJson,
  proxyRequest,
  readBody,
  resolveInside,
  sendFile,
  sendJson,
} from "./http-helpers.js";

const CODE_VERSION = "0.13.2";
const STORE_PREFIX = "/mykos-store/";
const CONTROL_PREFIX = "/mykos-control/";
const STORE_REGISTRY = Symbol.for("mykos.mykos-ui.stores");
const CONTROL_REGISTRY = Symbol.for("mykos.mykos-ui.control-tokens");
const STATIC_PREFIX = "/static/";
const API_PREFIX = "/api/";
const ACTIVE_BACKEND = Symbol.for("mykos.mykos-ui.active-backend");
const POLICY_REGISTRY = Symbol.for("mykos.mykos-ui.policy-limiters");
const WEB_SESSION_REGISTRY = Symbol.for("mykos.mykos-ui.web-session-token");
const WEB_SESSION_TOKEN = (globalThis[WEB_SESSION_REGISTRY] ??= randomBytes(32).toString("hex"));

function getCookie(req, name) {
  const header = req.headers?.cookie;
  if (!header || typeof header !== "string") return "";
  const parts = header.split(";");
  for (const part of parts) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return v.join("=");
  }
  return "";
}

function isWebAuthorized(req, sessionToken, controlToken) {
  // 1. Cookie de sesión del navegador (SameSite=Strict, HttpOnly)
  const cookieVal = getCookie(req, "mykos_session");
  if (cookieVal && cookieVal.length === sessionToken.length) {
    try {
      if (timingSafeEqual(Buffer.from(cookieVal, "utf8"), Buffer.from(sessionToken, "utf8"))) {
        return true;
      }
    } catch {}
  }

  // 2. Cabecera explícita X-MyKOS-Session
  const headerVal = String(req.headers?.["x-mykos-session"] ?? "").trim();
  if (headerVal && headerVal.length === sessionToken.length) {
    try {
      if (timingSafeEqual(Buffer.from(headerVal, "utf8"), Buffer.from(sessionToken, "utf8"))) {
        return true;
      }
    } catch {}
  }

  // 3. Cabecera interna X-MyKOS-Control-Token (para pruebas y sondas del sistema)
  if (controlToken) {
    const ctrlVal = String(req.headers?.["x-mykos-control-token"] ?? "").trim();
    if (ctrlVal && ctrlVal.length === controlToken.length) {
      try {
        if (timingSafeEqual(Buffer.from(ctrlVal, "utf8"), Buffer.from(controlToken, "utf8"))) {
          return true;
        }
      } catch {}
    }
  }

  return false;
}

const MAX_JSON_API_BYTES = 2_000_000; // el mismo límite que read_json() en server.py
const localNode = () => ({
  id: "local-desktop", name: os.hostname(), kind: "desktop", local: true, enabled: true, status: "online",
  capabilities: ["chat", "files", "microphone", "tts"], platform: `${os.type()} ${os.release()}`, pid: process.pid,
  last_seen: utcNow(),
});
const REMOTE_MODEL_PREFIXES = ["antigravity/", "qwen-cli/", "meta-ai/", "nvidia/", "kimi/", "mistral/", "openrouter/", "openai-codex-oauth/", "gemini/", "anthropic/", "grok/"];
const isRemoteModelName = (name) => REMOTE_MODEL_PREFIXES.some((prefix) => name.startsWith(prefix)) || name === "claude-sonnet-oauth";
const LOG_ROTATE_BYTES = 5 * 1024 * 1024;
const READY_TIMEOUT_MS = 90_000;
const BACKOFF_MS = [1_000, 2_000, 4_000, 8_000, 15_000, 30_000];
const MAX_QUICK_FAILURES = 6;
const STABLE_RUN_MS = 60_000;

// ───────────────────── conversaciones propiedad del Gateway ─────────────────────

function conversationStore(storeRuntime) {
  try {
    const doc = storeRuntime?.store?.get("conversations");
    return doc && Array.isArray(doc.data?.conversations) ? { store: storeRuntime.store, data: doc.data } : null;
  } catch (error) {
    return {
      store: storeRuntime?.store,
      data: null,
      error: "store_corrupt",
      detail: String(error?.message || error),
    };
  }
}

// Medidor visual: no prepara ni envía el chat. Lee exclusivamente la conversación
// canónica del almacén del Gateway y estima el presupuesto seleccionado en la UI.
function contextMeter(apiUrl, storeRuntime, cfg) {
  const state = conversationStore(storeRuntime);
  if (state?.error === "store_corrupt") {
    return {
      status: 503,
      body: {
        ok: false,
        error: "store_corrupt",
        document: "conversations",
        detail: state.detail,
        hint: "El archivo de conversaciones está dañado y no tiene copia de seguridad. Ejecuta: mykos store repair",
      },
    };
  }
  if (!state || !state.data) return { status: 503, body: { error: "El almacén de conversaciones del Gateway no está disponible." } };
  const id = String(apiUrl.searchParams.get("id") || "").trim();
  const conversation = id ? conversationById(state.data, id) : null;
  if (id && !conversation) return { status: 400, body: { error: "Conversación no encontrada." } };
  const speed = ["fast", "balanced", "quality", "full"].includes(apiUrl.searchParams.get("speed")) ? apiUrl.searchParams.get("speed") : "balanced";
  const presets = { fast: [16384, 768], balanced: [32768, 1536], quality: [65536, 3072], full: [131072, 8192] };
  let [numCtx, numPredict] = presets[speed];
  const attachments = Math.max(0, Math.min(4, Number(apiUrl.searchParams.get("attachments")) || 0));
  if (attachments) numCtx = Math.max(numCtx, 32768 * attachments);
  const model = String(apiUrl.searchParams.get("model") || "").trim();
  if (model === "claude-sonnet-oauth") numCtx = 131072;
  if (model.startsWith("openai-codex-oauth/")) numCtx = 258400;
  const source = (Array.isArray(conversation?.messages) ? conversation.messages : []).filter(isObject).map((m) => ({ role: m.role, content: m.content, tool_calls: m.tool_calls, images: m.images }));
  const manualCompacted = Boolean(conversation?.context_summary);
  const manualOmitted = Number(conversation?.context_omitted_count || 0);
  const prepared = prepareContext("MyKOS: contexto de sistema gestionado por MyKOS Gateway.", source, { options: { num_ctx: numCtx, num_predict: numPredict } });
  return { status: 200, body: { context: { ...prepared.context, model, speed, compaction_threshold_percent: 82, manual_compacted: manualCompacted, manual_omitted_messages: manualOmitted }, model } };
}

function saveConversations(store, data, source) {
  store.put("conversations", data, { source, allowShrink: true });
}

const AUTOMATION_TIMER = Symbol.for("mykos.mykos-ui.automation-timer");
function startGatewayAutomationScheduler(storeRuntime) {
  if (!storeRuntime?.store || globalThis[AUTOMATION_TIMER]) return;
  const tick = () => {
    try {
      const doc = storeRuntime.store.get("automations"); const data = doc?.data;
      if (!data || !Array.isArray(data.automations) || !Array.isArray(data.events)) return;
      const now = new Date(); let changed = false;
      for (const item of data.automations) {
        if (!isObject(item) || !item.enabled || Number.isNaN(Date.parse(item.run_at))) continue;
        const due = new Date(item.run_at); if (due > now) continue;
        data.events.push({ id: randomBytes(16).toString("hex"), automation_id: String(item.id || ""), title: String(item.title || ""), message: String(item.message || ""), fired_at: now.toISOString() });
        const repeat = Number(item.repeat_minutes) || 0;
        if (repeat > 0) { while (due <= now) due.setUTCMinutes(due.getUTCMinutes() + repeat); item.run_at = due.toISOString(); } else item.enabled = false;
        item.last_run_at = now.toISOString(); changed = true;
      }
      if (data.events.length > 200) data.events = data.events.slice(-200);
      if (changed) storeRuntime.store.put("automations", data, { source: "gateway.automations.scheduler", allowShrink: true });
    } catch {}
  };
  tick(); globalThis[AUTOMATION_TIMER] = setInterval(tick, 1000);
}
function stopGatewayAutomationScheduler() { const timer = globalThis[AUTOMATION_TIMER]; if (timer) clearInterval(timer); delete globalThis[AUTOMATION_TIMER]; }

async function handleConversationApi(req, res, apiPath, apiUrl, storeRuntime) {
  const ownsPath = apiPath === "/api/conversations" || apiPath === "/api/conversation" || apiPath === "/api/conversations/export" || apiPath === "/api/conversations/new" || apiPath === "/api/conversations/compact" || apiPath === "/api/conversations/messages" || apiPath === "/api/context";
  if (!ownsPath) return false;
  const state = conversationStore(storeRuntime);
  if (state?.error === "store_corrupt") {
    sendJson(res, 503, {
      ok: false,
      error: "store_corrupt",
      document: "conversations",
      detail: state.detail,
      hint: "El archivo de conversaciones está dañado y no tiene copia de seguridad. Ejecuta: mykos store repair",
    });
    return true;
  }
  if (!state) return false; // modo de compatibilidad sin almacén: conserva el trabajador Python.
  const { store, data } = state;
  try {
    if (req.method === "GET" && apiPath === "/api/context") {
      const result = contextMeter(apiUrl, storeRuntime, null);
      sendJson(res, result.status, result.body);
      return true;
    }
    if (req.method === "GET" && apiPath === "/api/conversations") {
      const conversations = [...data.conversations].map(conversationSummary).sort((a, b) => b.updated_at.localeCompare(a.updated_at));
      sendJson(res, 200, { conversations });
      return true;
    }
    if (req.method === "GET" && apiPath === "/api/conversation") {
      const id = apiUrl.searchParams.get("id") || "";
      const conversation = conversationById(data, id);
      if (!conversation) sendJson(res, 404, { error: "Conversación no encontrada." });
      else {
        const messages = (Array.isArray(conversation.messages) ? conversation.messages : []).filter(isObject).map((message, index) => ({ ...message, message_id: String(message.message_id || `legacy-${id}-${index}`) }));
        sendJson(res, 200, { conversation: { ...conversation, messages } });
      }
      return true;
    }
    if (req.method === "GET" && apiPath === "/api/conversations/export") {
      const id = apiUrl.searchParams.get("id") || "";
      const conversation = conversationById(data, id);
      if (!conversation) sendJson(res, 404, { error: "Conversación no encontrada." });
      else {
        const body = Buffer.from(conversationMarkdown(conversation), "utf8");
        res.statusCode = 200;
        for (const [key, value] of Object.entries({ ...BASE_HEADERS, "Content-Type": "text/markdown; charset=utf-8", "Content-Length": body.length, "Content-Disposition": `attachment; filename="mykos-session-${id.slice(0, 8)}.md"` })) res.setHeader(key, value);
        res.end(body);
      }
      return true;
    }
    if (req.method === "GET" && apiPath === "/api/conversations/compact") {
      sendJson(res, 405, { error: "La compactación requiere POST." });
      return true;
    }
    if (req.method === "POST" && apiPath === "/api/conversations/new") {
      const raw = await readBody(req, MAX_JSON_API_BYTES);
      if (!raw.length) throw new SyntaxError("Cuerpo de petición no válido.");
      const payload = JSON.parse(raw.toString("utf8"));
      if (!isObject(payload)) {
        const error = new SyntaxError("El cuerpo debe ser un objeto JSON.");
        error.publicMessage = "El cuerpo debe ser un objeto JSON.";
        throw error;
      }
      const now = utcNow();
      const conversation = { id: randomBytes(16).toString("hex"), title: "Nueva conversación", created_at: now, updated_at: now, messages: [] };
      data.conversations.push(conversation);
      saveConversations(store, data, "gateway.conversations.create");
      sendJson(res, 200, { conversation });
      return true;
    }
    if (req.method === "POST" && apiPath === "/api/conversations/compact") {
      const raw = await readBody(req, MAX_JSON_API_BYTES);
      if (!raw.length) throw new SyntaxError("Cuerpo de petición no válido.");
      const payload = JSON.parse(raw.toString("utf8"));
      if (!isObject(payload)) {
        const error = new SyntaxError("El cuerpo debe ser un objeto JSON.");
        error.publicMessage = "El cuerpo debe ser un objeto JSON.";
        throw error;
      }
      const conversationId = String(payload.conversation_id ?? "").trim();
      const conversation = conversationById(data, conversationId);
      if (!conversation) { sendJson(res, 400, { error: "Conversación no encontrada." }); return true; }
      const messages = (Array.isArray(conversation.messages) ? conversation.messages : []).filter(isObject);
      if (messages.length <= 10) {
        sendJson(res, 200, { ok: true, conversation_id: conversationId, compacted: false, message_count: messages.length, omitted_messages: 0, detail: "La conversación todavía es corta; no hacía falta compactarla." });
        return true;
      }
      const omitted = messages.slice(0, -10);
      conversation.context_summary = compactedConversationSummary(omitted);
      conversation.context_compacted_at = utcNow();
      conversation.context_omitted_count = omitted.length;
      conversation.updated_at = utcNow();
      saveConversations(store, data, "gateway.conversations.compact");
      sendJson(res, 200, { ok: true, conversation_id: conversationId, compacted: true, message_count: messages.length, omitted_messages: omitted.length, kept_messages: 10, detail: "Contexto compactado. El historial completo sigue disponible para exportarlo." });
      return true;
    }
    if (req.method === "DELETE" && apiPath === "/api/conversations") {
      const id = apiUrl.searchParams.get("id") || "";
      if (!id) { sendJson(res, 400, { error: "Falta el identificador de la conversación." }); return true; }
      const before = data.conversations.length;
      data.conversations = data.conversations.filter((row) => String(row?.id ?? "") !== id);
      if (data.conversations.length === before) sendJson(res, 404, { error: "Conversación no encontrada." });
      else { saveConversations(store, data, "gateway.conversations.delete"); sendJson(res, 200, { deleted: true, conversation_id: id, remaining: data.conversations.length }); }
      return true;
    }
    if (req.method === "DELETE" && apiPath === "/api/conversations/messages") {
      const conversationId = apiUrl.searchParams.get("conversation_id") || "";
      const messageId = apiUrl.searchParams.get("message_id") || "";
      if (!conversationId || !messageId) { sendJson(res, 400, { error: "Faltan la conversación o el mensaje." }); return true; }
      const conversation = conversationById(data, conversationId);
      if (!conversation) { sendJson(res, 404, { error: "Conversación no encontrada." }); return true; }
      const messages = Array.isArray(conversation.messages) ? conversation.messages : [];
      let deleted = false;
      conversation.messages = messages.filter((message, index) => {
        const id = String(message?.message_id || `legacy-${conversationId}-${index}`);
        if (!deleted && id === messageId && message?.role === "user") { deleted = true; return false; }
        return true;
      });
      if (!deleted) { sendJson(res, 400, { error: "Solo se pueden eliminar mensajes propios y el mensaje indicado debe existir." }); return true; }
      delete conversation.context_summary;
      delete conversation.context_compacted_at;
      delete conversation.context_omitted_count;
      conversation.updated_at = utcNow();
      saveConversations(store, data, "gateway.conversations.delete-message");
      sendJson(res, 200, { ok: true, deleted: true, conversation_id: conversationId, message_id: messageId });
      return true;
    }
  } catch (error) {
    if (error instanceof SyntaxError) sendJson(res, 400, { error: error.publicMessage || "El cuerpo no contiene JSON válido." });
    else if (error instanceof StoreError) sendJson(res, error.status, { error: error.message });
    else sendJson(res, 500, { error: "No se pudo actualizar la conversación." });
    return true;
  }
  return false;
}

// ───────────────────────────── configuración ─────────────────────────────

// Fecha y hora actuales en español, hora de Madrid, para que MyKOS no responda a ciegas en la
// llamada de voz (mismo texto que current_time_context() en server.py para el chat escrito).
const MADRID_TIME_FORMAT = new Intl.DateTimeFormat("es-ES", {
  timeZone: "Europe/Madrid", weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
});
function currentTimeContext() {
  const parts = Object.fromEntries(MADRID_TIME_FORMAT.formatToParts(new Date()).map((p) => [p.type, p.value]));
  return `Fecha y hora actuales: ${parts.weekday} ${parts.day} de ${parts.month} de ${parts.year}, ${parts.hour}:${parts.minute} (hora de Madrid, España).`;
}

// La hora cambia cada minuto. Dentro del mensaje de sistema (antes del historial) obliga a los modelos
// locales a releer el prompt entero, herramientas incluidas, en cada turno; por eso se quita de ahí y se
// antepone al último mensaje de Usuario: el prefijo largo queda idéntico y la caché de prompt se reutiliza.
const stripTimeLine = (prompt) => String(prompt ?? "").replace(/^Fecha y hora actuales:.*\n+/m, "");
function withTimeOnLastUser(messages) {
  const result = [...messages];
  for (let index = result.length - 1; index >= 0; index -= 1) {
    if (result[index]?.role !== "user" || typeof result[index].content !== "string") continue;
    result[index] = { ...result[index], content: `[${currentTimeContext()}]\n\n${result[index].content}` };
    break;
  }
  return result;
}

function parseUserMarkdown(content) {
  if (!content || typeof content !== "string") {
    return { name: "", location: "", role: "", tone: "Directo y al grano", notes: "", raw_markdown: "" };
  }
  const nameMatch = content.match(/^[ \t]*-[ \t]*\*\*Nombre(?:\s*\/\s*Alias)?:\*\*\s*(.*)$/im);
  const locationMatch = content.match(/^[ \t]*-[ \t]*\*\*Ubicación:\*\*\s*(.*)$/im);
  const roleMatch = content.match(/^[ \t]*-[ \t]*\*\*Rol(?:\s*\/\s*Profesión)?:\*\*\s*(.*)$/im);
  const toneMatch = content.match(/^[ \t]*-[ \t]*\*\*Tono preferido:\*\*\s*(.*)$/im);

  let notes = "";
  const notesIdx = content.search(/^[ \t]*-[ \t]*\*\*Notas personales:\*\*/im);
  if (notesIdx !== -1) {
    const afterNotes = content.slice(notesIdx);
    const firstLineEnd = afterNotes.indexOf("\n");
    if (firstLineEnd !== -1) {
      const rest = afterNotes.slice(firstLineEnd + 1);
      notes = rest
        .split("\n")
        .map((line) => line.replace(/^[ \t]*-[ \t]*/, "").trim())
        .filter(Boolean)
        .join("\n");
    }
  }

  return {
    name: nameMatch ? nameMatch[1].trim() : "",
    location: locationMatch ? locationMatch[1].trim() : "",
    role: roleMatch ? roleMatch[1].trim() : "",
    tone: toneMatch ? toneMatch[1].trim() : "Directo y al grano",
    notes: notes.trim(),
    raw_markdown: content,
  };
}

function buildUserMarkdown(payload) {
  if (typeof payload?.raw_markdown === "string" && payload.raw_markdown.trim()) {
    return payload.raw_markdown.trim() + "\n";
  }
  const name = typeof payload?.name === "string" ? payload.name.trim() : "";
  const location = typeof payload?.location === "string" ? payload.location.trim() : "";
  const role = typeof payload?.role === "string" ? payload.role.trim() : "";
  const tone = typeof payload?.tone === "string" ? payload.tone.trim() : "Directo y al grano";
  const notes = typeof payload?.notes === "string" ? payload.notes.trim() : "";

  const lines = ["# Perfil del Usuario"];
  if (name) lines.push(`- **Nombre:** ${name}`);
  if (location) lines.push(`- **Ubicación:** ${location}`);
  if (role) lines.push(`- **Rol:** ${role}`);
  if (tone) lines.push(`- **Tono preferido:** ${tone}`);
  if (notes) {
    lines.push("- **Notas personales:**");
    for (const noteLine of notes.split("\n")) {
      const trimmed = noteLine.trim();
      if (!trimmed) continue;
      lines.push(trimmed.startsWith("-") || trimmed.startsWith("*") ? `  ${trimmed}` : `  - ${trimmed}`);
    }
  }
  return lines.join("\n") + "\n";
}

async function handleUserProfileApi(req, res, cfg) {
  const workspace = cfg.workspaceDir || path.join(os.homedir(), ".mykos", "workspace");
  const userFile = path.join(workspace, "USER.md");

  if (req.method === "GET") {
    let rawContent = "";
    let effectivePath = userFile;
    try {
      rawContent = readFileSync(userFile, "utf8");
    } catch (e) {
      if (e.code === "ENOENT") {
        const fallback = path.join(os.homedir(), ".mykos", "USER.md");
        try {
          rawContent = readFileSync(fallback, "utf8");
          effectivePath = fallback;
        } catch {}
      } else {
        sendJson(res, 500, { ok: false, error: "No se pudo leer USER.md." });
        return true;
      }
    }
    const parsed = parseUserMarkdown(rawContent);
    sendJson(res, 200, { ok: true, file: effectivePath, exists: Boolean(rawContent), ...parsed });
    return true;
  }

  if (req.method === "POST") {
    let payload;
    try {
      const raw = await readBody(req, MAX_JSON_API_BYTES);
      payload = raw.length ? JSON.parse(raw.toString("utf8")) : {};
      if (!isObject(payload)) throw new Error();
    } catch {
      sendJson(res, 400, { ok: false, error: "JSON inválido en el cuerpo de la petición." });
      return true;
    }

    const markdown = buildUserMarkdown(payload);
    try {
      mkdirSync(workspace, { recursive: true });
      const tmpFile = `${userFile}.tmp.${Date.now()}`;
      writeFileSync(tmpFile, markdown, "utf8");
      renameSync(tmpFile, userFile);
    } catch (e) {
      sendJson(res, 500, { ok: false, error: `Error al guardar USER.md: ${e.message}` });
      return true;
    }

    const parsed = parseUserMarkdown(markdown);
    sendJson(res, 200, {
      ok: true,
      message: "Perfil guardado con éxito.",
      file: userFile,
      ...parsed,
    });
    return true;
  }

  return false;
}

// ── Actualizaciones del Sistema (GitHub Releases / Git) ────────────────────────
let updateCache = {
  data: null,
  cachedAt: 0,
};
const UPDATE_CACHE_TTL_MS = 10 * 60 * 1000; // 10 minutos

function fetchGithubJson(apiPath) {
  return new Promise((resolve) => {
    const req = https.request({
      hostname: "api.github.com",
      path: apiPath,
      method: "GET",
      headers: {
        "User-Agent": "MyKOS-Updater/1.0",
        "Accept": "application/vnd.github.v3+json",
      },
      timeout: 6000,
    }, (res) => {
      let data = "";
      res.on("data", (chunk) => { data += chunk; });
      res.on("end", () => {
        try {
          resolve({ status: res.statusCode, body: JSON.parse(data) });
        } catch {
          resolve({ status: res.statusCode, error: "parse_error" });
        }
      });
    });
    req.on("error", (err) => resolve({ status: 0, error: err.message }));
    req.on("timeout", () => {
      req.destroy();
      resolve({ status: 0, error: "timeout" });
    });
    req.end();
  });
}

async function handleSystemUpdatesApi(req, res, cfg, apiUrl) {
  const mykosRoot = path.resolve(cfg.projectDir || path.join(os.homedir(), "MyKOS"), "..", "..");
  const isGit = existsSync(path.join(mykosRoot, ".git"));

  // Leer versión local desde version.json
  let localVersion = "1.0.0";
  let repoName = "eskib0/MyKOS";
  try {
    const vRaw = readFileSync(path.join(mykosRoot, "version.json"), "utf8");
    const vJson = JSON.parse(vRaw);
    if (vJson.version) localVersion = vJson.version;
    if (vJson.repository) repoName = vJson.repository;
  } catch {}

  let localCommit = "";
  if (isGit) {
    try {
      const gitOut = spawnSync("git", ["rev-parse", "--short", "HEAD"], { cwd: mykosRoot, encoding: "utf8" });
      if (gitOut.status === 0 && gitOut.stdout) localCommit = gitOut.stdout.trim();
    } catch {}
  }

  // GET /api/system/updates: comprobar versión
  if (req.method === "GET" && apiUrl.pathname === "/api/system/updates") {
    const force = apiUrl.searchParams.get("force") === "1";
    const now = Date.now();

    if (!force && updateCache.data && (now - updateCache.cachedAt < UPDATE_CACHE_TTL_MS)) {
      sendJson(res, 200, {
        ok: true,
        cached: true,
        current_version: localVersion,
        current_commit: localCommit,
        is_git: isGit,
        repository: repoName,
        ...updateCache.data,
      });
      return true;
    }

    let updateData = {
      update_available: false,
      latest_version: localVersion,
      latest_commit: localCommit,
      release_name: "",
      release_notes: "",
      html_url: `https://github.com/${repoName}`,
      published_at: "",
      checked_at: new Date().toISOString(),
    };

    // 1. Probar GitHub Releases
    const relRes = await fetchGithubJson(`/repos/${repoName}/releases/latest`);
    if (relRes.status === 200 && relRes.body?.tag_name) {
      const remoteTag = relRes.body.tag_name;
      const cleanRemote = remoteTag.replace(/^v/, "");
      const cleanLocal = localVersion.replace(/^v/, "");
      updateData.latest_version = remoteTag;
      updateData.release_name = relRes.body.name || remoteTag;
      updateData.release_notes = relRes.body.body || "";
      updateData.html_url = relRes.body.html_url || `https://github.com/${repoName}`;
      updateData.published_at = relRes.body.published_at || "";
      updateData.update_available = cleanRemote !== cleanLocal;
    } else {
      // 2. Si no hay release formal aún, comprobar último commit de la rama main
      const commitRes = await fetchGithubJson(`/repos/${repoName}/commits/main`);
      if (commitRes.status === 200 && commitRes.body?.sha) {
        const remoteSha = commitRes.body.sha.slice(0, 7);
        updateData.latest_commit = remoteSha;
        updateData.latest_version = remoteSha;
        updateData.release_name = commitRes.body.commit?.message?.split("\n")[0] || "Actualización disponible";
        updateData.release_notes = commitRes.body.commit?.message || "";
        updateData.html_url = commitRes.body.html_url || `https://github.com/${repoName}`;
        updateData.published_at = commitRes.body.commit?.author?.date || "";
        if (isGit && localCommit && remoteSha !== localCommit) {
          updateData.update_available = true;
        }
      }
    }

    updateCache = { data: updateData, cachedAt: now };
    sendJson(res, 200, {
      ok: true,
      cached: false,
      current_version: localVersion,
      current_commit: localCommit,
      is_git: isGit,
      repository: repoName,
      ...updateData,
    });
    return true;
  }

  // POST /api/system/update: aplicar actualización
  if (req.method === "POST" && apiUrl.pathname === "/api/system/update") {
    if (isGit) {
      return new Promise((resolve) => {
        // H1 auditoría: comprobar primero si hay cambios locales sin commitear para no destruir trabajo
        exec("git status --porcelain", { cwd: mykosRoot }, (statusErr, statusOut) => {
          if (statusErr) {
            sendJson(res, 500, {
              ok: false,
              error: `Error al comprobar estado del repositorio: ${statusErr.message}`,
            });
            return resolve(true);
          }

          if (statusOut && statusOut.trim()) {
            sendJson(res, 409, {
              ok: false,
              error: "Actualización cancelada: tienes cambios locales sin guardar en el repositorio. Haz 'git commit' o 'git stash' antes de actualizar.",
            });
            return resolve(true);
          }

          // Árbol limpio: actualizar con avance rápido seguro (--ff-only)
          exec("git pull --ff-only origin main", { cwd: mykosRoot }, (err, stdout, stderr) => {
            if (err) {
              sendJson(res, 500, {
                ok: false,
                error: `Error al actualizar código desde Git: ${stderr || err.message}`,
              });
              return resolve(true);
            }

            sendJson(res, 200, {
              ok: true,
              message: "Actualización descargada e instalada con éxito. Reiniciando MyKOS...",
              restarting: true,
              output: stdout ? stdout.trim() : "",
            });

            // Programar reinicio limpio tras responder al cliente
            setTimeout(() => {
              const restartScript = path.join(mykosRoot, "bin", "mykos");
              if (existsSync(restartScript) && process.platform !== "win32") {
                spawn("/bin/bash", ["-c", `sleep 1 && "${restartScript}" restart`], {
                  detached: true,
                  stdio: "ignore",
                }).unref();
              }
              process.exit(0);
            }, 1200);

            resolve(true);
          });
        });
      });
    }

    sendJson(res, 400, {
      ok: false,
      error: "Este método de instalación empaquetado requiere descargar el nuevo instalador.",
    });
    return true;
  }

  return false;
}

function resolveConfig(api) {
  const raw = api.pluginConfig ?? {};

  let staticRoot;
  if (typeof raw.staticDir === "string" && raw.staticDir.trim()) {
    staticRoot = path.resolve(raw.staticDir.trim());
  } else {
    const pluginDir = api.rootDir ?? (api.source ? path.dirname(api.source) : process.cwd());
    staticRoot = path.resolve(pluginDir, "..", "..", "static");
  }
  const projectDir = path.resolve(typeof raw.projectDir === "string" && raw.projectDir.trim() ? raw.projectDir.trim() : path.dirname(staticRoot));
  const gatewayPort = Number(raw.gatewayPort || process.env.MYKOS_GATEWAY_PORT || api.config?.gateway?.port || 3210);

  let gatewayStateDir = "";
  try {
    gatewayStateDir = api.runtime?.state?.resolveStateDir?.(process.env) ?? "";
  } catch {}
  gatewayStateDir = gatewayStateDir || process.env.MYKOS_GATEWAY_STATE_DIR || path.join(os.homedir(), ".mykos");

  const workspaceDir = path.resolve(
    typeof raw.workspaceDir === "string" && raw.workspaceDir.trim()
      ? raw.workspaceDir.trim()
      : (api.config?.agents?.defaults?.workspace || process.env.MYKOS_GATEWAY_WORKSPACE_DIR || process.env.MYKOS_WORKSPACE_DIR || path.join(os.homedir(), ".mykos", "workspace"))
  );

  const rawControl = raw.control && typeof raw.control === "object" ? raw.control : {};
  const configuredControlToken = typeof rawControl.token === "string" && rawControl.token.trim()
    ? rawControl.token.trim()
    : (process.env.MYKOS_CONTROL_TOKEN || "");
  const controlRegistry = (globalThis[CONTROL_REGISTRY] ??= new Map());
  const controlKey = `${projectDir}|${gatewayPort}`;
  const controlToken = configuredControlToken || controlRegistry.get(controlKey) || randomBytes(32).toString("hex");
  controlRegistry.set(controlKey, controlToken);
  // Persistir controlToken en fichero local protegido (0600) para herramientas CLI autenticadas (bin/mykos)
  for (const targetDir of [gatewayStateDir, path.join(os.homedir(), ".mykos", "gateway-state")]) {
    try {
      mkdirSync(targetDir, { recursive: true, mode: 0o700 });
      try { chmodSync(targetDir, 0o700); } catch {}
      const tokenFile = path.join(targetDir, "control.token");
      writeFileSync(tokenFile, controlToken, { mode: 0o600, encoding: "utf8" });
      chmodSync(tokenFile, 0o600);
    } catch (err) {
      if (process.env.DEBUG_MYKOS) {
        console.error(`mykos-ui: no se pudo escribir control.token en ${targetDir}:`, err.message);
      }
    }
  }
  const modelRaw = rawControl.model && typeof rawControl.model === "object" ? rawControl.model : {};
  const voiceRaw = raw.voice && typeof raw.voice === "object" ? raw.voice : {};
  const realtimeRaw = raw.realtime && typeof raw.realtime === "object" ? raw.realtime : {};
  const geminiLiveRaw = raw.geminiLive && typeof raw.geminiLive === "object" ? raw.geminiLive : {};
  const storedVoiceMode = String(realtimeRaw.mode || "").trim().toLowerCase();
  const defaultLlamaBin = process.platform === "win32" ? "llama-server.exe" : "llama-server";
  const model = {
    llamaUrl: String(modelRaw.llamaUrl || process.env.MYKOS_LLAMA_CPP_URL || "http://127.0.0.1:8091").replace(/\/+$/, ""),
    strataUrl: String(modelRaw.strataUrl || process.env.MYKOS_STRATA_URL || process.env.STRATA_URL || "http://127.0.0.1:18080").replace(/\/+$/, ""),
    ollamaUrl: String(modelRaw.ollamaUrl || process.env.OLLAMA_URL || "http://127.0.0.1:11434").replace(/\/+$/, ""),
    llamaExe: String(modelRaw.llamaExe || process.env.MYKOS_LLAMA_CPP_EXE || path.join(os.homedir(), "llama.cpp", "build", "bin", defaultLlamaBin)),
    llamaModel: String(modelRaw.llamaModel || process.env.MYKOS_LLAMA_CPP_MODEL || path.join(os.homedir(), ".ollama", "models", "blobs", "sha256-d372de8e934898a59e6ccfabc3368474711384d8f1fd4d22d87a3f0a45400cdc")),
    llamaContext: Number(modelRaw.llamaContext || process.env.MYKOS_LLAMA_CPP_CONTEXT || 32768),
    llamaStartTimeoutMs: Number(modelRaw.llamaStartTimeoutMs || 120000),
  };

  // Bucle de chat con herramientas del modelo local en el Gateway (chat-loop.js). Apagado por defecto: sin activarlo, el
  // bucle sigue siendo el de server.py, igual que antes.
  const chatLoopEnabled = Boolean(raw.chatLoop && typeof raw.chatLoop === "object" && raw.chatLoop.enabled === true);

  let backend = null;
  const b = raw.backend;
  if (b && typeof b.url === "string" && b.url.trim()) {
    let url;
    try {
      url = new URL(b.url.trim());
    } catch {
      throw new Error(`mykos-ui: backend.url no es una URL válida: «${b.url}» (se esperaba algo como http://127.0.0.1:3211)`);
    }
    const childEnv = {};
    for (const [key, value] of Object.entries(process.env)) {
      if (!/^MYKOS_/i.test(key)) childEnv[key] = value; // el backend no debe heredar el estado del Gateway
    }
    Object.assign(childEnv, {
      PYTHONUTF8: "1",
      PYTHONIOENCODING: "utf-8",
      PYTHONUNBUFFERED: "1", // sin búfer: el registro (fichero) se lee en tiempo real y no se pierde nada si el proceso muere
      MYKOS_HOST: url.hostname,
      MYKOS_PORT: url.port || "80",
      MYKOS_PUBLIC_PORT: String(gatewayPort),
      MYKOS_GATEWAY_URL: `http://127.0.0.1:${gatewayPort}`,
      MYKOS_CONTROL_URL: `http://127.0.0.1:${gatewayPort}`,
      MYKOS_CONTROL_TOKEN: controlToken,
      MYKOS_CREDENTIALS_DIR: path.join(gatewayStateDir, "mykos", "credentials"),
      MYKOS_WORKSPACE_DIR: workspaceDir,
      MYKOS_GATEWAY_WORKSPACE_DIR: workspaceDir,
      MYKOS_BACKEND_ONLY: "1",
      MYKOS_WORKER_GUARD: "1", // el trabajador exige el token del Gateway en todo /api/* (menos /api/health)
      MYKOS_GATEWAY_CHAT_LOOP: chatLoopEnabled ? "1" : "0", // el bucle del modelo local lo ejecuta el Gateway (chat-loop.js)
      MYKOS_WHISPER_MODEL: String(raw.whisperModel || process.env.MYKOS_WHISPER_MODEL || "large-v3-turbo"), // modelo Whisper local para transcripción de voz
      MYKOS_PARENT_PID: String(process.pid),
      ...(b.env && typeof b.env === "object" ? b.env : {}),
    });
    backend = {
      url: url.origin,
      spawn: b.spawn !== false,
      python: b.python || process.env.MYKOS_BACKEND_PYTHON || "python",
      script: path.resolve(b.script || path.join(projectDir, "server.py")),
      cwd: projectDir,
      logFile: path.resolve(b.logFile || path.join(projectDir, "data", "mykos-backend.log")),
      env: childEnv,
      supervision: {
        delaysMs: Array.isArray(b.supervision?.delaysMs) && b.supervision.delaysMs.length ? b.supervision.delaysMs.map(Number) : BACKOFF_MS,
        maxQuickFailures: Number(b.supervision?.maxQuickFailures) || MAX_QUICK_FAILURES,
        stableRunMs: Number(b.supervision?.stableRunMs) || STABLE_RUN_MS,
        readyTimeoutMs: Number(b.supervision?.readyTimeoutMs) || READY_TIMEOUT_MS,
      },
    };
  }

  // Almacén de datos propiedad del Gateway. Apagado por defecto: sin «store.enabled» el plugin se comporta como la v0.2.
  let store = null;
  const s = raw.store;
  if (s && s.enabled === true) {
    const stateDir = gatewayStateDir;
    store = {
      dir: path.resolve(typeof s.dir === "string" && s.dir.trim() ? s.dir.trim() : path.join(stateDir, "mykos")),
      legacyDataDir: path.resolve(typeof s.legacyDataDir === "string" && s.legacyDataDir.trim() ? s.legacyDataDir.trim() : path.join(projectDir, "data")),
      autoImport: s.autoImport !== false,
      backupsKeep: Number(s.backupsKeep) || 40,
      snapshotDays: Number(s.snapshotDays) || 14,
    };
  }

  const extraOrigins = new Set((Array.isArray(raw.allowedOrigins) ? raw.allowedOrigins : []).map((o) => String(o).toLowerCase().replace(/\/+$/, "")));
  return {
    staticRoot,
    projectDir,
    workspaceDir,
    gatewayPort,
    backend,
    store,
    gatewayStateDir,
    gatewayConfigFile: process.env.MYKOS_GATEWAY_CONFIG || path.join(gatewayStateDir, "mykos-gateway.json"),
    credentialDir: path.join(gatewayStateDir, "mykos", "credentials"),
    extraOrigins,
    // Tabla de rutas (routes.js). Estricta por defecto: lo que no está en la tabla no se reenvía al trabajador.
    // Solo las pruebas con un backend falso desactivan «strict».
    routes: { strict: !(raw.routes && typeof raw.routes === "object" && raw.routes.strict === false) },
    // Política de servicios auxiliares (policy.js). Activa por defecto: el Gateway valida y limita antes de reenviar,
    // y firma la decisión. Solo las pruebas con un backend falso la desactivan.
    policy: { strict: !(raw.policy && typeof raw.policy === "object" && raw.policy.strict === false) },
    chatLoop: { enabled: chatLoopEnabled },
    voice: {
      model: String(voiceRaw.model || process.env.MYKOS_VOICE_MODEL || "openai-codex-oauth/gpt-5.6-luna").trim(),
    },
    // Apagado por defecto: el corte de migración jamás debe activar coste/red sin una
    // credencial propia de MyKOS y una decisión explícita de Usuario.
    realtime: {
      enabled: realtimeRaw.enabled === true,
      mode: ["local", "cloud", "gemini"].includes(storedVoiceMode) ? storedVoiceMode : (realtimeRaw.enabled === true ? "cloud" : "local"),
      apiBase: String(realtimeRaw.apiBase || "https://api.openai.com").replace(/\/+$/, ""),
      model: String(realtimeRaw.model || "gpt-live-1-codex").trim(),
      voice: String(realtimeRaw.voice || "cove").trim(),
      credentialFile: path.resolve(typeof realtimeRaw.credentialFile === "string" && realtimeRaw.credentialFile.trim()
        ? realtimeRaw.credentialFile.trim()
        : path.join(gatewayStateDir, "mykos", "credentials", "openai-realtime-api-key.txt")),
      oauthFile: path.resolve(typeof realtimeRaw.oauthFile === "string" && realtimeRaw.oauthFile.trim()
        ? realtimeRaw.oauthFile.trim()
        : path.join(gatewayStateDir, "mykos", "credentials", "openai-codex", "auth.json")),
      safetyIdentifier: String(realtimeRaw.safetyIdentifier || "mykos-mykos-local").trim().slice(0, 128),
      timeoutMs: Math.max(5_000, Math.min(60_000, Number(realtimeRaw.timeoutMs) || 30_000)),
    },
    geminiLive: {
      model: String(geminiLiveRaw.model || "gemini-3.8-live").trim().slice(0, 120) || "gemini-3.8-live",
      voice: String(geminiLiveRaw.voice || "Puck").trim().slice(0, 80) || "Puck",
    },
    terminal: {
      enabled: Boolean(raw.terminal?.enabled === true || process.env.MYKOS_ENABLE_WEB_TERMINAL === "1"),
    },
    control: {
      enabled: rawControl.enabled !== false,
      token: controlToken,
      model,
      auditFile: path.resolve(typeof rawControl.auditFile === "string" && rawControl.auditFile.trim()
        ? rawControl.auditFile.trim()
        : (process.env.MYKOS_CONTROL_AUDIT_FILE || path.join(gatewayStateDir, "mykos", "control-journal.jsonl"))),
    },
  };
}

// Guarda el nuevo estado de Realtime en el fichero de configuración del Gateway, igual que
// `mykos realtime on|off` (launchers/configure-realtime.cjs) hace desde fuera. Solo persiste en
// disco para que sobreviva a un reinicio; el efecto inmediato ya lo da mutar cfg.realtime.enabled
// (mismo objeto que usa MyKOSRealtimeController, por referencia). Si falla el guardado en disco, el
// cambio en memoria se mantiene igualmente: el llamador decide si avisar de que no es permanente.
function persistVoiceMode(configFile, mode, cfg, logger) {
  try {
    const raw = JSON.parse(readFileSync(configFile, "utf8"));
    const entry = raw.plugins?.entries?.["mykos-ui"];
    if (!entry || typeof entry !== "object") throw new Error("mykos-ui no está configurado en el fichero del Gateway.");
    entry.config = entry.config && typeof entry.config === "object" ? entry.config : {};
    entry.config.realtime = {
      ...(entry.config.realtime || {}),
      enabled: mode === "cloud",
      mode,
      model: entry.config.realtime?.model || cfg.realtime.model,
      voice: entry.config.realtime?.voice || cfg.realtime.voice,
    };
    entry.config.geminiLive = {
      ...(entry.config.geminiLive || {}),
      model: cfg.geminiLive.model,
      voice: cfg.geminiLive.voice,
    };
    const backup = `${configFile}.pre-realtime.bak`;
    if (!existsSync(backup)) copyFileSync(configFile, backup);
    writeFileSync(configFile, JSON.stringify(raw, null, 2));
    return true;
  } catch (error) {
    logger?.warn?.(`mykos-ui: no se pudo guardar el modo de voz en disco (seguirá activo hasta el próximo reinicio): ${error?.message || error}`);
    return false;
  }
}

class ModelController {
  constructor(config, logger) {
    this.config = config;
    this.logger = logger;
    this.child = null;
    this.starting = null;
  }

  async upstream(url, payload, timeoutMs = 900_000) {
    const result = await jsonRequest(`${url}/v1/chat/completions`, payload, timeoutMs);
    if (result.status >= 400) {
      const message = result.body?.error?.message || result.body?.error || `el motor devolvió HTTP ${result.status}`;
      throw new Error(String(message).slice(0, 800));
    }
    return result.body;
  }

  async probeLlama() {
    const result = await probeJson(`${this.config.llamaUrl}/health`, 1_500);
    return result?.json?.status === "ok" || result?.json?.status === "loading model";
  }

  async ensureLlama() {
    if (await this.probeLlama()) return;
    if (this.starting) return this.starting;
    this.starting = (async () => {
      if (await this.probeLlama()) return;
      try {
        statSync(this.config.llamaExe);
        statSync(this.config.llamaModel);
      } catch (error) {
        throw new Error(`El motor llama.cpp no está configurado: ${error.message}`);
      }
      const target = new URL(this.config.llamaUrl);
      const args = [
        "-m", this.config.llamaModel,
        "-c", String(this.config.llamaContext),
        "-n", "8192",
        "-ngl", "20",
        "-fa", "auto",
        "--reasoning", "auto",
        "--no-webui",
        "--host", target.hostname || "127.0.0.1",
        "--port", String(target.port || 8091),
      ];
      const child = spawn(this.config.llamaExe, args, {
        cwd: path.dirname(this.config.llamaExe),
        stdio: "ignore",
        windowsHide: true,
      });
      this.child = child;
      child.once("exit", () => {
        if (this.child === child) this.child = null;
      });
      try {
        const deadline = Date.now() + this.config.llamaStartTimeoutMs;
        while (Date.now() < deadline) {
          if (child.exitCode !== null) throw new Error(`llama.cpp terminó al arrancar (código ${child.exitCode}).`);
          if (await this.probeLlama()) return;
          await sleep(500);
        }
        throw new Error("llama.cpp tardó demasiado en cargar el modelo CUDA.");
      } catch (error) {
        if (this.child === child && child.exitCode === null) killTree(child.pid);
        if (this.child === child) this.child = null;
        throw error;
      }
    })();
    try {
      await this.starting;
    } finally {
      this.starting = null;
    }
  }

  async stopLlama() {
    const child = this.child;
    this.child = null;
    if (child && child.exitCode === null) killTree(child.pid);
  }

  async unloadOllama() {
    try {
      const psRes = await probeJson(`${this.config.ollamaUrl}/api/ps`, 1_500);
      const loaded = psRes?.json?.models;
      if (Array.isArray(loaded) && loaded.length) {
        for (const m of loaded) {
          const name = m.name || m.model;
          if (name) {
            await jsonRequest(`${this.config.ollamaUrl}/api/generate`, { model: name, keep_alive: 0 }, 5_000);
          }
        }
      }
    } catch {
      // Ignorar si Ollama no responde
    }
  }

  async probeStrata() {
    const result = await probeJson(`${this.config.strataUrl}/health`, 1_500);
    return result?.json?.status === "ok" || result?.json?.status === "loading model";
  }

  async ensureStrata() {
    if (await this.probeStrata()) return;
    await this.unloadOllama();
  }

  async request(provider, payload) {
    if (provider === "llama_cpp") {
      await this.ensureLlama();
      return this.upstream(this.config.llamaUrl, payload);
    }
    if (provider === "strata") {
      await this.ensureStrata();
      return this.upstream(this.config.strataUrl, payload);
    }
    if (provider === "ollama") {
      await this.stopLlama();
      const result = await jsonRequest(`${this.config.ollamaUrl}/api/chat`, payload, 900_000);
      if (result.status >= 400) {
        const message = result.body?.error || `Ollama devolvió HTTP ${result.status}`;
        throw new Error(String(message).slice(0, 800));
      }
      return result.body;
    }
    throw new Error(`Proveedor de modelo no permitido por MyKOS Gateway: ${provider}`);
  }

  snapshot() {
    return {
      enabled: true,
      owner: "mykos-gateway",
      llamaUrl: this.config.llamaUrl,
      ollamaUrl: this.config.ollamaUrl,
      llamaProcess: this.child?.pid ?? null,
      llamaManaged: Boolean(this.child),
    };
  }

  async stop() {
    await this.stopLlama();
  }
}

class ControlPlane {
  constructor(config, logger, backendProvider, modelController, authority, chatLoopEnabled = false, storeRuntime = null) {
    this.config = config;
    this.logger = logger;
    this.backendProvider = backendProvider;
    this.model = modelController;
    this.authority = authority;
    this.chatLoopEnabled = chatLoopEnabled;
    this.storeRuntime = storeRuntime;
    this.activity = new ActivityRegistry();
  }

  /** Cliente del trabajador Python para el bucle de chat: catálogo, herramientas, acciones, actividad y guardado. */
  workerClient(meta) {
    const backend = this.backendProvider();
    if (!backend || (backend.config.spawn && backend.phase !== "up")) {
      throw new Error("El backend interno de MyKOS no está listo para el bucle de chat.");
    }
    const token = this.config.token;
    const post = (route, payload, timeoutMs = 900_000, headers = {}, signal = null) => jsonRequest(
      `${backend.config.url}/mykos-control/${route}`,
      payload,
      timeoutMs,
      { "X-MyKOS-Control-Token": token, ...headers },
      signal,
    );
    const failure = (what, result) => new Error(`${what}: ${String(result.body?.error || `el trabajador devolvió HTTP ${result.status}`).slice(0, 400)}`);
    return {
      catalog: async (model) => {
        const result = await post("catalog", model ? { model } : {}, 30_000);
        if (result.status >= 400 || !result.body?.ok) throw failure("No se pudo leer el catálogo de herramientas", result);
        return result.body;
      },
      tool: async (name, args) => {
        const result = await post("tool", { tool_name: name, arguments: args });
        controlAudit(this.config.auditFile, { event: "loop_tool", ...meta, tool: name, ok: Boolean(result.body?.ok), status: result.status });
        return isObject(result.body) ? result.body : { ok: false, error: `el trabajador devolvió HTTP ${result.status}` };
      },
      prepare: async (name, args) => {
        const result = await post("prepare", { tool_name: name, arguments: args }, 60_000);
        return isObject(result.body) ? result.body : { ok: false, error: `el trabajador devolvió HTTP ${result.status}` };
      },
      action: async (action, conversationId, authorization) => {
        const payload = { action, conversation_id: conversationId, authorization: isObject(authorization) ? authorization : {} };
        // El trabajador ejecuta una acción solo si trae la firma del Gateway sobre el cuerpo exacto que recibe.
        const signature = actionRouteSignature(token, Buffer.from(JSON.stringify(payload), "utf8"));
        const result = await post("action", payload, 900_000, { "X-MyKOS-Gateway-Action": signature });
        controlAudit(this.config.auditFile, { event: "loop_action", ...meta, action: String(action?.kind || ""), ok: Boolean(result.body?.ok), status: result.status });
        return isObject(result.body) ? result.body : { ok: false, error: `el trabajador devolvió HTTP ${result.status}` };
      },
      activity: async (activityId, update) => {
        this.activity.update(activityId, update);
      },
      saveMessage: async (conversationId, message) => {
        if (isObject(message) && !String(message.message_id || "").trim()) {
          message.message_id = randomUUID().replace(/-/g, "");
        }
        const convState = conversationStore(this.storeRuntime);
        if (convState && convState.data) {
          const { store: convStoreObj, data: convData } = convState;
          const conv = conversationById(convData, conversationId);
          if (conv) {
            conv.messages = Array.isArray(conv.messages) ? conv.messages : [];
            conv.messages.push(message);
            conv.updated_at = utcNow();
            saveConversations(convStoreObj, convData, "gateway.chat.intermediate");
          }
        }
        return message;
      },
      remoteModel: async (model, messages, conversationId, generation, signal, permissionMode = "supervisado") => {
        const result = await post("remote-model", {
          model,
          messages,
          conversation_id: conversationId,
          supports_vision: false,
          generation: isObject(generation) ? generation : {},
          activity_id: `voice_${String(meta.call_id || "")}`,
          permission_mode: permissionMode,
        }, 900_000, {}, signal);
        if (result.status >= 400 || !isObject(result.body)) throw failure("No se pudo consultar el modelo de voz", result);
        return result.body;
      },
      tts: async (text, voice = "em_alex", signal) => {
        const result = await post("tts", { text, voice }, 120_000, {}, signal);
        if (result.status >= 400 || !result.body?.ok) throw failure("No se pudo sintetizar la frase", result);
        return result.body;
      },
    };
  }

  async resolveApprovalWithWorker(approvalId, decision, permissionMode) {
    return this.authority.resolveApproval(
      approvalId,
      decision,
      String(permissionMode || "once").trim().toLowerCase(),
      async (action, conversationId, record) => {
        const backend = this.backendProvider();
        if (!backend || (backend.config.spawn && backend.phase !== "up")) {
          throw new Error("El backend interno de MyKOS no está listo para ejecutar la aprobación.");
        }
        const descriptor = this.authority.descriptor(String(action?.kind || ""), action);
        const forwarded = await jsonRequest(
          `${backend.config.url}/mykos-control/action`,
          {
            action,
            conversation_id: conversationId,
            authorization: {
              gateway_execution_grant: executionGrant(this.config.token, record?.id, conversationId, descriptor),
            },
          },
          900_000,
          { "X-MyKOS-Control-Token": this.config.token },
        );
        if (forwarded.status >= 400 || !isObject(forwarded.body)) {
          throw new Error(String(forwarded.body?.error || `el trabajador devolvió HTTP ${forwarded.status}`));
        }
        return forwarded.body;
      },
    );
  }

  authorized(req, extraOrigins) {
    if (!isOwnRequest(req, extraOrigins)) return false;
    const provided = Buffer.from(String(req.headers["x-mykos-control-token"] ?? ""), "utf8");
    const expected = Buffer.from(String(this.config.token ?? ""), "utf8");
    return provided.length > 0 && provided.length === expected.length && timingSafeEqual(provided, expected);
  }

  async handle(req, res, extraOrigins) {
    if (!this.authorized(req, extraOrigins)) {
      sendJson(res, 403, { ok: false, error: "forbidden", message: "El plano de control solo acepta peticiones internas autenticadas." });
      return;
    }
    const pathName = new URL(req.url ?? "/", "http://127.0.0.1").pathname;
    const operation = pathName.slice(CONTROL_PREFIX.length).replace(/\/+$/, "");
    if (operation === "status") {
      if (!onlyGetHead(req, res)) return;
      sendJson(res, 200, { ok: true, control: "mykos-gateway", model: this.model.snapshot() });
      return;
    }
    if (req.method !== "POST") {
      res.setHeader("Allow", "POST");
      sendJson(res, 405, { ok: false, error: "method_not_allowed" });
      return;
    }
    const raw = await readBody(req, MAX_CHUNKED_BODY_BYTES);
    let body;
    try {
      body = JSON.parse(raw.toString("utf8"));
    } catch {
      sendJson(res, 400, { ok: false, error: "bad_json" });
      return;
    }
    const meta = {
      operation,
      provider: typeof body?.provider === "string" ? body.provider : "",
      tool: typeof body?.tool_name === "string" ? body.tool_name : String(body?.action?.kind || ""),
      conversation_id: typeof body?.conversation_id === "string" ? body.conversation_id : "",
    };
    controlAudit(this.config.auditFile, { event: "control_request", ...meta });
    try {
      if (operation === "authorize") {
        if (!this.authority) throw new Error("La autoridad de permisos del Gateway no está disponible.");
        const action = body?.action;
        if (!action || typeof action !== "object" || Array.isArray(action)) {
          sendJson(res, 400, { ok: false, error: "Falta la acción a autorizar." });
          return;
        }
        const toolName = String(body?.tool_name || action.kind || "");
        const sessionId = String(body?.conversation_id || "");
        if (body?.auto_grant === true) {
          const descriptor = this.authority.descriptor(toolName, action);
          const grant = this.authority.grant(toolName, action, sessionId);
          const result = grant
            ? { ok: true, decision: "granted", descriptor, grant, authorization: { permission_id: grant.id, scope_key: descriptor.scope_key } }
            : { ok: true, decision: "approval_required", descriptor };
          controlAudit(this.config.auditFile, { event: "control_result", ...meta, ok: true, decision: result.decision, auto_grant: true });
          sendJson(res, 200, result);
          return;
        }
        const result = this.authority.authorize(toolName, action, sessionId);
        controlAudit(this.config.auditFile, { event: "control_result", ...meta, ok: true, decision: result.decision });
        sendJson(res, 200, result);
        return;
      }
      if (operation === "approval") {
        if (!this.authority) throw new Error("La autoridad de aprobaciones del Gateway no está disponible.");
        const subOperation = String(body?.operation || "").trim();
        if (subOperation === "create") {
          const result = this.authority.createApproval(body);
          controlAudit(this.config.auditFile, { event: "control_result", ...meta, ok: true, approval_operation: subOperation });
          sendJson(res, 200, result);
          return;
        }
        if (subOperation === "list") {
          const result = { ok: true, approvals: this.authority.listApprovals(String(body?.conversation_id || "")) };
          sendJson(res, 200, result);
          return;
        }
        if (subOperation === "resolve") {
          const approvalId = String(body?.approval_id || "").trim();
          const decision = String(body?.decision || "").trim();
          if (!approvalId || !["approve", "reject"].includes(decision)) {
            sendJson(res, 400, { ok: false, error: "Falta la aprobación o la decisión válida." });
            return;
          }
          const result = await this.resolveApprovalWithWorker(approvalId, decision, body?.permission_mode);
          const status = Number(result.status) || (result.ok ? 200 : 409);
          controlAudit(this.config.auditFile, { event: "control_result", ...meta, ok: Boolean(result.ok), approval_operation: subOperation, decision });
          sendJson(res, status, result);
          return;
        }
        sendJson(res, 400, { ok: false, error: "Operación de aprobación no válida." });
        return;
      }
      if (operation === "permissions") {
        if (!this.authority) throw new Error("La autoridad de permisos del Gateway no está disponible.");
        const subOperation = String(body?.operation || "list").trim();
        if (subOperation === "list") {
          sendJson(res, 200, { ok: true, permissions: this.authority.listPermissions(String(body?.conversation_id || "")) });
          return;
        }
        if (subOperation === "audit") {
          sendJson(res, 200, { ok: true, audit: this.authority.listAudit(body?.limit, String(body?.conversation_id || "")) });
          return;
        }
        if (subOperation === "revoke") {
          const revoked = this.authority.revoke(String(body?.permission_id || ""));
          if (!revoked) {
            sendJson(res, 404, { ok: false, error: "El permiso no existe, ya está revocado o ya no está activo." });
            return;
          }
          sendJson(res, 200, { ok: true, revoked: true, permission: revoked });
          return;
        }
        sendJson(res, 400, { ok: false, error: "Operación de permisos no válida." });
        return;
      }
      if (operation === "context") {
        const context = prepareContext(body?.system_prompt, body?.context, body?.generation);
        sendJson(res, 200, { ok: true, ...context });
        return;
      }
      if (operation === "activity") {
        const subOperation = String(body?.operation || "update").trim();
        const activityId = String(body?.activity_id || body?.id || "").trim();
        if (!activityId) {
          sendJson(res, 400, { ok: false, error: "Falta activity_id." });
          return;
        }
        if (subOperation === "start") {
          this.activity.start({
            id: activityId,
            conversationId: String(body?.conversation_id || ""),
            model: String(body?.model || ""),
            modelLabel: String(body?.model_label || "Modelo"),
            providerLabel: String(body?.provider_label || "Ollama local"),
            remote: Boolean(body?.remote),
            location: String(body?.location || (body?.remote ? "remoto" : "local")),
          });
        } else if (subOperation === "finish") {
          this.activity.finish(activityId);
        } else if (subOperation === "update") {
          this.activity.update(activityId, body);
        } else {
          sendJson(res, 400, { ok: false, error: "Operación de actividad no válida." });
          return;
        }
        const result = this.activity.view({ activityId, conversationId: String(body?.conversation_id || "") });
        controlAudit(this.config.auditFile, { event: "control_result", ...meta, ok: true, activity_operation: subOperation });
        sendJson(res, 200, result);
        return;
      }
      if (operation === "remote-model") {
        const modelName = String(body?.model || "").trim();
        const allowed = isRemoteModelName(modelName);
        if (!allowed || !Array.isArray(body?.messages)) {
          sendJson(res, 400, { ok: false, error: "Modelo remoto o contexto no permitido por MyKOS Gateway." });
          return;
        }
        const backend = this.backendProvider();
        if (!backend || (backend.config.spawn && backend.phase !== "up")) {
          throw new Error("El backend interno de MyKOS no está listo para el proveedor remoto.");
        }
        const status = await proxyRequest(req, res, backend.config.url, raw);
        controlAudit(this.config.auditFile, { event: "control_result", ...meta, ok: status < 400, status, model: modelName });
        return;
      }
      if (operation === "model") {
        const provider = String(body?.provider || "").trim();
        if (!body?.payload || typeof body.payload !== "object" || Array.isArray(body.payload)) {
          sendJson(res, 400, { ok: false, error: "Falta payload de modelo." });
          return;
        }
        const result = await this.model.request(provider, body.payload);
        controlAudit(this.config.auditFile, { event: "control_result", ...meta, ok: true });
        sendJson(res, 200, result);
        return;
      }
      if (operation === "loop") {
        // Bucle de chat con herramientas del modelo local (chat-loop.js): el Gateway decide cada paso y el trabajador
        // Python solo ejecuta lo que se le pide. Solo modelos locales; los remotos tienen su propia ruta.
        if (!this.chatLoopEnabled) {
          sendJson(res, 409, { ok: false, error: "El bucle de chat del Gateway está apagado (chatLoop.enabled)." });
          return;
        }
        if (!this.authority) throw new Error("La autoridad de permisos del Gateway no está disponible.");
        const modelName = String(body?.model || "").trim();
        if (!modelName || !Array.isArray(body?.messages) || isRemoteModelName(modelName)) {
          sendJson(res, 400, { ok: false, error: "El bucle de chat del Gateway necesita un modelo local y el contexto." });
          return;
        }
        const result = await runChatLoop(body, {
          model: this.model,
          authority: this.authority,
          worker: this.workerClient(meta),
          now: utcNow,
        });
        controlAudit(this.config.auditFile, {
          event: "control_result",
          ...meta,
          ok: true,
          tools_used: result.tools_used,
          pending_approval: Boolean(result.pending_action),
        });
        sendJson(res, 200, result);
        return;
      }
      if (operation === "tool" || operation === "action") {
        const backend = this.backendProvider();
        if (!backend || (backend.config.spawn && backend.phase !== "up")) {
          throw new Error("El backend interno de MyKOS no está listo para ejecutar el control solicitado.");
        }
        // «tool» y «action» reenvían el cuerpo EXACTO a server.py, cuyo read_json() rechaza más de 2 MB sin leerlos.
        // El plano de control acepta hasta 40 MB (contexto de conversación largo en otras operaciones), así que sin
        // este aviso Python cortaba la lectura a mitad de una subida de 3 MB: la conexión se reseteaba y el cliente
        // veía un 502 «no responde» en vez de un rechazo limpio.
        if (raw.length > MAX_JSON_API_BYTES) {
          controlAudit(this.config.auditFile, { event: "control_result", ...meta, ok: false, error: "body_too_large" });
          sendJson(res, 413, { ok: false, error: `El cuerpo de esta operación no puede pasar de ${MAX_JSON_API_BYTES} bytes.` });
          return;
        }
        if (operation === "action") {
          if (!this.authority) {
            sendJson(res, 503, { ok: false, error: "La autoridad de permisos del Gateway no está disponible." });
            return;
          }
          const action = body?.action;
          const authorization = body?.authorization;
          const verified = this.authority.verifyAuthorization(String(action?.kind || ""), action, String(body?.conversation_id || ""), authorization);
          if (!verified.ok) {
            controlAudit(this.config.auditFile, {
              event: "permission_denied",
              ...meta,
              ok: false,
              reason: verified.error || "action_not_authorized",
              action: String(action?.kind || ""),
            });
            sendJson(res, 403, verified);
            return;
          }
          const status = await proxyRequest(
            req,
            res,
            backend.config.url,
            raw,
            null,
            { "X-MyKOS-Gateway-Action": actionRouteSignature(this.config.token, raw) },
          );
          if (verified.grant) this.authority.audit("permission_used", verified.descriptor, { permission_id: verified.grant.id, session_id: String(body?.conversation_id || ""), status: status < 400 ? "ok" : "failed" });
          controlAudit(this.config.auditFile, { event: "permission_execution", ...meta, ok: status < 400, status });
          return;
        }
        const status = await proxyRequest(req, res, backend.config.url, raw);
        controlAudit(this.config.auditFile, { event: "control_result", ...meta, ok: status < 400, status });
        return;
      }
      sendJson(res, 404, { ok: false, error: "control_route_not_found" });
    } catch (error) {
      controlAudit(this.config.auditFile, { event: "control_result", ...meta, ok: false, error: String(error?.message || error).slice(0, 500) });
      sendJson(res, 502, { ok: false, error: String(error?.message || error).slice(0, 800) });
    }
  }
}

// ───────────────────────────── backend Python supervisado ─────────────────────────────

function killTree(pid) {
  if (!pid) return;
  try {
    if (process.platform === "win32") {
      spawnSync("taskkill", ["/pid", String(pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
    } else {
      process.kill(pid, "SIGTERM");
    }
  } catch {}
}

function isSameOrChildProcess(childPid, health) {
  if (!childPid || !health) return true;
  if (health.pid === childPid) return true;
  if (health.ppid && health.ppid === childPid) return true;
  if (process.platform === "win32") {
    try {
      const res = spawnSync("powershell.exe", [
        "-NoProfile",
        "-Command",
        `(Get-CimInstance Win32_Process -Filter "ProcessId = ${health.pid}").ParentProcessId`
      ], { encoding: "utf8", windowsHide: true, timeout: 2000 });
      const ppid = parseInt(res.stdout?.trim(), 10);
      return ppid === childPid;
    } catch {
      return false;
    }
  }
  return false;
}

function rotateLog(logFile) {
  try {
    if (statSync(logFile).size > LOG_ROTATE_BYTES) renameSync(logFile, `${logFile}.1`);
  } catch {}
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class Backend {
  constructor(config, logger, envProvider = null) {
    this.config = config; // { url, spawn, python, script, cwd, logFile, env }
    this.logger = logger;
    this.envProvider = envProvider; // () => entorno extra para el backend (p. ej. el del almacén), calculado en cada start()
    this.extraEnv = {};
    this.phase = "stopped"; // stopped | starting | up | restarting | failed
    this.child = null;
    this.backendPid = null;
    this.restarts = 0;
    this.quickFailures = 0;
    this.lastError = "";
    this.startedAt = 0;
    this.stopping = true;
    this.timer = null;
    this.ctx = null;
  }

  info(message) {
    this.logger?.info?.(`mykos-ui: ${message}`);
  }

  async start(ctx) {
    const previous = globalThis[ACTIVE_BACKEND];
    if (previous && previous !== this) await previous.stop(); // una recarga del plugin no puede dejar dos backends
    globalThis[ACTIVE_BACKEND] = this;
    this.ctx = ctx ?? null;
    this.stopping = false;
    this.restarts = 0;
    this.quickFailures = 0;
    this.lastError = "";
    try {
      this.extraEnv = this.envProvider ? this.envProvider() : {};
    } catch (error) {
      this.extraEnv = {};
      this.logger?.error?.(`mykos-ui: no se pudo preparar el entorno extra del backend: ${error.message}`);
    }
    this.spawnChild();
  }

  spawnChild() {
    if (this.stopping) return;
    const { python, script, cwd, logFile } = this.config;
    const env = { ...this.config.env, ...this.extraEnv };
    this.phase = this.restarts === 0 ? "starting" : "restarting";
    let fd;
    try {
      mkdirSync(path.dirname(logFile), { recursive: true });
      rotateLog(logFile);
      fd = openSync(logFile, "a");
    } catch (error) {
      this.fail(`No se puede abrir el registro ${logFile}: ${error.message}`);
      return;
    }
    let child;
    try {
      child = spawn(python, [script], { cwd, env, stdio: ["ignore", fd, fd], windowsHide: true });
    } catch (error) {
      closeSync(fd);
      this.fail(`No se pudo lanzar Python (${python}): ${error.message}`);
      return;
    }
    closeSync(fd); // el hijo ya tiene su propia copia del descriptor
    this.child = child;
    this.startedAt = 0;
    child.once("error", (error) => this.onExit(child, null, `error: ${error.code ?? error.message}`));
    child.once("exit", (code, signal) => this.onExit(child, code, signal ? `señal ${signal}` : `código ${code}`));
    this.info(`arrancando el backend (PID ${child.pid}, ${this.config.url}); registro en ${logFile}`);
    void this.waitUntilReady(child);
  }

  async waitUntilReady(child) {
    const { readyTimeoutMs } = this.config.supervision;
    const deadline = Date.now() + readyTimeoutMs;
    while (Date.now() < deadline && !this.stopping && this.child === child) {
      const probe = await probeJson(`${this.config.url}/api/health`);
      const health = probe?.json;
      if (health?.service === "mykos-backend") {
        if (isSameOrChildProcess(child.pid, health)) {
          this.backendPid = health.pid;
          this.phase = "up";
          this.startedAt = Date.now();
          this.ctx?.serviceHealth?.clearFailure?.();
          this.info(`backend listo (PID ${child.pid}${health.pid !== child.pid ? `, Python PID ${health.pid}` : ""})`);
          return;
        }
        this.fail(`El puerto ${new URL(this.config.url).port} lo ocupa otro backend de MyKOS (PID ${health.pid}); ciérralo con «mykos stop».`);
        killTree(child.pid);
        return;
      }
      await sleep(300);
    }
    if (!this.stopping && this.child === child && this.phase !== "up") {
      this.fail(`El backend no respondió en ${readyTimeoutMs / 1000} s; revisa ${this.config.logFile}`);
      killTree(child.pid);
    }
  }

  onExit(child, code, reason) {
    if (this.child !== child) return; // proceso antiguo o ya gestionado
    this.child = null;
    if (this.stopping) {
      this.phase = "stopped";
      return;
    }
    if (this.phase === "failed") return;
    const { delaysMs, maxQuickFailures, stableRunMs } = this.config.supervision;
    const ranMs = this.startedAt ? Date.now() - this.startedAt : 0;
    this.quickFailures = ranMs >= stableRunMs ? 1 : this.quickFailures + 1;
    const why = String(reason).startsWith("error: ENOENT") ? `no se encuentra el ejecutable de Python «${this.config.python}»` : reason;
    this.lastError = `el backend terminó (${why}); registro: ${this.config.logFile}`;
    if (this.quickFailures > maxQuickFailures) {
      this.fail(`El backend se cae al arrancar (${maxQuickFailures} intentos seguidos; último motivo: ${why}); revisa ${this.config.logFile}`);
      return;
    }
    const delay = delaysMs[Math.min(this.quickFailures - 1, delaysMs.length - 1)];
    this.phase = "restarting";
    this.restarts += 1;
    this.logger?.warn?.(`mykos-ui: ${this.lastError}; reintento en ${delay / 1000} s`);
    this.timer = setTimeout(() => {
      this.timer = null;
      this.spawnChild();
    }, delay);
    this.timer.unref?.();
  }

  fail(message) {
    this.phase = "failed";
    this.lastError = message;
    this.logger?.error?.(`mykos-ui: ${message}`);
    this.ctx?.serviceHealth?.reportFailure?.(new Error(message));
  }

  async stop() {
    this.stopping = true;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    const child = this.child;
    if (child && child.exitCode === null) {
      if (this.backendPid && process.platform === "win32") {
        killTree(this.backendPid);
      }
      killTree(child.pid);
      for (let i = 0; i < 50 && child.exitCode === null && child.signalCode === null; i += 1) await sleep(100);
      this.info(`backend detenido (PID ${child.pid})`);
    }
    this.child = null;
    this.backendPid = null;
    this.phase = "stopped";
    if (globalThis[ACTIVE_BACKEND] === this) globalThis[ACTIVE_BACKEND] = null;
  }

  /** Estado para /mykos-health, con una sonda real al backend. */
  async snapshot() {
    const probe = await probeJson(`${this.config.url}/api/health`);
    const health = probe?.json?.service === "mykos-backend" ? probe.json : null;
    const pidMatches = isSameOrChildProcess(this.child?.pid, health);
    return {
      configured: true,
      spawn: this.config.spawn,
      url: this.config.url,
      phase: this.config.spawn ? this.phase : "external",
      pid: this.child?.pid ?? null,
      restarts: this.restarts,
      uptimeSec: this.phase === "up" && this.startedAt ? Math.round((Date.now() - this.startedAt) / 1000) : 0,
      reachable: Boolean(health),
      up: Boolean(health) && pidMatches && (!this.config.spawn || this.phase === "up"),
      backendPid: health?.pid ?? null,
      lastError: this.lastError,
      logFile: this.config.logFile,
    };
  }
}

// ───────────────────────────── almacén de datos (fase 2) ─────────────────────────────

/** Un único almacén por carpeta en todo el proceso: register() se ejecuta varias veces y no puede duplicarlo. */
function acquireStore(cfg, logger) {
  const registry = (globalThis[STORE_REGISTRY] ??= new Map());
  let store = registry.get(cfg.dir);
  if (!store) {
    store = new DocumentStore({ dir: cfg.dir, logger, backupsKeep: cfg.backupsKeep, snapshotDays: cfg.snapshotDays });
    registry.set(cfg.dir, store);
  } else {
    store.logger = logger;
  }
  return store;
}

/**
 * Prepara el almacén antes de arrancar el backend y devuelve el entorno que se le pasa:
 *   - importa (todo o nada) los ficheros antiguos de data/ si aún no están en el almacén;
 *   - si algo falla, NO activa el almacén: el backend sigue con sus ficheros de siempre y el motivo queda en /mykos-health.
 */
function prepareStore(runtime, gatewayPort, logger) {
  const fileMode = { MYKOS_STORE_MODE: "file" };
  if (!runtime) return fileMode;
  const state = storeState(runtime);
  state.active = false;
  try {
    const { store } = runtime;
    store.ensure();
    const results = runtime.autoImport ? store.importAll(runtime.legacyDir) : [];
    const failed = results.filter((r) => r.status === "failed");
    if (failed.length) {
      state.error = `la importación de los datos antiguos falló (${failed.map((f) => `${f.name}: ${f.error}`).join("; ")}); se siguen usando los ficheros de data/ y no se ha tocado nada`;
      logger?.error?.(`mykos-ui: almacén desactivado: ${state.error}`);
      return fileMode;
    }
    // A clean installation must own empty documents too; otherwise the UI falls through to removed worker routes.
    const emptyDocs = {
      conversations: { conversations: [] }, memory: { entries: [] }, "memory-index": { entries: {} },
      permissions: { grants: [], audit: [] }, approvals: { approvals: [] },
      automations: { automations: [], events: [] }, subagents: { jobs: [] }, nodes: { nodes: [] },
    };
    for (const [name, data] of Object.entries(emptyDocs)) {
      if (!store.get(name)) store.put(name, data, { source: "clean-install" });
    }
    state.active = true;
    state.error = "";
    logger?.info?.(`mykos-ui: almacén activo en ${store.dir} (${store.list().filter((d) => d.exists).map((d) => `${d.name} r${d.revision}`).join(", ") || "vacío"})`);
    return { MYKOS_STORE_MODE: "gateway", MYKOS_STORE_URL: `http://127.0.0.1:${gatewayPort}`, MYKOS_STORE_TOKEN: store.token };
  } catch (error) {
    state.error = `no se pudo preparar el almacén: ${error.message}; se siguen usando los ficheros de data/`;
    logger?.error?.(`mykos-ui: almacén desactivado: ${state.error}`);
    return fileMode;
  }
}

/** Copia una sola vez las credenciales propias de MyKOS al estado del Gateway. */
function prepareCredentials(projectDir, targetDir, logger) {
  const legacyDir = path.join(projectDir, "data", "oauth");
  try {
    mkdirSync(targetDir, { recursive: true });
    if (existsSync(legacyDir) && readdirSync(targetDir).length === 0) {
      cpSync(legacyDir, targetDir, { recursive: true, force: false, errorOnExist: false });
      logger?.info?.("mykos-ui: credenciales MyKOS copiadas al estado privado del Gateway");
    }
    return targetDir;
  } catch (error) {
    logger?.error?.(`mykos-ui: no se pudo preparar el almacén privado de credenciales: ${error.message}`);
    return legacyDir;
  }
}

/** El estado (activo / motivo) vive en el propio almacén, para que lo compartan todos los registros del plugin. */
function storeState(runtime) {
  return (runtime.store.state ??= { active: false, error: "" });
}

/** Resumen para /mykos-health. */
function storeSnapshot(runtime) {
  const { store } = runtime;
  const state = storeState(runtime);
  try {
    store.ensure();
    return {
      enabled: true,
      active: state.active,
      error: state.error,
      dir: store.dir,
      docs: store.list(),
      imports: store.imports.map(({ name, status, count, revision, error }) => ({ name, status, count, revision, error })),
    };
  } catch (error) {
    return { enabled: true, active: false, error: `no se puede leer el almacén: ${error.message}`, dir: store.dir, docs: [], imports: [] };
  }
}

function callPath(pathname) {
  try {
    let match = /^\/api\/sessions\/([^/]+)\/calls$/.exec(pathname);
    if (match) return { kind: "create", sessionId: decodeURIComponent(match[1]) };
    match = /^\/api\/calls\/([^/]+)\/(turn|interrupt|transcript)$/.exec(pathname);
    if (match) return { kind: match[2], callId: decodeURIComponent(match[1]) };
    match = /^\/api\/calls\/([^/]+)$/.exec(pathname);
    if (match) return { kind: "call", callId: decodeURIComponent(match[1]) };
  } catch {
    return null;
  }
  return null;
}

async function handleCallApi(req, res, route, registry, voiceEngine) {
  try {
    if (route.kind === "create") {
      if (req.method !== "POST") return false;
      const declared = Number(req.headers["content-length"]);
      if (Number.isFinite(declared) && declared > 16 * 1024) {
        sendJson(res, 413, { error: "El cuerpo de la llamada no puede pasar de 16 KB." });
        return true;
      }
      let payload = {};
      if (declared > 0 || req.headers["transfer-encoding"]) {
        const raw = await readBody(req, 16 * 1024);
        try { payload = raw.length ? JSON.parse(raw.toString("utf8")) : {}; } catch { sendJson(res, 400, { error: "El cuerpo de la llamada no es JSON válido." }); return true; }
        if (!isObject(payload)) { sendJson(res, 400, { error: "El cuerpo de la llamada debe ser un objeto JSON." }); return true; }
      }
      const call = registry.create({ sessionId: route.sessionId, model: payload.model });
      sendJson(res, 201, { ok: true, ...call });
      return true;
    }
    if (route.kind === "interrupt") {
      if (req.method !== "POST") return false;
      sendJson(res, 200, { ok: true, ...voiceEngine.interrupt(route.callId) });
      return true;
    }
    if (route.kind === "transcript") {
      if (req.method !== "POST") return false;
      const raw = await readBody(req, 16 * 1024);
      let payload;
      try { payload = raw.length ? JSON.parse(raw.toString("utf8")) : {}; } catch { sendJson(res, 400, { error: "La transcripción no es JSON válido." }); return true; }
      if (!isObject(payload)) { sendJson(res, 400, { error: "La transcripción debe ser un objeto JSON." }); return true; }
      sendJson(res, 200, { ok: true, ...registry.appendTranscript(route.callId, payload) });
      return true;
    }
    if (route.kind === "turn") {
      if (req.method !== "POST") return false;
      const declared = Number(req.headers["content-length"]);
      if (Number.isFinite(declared) && declared > 64 * 1024) {
        sendJson(res, 413, { error: "El turno de voz no puede pasar de 64 KB." });
        return true;
      }
      const raw = await readBody(req, 64 * 1024);
      let payload;
      try { payload = raw.length ? JSON.parse(raw.toString("utf8")) : {}; } catch { sendJson(res, 400, { error: "El turno de voz no es JSON válido." }); return true; }
      if (!isObject(payload)) { sendJson(res, 400, { error: "El turno de voz debe ser un objeto JSON." }); return true; }

      if (payload.stream !== true) {
        // Camino clásico: una respuesta JSON de una sola vez, igual que siempre.
        const result = await voiceEngine.turn(route.callId, payload);
        sendJson(res, 200, result);
        return true;
      }

      // Camino nuevo, opt-in con {"stream": true}: NDJSON por partes, una línea por
      // frase en cuanto está lista, para que el navegador pueda reproducirla sin
      // esperar a que termine de sintetizarse la respuesta entera.
      res.statusCode = 200;
      res.setHeader("Content-Type", "application/x-ndjson; charset=utf-8");
      for (const [key, value] of Object.entries(BASE_HEADERS)) res.setHeader(key, value);
      const writeLine = (obj) => { if (!res.destroyed) res.write(`${JSON.stringify(obj)}\n`); };
      try {
        const result = await voiceEngine.turn(route.callId, {
          ...payload,
          onPhrase: async (piece) => { writeLine({ type: "phrase", ...piece }); },
        });
        writeLine({ type: "done", ...result });
      } catch (error) {
        if (error instanceof CallError || error instanceof VoiceEngineError) {
          writeLine({ type: "error", error: error.code, message: error.message, ...(error.details || {}) });
        } else {
          writeLine({ type: "error", error: "voice_turn_failed", message: String(error?.message || error) });
        }
      } finally {
        if (!res.destroyed) res.end();
      }
      return true;
    }
    if (req.method === "GET") {
      sendJson(res, 200, { ok: true, ...registry.get(route.callId) });
      return true;
    }
    if (req.method === "DELETE") {
      sendJson(res, 200, { ok: true, ...registry.end(route.callId) });
      return true;
    }
    return false;
  } catch (error) {
    if (error instanceof CallError) {
      sendJson(res, error.status, { ok: false, error: error.code, message: error.message });
      return true;
    }
    if (error instanceof VoiceEngineError) {
      sendJson(res, error.status, { ok: false, error: error.code, message: error.message, ...error.details });
      return true;
    }
    throw error;
  }
}

/** Crea una sesión WebRTC de OpenAI Realtime sin exponer la credencial de MyKOS. */
async function handleRealtimeApi(req, res, sessionId, realtime) {
  if (req.method !== "POST") return false;
  const declared = Number(req.headers["content-length"]);
  if (Number.isFinite(declared) && declared > 300 * 1024) {
    sendJson(res, 413, { error: "La oferta WebRTC no puede pasar de 300 KB." });
    return true;
  }
  let payload;
  try {
    payload = JSON.parse((await readBody(req, 300 * 1024)).toString("utf8"));
  } catch {
    sendJson(res, 400, { error: "La sesión Realtime debe contener JSON válido." });
    return true;
  }
  if (!isObject(payload)) {
    sendJson(res, 400, { error: "La sesión Realtime debe ser un objeto JSON." });
    return true;
  }
  try {
    const result = await realtime.create({ sessionId, sdp: payload.sdp, model: payload.model, voice: payload.voice });
    sendJson(res, 201, result);
  } catch (error) {
    if (error instanceof RealtimeError || error instanceof CallError) {
      sendJson(res, error.status, { ok: false, error: error.code, message: error.message });
    } else throw error;
  }
  return true;
}

/**
 * Prepara una llamada Gemini Live. El token que devuelve el backend es efímero,
 * de un solo uso y es lo único que recibe el navegador; la API key de MyKOS no
 * sale nunca de su proceso Python.
 */
async function handleGeminiLiveApi(req, res, sessionId, cfg, registry) {
  if (req.method !== "POST") return false;
  const declared = Number(req.headers["content-length"]);
  if (Number.isFinite(declared) && declared > 2048) {
    sendJson(res, 413, { ok: false, error: "La preparación de Gemini Live no admite datos adicionales." });
    return true;
  }
  try {
    const raw = (await readBody(req, 2048)).toString("utf8").trim();
    if (raw) {
      const payload = JSON.parse(raw);
      if (!isObject(payload) || Object.keys(payload).length) {
        sendJson(res, 400, { ok: false, error: "Gemini Live usa la configuración privada de MyKOS." });
        return true;
      }
    }
  } catch {
    sendJson(res, 400, { ok: false, error: "La preparación de Gemini Live debe contener JSON válido." });
    return true;
  }

  let created;
  try {
    created = registry.create({ sessionId, model: `gemini/${cfg.geminiLive.model}` });
    const provisioned = await jsonRequest(
      `${cfg.backend.url}/mykos-control/gemini-live/token`,
      { model: cfg.geminiLive.model, voice: cfg.geminiLive.voice },
      25_000,
      { "X-MyKOS-Control-Token": cfg.control.token },
    );
    const token = typeof provisioned.body?.token === "string" ? provisioned.body.token.trim() : "";
    if (provisioned.status >= 400 || !token.startsWith("auth_tokens/")) {
      const message = String(provisioned.body?.error || "MyKOS no pudo preparar la llamada Gemini Live.").slice(0, 800);
      registry.setState(created.callId, "error", { error: message });
      sendJson(res, provisioned.status >= 400 && provisioned.status < 500 ? provisioned.status : 502, {
        ok: false,
        error: "gemini_live_unavailable",
        message,
      });
      return true;
    }
    const call = registry.setState(created.callId, "active", {
      connection: { transport: "websocket", audio: true, realtime: true, provider_session_id: "pending" },
    });
    sendJson(res, 201, {
      ok: true,
      call,
      session: { model: cfg.geminiLive.model, voice: cfg.geminiLive.voice },
      transport: {
        type: "websocket",
        endpoint: "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained",
        token,
      },
    });
  } catch (error) {
    if (created?.callId) {
      try { registry.setState(created.callId, "error", { error: String(error?.message || error).slice(0, 300) }); } catch {}
    }
    if (error instanceof CallError) sendJson(res, error.status, { ok: false, error: error.code, message: error.message });
    else sendJson(res, 503, { ok: false, error: "gemini_live_unavailable", message: "No se pudo preparar la llamada Gemini Live." });
  }
  return true;
}

/**
 * El navegador retransmite la llamada de función de Gemini, pero jamás recibe permiso
 * para ejecutar nada: esta ruta la valida contra el registro de llamadas y solo deja
 * pasar la lista blanca definida en gemini-live-tools.js.
 */
async function handleGeminiLiveToolsApi(req, res, callId, registry, controlPlane) {
  if (req.method !== "POST") return false;
  const declared = Number(req.headers["content-length"]);
  if (Number.isFinite(declared) && declared > 32 * 1024) {
    sendJson(res, 413, { ok: false, error: "La respuesta de herramienta Gemini no puede pasar de 32 KB." });
    return true;
  }
  let payload;
  try { payload = JSON.parse((await readBody(req, 32 * 1024)).toString("utf8")); } catch {
    sendJson(res, 400, { ok: false, error: "La llamada de herramienta Gemini debe contener JSON válido." });
    return true;
  }
  if (!isObject(payload) || !Array.isArray(payload.functionCalls)) {
    sendJson(res, 400, { ok: false, error: "Falta la lista functionCalls de Gemini." });
    return true;
  }
  try {
    const result = await runGeminiLiveFunctionCalls(callId, payload.functionCalls, {
      registry,
      worker: controlPlane.workerClient({ call_id: callId, provider: "gemini_live" }),
      authority: controlPlane.authority,
      permissionMode: String(payload.permission_mode || "supervisado"),
    });
    sendJson(res, 200, { ok: true, ...result });
  } catch (error) {
    const status = error instanceof CallError ? error.status : 400;
    sendJson(res, status, { ok: false, error: error instanceof CallError ? error.code : "gemini_tool_rejected", message: String(error?.message || error).slice(0, 800) });
  }
  return true;
}

/** API interna del almacén (solo para el backend): GET /mykos-store/, GET|PUT /mykos-store/<documento>. Exige token. */
async function handleStoreRequest(req, res, runtime, logger) {
  // Es una API de servidor a servidor: nada de navegadores (sin Origin), solo Host propio y el token.
  if (!isOwnRequest(req, new Set()) || req.headers.origin !== undefined) {
    sendJson(res, 403, { error: "forbidden", message: "El almacén solo acepta peticiones internas." });
    return;
  }
  const state = storeState(runtime);
  if (!state.active) {
    sendJson(res, 503, { error: "store_inactive", message: state.error || "El almacén no está activo." });
    return;
  }
  const { store } = runtime;
  store.ensure();
  if (!store.checkToken(String(req.headers["x-mykos-store-token"] ?? ""))) {
    sendJson(res, 401, { error: "bad_token", message: "Token del almacén no válido." });
    return;
  }
  let name;
  try {
    name = decodeURIComponent(new URL(req.url ?? "/", "http://127.0.0.1").pathname.slice(STORE_PREFIX.length).replace(/\/+$/, ""));
  } catch {
    sendJson(res, 400, { error: "bad_path" });
    return;
  }
  try {
    if (name === "") {
      if (req.method !== "GET") {
        res.setHeader("Allow", "GET");
        sendJson(res, 405, { error: "method_not_allowed" });
        return;
      }
      sendJson(res, 200, { docs: store.list() });
      return;
    }
    if (req.method === "GET") {
      const doc = store.get(name);
      if (!doc) sendJson(res, 404, { error: "not_found" });
      else sendJson(res, 200, doc);
      return;
    }
    if (req.method === "PUT") {
      store.spec(name); // rechaza un nombre desconocido antes de leer el cuerpo
      const body = await readBody(req, store.maxDocBytes + 4096);
      let payload;
      try {
        payload = JSON.parse(body.toString("utf8"));
      } catch {
        sendJson(res, 400, { error: "bad_json", message: "El cuerpo no es JSON válido." });
        return;
      }
      if (payload === null || typeof payload !== "object" || Array.isArray(payload) || !("data" in payload)) {
        sendJson(res, 400, { error: "bad_request", message: "Falta el campo «data»." });
        return;
      }
      const result = store.put(name, payload.data, {
        expectedRevision: Number.isInteger(payload.expectedRevision) ? payload.expectedRevision : undefined,
        source: typeof payload.source === "string" ? payload.source.slice(0, 80) : "http",
        allowShrink: payload.allowShrink === true,
      });
      sendJson(res, 200, { ok: true, ...result });
      return;
    }
    res.setHeader("Allow", "GET, PUT");
    sendJson(res, 405, { error: "method_not_allowed" });
  } catch (error) {
    if (error instanceof StoreError) {
      sendJson(res, error.status, { error: error.code, message: error.message });
    } else if (error?.code === "BODY_TOO_LARGE") {
      sendJson(res, 413, { error: "too_large", message: "El documento es demasiado grande." });
    } else {
      logger?.error?.(`mykos-ui: almacén: error interno: ${error?.stack ?? error}`);
      sendJson(res, 500, { error: "internal", message: String(error?.message ?? error).slice(0, 200) });
    }
  }
}

// ───────────────────────────── entrada del plugin ─────────────────────────────

export default {
  id: "mykos-ui",
  name: "MyKOS UI",
  description: "Interfaz MyKOS servida por MyKOS Gateway, con backend supervisado y plano de control interno.",
  register(api) {
    const cfg = resolveConfig(api);
    const storeRuntime = cfg.store ? { store: acquireStore(cfg.store, api.logger), legacyDir: cfg.store.legacyDataDir, autoImport: cfg.store.autoImport } : null;
    const backendEnv = () => ({
      ...prepareStore(storeRuntime, cfg.gatewayPort, api.logger),
      MYKOS_CREDENTIALS_DIR: prepareCredentials(cfg.projectDir, cfg.credentialDir, api.logger),
    });
    const backend = cfg.backend ? new Backend(cfg.backend, api.logger, backendEnv) : null;
    const modelController = cfg.control.enabled && backend ? new ModelController(cfg.control.model, api.logger) : null;
    const authority = cfg.control.enabled && storeRuntime ? new PermissionAuthority(storeRuntime.store, api.logger) : null;
    const callRegistry = acquireCallRegistry(`${cfg.projectDir}|${cfg.gatewayPort}`, {
      store: storeRuntime?.store,
      isActive: () => Boolean(storeRuntime && storeState(storeRuntime).active),
      defaultModel: cfg.voice.model,
      logger: api.logger,
    });
    const realtime = new MyKOSRealtimeController({ registry: callRegistry, config: cfg.realtime, logger: api.logger });
    let controlPlane = null;
    // La llamada Realtime registra su callId con "openai-realtime/<modelo>" solo para
    // distinguirla en listados; el backend (catálogo, herramientas, modelo remoto) necesita
    // el identificador real sin ese prefijo para reconocerlo y no caer por el camino local.
    // "gpt-live-1-codex" tampoco es una entrada real del catálogo: la delegación de esa
    // llamada usa el mismo modelo de Codex OAuth que el resto de MyKOS (server.py hace la
    // misma sustitución para la llamada remota real; aquí se iguala para que el catálogo
    // de herramientas y el protocolo de llamada coincidan con el modelo que de verdad responde).
    const realVoiceModel = (model) => {
      const raw = String(model || "");
      const stripped = raw.startsWith("openai-realtime/") ? raw.slice("openai-realtime/".length) : raw;
      return stripped === "gpt-live-1-codex" ? "openai-codex-oauth/gpt-5.6-luna" : stripped;
    };
    const voiceEngine = acquireVoiceEngine(`${cfg.projectDir}|${cfg.gatewayPort}`, {
      registry: callRegistry,
      store: storeRuntime?.store,
      logger: api.logger,
      contextBuilder: async (messages, generation, call) => {
        // La hora no va en el mensaje de sistema (ver withTimeOnLastUser).
        let prompt = "Eres MyKOS en una llamada de voz. Responde en español de España, de forma clara y breve. No ejecutes acciones sensibles por voz sin la aprobación explícita de Usuario.";
        if (controlPlane && call && call.model) {
          try {
            const catalog = await controlPlane.workerClient({ operation: "voice-turn" }).catalog(realVoiceModel(call.model));
            if (catalog.system_prompt) {
                prompt = stripTimeLine(catalog.system_prompt) + "\n\nIMPORTANTE: Estás en una llamada de voz bidireccional en tiempo real con Usuario. Responde de forma natural, concisa y sin usar formato Markdown complejo que no se pueda locutar bien.";
            }
          } catch (e) {
            api.logger.warn("No se pudo obtener el system_prompt completo para la llamada de voz", e);
          }
        }
        return withTimeOnLastUser(prepareContext(prompt, messages, generation).messages);
      },
      responder: async ({ call, messages, generation, signal, permissionMode }) => {
        if (!controlPlane) throw new VoiceEngineError(503, "control_unavailable", "El plano de control de voz no está disponible.");
        const worker = controlPlane.workerClient({ operation: "voice-turn", call_id: call.callId });
        const mode = ["solo_lectura", "acceso_total"].includes(String(permissionMode || "")) ? String(permissionMode) : "supervisado";
        await worker.activity(`voice_${call.callId}`, {
          status: "working",
          phase: "voice-model",
          label: "MyKOS está respondiendo…",
          detail: `${call.model} · llamada de voz.`,
        });
        // Modelos remotos: Python lleva las herramientas del proveedor internamente.
        // Modelos locales (Ollama/llama.cpp): usamos runChatLoop nativo del Gateway,
        // igual que /api/chat, para que la voz tenga acceso completo a herramientas,
        // aprobaciones y el almacen de conversaciones, resolviendo la desconexion
        // donde los turnos de voz eran ciegos al resultado de las herramientas.
        const voiceModel = realVoiceModel(call.model);
        const isVoiceRemote = isRemoteModelName(voiceModel)
          || voiceModel === 'gpt-live-1-codex';

        if (isVoiceRemote) {
          return worker.remoteModel(voiceModel, messages, call.sessionId, generation, signal, mode);
        }

        // Modelo local: bucle de chat nativo. Voz y texto comparten el mismo motor.
        if (!controlPlane.chatLoopEnabled) {
          throw new VoiceEngineError(409, 'chat_loop_disabled', 'El bucle de chat del Gateway esta apagado (chatLoop.enabled).');
        }
        return runChatLoop(
          {
            model: voiceModel,
            messages,
            conversation_id: call.sessionId,
            generation,
            activity_id: "voice_",
            permission_mode: mode,
          },
          {
            model: controlPlane.model,
            authority: controlPlane.authority,
            worker,
            now: utcNow,
          },
        );
      },
      synthesizer: async (phrase, { signal }) => {
        if (!controlPlane) throw new VoiceEngineError(503, "control_unavailable", "El plano de control de voz no está disponible.");
        return controlPlane.workerClient({ operation: "voice-tts" }).tts(phrase, "em_alex", signal);
      },
    });
    // El Gateway puede registrar el plugin más de una vez antes de arrancar los servicios. El motor de voz se
    // conserva entre esos registros, así que debe resolver siempre el Backend que realmente quedó activo, no el
    // objeto de una primera carga que ya no tiene la fase "up".
    const activeBackend = () => globalThis[ACTIVE_BACKEND] ?? backend;
    controlPlane = modelController
      ? new ControlPlane(cfg.control, api.logger, activeBackend, modelController, authority, cfg.chatLoop.enabled, storeRuntime)
      : null;
    // Los contadores de carga de la política sobreviven a los registros repetidos del plugin (regla 3).
    const policyRegistry = (globalThis[POLICY_REGISTRY] ??= new Map());
    const policyKey = `${cfg.projectDir}|${cfg.gatewayPort}`;
    const policyLimiter = policyRegistry.get(policyKey) ?? new PolicyLimiter();
    policyRegistry.set(policyKey, policyLimiter);
    api.logger?.info?.(`mykos-ui ${CODE_VERSION}: interfaz desde ${cfg.staticRoot}; backend ${backend ? cfg.backend.url + (cfg.backend.spawn ? " (supervisado)" : " (externo)") : "no configurado"}; control ${controlPlane ? "activo" : "apagado"}; almacén ${storeRuntime ? cfg.store.dir : "apagado (ficheros de data/)"}`);

    // Estado del plugin (sonda de salud).
    api.registerHttpRoute({
      path: "/mykos-health",
      auth: "plugin",
      match: "exact",
      handler: async (req, res) => {
        if (!onlyGetHead(req, res)) return true;
        if (req.method === "HEAD") {
          res.statusCode = 204;
          res.setHeader("Cache-Control", "no-store");
          res.end();
          return true;
        }
        let indexOk = false;
        try {
          indexOk = (await stat(path.join(cfg.staticRoot, "index.html"))).isFile();
        } catch {}
        const backendState = backend ? await backend.snapshot() : { configured: false, up: true };
        const storeInfo = storeRuntime ? storeSnapshot(storeRuntime) : { enabled: false };
        const ok = indexOk && backendState.up;
        sendJson(res, ok ? 200 : 503, {
          ok,
          service: "mykos-ui",
          owner: "mykos-gateway",
          version: CODE_VERSION,
          pid: process.pid,
          port: req.socket?.localPort ?? null,
          staticRoot: cfg.staticRoot,
          indexHtml: indexOk,
          backend: backendState,
          control: controlPlane ? modelController.snapshot() : { enabled: false },
          routes: { strict: cfg.routes.strict, known: ROUTE_TABLE.length },
          policy: { strict: cfg.policy.strict, governed: POLICY_TABLE.length, load: policyLimiter.snapshot() },
          chatLoop: { enabled: cfg.chatLoop.enabled },
          realtime: {
            enabled: cfg.realtime.enabled,
            configured: realtime.configured(),
            model: cfg.realtime.model,
            voice: cfg.realtime.voice,
            auth: String(cfg.realtime.model).trim().toLowerCase() === "gpt-live-1-codex" ? "mykos_openai_oauth" : "mykos_platform_api_key",
          },
          store: storeInfo,
          ...(storeInfo.enabled && !storeInfo.active && storeInfo.error ? { warnings: [`almacén: ${storeInfo.error}`] } : {}),
        });
        return true;
      },
    });

    // Página principal: emite cookie de sesión local con SameSite=Strict y HttpOnly
    api.registerHttpRoute({
      path: "/",
      auth: "plugin",
      match: "exact",
      handler: async (req, res) => {
        if (!onlyGetHead(req, res)) return true;
        res.setHeader("Set-Cookie", `mykos_session=${WEB_SESSION_TOKEN}; Path=/; HttpOnly; SameSite=Strict`);
        await sendFile(req, res, path.join(cfg.staticRoot, "index.html"));
        return true;
      },
    });

    // Recursos estáticos (app.js, styles.css, logo...).
    api.registerHttpRoute({
      path: STATIC_PREFIX,
      auth: "plugin",
      match: "prefix",
      handler: async (req, res) => {
        if (!onlyGetHead(req, res)) return true;
        let rel;
        try {
          const { pathname } = new URL(req.url ?? "/", "http://127.0.0.1");
          rel = decodeURIComponent(pathname.slice(STATIC_PREFIX.length));
        } catch {
          sendJson(res, 400, { ok: false, error: "bad_path" });
          return true;
        }
        const abs = resolveInside(cfg.staticRoot, rel);
        if (!abs) {
          sendJson(res, 404, { ok: false, error: "not_found" });
          return true;
        }
        await sendFile(req, res, abs);
        return true;
      },
    });

    // Terminal interactiva Bash (desactivada por defecto por seguridad; requiere MYKOS_ENABLE_WEB_TERMINAL=1)
    api.registerHttpRoute({
      path: "/terminal",
      auth: "plugin",
      match: "exact",
      handler: async (req, res) => {
        if (!req.headers.origin || !isOwnRequest(req, cfg.extraOrigins)) {
          sendJson(res, 403, { ok: false, error: "Petición bloqueada." });
          return true;
        }
        if (!isWebAuthorized(req, WEB_SESSION_TOKEN, cfg.control?.token)) {
          sendJson(res, 401, { ok: false, error: "unauthorized", message: "Sesión no autorizada para la terminal web." });
          return true;
        }
        if (req.method !== "POST") {
          sendJson(res, 405, { ok: false, error: "method_not_allowed" });
          return true;
        }
        const terminalEnabled = process.env.MYKOS_ENABLE_WEB_TERMINAL === "1" || cfg.terminal?.enabled === true;
        if (!terminalEnabled) {
          sendJson(res, 403, {
            ok: false,
            error: "terminal_disabled",
            output: "La terminal web está desactivada por seguridad. Define MYKOS_ENABLE_WEB_TERMINAL=1 para habilitarla.",
            exitCode: 1,
          });
          return true;
        }
        let body;
        try {
          const buf = await readBody(req, 1_000_000);
          body = JSON.parse(buf.toString("utf8") || "{}");
        } catch {
          sendJson(res, 400, { ok: false, error: "bad_json" });
          return true;
        }
        const rawCommand = String(body?.command ?? "").trim();
        let clientCwd = String(body?.cwd ?? os.homedir()).trim();
        if (!existsSync(clientCwd) || !statSync(clientCwd).isDirectory()) {
          clientCwd = os.homedir();
        }
        if (!rawCommand) {
          sendJson(res, 200, { ok: true, output: "", cwd: clientCwd, exitCode: 0 });
          return true;
        }
        controlAudit(cfg.control.auditFile, { event: "terminal_exec", cwd: clientCwd, command_preview: rawCommand.slice(0, 120) });
        const safeEnv = {};
        for (const [k, v] of Object.entries(process.env)) {
          if (/(TOKEN|KEY|SECRET|PASSWORD|AUTH)/i.test(k) && !/^(SSH_AUTH_SOCK|GPG_AGENT_INFO)$/i.test(k)) continue;
          safeEnv[k] = v;
        }
        const isWin = process.platform === "win32";
        const shellExe = isWin ? "powershell.exe" : "/bin/bash";
        const wrapped = isWin
          ? `${rawCommand}\n$__CMD_EXIT__ = $LASTEXITCODE; if ($null -eq $__CMD_EXIT__) { $__CMD_EXIT__ = 0 }\nWrite-Output "___CWD_DELIM___"\n(Get-Location).Path\nWrite-Output "___EXIT_DELIM___"\nWrite-Output $__CMD_EXIT__`
          : `${rawCommand}\n__CMD_EXIT__=$?\necho "___CWD_DELIM___"\npwd\necho "___EXIT_DELIM___"\necho $__CMD_EXIT__`;
        exec(wrapped, { cwd: clientCwd, shell: shellExe, maxBuffer: 10 * 1024 * 1024, timeout: 60000, env: safeEnv }, (err, stdout = "", stderr = "") => {
          stdout = stdout.replace(/\r\n/g, "\n");
          let outputPart = stdout;
          let newCwd = clientCwd;
          let exitCode = 0;
          if (stdout.includes("___CWD_DELIM___\n")) {
            const [out, rest] = stdout.split("___CWD_DELIM___\n");
            outputPart = out;
            if (rest && rest.includes("___EXIT_DELIM___\n")) {
              const [c, e] = rest.split("___EXIT_DELIM___\n");
              newCwd = (c || "").trim() || clientCwd;
              exitCode = parseInt((e || "").trim(), 10);
              if (Number.isNaN(exitCode)) exitCode = err?.code ?? 0;
            }
          } else if (err) {
            exitCode = typeof err.code === "number" ? err.code : 1;
          }
          const combined = (outputPart + (stderr ? (outputPart ? "\n" : "") + stderr : "")).replace(/\r\n/g, "\n");
          sendJson(res, 200, {
            ok: exitCode === 0,
            output: combined,
            cwd: newCwd,
            exitCode,
          });
        });
        return true;
      },
    });

    const controlRoutesEnabled = Boolean(controlPlane && (api.registrationMode === undefined || api.registrationMode === "full"));
    if (controlRoutesEnabled) {
      api.registerHttpRoute({
        path: CONTROL_PREFIX,
        auth: "plugin",
        match: "prefix",
        handler: async (req, res) => {
          await controlPlane.handle(req, res, cfg.extraOrigins);
          return true;
        },
      });
    }

    if (!backend) return;

    // API de MyKOS: reenvío al backend Python.
    api.registerHttpRoute({
      path: API_PREFIX,
      auth: "plugin",
      match: "prefix",
      handler: async (req, res) => {
        if (!isOwnRequest(req, cfg.extraOrigins)) {
          sendJson(res, 403, { error: `Petición bloqueada: la API de MyKOS solo acepta peticiones desde http://127.0.0.1:${req.socket?.localPort}/.` });
          return true;
        }
        const apiUrl = new URL(req.url ?? "/", "http://127.0.0.1");
        const apiPath = apiUrl.pathname;

        // Comprobación de sesión web: /api/health y /api/oauth/openrouter/callback quedan exentas.
        // El callback OAuth es una redirección externa del navegador (SameSite=Strict cookie no viaja en cross-site),
        // y queda protegido de forma robusta por PKCE, el parámetro state criptográfico y el token interno del trabajador.
        if (apiPath !== "/api/health" && apiPath !== "/api/oauth/openrouter/callback") {
          if (!isWebAuthorized(req, WEB_SESSION_TOKEN, cfg.control?.token)) {
            sendJson(res, 401, {
              ok: false,
              error: "unauthorized",
              message: "Acceso no autorizado: abre MyKOS en tu navegador para autenticar la sesión.",
            });
            return true;
          }
        }
        // Lo que se clasifica es exactamente lo que se reenvía (ruta ya normalizada), para que el trabajador vea la
        // misma ruta que el Gateway ha comprobado.
        const workerPath = `${apiPath}${apiUrl.search}`;
        const route = classifyRoute(req.method, apiPath);
        if (cfg.routes.strict && (!route.known || !route.methodAllowed)) {
          const denied = !route.known ? { status: 404, reason: "unknown_route" } : { status: 405, reason: "method_not_allowed" };
          controlAudit(cfg.control.auditFile, { event: "api_denied", method: req.method, path: apiPath, status: denied.status, reason: denied.reason });
          sendJson(res, denied.status, { error: denied.status === 404 ? "Ruta no encontrada." : "Método no permitido para esta ruta." }, denied.status === 405 ? { Allow: route.allow.join(", ") } : {});
          return true;
        }
        const routeMeta = route.known && route.methodAllowed
          ? { domain: route.domain, action: route.action, risk: route.risk, route_owner: route.owner }
          : { domain: "unclassified" };
        const apiMeta = { event: "api_request", method: req.method, path: apiPath, ...routeMeta };
        controlAudit(cfg.control.auditFile, apiMeta);
        const recordApiResult = (status, extra = {}) => controlAudit(cfg.control.auditFile, {
          event: "api_result",
          method: req.method,
          path: apiPath,
          ...routeMeta,
          status,
          ok: Number(status) < 400,
          ...extra,
        });
        const realtimeMatch = /^\/api\/sessions\/([^/]+)\/realtime$/.exec(apiPath);
        if (realtimeMatch) {
          const handled = await handleRealtimeApi(req, res, decodeURIComponent(realtimeMatch[1]), realtime);
          if (handled) {
            recordApiResult(res.statusCode || 200, { owner: "mykos-gateway" });
            return true;
          }
        }
        const geminiLiveMatch = /^\/api\/sessions\/([^/]+)\/gemini-live$/.exec(apiPath);
        if (geminiLiveMatch) {
          const handled = await handleGeminiLiveApi(req, res, decodeURIComponent(geminiLiveMatch[1]), cfg, callRegistry);
          if (handled) {
            recordApiResult(res.statusCode || 200, { owner: "mykos-gateway" });
            return true;
          }
        }
        const geminiToolsMatch = /^\/api\/calls\/([^/]+)\/gemini-tools$/.exec(apiPath);
        if (geminiToolsMatch) {
          const handled = await handleGeminiLiveToolsApi(req, res, decodeURIComponent(geminiToolsMatch[1]), callRegistry, controlPlane);
          if (handled) {
            recordApiResult(res.statusCode || 200, { owner: "mykos-gateway" });
            return true;
          }
        }
        const call = callPath(apiPath);
        if (call) {
          const statusBefore = res.statusCode;
          const handled = await handleCallApi(req, res, call, callRegistry, voiceEngine);
          if (handled) {
            recordApiResult(res.statusCode || statusBefore || 200, { owner: "mykos-gateway" });
            return true;
          }
        }
        const conversationsHandled = await handleConversationApi(req, res, apiPath, apiUrl, storeRuntime);
        if (conversationsHandled) {
          recordApiResult(res.statusCode || 200, { owner: "mykos-gateway" });
          return true;
        }
        if (apiPath === "/api/user-profile") {
          const profileHandled = await handleUserProfileApi(req, res, cfg);
          if (profileHandled) {
            recordApiResult(res.statusCode || 200, { owner: "mykos-gateway" });
            return true;
          }
        }
        if (apiPath === "/api/system/updates" || apiPath === "/api/system/update") {
          const updateHandled = await handleSystemUpdatesApi(req, res, cfg, apiUrl);
          if (updateHandled) {
            recordApiResult(res.statusCode || 200, { owner: "mykos-gateway" });
            return true;
          }
        }
        // Actividad: la URL pública es del Gateway. Durante la transición el trabajador conserva el registro vivo,
        // accesible únicamente por este plano de control autenticado; el chat no se altera.
        if (req.method === "GET" && apiPath === "/api/activity") {
          const result = controlPlane?.activity?.view({
            activityId: apiUrl.searchParams.get("activity_id") || "",
            conversationId: apiUrl.searchParams.get("conversation_id") || "",
          }) || { ok: true, active: false, status: "idle" };
          sendJson(res, 200, result);
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        // Salud pública: el Gateway responde con su propio estado y el del backend.
        // Python conserva /api/health para la sonda interna del supervisor; esta ruta pública ya no llega al worker.
        if (req.method === "GET" && apiPath === "/api/health") {
          const backendState = backend ? await backend.snapshot() : { configured: false, up: true };
          const ok = backendState.up;
          sendJson(res, ok ? 200 : 503, {
            ok,
            service: "mykos",
            owner: "mykos-gateway",
            version: CODE_VERSION,
            pid: process.pid,
            backend: {
              up: backendState.up,
              pid: backendState.backendPid ?? null,
              phase: backendState.phase ?? null,
              reachable: backendState.reachable ?? null,
            },
          });
          recordApiResult(ok ? 200 : 503, { owner: "mykos-gateway" });
          return true;
        }
        // ── /api/chat: bucle de chat nativo del Gateway ──────────────────────────────
        // El Gateway es el único que necesita esta ruta. El worker ya no la ve: recibe
        // únicamente /mykos-control/* con token. Esta implementación:
        //   1. Lee la conversación del almacén del Gateway.
        //   2. Guarda el mensaje del usuario.
        //   3. Obtiene el system_prompt real vía /mykos-control/catalog.
        //   4. Llama a runChatLoop (modelo local) o remoteModel (modelos remotos).
        //   5. Devuelve la respuesta en el mismo formato que usaba Python.
        if (req.method === "POST" && apiPath === "/api/chat") {
          if (!controlPlane) {
            sendJson(res, 503, { error: "El plano de control del Gateway no está disponible." });
            recordApiResult(503, { owner: "mykos-gateway" });
            return true;
          }
          if (!storeRuntime) {
            sendJson(res, 503, { error: "El almacén del Gateway no está disponible." });
            recordApiResult(503, { owner: "mykos-gateway" });
            return true;
          }
          let chatPayload;
          try {
            const raw = await readBody(req, MAX_JSON_API_BYTES);
            chatPayload = raw.length ? JSON.parse(raw.toString("utf8")) : {};
            if (!isObject(chatPayload)) throw new SyntaxError("El cuerpo debe ser un objeto JSON.");
          } catch {
            sendJson(res, 400, { error: "El cuerpo de /api/chat no es JSON válido." });
            recordApiResult(400, { owner: "mykos-gateway" });
            return true;
          }
          const chatMeta = { operation: "chat", domain: "chat" };
          try {
            const message = String(chatPayload.message ?? "").trim();
            const attachmentIds = Array.isArray(chatPayload.attachments) ? chatPayload.attachments : [];
            if (!message && !attachmentIds.length) {
              sendJson(res, 400, { error: "Escribe un mensaje o adjunta un archivo antes de enviarlo." });
              recordApiResult(400, { owner: "mykos-gateway" });
              return true;
            }
            const MAX_MSG = 32_000;
            if (message.length > MAX_MSG) {
              sendJson(res, 400, { error: `El mensaje supera el límite de ${MAX_MSG} caracteres.` });
              recordApiResult(400, { owner: "mykos-gateway" });
              return true;
            }

            // — Actividad —
            const activityId = String(chatPayload.activity_id ?? "").trim() || randomUUID().replace(/-/g, "");
            controlPlane.activity.update(activityId, { status: "working", phase: "preparing", label: "Preparando contexto." });

            // — Conversación del almacén —
            const convState = conversationStore(storeRuntime);
            if (convState?.error === "store_corrupt") {
              sendJson(res, 503, {
                ok: false,
                error: "store_corrupt",
                document: "conversations",
                detail: convState.detail,
                hint: "El archivo de conversaciones está dañado y no tiene copia de seguridad. Ejecuta: mykos store repair",
              });
              recordApiResult(503, { owner: "mykos-gateway" });
              return true;
            }
            if (!convState || !convState.data) {
              sendJson(res, 503, { error: "El almacén de conversaciones del Gateway no está disponible." });
              recordApiResult(503, { owner: "mykos-gateway" });
              return true;
            }
            const { store: convStoreObj, data: convData } = convState;
            let requestedConvId = String(chatPayload.conversation_id ?? "").trim();
            let conversation = requestedConvId ? conversationById(convData, requestedConvId) : null;
            if (!conversation) {
              const newId = randomUUID();
              conversation = { id: newId, title: "Nueva conversación", messages: [], created_at: utcNow(), updated_at: utcNow() };
              convData.conversations.push(conversation);
              requestedConvId = newId;
            }

            // — Mensaje del usuario —
            const clientMessageId = String(chatPayload.client_message_id ?? "").trim() || randomUUID().replace(/-/g, "");
            const displayMessage = message || "Analiza los archivos adjuntos.";
            const userMessage = { message_id: clientMessageId, role: "user", content: displayMessage, created_at: utcNow() };
            conversation.messages.push(userMessage);
            if (conversation.title === "Nueva conversación" && message) conversation.title = message.slice(0, 60) + (message.length > 60 ? "." : "");
            conversation.updated_at = utcNow();
            saveConversations(convStoreObj, convData, "gateway.chat.user-message");

            // — Catálogo y system_prompt —
            const worker = controlPlane.workerClient(chatMeta);
            const requestedModel = String(chatPayload.model ?? "").trim();
            const catalog = await worker.catalog(requestedModel || undefined);
            const model = requestedModel || String(catalog.default_model ?? "").trim();
            if (!model) {
              sendJson(res, 503, { error: "No hay modelos disponibles. Comprueba Ollama o la sesión OAuth." });
              recordApiResult(503, { owner: "mykos-gateway" });
              return true;
            }
            const systemPrompt = String(catalog.system_prompt ?? "").trim() || "Eres MyKOS, el asistente de Usuario.";
            const generationRaw = isObject(chatPayload.generation) ? chatPayload.generation : {};
            // Normalizar generation: equivalente a normalise_generation_settings() de Python.
            // Sin esto, generation.options queda vacío y Ollama usa su num_predict por defecto
            // (~128 tokens), lo que corta las respuestas a mitad de frase.
            const GENERATION_PRESETS = {
              fast:     { num_ctx: 16384,  num_predict: 2048 },
              balanced: { num_ctx: 32768,  num_predict: 4096 },
              quality:  { num_ctx: 65536,  num_predict: 6144 },
              full:     { num_ctx: 131072, num_predict: 8192 },
            };
            const CREATIVITY_TEMPERATURE = { precise: 0.2, balanced: 0.5, creative: 0.8 };
            const speed      = ["fast","balanced","quality","full"].includes(generationRaw.speed)      ? generationRaw.speed      : "balanced";
            const creativity = ["precise","balanced","creative"].includes(generationRaw.creativity)    ? generationRaw.creativity : "balanced";
            const effort     = ["off","low","medium","high"].includes(generationRaw.effort)            ? generationRaw.effort     : "off";
            const preset     = GENERATION_PRESETS[speed];
            // Si el front-end ya envía options con num_predict (p.ej. desde el slider) respetarlo;
            // si no, usar el preset basado en speed.
            const rawOpts = isObject(generationRaw.options) ? generationRaw.options : {};
            const thinkValue = generationRaw.think ?? (effort !== "off" ? effort : false);
            const generation = {
              effort,
              speed,
              creativity,
              thinking_supported: Boolean(generationRaw.thinking_supported),
              think: thinkValue,
              options: {
                num_ctx:     Number(rawOpts.num_ctx)     || preset.num_ctx,
                num_predict: Number(rawOpts.num_predict) || (thinkValue ? Math.max(preset.num_predict, 2048) : preset.num_predict),
                temperature: Number(rawOpts.temperature) || CREATIVITY_TEMPERATURE[creativity],
              },
            };

            // — Despacho: local (runChatLoop) o remoto (remoteModel) —
            const REMOTE_PREFIXES = ["antigravity/", "qwen-cli/", "meta-ai/", "nvidia/", "kimi/", "mistral/", "gemini/", "openrouter/", "openai-codex-oauth/", "anthropic/", "grok/"];
            const isRemote = REMOTE_PREFIXES.some((p) => model.startsWith(p)) || model === "claude-sonnet-oauth" || model === "gpt-live-1-codex";

            // — Contexto: mensajes de la conversación → array para el modelo —
            const rawMessages = Array.isArray(conversation.messages) ? conversation.messages : [];
            const validMessages = rawMessages.filter(
              (m) => m && (m.role === "user" || m.role === "assistant" || m.role === "system" || m.role === "tool"),
            );
            // Para modelos locales (nativos con tool_calls), expandimos el tool_exchange de los últimos 2 turnos
            // del asistente para que el modelo conserve el contenido real leído y el patrón nativo de tool_calls.
            const expandExchangeIndices = new Set();
            if (!isRemote) {
              for (let idx = validMessages.length - 1; idx >= 0 && expandExchangeIndices.size < 2; idx -= 1) {
                const candidate = validMessages[idx];
                if (candidate.role === "assistant" && Array.isArray(candidate.tool_exchange) && candidate.tool_exchange.length) {
                  expandExchangeIndices.add(idx);
                }
              }
            }
            const context = [];
            for (let idx = 0; idx < validMessages.length; idx += 1) {
              const m = validMessages[idx];
              if (expandExchangeIndices.has(idx)) {
                for (const ex of m.tool_exchange) {
                  if (!isObject(ex) || (ex.role !== "assistant" && ex.role !== "tool")) continue;
                  const exItem = { role: ex.role, content: String(ex.content ?? "") };
                  if (Array.isArray(ex.tool_calls) && ex.tool_calls.length) exItem.tool_calls = ex.tool_calls;
                  if (ex.tool_call_id) exItem.tool_call_id = ex.tool_call_id;
                  context.push(exItem);
                }
              }
              const rawContent = String(m.content ?? "");
              const item = {
                role: m.role,
                content: m.role === "assistant" ? stripFakeLedgerTags(rawContent) : rawContent,
              };
              if (Array.isArray(m.tool_calls) && m.tool_calls.length) item.tool_calls = m.tool_calls;
              if (m.tool_call_id) item.tool_call_id = m.tool_call_id;
              if (Array.isArray(m.images) && m.images.length) item.images = m.images;
              if (m.image_mime_type) item.image_mime_type = m.image_mime_type;
              if (m.role === "assistant" && Array.isArray(m.sources) && m.sources.length) item.sources = m.sources;
              if (m.role === "assistant" && Array.isArray(m.verified_tool_trace) && m.verified_tool_trace.length) {
                item.verified_tool_trace = m.verified_tool_trace;
              }
              context.push(item);
            }

            const { messages: preparedMessages, context: contextInfo } = prepareContext(systemPrompt, context, generation);

            controlPlane.activity.update(activityId, { status: "working", phase: "model", label: "Trabajando.", detail: `${model} — esperando respuesta del modelo.` });

            let result;
            if (isRemote) {
              result = await worker.remoteModel(model, preparedMessages, requestedConvId, generation, null, String(chatPayload.permission_mode || "supervisado"));
            } else {
              if (!controlPlane.chatLoopEnabled) {
                sendJson(res, 409, { error: "El bucle de chat del Gateway está apagado (chatLoop.enabled)." });
                recordApiResult(409, { owner: "mykos-gateway" });
                return true;
              }
              result = await runChatLoop(
                {
                  model,
                  messages: withTimeOnLastUser(preparedMessages.map((item, index) => (index === 0 && item.role === "system" ? { ...item, content: stripTimeLine(item.content) } : item))),
                  conversation_id: requestedConvId, generation, activity_id: activityId, permission_mode: String(chatPayload.permission_mode || "supervisado"),
                },
                { model: controlPlane.model, authority: controlPlane.authority, worker, now: utcNow },
              );
            }

            controlPlane.activity.update(activityId, { status: "idle", phase: "done", label: "Listo." });


            // — Respuesta —
            const responsePayload = {
              conversation_id: requestedConvId,
              model,
              generation: { effort: generation.effort, speed: generation.speed, creativity: generation.creativity, thinking_supported: generation.thinking_supported },
              done: Boolean(result.done ?? !result.pending_action),
              tools_used: Array.isArray(result.tools_used) ? result.tools_used : [],
              context: contextInfo,
            };
            if (isRemote && result.usage && typeof result.usage === "object") responsePayload.usage = result.usage;
            if (isRemote && Number.isFinite(Number(result.duration_seconds))) responsePayload.duration_seconds = Number(result.duration_seconds);
            if (isRemote) {
              const durSec = Number(result.duration_seconds) || 0;
              const compTokens = Number(result.usage?.completion_tokens) || 0;
              const promptToks = Number(result.usage?.prompt_tokens) || 0;
              const tps = (durSec > 0 && compTokens > 0) ? Math.round((compTokens / durSec) * 10) / 10 : 0;
              const telemetry = {
                duration_ms: Math.round(durSec * 1000),
                tokens_out: compTokens,
                tokens_in: promptToks,
                tokens_per_second: tps,
              };
              responsePayload.telemetry = telemetry;
              if (responsePayload.message) responsePayload.message.telemetry = telemetry;
            } else if (result.telemetry) {
              responsePayload.telemetry = result.telemetry;
              if (responsePayload.message) responsePayload.message.telemetry = result.telemetry;
            }
            if (result.pending_action) {
              const proposal = String(result.proposal ?? "").trim();
              responsePayload.needs_approval = true;
              responsePayload.pending_action = result.pending_action;
              responsePayload.message = { role: "assistant", content: proposal || "He preparado una acción pendiente de tu aprobación." };
              if (result.sources?.length) responsePayload.message.sources = result.sources;
            } else {
              responsePayload.message = result.message;
            }
            sendJson(res, 200, responsePayload);
            recordApiResult(200, { owner: "mykos-gateway", model });
          } catch (chatError) {
            controlPlane.activity.update(String(chatPayload?.activity_id ?? ""), { status: "error", phase: "done", label: "Error." });
            const msg = String(chatError?.message || "Error interno del chat.").slice(0, 400);
            sendJson(res, 502, { error: msg });
            recordApiResult(502, { owner: "mykos-gateway" });
          }
          return true;
        }
        // ─────────────────────────────────────────────────────────────────────────────
        // Límite de tamaño para toda la API JSON (2 MB, igual que read_json() en server.py), antes de cualquier otro
        // manejo: sin esto, un cuerpo mayor no lo rechaza el Gateway, lo corta el trabajador a mitad de lectura, y el
        // navegador/proxy lo ve como una conexión reiniciada (502 «no responde») en vez de un rechazo limpio.
        // Las subidas (32 MB, con su propia política) y las rutas con política propia (que ya validan su tamaño) quedan fuera.
        if (apiPath !== "/api/uploads" && !policyFor(req.method, apiPath) && req.method !== "GET" && req.method !== "HEAD" && req.method !== "DELETE") {
          const declared = Number(req.headers["content-length"]);
          if (Number.isFinite(declared) && declared > MAX_JSON_API_BYTES) {
            controlAudit(cfg.control.auditFile, {
              event: "api_denied", method: req.method, path: apiPath, ...routeMeta,
              status: 413, reason: "body_too_large",
            });
            sendJson(res, 413, { error: `El cuerpo de esta ruta no puede pasar de ${MAX_JSON_API_BYTES} bytes.` });
            return true;
          }
        }
        if (authority && req.method === "GET" && apiPath === "/api/permissions") {
          sendJson(res, 200, { permissions: authority.listPermissions(apiUrl.searchParams.get("conversation_id") || "") });
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (authority && req.method === "GET" && apiPath === "/api/audit") {
          sendJson(res, 200, { audit: authority.listAudit(apiUrl.searchParams.get("limit") || "100", apiUrl.searchParams.get("conversation_id") || "") });
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (authority && req.method === "GET" && apiPath === "/api/approvals") {
          sendJson(res, 200, { approvals: authority.listApprovals(apiUrl.searchParams.get("conversation_id") || "") });
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (storeRuntime && req.method === "GET" && apiPath === "/api/automations") {
          const rawLimit = apiUrl.searchParams.get("limit") || "50";
          const limit = Number(rawLimit);
          if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
            sendJson(res, 400, { error: "limit debe ser un entero entre 1 y 100." });
            recordApiResult(400, { owner: "mykos-gateway" });
            return true;
          }
          const data = storeRuntime.store.get("automations")?.data;
          const automations = Array.isArray(data?.automations) ? data.automations.filter(isObject) : [];
          const events = Array.isArray(data?.events) ? data.events.filter(isObject).slice(-limit) : [];
          sendJson(res, 200, { ok: true, automations, events });
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (storeRuntime && req.method === "POST" && apiPath === "/api/automations/clear-events") {
          // Solo limpia el historial de eventos ya disparados (una bitácora, no una acción sobre el sistema):
          // acción directa del Gateway, sin aprobación, igual que revocar un permiso.
          const current = storeRuntime.store.get("automations")?.data;
          const base = isObject(current) ? current : { automations: [], events: [] };
          const automations = Array.isArray(base.automations) ? base.automations.filter(isObject) : [];
          storeRuntime.store.put("automations", { automations, events: [] }, { source: "gateway.automations.clear_events" });
          controlAudit(cfg.control.auditFile, { event: "control_result", ...routeMeta, ok: true, cleared_events: true });
          sendJson(res, 200, { ok: true, events: [] });
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (storeRuntime && req.method === "GET" && apiPath === "/api/subagents") {
          const rawLimit = apiUrl.searchParams.get("limit") || "50";
          const limit = Number(rawLimit);
          if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
            sendJson(res, 400, { error: "limit debe ser un entero entre 1 y 100." });
            recordApiResult(400, { owner: "mykos-gateway" });
            return true;
          }
          const data = storeRuntime.store.get("subagents")?.data;
          const jobs = Array.isArray(data?.jobs) ? data.jobs.filter(isObject).slice(-limit) : [];
          sendJson(res, 200, { ok: true, action: "list_subagents", jobs });
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (storeRuntime && req.method === "GET" && apiPath === "/api/nodes") {
          const data = storeRuntime.store.get("nodes")?.data;
          const remote = Array.isArray(data?.nodes) ? data.nodes.filter(isObject).map((node) => {
            const { token_hash: _tokenHash, ...publicNode } = node;
            publicNode.local = false;
            if (!publicNode.enabled) publicNode.status = "revoked";
            else if (!publicNode.last_seen) publicNode.status = "pending";
            return publicNode;
          }) : [];
          sendJson(res, 200, { ok: true, nodes: [localNode(), ...remote], local_only: true });
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (req.method === "GET" && apiPath === "/api/media") {
          const rawLimit = apiUrl.searchParams.get("limit") || "50"; const limit = Number(rawLimit);
          if (!Number.isInteger(limit) || limit < 1 || limit > 100) { sendJson(res, 400, { error: "limit debe ser un entero entre 1 y 100." }); recordApiResult(400, { owner: "mykos-gateway" }); return true; }
          const status = await jsonRequest(`${backend.config.url}/mykos-control/media-status`, null, 10_000, { "X-MyKOS-Control-Token": cfg.control.token }, null, "GET");
          if (status.status >= 400 || !status.body?.ok) { sendJson(res, 503, { error: "El estado multimedia no está disponible." }); recordApiResult(503, { owner: "mykos-gateway" }); return true; }
          sendJson(res, 200, { status: status.body.status, library: mediaLibrary(cfg.projectDir, limit) }); recordApiResult(200, { owner: "mykos-gateway" }); return true;
        }
        if (req.method === "GET" && apiPath === "/api/management") {
          const status = await jsonRequest(`${backend.config.url}/mykos-control/management-status`, null, 10_000, { "X-MyKOS-Control-Token": cfg.control.token }, null, "GET");
          if (status.status >= 400 || !status.body?.ok || !isObject(status.body.status)) {
            sendJson(res, 503, { error: "El estado de gestión local no está disponible." });
            recordApiResult(503, { owner: "mykos-gateway" });
            return true;
          }
          sendJson(res, 200, status.body.status);
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (req.method === "GET" && apiPath === "/api/memory") {
          const catalog = await jsonRequest(`${backend.config.url}/mykos-control/memory-catalog`, {}, 10_000, { "X-MyKOS-Control-Token": cfg.control.token });
          if (catalog.status >= 400 || !isObject(catalog.body)) {
            sendJson(res, 503, { ok: false, count: 0, entries: [], error: "El catálogo de memoria no está disponible." });
            recordApiResult(503, { owner: "mykos-gateway" });
            return true;
          }
          sendJson(res, 200, catalog.body);
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (req.method === "GET" && ["/api/library/list", "/api/library/search", "/api/library/preview"].includes(apiPath)) {
          const operation = apiPath.slice("/api/library/".length);
          const payload = {
            root: apiUrl.searchParams.get("root") || "mykos",
            path: apiUrl.searchParams.get("path") || "",
            query: apiUrl.searchParams.get("query") || "",
          };
          const result = await jsonRequest(`${backend.config.url}/mykos-control/library/${operation}`, payload, 30_000, { "X-MyKOS-Control-Token": cfg.control.token });
          if (result.status >= 400 || !isObject(result.body)) {
            const status = result.status >= 400 ? result.status : 503;
            sendJson(res, status, { ok: false, error: String(result.body?.error || "La biblioteca no está disponible.") });
            recordApiResult(status, { owner: "mykos-gateway" });
            return true;
          }
          sendJson(res, 200, result.body);
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (req.method === "GET" && apiPath === "/api/tools") {
          const catalog = await jsonRequest(`${backend.config.url}/mykos-control/tools-catalog`, null, 10_000, { "X-MyKOS-Control-Token": cfg.control.token });
          if (catalog.status >= 400 || !catalog.body?.ok || !Array.isArray(catalog.body.tools) || !Array.isArray(catalog.body.allowed_roots)) {
            sendJson(res, 503, { error: "El catálogo de herramientas no está disponible." });
            recordApiResult(503, { owner: "mykos-gateway" });
            return true;
          }
          sendJson(res, 200, { tools: catalog.body.tools, allowed_roots: catalog.body.allowed_roots });
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (req.method === "GET" && apiPath === "/api/models") {
          const catalog = await jsonRequest(`${backend.config.url}/mykos-control/models-catalog`, null, 15_000, { "X-MyKOS-Control-Token": cfg.control.token });
          if (catalog.status >= 400 || !catalog.body?.ok || !Array.isArray(catalog.body.models)) {
            sendJson(res, 503, { error: "El catálogo de modelos no está disponible.", models: [] });
            recordApiResult(503, { owner: "mykos-gateway" });
            return true;
          }
          sendJson(res, 200, { models: catalog.body.models });
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (req.method === "GET" && apiPath === "/api/status") {
          const status = await jsonRequest(`${backend.config.url}/mykos-control/status-catalog`, {}, 15_000, { "X-MyKOS-Control-Token": cfg.control.token });
          if (status.status >= 400 || !status.body?.ok || !Array.isArray(status.body.models)) {
            sendJson(res, 503, { ok: false, error: String(status.body?.error || "El estado de modelos no está disponible."), models: [] });
            recordApiResult(503, { owner: "mykos-gateway" });
            return true;
          }
          sendJson(res, 200, status.body);
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (req.method === "GET" && apiPath === "/api/ollama/catalog") {
          const catalog = await jsonRequest(`${backend.config.url}/mykos-control/ollama/catalog`, { query: apiUrl.searchParams.get("query") || "" }, 20_000, { "X-MyKOS-Control-Token": cfg.control.token });
          if (catalog.status >= 400 || !isObject(catalog.body) || !Array.isArray(catalog.body.models)) {
            const status = catalog.status >= 400 ? catalog.status : 503;
            sendJson(res, status, { error: String(catalog.body?.error || "El catálogo de Ollama no está disponible."), models: [] });
            recordApiResult(status, { owner: "mykos-gateway" });
            return true;
          }
          sendJson(res, 200, catalog.body);
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (req.method === "GET" && apiPath === "/api/ollama/jobs") {
          const jobs = await jsonRequest(`${backend.config.url}/mykos-control/ollama/jobs`, { id: apiUrl.searchParams.get("id") || "" }, 10_000, { "X-MyKOS-Control-Token": cfg.control.token });
          if (jobs.status >= 400 || !isObject(jobs.body) || !Array.isArray(jobs.body.jobs)) {
            const status = jobs.status >= 400 ? jobs.status : 503;
            sendJson(res, status, { error: String(jobs.body?.error || "El estado de trabajos de Ollama no está disponible."), jobs: [] });
            recordApiResult(status, { owner: "mykos-gateway" });
            return true;
          }
          sendJson(res, 200, jobs.body);
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (req.method === "GET" && apiPath === "/api/oauth/status") {
          const oauth = await jsonRequest(`${backend.config.url}/mykos-control/oauth-status`, {}, 10_000, { "X-MyKOS-Control-Token": cfg.control.token });
          if (oauth.status >= 400 || !isObject(oauth.body) || !Array.isArray(oauth.body.providers)) {
            const status = oauth.status >= 400 ? oauth.status : 503;
            sendJson(res, status, { error: String(oauth.body?.error || "El estado de OAuth no está disponible."), providers: [] });
            recordApiResult(status, { owner: "mykos-gateway" });
            return true;
          }
          sendJson(res, 200, oauth.body);
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (req.method === "POST" && ["/api/oauth/openrouter/refresh", "/api/oauth/meta/refresh", "/api/oauth/grok/refresh"].includes(apiPath)) {
          const isMeta = apiPath === "/api/oauth/meta/refresh";
          const isGrok = apiPath === "/api/oauth/grok/refresh";
          let payload = {};
          try { payload = JSON.parse((await readBody(req, 2048)) || "{}"); } catch {
            sendJson(res, 400, { error: "El cuerpo debe ser JSON válido." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
          }
          if (isGrok) {
            if (payload?.provider !== undefined && payload.provider !== "grok" && payload.provider !== "grok_oauth" && payload.provider !== "grok_api") {
              sendJson(res, 400, { error: "Proveedor OAuth no compatible." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
            }
            const refreshed = await jsonRequest(`${backend.config.url}/mykos-control/grok/refresh`, { provider: "grok_oauth" }, 30_000, { "X-MyKOS-Control-Token": cfg.control.token });
            const status = refreshed.status >= 400 ? refreshed.status : 503;
            if (refreshed.status >= 400 || !isObject(refreshed.body)) {
              sendJson(res, status, { ok: false, error: String(refreshed.body?.error || "No se pudo refrescar Grok."), models: 0 }); recordApiResult(status, { owner: "mykos-gateway" }); return true;
            }
            sendJson(res, 200, refreshed.body); recordApiResult(200, { owner: "mykos-gateway" }); return true;
          }
          if (isMeta) {
            if (payload?.provider !== undefined && payload.provider !== "meta" && payload.provider !== "meta_ai_oauth") {
              sendJson(res, 400, { error: "Proveedor OAuth no compatible." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
            }
            const refreshed = await jsonRequest(`${backend.config.url}/mykos-control/meta/refresh`, { provider: "meta_ai_oauth" }, 60_000, { "X-MyKOS-Control-Token": cfg.control.token });
            const status = refreshed.status >= 400 ? refreshed.status : 503;
            if (refreshed.status >= 400 || !isObject(refreshed.body)) {
              sendJson(res, status, { ok: false, error: String(refreshed.body?.error || "No se pudo refrescar Meta AI."), models: 0 }); recordApiResult(status, { owner: "mykos-gateway" }); return true;
            }
            sendJson(res, 200, refreshed.body); recordApiResult(200, { owner: "mykos-gateway" }); return true;
          }
          if (payload?.provider !== undefined && payload.provider !== "openrouter") {
            sendJson(res, 400, { error: "Proveedor OAuth no compatible." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
          }
          const refreshed = await jsonRequest(`${backend.config.url}/mykos-control/openrouter/refresh`, { provider: "openrouter" }, 30_000, { "X-MyKOS-Control-Token": cfg.control.token });
          const status = refreshed.status >= 400 ? refreshed.status : 503;
          if (refreshed.status >= 400 || !isObject(refreshed.body)) {
            sendJson(res, status, { ok: false, error: String(refreshed.body?.error || "No se pudo refrescar OpenRouter."), models: 0 }); recordApiResult(status, { owner: "mykos-gateway" }); return true;
          }
          sendJson(res, 200, refreshed.body); recordApiResult(200, { owner: "mykos-gateway" }); return true;
        }
        if (req.method === "POST" && ["/api/oauth/openai/start", "/api/oauth/claude/start", "/api/oauth/openrouter/start", "/api/oauth/meta/start", "/api/oauth/grok/start"].includes(apiPath)) {
          const name = apiPath.split("/")[3];
          const provider = ({ openai: "openai_codex_oauth", claude: "anthropic_oauth", openrouter: "openrouter", meta: "meta_ai_oauth", grok: "grok_oauth" })[name];
          let payload = {};
          try { payload = JSON.parse((await readBody(req, 2048)) || "{}"); } catch {
            sendJson(res, 400, { error: "El cuerpo debe ser JSON válido." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
          }
          if (!provider || (payload?.provider !== undefined && payload.provider !== provider && payload.provider !== name)) {
            sendJson(res, 400, { error: "Proveedor OAuth no compatible." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
          }
          const started = await jsonRequest(`${backend.config.url}/mykos-control/oauth/${name}/start`, { provider }, 60_000, { "X-MyKOS-Control-Token": cfg.control.token });
          const status = started.status >= 400 ? started.status : 503;
          if (started.status >= 400 || !isObject(started.body)) {
            sendJson(res, status, { ok: false, error: String(started.body?.error || `No se pudo iniciar ${name}.`) }); recordApiResult(status, { owner: "mykos-gateway" }); return true;
          }
          sendJson(res, 200, started.body); recordApiResult(200, { owner: "mykos-gateway" }); return true;
        }
        if (req.method === "GET" && apiPath === "/api/oauth/openrouter/callback") {
          // El retorno trae el código OAuth en la consulta. Se reenvía por streaming al ejecutor interno para que
          // éste haga el canje PKCE y devuelva su página HTML, sin interpretar ni registrar el código en el Gateway.
          const status = await proxyRequest(req, res, backend.config.url, null, `/mykos-control/oauth/openrouter/callback${apiUrl.search}`, { "x-mykos-control-token": cfg.control.token });
          recordApiResult(status, { owner: "mykos-gateway", internal_path: "/mykos-control/oauth/openrouter/callback" }); return true;
        }
        if (req.method === "POST" && ["/api/oauth/openai/logout", "/api/oauth/claude/logout", "/api/oauth/openrouter/logout", "/api/oauth/meta/logout", "/api/oauth/grok/logout", "/api/providers/nvidia/logout", "/api/providers/kimi/logout", "/api/providers/gemini/logout", "/api/providers/mistral/logout", "/api/providers/anthropic/logout", "/api/providers/antigravity/logout", "/api/providers/qwen/logout", "/api/providers/grok/logout"].includes(apiPath)) {
          const match = apiPath.match(/^\/api\/(oauth|providers)\/([^/]+)\/logout$/);
          const group = match?.[1] || "";
          const name = match?.[2] || "";
          const provider = ({ openai: "openai_codex_oauth", claude: "anthropic_oauth", openrouter: "openrouter", meta: "meta_ai_oauth", grok: group === "oauth" ? "grok_oauth" : "grok_api", nvidia: "nvidia_api", kimi: "kimi_api", gemini: "gemini_api", mistral: "mistral_api", anthropic: "anthropic_api", antigravity: "antigravity_cli", qwen: "qwen_cli" })[name];
          let payload = {};
          try { payload = JSON.parse((await readBody(req, 2048)) || "{}"); } catch {
            sendJson(res, 400, { error: "El cuerpo debe ser JSON válido." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
          }
          if (!provider || (payload?.provider !== undefined && payload.provider !== provider && payload.provider !== name && payload.provider !== provider.replace(/_api$/, "") && payload.provider !== provider.replace(/_cli$/, ""))) {
            sendJson(res, 400, { error: "Proveedor no compatible." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
          }
          const loggedOut = await jsonRequest(`${backend.config.url}/mykos-control/${group}/${name}/logout`, { provider }, 60_000, { "X-MyKOS-Control-Token": cfg.control.token });
          const status = loggedOut.status >= 400 ? loggedOut.status : 503;
          if (loggedOut.status >= 400 || !isObject(loggedOut.body)) {
            sendJson(res, status, { ok: false, error: String(loggedOut.body?.error || `No se pudo cerrar ${name}.`) }); recordApiResult(status, { owner: "mykos-gateway" }); return true;
          }
          sendJson(res, 200, loggedOut.body); recordApiResult(200, { owner: "mykos-gateway" }); return true;
        }
        if (req.method === "POST" && /^\/api\/providers\/(nvidia|kimi|gemini|mistral|anthropic|antigravity|qwen|grok)\/refresh$/.test(apiPath)) {
          const match = apiPath.match(/^\/api\/providers\/([^/]+)\/refresh$/);
          const provider = match?.[1] || "";
          const expectedProvider = (provider === "antigravity" || provider === "qwen") ? `${provider}_cli` : `${provider}_api`;
          let payload = {};
          try { payload = JSON.parse((await readBody(req, 2048)) || "{}"); } catch {
            sendJson(res, 400, { error: "El cuerpo debe ser JSON válido." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
          }
          if (payload?.provider !== undefined && payload.provider !== provider && payload.provider !== expectedProvider) {
            sendJson(res, 400, { error: "Proveedor no compatible." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
          }
          const refreshed = await jsonRequest(`${backend.config.url}/mykos-control/providers/${provider}/refresh`, { provider: expectedProvider }, 30_000, { "X-MyKOS-Control-Token": cfg.control.token });
          const status = refreshed.status >= 400 ? refreshed.status : 503;
          if (refreshed.status >= 400 || !isObject(refreshed.body)) {
            sendJson(res, status, { ok: false, error: String(refreshed.body?.error || `No se pudo refrescar ${provider}.`), models: 0 }); recordApiResult(status, { owner: "mykos-gateway" }); return true;
          }
          sendJson(res, 200, refreshed.body); recordApiResult(200, { owner: "mykos-gateway" }); return true;
        }
        if (req.method === "POST" && /^\/api\/providers\/(nvidia|kimi|gemini|mistral|anthropic|antigravity|qwen|grok)\/connect$/.test(apiPath)) {
          const match = apiPath.match(/^\/api\/providers\/([^/]+)\/connect$/);
          const provider = match?.[1] || "";
          const expectedProvider = (provider === "antigravity" || provider === "qwen") ? `${provider}_cli` : `${provider}_api`;
          let payload = {};
          try { payload = JSON.parse((await readBody(req, 2048)) || "{}"); } catch {
            sendJson(res, 400, { error: "El cuerpo debe ser JSON válido." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
          }
          if (payload?.provider !== undefined && payload.provider !== provider && payload.provider !== expectedProvider) {
            sendJson(res, 400, { error: "Proveedor no compatible." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
          }
          let forwardPayload = { provider: expectedProvider };
          if (provider === "antigravity" || provider === "qwen") {
            // Antigravity y Qwen Code se activan/desactivan usando la configuración/sesión local del CLI
            forwardPayload.enabled = true;
          } else if (provider === "mistral" && payload?.link_vibe) {
            forwardPayload.link_vibe = true;
          } else {
            const apiKey = typeof payload?.api_key === "string" ? payload.api_key.trim() : "";
            if (!apiKey) {
              const names = { nvidia: "NVIDIA", gemini: "Google AI Studio (Gemini)", kimi: "Kimi", mistral: "Mistral", anthropic: "Anthropic", grok: "xAI (Grok)" };
              sendJson(res, 400, { ok: false, error: `Introduce una clave personal de ${names[provider] || provider}.` }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
            }
            forwardPayload.api_key = apiKey;
          }
          const connected = await jsonRequest(`${backend.config.url}/mykos-control/providers/${provider}/connect`, forwardPayload, 60_000, { "X-MyKOS-Control-Token": cfg.control.token });
          const status = connected.status >= 400 ? connected.status : 503;
          if (connected.status >= 400 || !isObject(connected.body)) {
            sendJson(res, status, { ok: false, error: String(connected.body?.error || `No se pudo conectar ${provider}.`) }); recordApiResult(status, { owner: "mykos-gateway" }); return true;
          }
          sendJson(res, 200, connected.body); recordApiResult(200, { owner: "mykos-gateway" }); return true;
        }
        if (req.method === "POST" && (apiPath === "/api/ollama/pull-request" || apiPath === "/api/ollama/delete-request")) {
          let payload = {};
          try { payload = JSON.parse((await readBody(req, 2048)) || "{}"); } catch {
            sendJson(res, 400, { error: "El cuerpo debe ser JSON válido." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
          }
          const action = apiPath.endsWith("pull-request") ? "pull-request" : "delete-request";
          const requested = await jsonRequest(`${backend.config.url}/mykos-control/ollama/${action}`, payload, 30_000, { "X-MyKOS-Control-Token": cfg.control.token });
          const status = requested.status >= 400 ? requested.status : 503;
          if (requested.status >= 400 || !isObject(requested.body)) {
            sendJson(res, status, { ok: false, error: String(requested.body?.error || "No se pudo preparar la acción de Ollama.") }); recordApiResult(status, { owner: "mykos-gateway" }); return true;
          }
          sendJson(res, 200, requested.body); recordApiResult(200, { owner: "mykos-gateway" }); return true;
        }
        if (req.method === "POST" && (apiPath === "/api/automations/create-request" || apiPath === "/api/automations/delete-request")) {
          let payload = {};
          try { payload = JSON.parse((await readBody(req, 8192)) || "{}"); } catch {
            sendJson(res, 400, { error: "El cuerpo debe ser JSON válido." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
          }
          const action = apiPath.endsWith("create-request") ? "create-request" : "delete-request";
          const requested = await jsonRequest(`${backend.config.url}/mykos-control/automations/${action}`, payload, 30_000, { "X-MyKOS-Control-Token": cfg.control.token });
          const status = requested.status >= 400 ? requested.status : 503;
          if (requested.status >= 400 || !isObject(requested.body)) {
            sendJson(res, status, { ok: false, error: String(requested.body?.error || "No se pudo preparar el recordatorio.") }); recordApiResult(status, { owner: "mykos-gateway" }); return true;
          }
          sendJson(res, 200, requested.body); recordApiResult(200, { owner: "mykos-gateway" }); return true;
        }
        if (req.method === "POST" && /^\/api\/approvals\/[^/]+\/(approve|reject)$/.test(apiPath)) {
          let payload = {};
          try { payload = JSON.parse((await readBody(req, 2048)) || "{}"); } catch {
            sendJson(res, 400, { error: "El cuerpo debe ser JSON válido." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
          }
          const parts = apiPath.split("/");
          let approvalId = "";
          try { approvalId = decodeURIComponent(parts[3] || ""); } catch {
            sendJson(res, 400, { error: "El identificador de aprobación no es válido." }); recordApiResult(400, { owner: "mykos-gateway" }); return true;
          }
          const decision = parts[4] || "";
          if (controlPlane && authority && controlPlane.chatLoopEnabled) {
            const activityId = String(payload?.activity_id || "").trim() || randomUUID().replaceAll("-", "");
            const permissionMode = ["once", "session", "permanent"].includes(String(payload?.permission_mode || "").trim().toLowerCase())
              ? String(payload.permission_mode).trim().toLowerCase()
              : "once";
            const result = await controlPlane.resolveApprovalWithWorker(approvalId, decision, permissionMode);
            if (!result.ok) {
              const status = Number(result.status) || 502;
              sendJson(res, status, { ok: false, error: String(result.error || "No se pudo resolver la aprobación.") });
              recordApiResult(status, { owner: "mykos-gateway" });
              return true;
            }
            if (result.rejected) {
              sendJson(res, 200, {
                ok: true,
                approved: false,
                rejected: true,
                conversation_id: result.conversation_id || "",
                action: result.action || {},
              });
              recordApiResult(200, { owner: "mykos-gateway" });
              return true;
            }
            const record = isObject(result._record) ? result._record : {};
            const action = isObject(record.action) ? record.action : {};
            const publicResult = { ...result };
            delete publicResult._record;
            if (action.panel_request) {
              sendJson(res, 200, publicResult);
              recordApiResult(200, { owner: "mykos-gateway" });
              return true;
            }
            const actionResult = isObject(result.action_result) ? result.action_result : {};
            const messages = Array.isArray(record.messages) ? record.messages.slice() : [];
            const model = String(record.model || "").trim();
            const conversationId = String(record.conversation_id || "").trim();
            const reqConvMode = String(payload?.conversation_permission_mode || record.conversation_permission_mode || "supervisado").trim().toLowerCase();
            const effectiveConvMode = ["solo_lectura", "supervisado", "acceso_total"].includes(reqConvMode) ? reqConvMode : "supervisado";
            const worker = controlPlane.workerClient({ operation: "approval-continue", conversation_id: conversationId });

            if (!messages.length || model.toLowerCase().includes("live")) {
              const summaryText = actionResult.ok
                ? `Acción «${record.tool_name || action.kind || "aprobada"}» ejecutada correctamente.`
                : `No se pudo completar la acción: ${actionResult.error || "error desconocido"}.`;
              const assistantMessage = { role: "assistant", model, content: summaryText, created_at: utcNow() };
              const saved = conversationId ? await worker.saveMessage(conversationId, assistantMessage) : assistantMessage;
              Object.assign(publicResult, {
                conversation_id: conversationId,
                model,
                done: true,
                tools_used: [String(record.tool_name || action.kind || "")],
                message: isObject(saved) ? saved : assistantMessage,
              });
              sendJson(res, 200, publicResult);
              recordApiResult(200, { owner: "mykos-gateway" });
              return true;
            }

            controlPlane.activity.start({
              id: activityId,
              conversationId,
              model,
              modelLabel: model,
              providerLabel: isRemoteModelName(model) ? "Proveedor remoto" : "Modelo local",
              remote: isRemoteModelName(model),
              location: isRemoteModelName(model) ? "remoto" : "local",
            });
            try {
              controlPlane.activity.update(activityId, {
                status: "working",
                phase: "model",
                label: "Continuando después de la aprobación…",
                detail: "El Gateway ha ejecutado la acción y MyKOS está preparando la respuesta.",
              });
              const toolMsg = toolMessageForResult(actionResult, Boolean(record.supports_vision), String(record.tool_name || action.kind || ""));
              const lastMsg = messages.at(-1);
              if ((model === "mykos-cuda" || model.startsWith("strata/")) && Array.isArray(lastMsg?.tool_calls) && lastMsg.tool_calls[0]?.id) {
                toolMsg.tool_call_id = String(lastMsg.tool_calls[0].id);
              }
              messages.push(toolMsg);
              const continuation = isRemoteModelName(model)
                ? await worker.remoteModel(model, messages, conversationId, isObject(record.generation) ? record.generation : {}, null, effectiveConvMode)
                : await runChatLoop(
                    {
                      model,
                      messages,
                      conversation_id: conversationId,
                      supports_vision: Boolean(record.supports_vision),
                      generation: isObject(record.generation) ? record.generation : {},
                      activity_id: activityId,
                      permission_mode: effectiveConvMode,
                    },
                    {
                      model: controlPlane.model,
                      authority: controlPlane.authority,
                      worker,
                      now: utcNow,
                    },
                  );
              Object.assign(publicResult, {
                conversation_id: conversationId,
                model,
                done: Boolean(continuation.done ?? true),
                tools_used: continuation.tools_used || [],
              });
              if (continuation.pending_action) {
                publicResult.needs_approval = true;
                publicResult.pending_action = continuation.pending_action;
                publicResult.message = {
                  role: "assistant",
                  model,
                  content: String(continuation.proposal || "").trim() || "La siguiente acción también necesita tu aprobación.",
                };
                if (continuation.sources) publicResult.message.sources = continuation.sources;
              } else {
                publicResult.message = continuation.message;
              }
              sendJson(res, 200, publicResult);
              recordApiResult(200, { owner: "mykos-gateway" });
              return true;
            } catch (error) {
              const continuationError = String(error?.message || error || "").trim() || "El modelo no pudo continuar después de la aprobación.";
              Object.assign(publicResult, {
                conversation_id: conversationId,
                model,
                error: continuationError,
                continuation_failed: true,
              });
              sendJson(res, 502, publicResult);
              recordApiResult(502, { owner: "mykos-gateway" });
              return true;
            } finally {
              controlPlane.activity.finish(activityId);
            }
          }
          const resolved = await jsonRequest(
            `${backend.config.url}/mykos-control/approvals/resolve`,
            {
              approval_id: approvalId,
              decision,
              activity_id: payload?.activity_id,
              permission_mode: payload?.permission_mode,
              conversation_permission_mode: payload?.conversation_permission_mode,
            },
            900_000,
            { "X-MyKOS-Control-Token": cfg.control.token },
          );
          const status = resolved.status >= 400 ? resolved.status : 503;
          if (resolved.status >= 400 || !isObject(resolved.body)) {
            sendJson(res, status, { ok: false, error: String(resolved.body?.error || "No se pudo resolver la aprobación.") }); recordApiResult(status, { owner: "mykos-gateway" }); return true;
          }
          sendJson(res, 200, resolved.body); recordApiResult(200, { owner: "mykos-gateway" }); return true;
        }
        if (req.method === "POST" && apiPath === "/api/session/diary") {
          let payload = {};
          try { payload = JSON.parse((await readBody(req, 8192)).toString("utf-8") || "{}"); } catch {}
          const convId = String(payload.conversation_id || "").trim();
          const model = String(payload.model || "").trim();
          // Leer conversación del almacén
          if (!storeRuntime?.store) { sendJson(res, 503, { ok: false, error: "El almacén no está disponible." }); recordApiResult(503, { owner: "mykos-gateway" }); return true; }
          const convDoc = storeRuntime.store.get("conversations");
          const convs = convDoc?.data?.conversations || [];
          const conv = convId ? convs.find((c) => c?.id === convId) : convs.at(-1);
          const messages = conv?.messages || [];
          const chatMessages = messages.filter((m) => m?.role === "user" || m?.role === "assistant");
          if (!chatMessages.length) { sendJson(res, 400, { ok: false, error: "No hay mensajes en esta sesión para resumir." }); recordApiResult(400, { owner: "mykos-gateway" }); return true; }
          // Construir texto de conversación
          let conversationText = "";
          for (const m of chatMessages) {
            const label = m.role === "user" ? "Usuario" : "MyKOS";
            const content = String(m.content || "").trim();
            if (content) conversationText += `${label}: ${content}\n\n`;
          }
          const now = new Date();
          const dateStr = now.toLocaleDateString("es-ES", { year: "numeric", month: "2-digit", day: "2-digit" }) + " " + now.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
          // Hasta ~30.000 caracteres (caben en el contexto mínimo de 16384). Si la sesión es más larga se
          // conservan el arranque y, sobre todo, el final, que es donde quedan las decisiones y los pendientes.
          const diaryExcerpt = conversationText.length <= 30_000
            ? conversationText
            : `${conversationText.slice(0, 6_000)}\n\n[… parte central de la sesión omitida por longitud …]\n\n${conversationText.slice(-24_000)}`;
          const summaryPrompt = `Eres MyKOS. Acaba de terminar una sesión de trabajo con Usuario el ${dateStr}. Resume esta conversación de forma muy concisa (máximo 200 palabras) para tu diario personal. Incluye: (1) los temas principales tratados, (2) las decisiones tomadas o los avances conseguidos, (3) cualquier tarea pendiente que quedó sin terminar. Escribe en primera persona como MyKOS. No incluyas saludos ni despedidas.\n\nCONVERSACIÓN:\n${diaryExcerpt}`;
          // Llamar a Ollama directamente con un modelo local que exista: el del selector si está instalado;
          // si no (modelo remoto o vacío), el que ya esté cargado en memoria; si no, el primero con chat.
          const ollamaBase = (cfg.backend?.ollamaUrl || "http://127.0.0.1:11434").replace(/\/+$/, "");
          const ollamaGet = async (route) => {
            try { return await (await fetch(`${ollamaBase}${route}`, { signal: AbortSignal.timeout(5_000) })).json(); } catch { return {}; }
          };
          const installed = Array.isArray((await ollamaGet("/api/tags")).models) ? (await ollamaGet("/api/tags")).models : [];
          const loaded = Array.isArray((await ollamaGet("/api/ps")).models) ? (await ollamaGet("/api/ps")).models : [];
          const canChat = (m) => Array.isArray(m?.capabilities) && m.capabilities.includes("completion");
          const ollamaModel = (installed.find((m) => m?.name === model && canChat(m))
            || installed.find((m) => canChat(m) && loaded.some((l) => l?.name === m.name))
            || installed.find(canChat))?.name || "";
          if (!ollamaModel) { sendJson(res, 503, { ok: false, error: "No hay ningún modelo local de Ollama con el que generar el resumen." }); recordApiResult(503, { owner: "mykos-gateway" }); return true; }
          // Mismo contexto con el que ya está cargado el modelo, para no forzar una recarga.
          const diaryCtx = Number(loaded.find((l) => l?.name === ollamaModel)?.context_length) || 16384;

          let summary = "";
          try {
            const ollamaRes = await fetch(`${ollamaBase}/api/chat`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ model: ollamaModel, messages: [{ role: "user", content: summaryPrompt }], stream: false, think: false, keep_alive: -1, options: { num_predict: 2000, num_ctx: diaryCtx } }),
              signal: AbortSignal.timeout(180_000),
            });
            const ollamaJson = await ollamaRes.json();
            summary = String(ollamaJson?.message?.content || "").trim();
            if (!summary && ollamaJson?.error) throw new Error(ollamaJson.error);
            if (!summary) {
              sendJson(res, 502, { ok: false, error: "El modelo no generó ningún resumen. Respuesta cruda: " + JSON.stringify(ollamaJson).slice(0, 500) });
              recordApiResult(502, { owner: "mykos-gateway" });
              return true;
            }
          } catch (err) {
            sendJson(res, 502, { ok: false, error: `No se pudo generar el resumen: ${err?.message || err}` }); recordApiResult(502, { owner: "mykos-gateway" }); return true;
          }
          if (!summary) { sendJson(res, 502, { ok: false, error: "El modelo no generó ningún resumen." }); recordApiResult(502, { owner: "mykos-gateway" }); return true; }
          // Escribir en el diario
          const { appendFileSync, mkdirSync } = await import("node:fs");
          const { join } = await import("node:path");
          const diaryDir = join(cfg.workspaceDir || join(os.homedir(), ".mykos", "workspace"), "memory", "core");
          const diaryFile = join(diaryDir, "diario-mykos.md");
          try {
            mkdirSync(diaryDir, { recursive: true });
            appendFileSync(diaryFile, `\n\n---\n\n## 📅 Sesión del ${dateStr}\n\n${summary}\n`, "utf-8");
          } catch (err) {
            sendJson(res, 500, { ok: false, error: `No se pudo escribir el diario: ${err?.message || err}` }); recordApiResult(500, { owner: "mykos-gateway" }); return true;
          }
          sendJson(res, 200, { ok: true, date: dateStr, summary });
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (req.method === "GET" && apiPath === "/api/voice/mode") {
          const currentMode = cfg.realtime.mode || (cfg.realtime.enabled ? "cloud" : "local");
          let gemini = { model: cfg.geminiLive.model, voice: cfg.geminiLive.voice, available: false, error: "No se ha podido comprobar la credencial de Gemini Live." };
          try {
            const status = await jsonRequest(`${backend.config.url}/mykos-control/gemini-live/status`, {}, 2_500, { "X-MyKOS-Control-Token": cfg.control.token });
            if (status.status < 400 && isObject(status.body)) {
              gemini = {
                model: cfg.geminiLive.model,
                voice: cfg.geminiLive.voice,
                available: status.body.available === true,
                error: String(status.body.error || "").slice(0, 300),
              };
            }
          } catch { /* el selector sigue mostrando el modo aunque el backend esté arrancando */ }
          sendJson(res, 200, {
            ok: true,
            mode: currentMode,
            cloud: { model: cfg.realtime.model, voice: cfg.realtime.voice, available: realtime.credentialAvailable() },
            gemini,
          });
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (req.method === "POST" && apiPath === "/api/voice/mode") {
          let payload = null;
          try {
            payload = JSON.parse((await readBody(req, 2048)) || "{}");
          } catch {
            sendJson(res, 400, { error: "El cuerpo debe ser JSON válido." });
            recordApiResult(400, { owner: "mykos-gateway" });
            return true;
          }
          const mode = typeof payload?.mode === "string" ? payload.mode.trim().toLowerCase() : "";
          if (mode !== "local" && mode !== "cloud" && mode !== "gemini") {
            sendJson(res, 400, { error: 'mode debe ser "local", "cloud" o "gemini".' });
            recordApiResult(400, { owner: "mykos-gateway" });
            return true;
          }
          if (mode === "cloud" && !realtime.credentialAvailable()) {
            sendJson(res, 409, {
              error: "La llamada en la nube (OpenAI) todavía no tiene credencial propia de MyKOS. Ejecuta «mykos realtime set-key» y vuelve a intentarlo.",
              code: "realtime_not_configured",
            });
            recordApiResult(409, { owner: "mykos-gateway" });
            return true;
          }
          if (mode === "gemini") {
            let available = false;
            let reason = "";
            try {
              const status = await jsonRequest(`${backend.config.url}/mykos-control/gemini-live/status`, {}, 2_500, { "X-MyKOS-Control-Token": cfg.control.token });
              available = status.status < 400 && status.body?.available === true;
              reason = String(status.body?.error || "").slice(0, 300);
            } catch { reason = "El backend de MyKOS no responde todavía."; }
            if (!available) {
              sendJson(res, 409, {
                error: reason || "Gemini Live necesita una API key de Gemini guardada en MyKOS.",
                code: "gemini_live_not_configured",
              });
              recordApiResult(409, { owner: "mykos-gateway" });
              return true;
            }
          }
          const enabled = mode === "cloud";
          cfg.realtime.enabled = enabled;
          cfg.realtime.mode = mode;
          const persisted = persistVoiceMode(cfg.gatewayConfigFile, mode, cfg, api.logger);
          controlAudit(cfg.control.auditFile, { event: "voice_mode_changed", mode, persisted });
          sendJson(res, 200, { ok: true, mode, persisted });
          recordApiResult(200, { owner: "mykos-gateway" });
          return true;
        }
        if (authority && req.method === "POST" && /^\/api\/permissions\/[^/]+\/revoke$/.test(apiPath)) {
          const permissionId = decodeURIComponent(apiPath.split("/")[3] || "");
          const revoked = authority.revoke(permissionId);
          if (!revoked) {
            sendJson(res, 404, { error: "El permiso no existe, ya está revocado o ya no está activo." });
            recordApiResult(404, { owner: "mykos-gateway" });
          } else {
            sendJson(res, 200, { ok: true, revoked: true, permission: revoked });
            recordApiResult(200, { owner: "mykos-gateway" });
          }
          return true;
        }
        if (req.method === "POST" && (apiPath === "/api/transcribe" || apiPath === "/api/tts")) {
          const privatePath = apiPath === "/api/transcribe" ? "/mykos-control/transcribe" : "/mykos-control/tts";
          const status = await proxyRequest(
            req,
            res,
            backend.config.url,
            null,
            privatePath,
            { "x-mykos-control-token": cfg.control.token },
          );
          recordApiResult(status, { owner: "mykos-gateway", internal_path: privatePath });
          return true;
        }
        if (backend.config.spawn && backend.phase !== "up") {
          const starting = backend.phase === "starting" || backend.phase === "restarting";
          sendJson(
            res,
            503,
            { error: starting ? "MyKOS está arrancando. Vuelve a intentarlo en unos segundos." : `El servidor interno de MyKOS no está en marcha. ${backend.lastError}`.trim() },
            starting ? { "Retry-After": "2" } : {},
          );
          recordApiResult(503, { owner: "mykos-gateway", backend_phase: backend.phase });
          return true;
        }
        // Servicios auxiliares (fase 3, cuarto corte): el Gateway DECIDE antes de reenviar. Valida la forma exacta de
        // la petición, aplica límites de carga y firma la decisión; el trabajador exige esa firma en estas rutas.
        const policy = cfg.policy.strict ? policyFor(req.method, apiPath) : null;
        const forwardHeaders = { "x-mykos-control-token": cfg.control.token };
        let bufferedBody = null;
        let lease = null;
        if (policy) {
          if (policy.body === "json") {
            // Con el tamaño declarado se responde 413 limpio, sin leer nada: cortar la lectura a mitad deja al
            // navegador con una conexión reiniciada en vez de un error claro.
            const declared = Number(req.headers["content-length"]);
            if (Number.isFinite(declared) && declared > (policy.maxBytes || 2048)) {
              controlAudit(cfg.control.auditFile, {
                event: "api_denied", method: req.method, path: apiPath, ...routeMeta,
                status: 413, reason: "body_too_large", policy: policy.group,
              });
              sendJson(res, 413, { error: `El cuerpo de esta ruta no puede pasar de ${policy.maxBytes || 2048} bytes.` });
              return true;
            }
            try {
              bufferedBody = await readBody(req, (policy.maxBytes || 2048) + 4096);
            } catch (error) {
              const tooLarge = error?.code === "BODY_TOO_LARGE";
              controlAudit(cfg.control.auditFile, {
                event: "api_denied", method: req.method, path: apiPath, ...routeMeta,
                status: tooLarge ? 413 : 400, reason: tooLarge ? "body_too_large" : "unreadable_body", policy: policy.group,
              });
              sendJson(res, tooLarge ? 413 : 400, { error: tooLarge ? "El cuerpo de esta ruta es demasiado grande." : "No se pudo leer la petición." });
              return true;
            }
          }
          const decision = decide(
            policy,
            { method: req.method, pathname: apiPath, headers: req.headers, body: bufferedBody, searchParams: apiUrl.searchParams },
            policyLimiter,
          );
          if (!decision.ok) {
            controlAudit(cfg.control.auditFile, {
              event: "api_denied", method: req.method, path: apiPath, ...routeMeta,
              status: decision.status, reason: decision.reason, policy: policy.group,
            });
            sendJson(res, decision.status, { error: decision.message }, decision.retryAfter ? { "Retry-After": String(decision.retryAfter) } : {});
            return true;
          }
          lease = decision;
          forwardHeaders[DECISION_HEADER] = decisionHeaderValue(cfg.control.token, req.method, apiPath, policy.body === "json" ? bufferedBody : null);
          controlAudit(cfg.control.auditFile, {
            event: "api_decision", method: req.method, path: apiPath, ...routeMeta,
            decision: "allow", policy: policy.group, body_bound: policy.body === "json",
          });
        }
        // El trabajador solo atiende lo que trae el token del Gateway (server.py rechaza el resto con 403). El token
        // se pone aquí y sustituye a cualquiera que el navegador hubiera enviado.
        try {
          let internalPath = workerPath;
          if (apiPath === "/api/benchmark") internalPath = "/mykos-control/benchmark";
          else if (apiPath === "/api/nodes/heartbeat") internalPath = "/mykos-control/nodes/heartbeat";
          else if (apiPath === "/api/uploads") internalPath = "/mykos-control/uploads";
          const status = await proxyRequest(req, res, backend.config.url, bufferedBody, internalPath, forwardHeaders);
          recordApiResult(status, { owner: "mykos-gateway", worker: "python", ...(policy ? { policy: policy.group } : {}), ...(internalPath !== workerPath ? { internal_path: internalPath } : {}) });
        } finally {
          lease?.release?.();
        }
        return true;
      },
    });

    // API interna del almacén de datos (solo para el backend, con token). Solo existe con store.enabled.
    if (storeRuntime) {
      api.registerHttpRoute({
        path: STORE_PREFIX,
        auth: "plugin",
        match: "prefix",
        handler: async (req, res) => {
          await handleStoreRequest(req, res, storeRuntime, api.logger);
          return true;
        },
      });
    }

    // El backend solo se lanza desde el servicio completo, nunca al registrar (ver regla 3).
    if (backend.config.spawn && (api.registrationMode === undefined || api.registrationMode === "full")) {
      api.registerService({
        id: "mykos-backend",
        start: async (ctx) => { startGatewayAutomationScheduler(storeRuntime); return backend.start(ctx); },
        stop: async () => {
          await backend.stop();
          await modelController?.stop();
          stopGatewayAutomationScheduler();
        },
      });
    }
  },
};




