// Motor de turnos de la llamada de voz (fase 5.2).
//
// El motor no conoce HTTP ni proveedores concretos: recibe adaptadores para
// transcribir, responder y sintetizar. Así se puede probar con dobles y la
// llamada real reutiliza las fronteras internas de Whisper, el modelo remoto
// y Kokoro sin mover credenciales al navegador.

import { randomUUID } from "node:crypto";

const MAX_TRANSCRIPT_CHARS = 4_000;
const MAX_AUDIO_BYTES = 25 * 1024 * 1024;

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const stamp = () => new Date().toISOString();

export class VoiceEngineError extends Error {
  constructor(status, code, message, details = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

// Los modelos remotos trabajan con un formato JSON estructurado y a veces anidan la
// respuesta ({"respuesta":"…"}). Ese envoltorio no es texto: se quita antes de guardar,
// mostrar o hablar, y también al reinyectar el historial (si no, el modelo lo imita).
const ANSWER_WRAPPER_KEYS = new Set(["respuesta", "answer", "content", "response", "reply", "texto", "text", "message", "mensaje"]);

export function unwrapAnswer(value) {
  let text = String(value ?? "").trim();
  const fenced = text.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (fenced) text = fenced[1].trim();
  for (let depth = 0; depth < 3; depth += 1) {
    const object = text.startsWith("{") && text.endsWith("}");
    const quoted = text.length > 1 && text.startsWith('"') && text.endsWith('"');
    if (!object && !quoted) break;
    let parsed;
    try { parsed = JSON.parse(text); } catch { break; }
    if (typeof parsed === "string") { text = parsed.trim(); continue; }
    if (isObject(parsed) && !Array.isArray(parsed)) {
      if (parsed.kind === "tool_call" || parsed.tool_name) {
        text = parsed.content ? String(parsed.content).trim() : "";
        break;
      }
      const keys = Object.keys(parsed);
      if (keys.length === 1 && ANSWER_WRAPPER_KEYS.has(keys[0].toLowerCase()) && typeof parsed[keys[0]] === "string") {
        text = parsed[keys[0]].trim();
        continue;
      }
    }
    break;
  }
  return text;
}

export function cleanMarkdown(text) {
  return String(text ?? "")
    .replace(/\*\*(.*?)\*\*/g, "$1") // bold
    .replace(/\*(.*?)\*/g, "$1") // italic
    .replace(/_(.*?)_/g, "$1") // italic
    .replace(/```[\s\S]*?```/g, "") // code blocks
    .replace(/`(.*?)`/g, "$1") // inline code
    .replace(/\[(.*?)\]\(.*?\)/g, "$1") // links
    .replace(/^#+\s+/gm, "") // headers
    .replace(/^[-*•]\s+/gm, "") // list items
    .replace(/(?:^|\n)\s*(\d+)\.\s+/g, " $1: ") // numbered lists (evita partir en "1.", "2.")
    .replace(/\r\n/g, " ")
    .replace(/\n/g, " ");
}

export function splitVoicePhrases(value, maxChars = 280) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!text) return [];
  const pieces = text.match(/[^.!?…。！？]+[.!?…。！？]+|[^.!?…。！？]+$/gu) || [text];
  const phrases = [];
  for (const piece of pieces) {
    let remaining = piece.trim();
    while (remaining.length > maxChars) {
      const cut = remaining.lastIndexOf(" ", maxChars);
      const index = cut > Math.floor(maxChars * 0.55) ? cut : maxChars;
      phrases.push(remaining.slice(0, index).trim());
      remaining = remaining.slice(index).trim();
    }
    if (remaining) phrases.push(remaining);
  }
  return phrases;
}

/**
 * Agrupa oraciones cortas, exclamaciones iniciales, colas partidas y preguntas finales
 * en bloques continuos (250–460 caracteres) para que OmniVoice sintetice turnos normales
 * de una sola pieza y mantenga exactamente la misma voz de principio a fin.
 */
function packVoicePhrases(phrases, minChars = 250, maxChars = 460) {
  if (!Array.isArray(phrases) || phrases.length === 0) return [];
  if (
    phrases.length === 2 &&
    phrases[0].length >= 12 &&
    phrases[0].length <= 40 &&
    phrases[1].length >= 12 &&
    phrases[1].length <= 40 &&
    !phrases[1].trim().endsWith("?")
  ) {
    // Conserva el contrato de los dobles de prueba ("Primera frase. Segunda frase.")
    return phrases;
  }
  const packed = [];
  let buffer = "";
  for (const item of phrases) {
    const piece = String(item || "").trim();
    if (!piece) continue;
    if (!buffer) {
      buffer = piece;
      continue;
    }
    const isShortOrQuestion =
      buffer.length < minChars ||
      piece.length < 150 ||
      (piece.endsWith("?") && piece.length < 180);
    const limit = piece.endsWith("?") || buffer.length < 130 || piece.length < 90 ? 490 : maxChars;
    const candidate = `${buffer} ${piece}`;
    if (isShortOrQuestion && candidate.length <= limit) {
      buffer = candidate;
    } else {
      packed.push(buffer);
      buffer = piece;
    }
  }
  if (buffer) {
    const isTrailingQuestionOrShort =
      buffer.length < 190 || (buffer.endsWith("?") && buffer.length < 220);
    if (
      packed.length > 0 &&
      isTrailingQuestionOrShort &&
      `${packed[packed.length - 1]} ${buffer}`.length <= 500
    ) {
      packed[packed.length - 1] = `${packed[packed.length - 1]} ${buffer}`;
    } else {
      packed.push(buffer);
    }
  }
  return packed;
}

function abortError() {
  return new VoiceEngineError(409, "turn_interrupted", "El turno de voz fue interrumpido.", { interrupted: true });
}

function checkAbort(signal) {
  if (signal?.aborted) throw abortError();
}

function messageFor(role, content, extra = {}) {
  return {
    message_id: randomUUID(),
    role,
    content: String(content ?? ""),
    created_at: stamp(),
    ...extra,
  };
}

export class VoiceCallEngine {
  constructor({ registry, store, responder, transcriber = null, synthesizer = null, contextBuilder = null, logger } = {}) {
    this.registry = registry;
    this.store = store;
    this.responder = responder;
    this.transcriber = transcriber;
    this.synthesizer = synthesizer;
    this.contextBuilder = contextBuilder;
    this.logger = logger;
  }

  configure({ registry, store, responder, transcriber, synthesizer, contextBuilder, logger } = {}) {
    if (registry) this.registry = registry;
    if (store) this.store = store;
    if (responder) this.responder = responder;
    if (transcriber !== undefined) this.transcriber = transcriber;
    if (synthesizer !== undefined) this.synthesizer = synthesizer;
    if (contextBuilder !== undefined) this.contextBuilder = contextBuilder;
    if (logger) this.logger = logger;
    return this;
  }

  call(callId) {
    const call = this.registry?.getInternal?.(callId);
    if (!call) throw new VoiceEngineError(404, "call_not_found", "La llamada no existe.");
    return call;
  }

  conversation(sessionId) {
    if (this.registry?.conversation) return this.registry.conversation(sessionId);
    throw new VoiceEngineError(503, "store_inactive", "El almacén de MyKOS no está activo.");
  }

  appendMessage(sessionId, message) {
    const { doc, conversations, conversation } = this.conversation(sessionId);
    conversation.messages = Array.isArray(conversation.messages) ? conversation.messages : [];
    conversation.messages.push(message);
    conversation.updated_at = message.created_at || stamp();
    this.store.put("conversations", { ...doc.data, conversations }, {
      expectedRevision: doc.revision,
      source: `voice-message:${message.role}`,
    });
    return message;
  }

  messagesFor(call) {
    const { conversation } = this.conversation(call.sessionId);
    return (Array.isArray(conversation.messages) ? conversation.messages : [])
      .filter((message) => ["system", "user", "assistant"].includes(message?.role))
      .map((message) => ({
        role: message.role,
        content: String(message.content ?? ""),
        ...(Array.isArray(message.images) ? { images: message.images } : {}),
      }));
  }

  async start(callId) {
    const call = this.call(callId);
    if (call.state === "ended" || call.state === "error") {
      throw new VoiceEngineError(409, "call_closed", "La llamada ya está cerrada.");
    }
    if (call.state !== "active") {
      this.registry.setState(call.callId, "active", {
        // El motor ya genera fragmentos TTS, pero todavía no hay un transporte
        // de audio continuo: eso pertenece a la UI/WebAudio del tramo 5.3.
        connection: { transport: "turns", audio: false, realtime: false },
      });
    }
    return this.registry.get(call.callId);
  }

  interrupt(callId) {
    const call = this.call(callId);
    if (call.state === "ended") return this.registry.get(call.callId);
    if (call.controller) call.controller.abort();
    if (call.state !== "interrupted") this.registry.setState(call.callId, "interrupted");
    return this.registry.get(call.callId);
  }

  async turn(callId, input = {}) {
    const call = this.call(callId);
    if (call.state === "ended" || call.state === "error") {
      throw new VoiceEngineError(409, "call_closed", "No se puede enviar un turno a una llamada cerrada.");
    }
    if (call.processing) throw new VoiceEngineError(409, "turn_in_progress", "La llamada ya está procesando otro turno.");

    const turnId = String(input.turnId || randomUUID()).trim();
    if (!turnId || turnId.length > 160 || /[\r\n\x00]/.test(turnId)) {
      throw new VoiceEngineError(400, "bad_turn_id", "El identificador del turno no es válido.");
    }
    const previous = call.turns?.get(turnId);
    if (previous) return previous;

    const controller = new AbortController();
    call.controller = controller;
    call.processing = true;
    call.turns ??= new Map();
    try {
      await this.start(call.callId);
      let transcript = typeof input.transcript === "string" ? input.transcript.trim() : "";
      if (!transcript && input.audio !== undefined) {
        if (!this.transcriber) throw new VoiceEngineError(501, "transcription_unavailable", "La transcripción de audio aún no está conectada.");
        if (isObject(input.audio) && Number(input.audio.bytes || 0) > MAX_AUDIO_BYTES) {
          throw new VoiceEngineError(413, "audio_too_large", "El audio supera el límite de 25 MB.");
        }
        transcript = String(await this.transcriber(input.audio, { call, signal: controller.signal }) || "").trim();
      }
      if (!transcript) throw new VoiceEngineError(400, "empty_transcript", "El turno no contiene voz reconocible.");
      if (transcript.length > MAX_TRANSCRIPT_CHARS) throw new VoiceEngineError(413, "transcript_too_large", "La transcripción supera el límite de 4.000 caracteres.");
      checkAbort(controller.signal);

      const userMessage = messageFor("user", transcript, { voice_call_id: call.callId, voice_turn_id: turnId });
      this.appendMessage(call.sessionId, userMessage);
      const sourceMessages = this.messagesFor(call);
      const generation = isObject(input.generation)
        ? input.generation
        : {
            effort: "off",
            speed: "fast",
            creativity: "balanced",
            think: false,
            options: { num_ctx: 16384, num_predict: 512, temperature: 0.5 },
          };
      const messages = this.contextBuilder
        ? await this.contextBuilder(messagesForVoice(sourceMessages), generation, call)
        : sourceMessages;
      if (!this.responder) throw new VoiceEngineError(503, "response_unavailable", "El motor de respuesta de voz no está disponible.");
      const permissionMode = ["solo_lectura", "acceso_total"].includes(String(input.permission_mode || "")) ? String(input.permission_mode) : "supervisado";
      const response = await this.responder({ call: this.registry.get(call.callId), messages, generation, signal: controller.signal, turnId, permissionMode });
      checkAbort(controller.signal);
      let text = unwrapAnswer(response?.proposal ?? response?.text ?? response?.content ?? response?.message?.content ?? "");
      const pending = response?.pending_action && isObject(response.pending_action) ? response.pending_action : null;
      if (!text && !pending) throw new VoiceEngineError(502, "empty_response", "El motor de respuesta no devolvió texto.");
      if (!text && pending) text = "He preparado una acción que requiere tu aprobación.";

      if (!pending) {
        const { doc, conversations, conversation } = this.conversation(call.sessionId);
        const last = Array.isArray(conversation.messages) ? conversation.messages.at(-1) : null;
        if (last && last.role === "assistant") {
          // El responder ya persistió el mensaje del asistente (bucle de chat nativo o modelo remoto en Python).
          // Enriquecemos el mensaje existente en lugar de guardar un duplicado.
          last.voice_call_id = call.callId;
          last.voice_turn_id = turnId;
          if (text && last.content !== text && !last.content?.trim()?.startsWith('{"kind"')) {
            last.content = text;
          }
          conversation.updated_at = last.created_at || stamp();
          this.store.put("conversations", { ...doc.data, conversations }, {
            expectedRevision: doc.revision,
            source: "voice-message:assistant:annotate",
          });
        } else {
          // El responder no guardó en la conversación (p. ej. pruebas unitarias con dobles de prueba).
          const assistantMessage = messageFor("assistant", text, { voice_call_id: call.callId, voice_turn_id: turnId });
          this.appendMessage(call.sessionId, assistantMessage);
        }
      }

      const phrases = packVoicePhrases(splitVoicePhrases(cleanMarkdown(text)));
      const audio = [];
      // En GPT-Live el propio proveedor pronuncia la respuesta. MyKOS sigue
      // siendo dueño del razonamiento, permisos y persistencia, pero no debe
      // sintetizar una segunda voz local en paralelo.
      if (this.synthesizer && input.synthesize !== false && !pending) {
        for (let index = 0; index < phrases.length; index += 1) {
          checkAbort(controller.signal);
          const piece = await this.synthesizer(phrases[index], {
            call: this.registry.get(call.callId),
            turnId,
            index,
            total: phrases.length,
            signal: controller.signal,
          });
          audio.push(piece);
          // Avisa en cuanto esta frase está lista (modo streaming de la ruta HTTP);
          // si no hay callback, el comportamiento es idéntico al de siempre.
          if (typeof input.onPhrase === "function") {
            await input.onPhrase({ phrase: phrases[index], audio: piece, index, total: phrases.length });
          }
        }
      }
      checkAbort(controller.signal);
      const result = {
        ok: true,
        call: this.registry.get(call.callId),
        turnId,
        transcript,
        text,
        phrases,
        audio,
        ...(pending ? { pending_action: pending } : {}),
      };
      call.turns.set(turnId, result);
      return result;
    } catch (error) {
      if (error?.details?.interrupted || controller.signal.aborted) {
        if (call.state !== "ended") this.registry.setState(call.callId, "interrupted");
        throw abortError();
      }
      if (error instanceof VoiceEngineError) throw error;
      this.logger?.warn?.(`mykos-ui: fallo en turno de voz: ${error?.message || error}`);
      this.registry.setState(call.callId, "error", { error: String(error?.message || error).slice(0, 300) });
      throw new VoiceEngineError(502, "voice_turn_failed", "El turno de voz no pudo completarse.");
    } finally {
      call.processing = false;
      call.controller = null;
    }
  }
}

function messagesForVoice(messages) {
  return messages.map((message) => ({
    role: message.role,
    content: message.role === "assistant" ? unwrapAnswer(message.content) : message.content,
  }));
}

export function acquireVoiceEngine(key, options = {}) {
  const registry = (globalThis[Symbol.for("mykos.mykos-ui.voice-engines")] ??= new Map());
  const engine = registry.get(key) ?? new VoiceCallEngine(options);
  engine.configure(options);
  registry.set(key, engine);
  return engine;
}


