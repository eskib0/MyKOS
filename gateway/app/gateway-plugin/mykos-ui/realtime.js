// Controlador de sesiones OpenAI Realtime propiedad de MyKOS.
// El navegador entrega SDP a MyKOS; MyKOS usa solo su propia credencial y devuelve
// la respuesta SDP. La clave nunca llega al navegador.

import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";

const MAX_SDP_BYTES = 256 * 1024;
const MIN_SDP_BYTES = 32;
const OPENAI_LIVE_SESSIONS_URL = "/v1/live/sessions";
const CHATGPT_QUICKSILVER_URL = "https://chatgpt.com/backend-api/codex/realtime/calls?intent=quicksilver&architecture=avas";
const GPT_LIVE_CODEX = "gpt-live-1-codex";

// La capa Live conversa y MyKOS ejecuta el trabajo real a través de su llamada de voz y sus permisos.
const MYKOS_LIVE_INSTRUCTIONS = `You are MyKOS's realtime voice layer. You have no tools of your own.
Delegate any request that requires real work, reasoning, current information, or actions to the client through a delegation.
Delegate each user request once and wait for its result. New user follow-ups, corrections, and explicit retries are new requests. Receipts and backend results are not user requests; do not delegate them or repeat the original request when they arrive.
Keep the conversation natural while delegated work runs.

Context on the commentary channel is silent background. You may use it, but never read it aloud.
Context on the speakable channel is your answer to deliver naturally in your own words. Never mention the channel or the delegation.
Speak like a person, in Spanish from Spain. Never read out symbols or formatting: quotes, braces, brackets, asterisks, URLs, markdown or JSON keys. If the speakable context contains any, ignore them and say only the natural sentence.`;

export class RealtimeError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function clean(value, max = 200) {
  const text = String(value ?? "").trim();
  return text && text.length <= max && !/[\r\n\0]/.test(text) ? text : "";
}

function secretFromFile(file) {
  try { return file ? String(readFileSync(file, "utf8")).trim() : ""; } catch { return ""; }
}

function mykosCodexOAuthFromFile(file) {
  try {
    const data = JSON.parse(readFileSync(file, "utf8"));
    const tokens = data?.tokens && typeof data.tokens === "object" ? data.tokens : {};
    const accessToken = clean(tokens.access_token, 20_000);
    const accountId = clean(tokens.account_id, 300);
    return accessToken && accountId ? { accessToken, accountId } : null;
  } catch {
    return null;
  }
}

function isSubscriptionGptLive(model) {
  return String(model || "").trim().toLowerCase() === GPT_LIVE_CODEX;
}

function buildLiveSession(model, voice) {
  return {
    model,
    instructions: MYKOS_LIVE_INSTRUCTIONS,
    audio: { output: { voice } },
    delegation: { type: "client" },
  };
}

function readErrorDetail(text, secrets = []) {
  let value = String(text || "").trim();
  for (const secret of secrets) if (secret) value = value.split(secret).join("[REDACTED]");
  try {
    const parsed = JSON.parse(value);
    value = String(parsed?.error?.message || parsed?.message || parsed?.error?.code || value);
  } catch {}
  return clean(value, 300) || "sin detalle";
}

export function validateSdp(value) {
  if (typeof value !== "string") throw new RealtimeError(400, "bad_sdp", "Falta la oferta SDP de WebRTC.");
  // SDP es un formato sensible a su terminador de línea. No usar trim():
  // Chrome entrega \r\n al final y GPT-Live rechaza la oferta si se elimina.
  const sdp = value;
  const bytes = Buffer.byteLength(sdp, "utf8");
  if (bytes < MIN_SDP_BYTES || bytes > MAX_SDP_BYTES || !/^v=0\r?$/m.test(sdp.trim())) {
    throw new RealtimeError(400, "bad_sdp", "La oferta SDP de WebRTC no es válida.");
  }
  return sdp;
}

// La suscripción de ChatGPT comparte cuota con Codex: cuando se agota, el
// proveedor responde 429 usage_limit_reached con la hora de restablecimiento.
// Solo se expone un texto en español y la hora; nunca el cuerpo del proveedor.
export function usageLimitMessage(status, rawBody, now = Date.now()) {
  let error = null;
  try { error = JSON.parse(String(rawBody || ""))?.error ?? null; } catch {}
  if (status !== 429 && error?.type !== "usage_limit_reached") return "";
  const resetsAt = Number(error?.resets_at);
  const resetsIn = Number(error?.resets_in_seconds);
  const at = Number.isFinite(resetsAt) && resetsAt > 0 ? resetsAt * 1000 : Number.isFinite(resetsIn) && resetsIn > 0 ? now + resetsIn * 1000 : 0;
  if (!at) return "Límite de uso de ChatGPT alcanzado. Inténtalo más tarde.";
  const zone = "Europe/Madrid";
  const time = new Date(at).toLocaleTimeString("en-GB", { timeZone: zone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const sameDay = new Date(at).toLocaleDateString("es-ES", { timeZone: zone }) === new Date(now).toLocaleDateString("es-ES", { timeZone: zone });
  const day = sameDay ? "" : `el ${new Date(at).toLocaleDateString("en-GB", { timeZone: zone, day: "2-digit", month: "2-digit" })} `;
  return `Límite de uso de ChatGPT alcanzado. Se restablece ${day}a las ${time}.`;
}

// La respuesta SDP también es sensible al terminador: su última línea es
// a=ice-pwd y Chrome la rechaza ("Invalid SDP line") si falta el CRLF final.
// No usar trim(): se conserva el contenido y se garantiza un único CRLF final.
export function finishAnswerSdp(value) {
  if (typeof value !== "string" || !value.trim()) return "";
  return `${value.replace(/[\r\n\s]+$/, "")}\r\n`;
}

export class MyKOSRealtimeController {
  constructor({ registry, config, logger, fetchImpl = globalThis.fetch } = {}) {
    this.registry = registry;
    this.config = config ?? {};
    this.logger = logger;
    this.fetch = fetchImpl;
  }

  configured() {
    return this.config.enabled === true && this.credentialAvailable();
  }

  // Independiente de `enabled`: permite comprobar si activar la nube tendría sentido
  // antes de activarla (el interruptor de modo de llamada no debe encender algo roto).
  credentialAvailable() {
    if (isSubscriptionGptLive(this.config.model)) return Boolean(mykosCodexOAuthFromFile(this.config.oauthFile));
    return Boolean(clean(process.env.MYKOS_REALTIME_API_KEY, 500) || clean(secretFromFile(this.config.credentialFile), 500));
  }

  apiKey() {
    const key = clean(process.env.MYKOS_REALTIME_API_KEY, 500) || clean(secretFromFile(this.config.credentialFile), 500);
    if (!key) throw new RealtimeError(503, "realtime_not_configured", "La voz Realtime de MyKOS todavía no tiene una credencial propia.");
    return key;
  }

  async create({ sessionId, sdp, model, voice } = {}) {
    if (this.config.enabled !== true) throw new RealtimeError(503, "realtime_disabled", "La voz Realtime independiente de MyKOS todavía no está activada.");
    if (typeof this.fetch !== "function") throw new RealtimeError(503, "realtime_unavailable", "El Gateway no dispone de cliente HTTP para Realtime.");
    const offer = validateSdp(sdp);
    const selectedModel = clean(model || this.config.model, 120);
    const selectedVoice = clean(voice || this.config.voice, 80);
    if (!selectedModel || !selectedVoice) throw new RealtimeError(400, "bad_realtime_config", "El modelo o la voz de Realtime no son válidos.");
    const subscription = isSubscriptionGptLive(selectedModel);
    const oauth = subscription ? mykosCodexOAuthFromFile(this.config.oauthFile) : null;
    if (subscription && !oauth) {
      throw new RealtimeError(503, "realtime_oauth_missing", "MyKOS necesita su propia sesión OAuth de OpenAI para usar gpt-live-1-codex con Cove.");
    }

    const call = this.registry.create({ sessionId, model: `openai-realtime/${selectedModel}` });
    try {
      const requestIds = { sessionId: randomUUID(), threadId: randomUUID(), realtimeSessionId: randomUUID() };
      const response = await this.fetch(subscription ? CHATGPT_QUICKSILVER_URL : `${this.config.apiBase}${OPENAI_LIVE_SESSIONS_URL}`, {
        method: "POST",
        headers: subscription
          ? {
            Authorization: `Bearer ${oauth.accessToken}`,
            "Content-Type": "application/json",
            "OpenAI-Alpha": "quicksilver=v2",
            "session-id": requestIds.sessionId,
            "thread-id": requestIds.threadId,
            "x-session-id": requestIds.realtimeSessionId,
            "chatgpt-account-id": oauth.accountId,
          }
          : { Authorization: `Bearer ${this.apiKey()}`, "Content-Type": "application/json", "OpenAI-Safety-Identifier": this.config.safetyIdentifier },
        // gpt-live-1-codex es la ruta ChatGPT OAuth de Talk. gpt-live-1 (API
        // pública) usa /v1/live/sessions. Mezclarlos era la causa del HTTP 400.
        body: subscription
          ? JSON.stringify({ sdp: offer, session: buildLiveSession(selectedModel, selectedVoice) })
          : JSON.stringify({ session: buildLiveSession(selectedModel, selectedVoice), transport: { type: "webrtc", sdp: offer } }),
        signal: AbortSignal.timeout(this.config.timeoutMs),
      });
      const rawBody = await response.text().catch(() => "");
      let body = null;
      if (!subscription) try { body = rawBody ? JSON.parse(rawBody) : null; } catch {}
      const answer = finishAnswerSdp(subscription ? rawBody : body?.transport?.sdp);
      const providerSessionId = clean(subscription ? response.headers.get("openai-session-id") : body?.session?.id, 200)
        || clean(response.headers.get("location")?.split("/").filter(Boolean).at(-1), 200);
      if (!response.ok || !answer || !providerSessionId) {
        this.registry.setState(call.callId, "error", { error: `Realtime rechazó la creación de sesión (HTTP ${response.status || 502}).` });
        const providerCode = clean(body?.error?.code || body?.error?.type, 80) || (subscription ? "chatgpt-oauth" : "sin_código");
        const providerMessage = readErrorDetail(rawBody, subscription ? [oauth?.accessToken, oauth?.accountId] : [this.apiKey()]);
        // Solo diagnóstico de protocolo: nunca incluir Authorization, SDP ni cuerpo enviado.
        this.logger?.warn?.(`mykos-ui: Realtime rechazó una sesión (HTTP ${response.status || 502}; ${providerCode}; ${providerMessage})`);
        const usageLimit = usageLimitMessage(response.status, rawBody);
        if (usageLimit) {
          this.registry.setState(call.callId, "error", { error: usageLimit });
          throw new RealtimeError(429, "realtime_usage_limit", usageLimit);
        }
        throw new RealtimeError(response.status >= 400 && response.status < 500 ? 502 : 503, "realtime_create_failed", "No se pudo crear la llamada Realtime de MyKOS.");
      }
      const active = this.registry.setState(call.callId, "active", { connection: { transport: "webrtc", audio: true, realtime: true, provider_session_id: providerSessionId } });
      return { ok: true, call: active, session: { id: providerSessionId, model: selectedModel, voice: selectedVoice }, transport: { type: "webrtc", sdp: answer } };
    } catch (error) {
      if (error instanceof RealtimeError) throw error;
      this.registry.setState(call.callId, "error", { error: "No se pudo contactar con OpenAI Realtime." });
      this.logger?.warn?.(`mykos-ui: fallo al crear Realtime: ${error?.message ?? error}`);
      throw new RealtimeError(503, "realtime_unreachable", "No se pudo contactar con OpenAI Realtime.");
    }
  }
}
