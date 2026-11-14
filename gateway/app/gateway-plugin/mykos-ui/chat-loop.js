// Bucle de chat con herramientas del modelo local (llama.cpp / Ollama), propiedad del Gateway (fase 3, tramo 5).
//
// Es la versión en Node de la rama «modelo local» de run_model_until_result() de server.py: llama al modelo, mira si pide
// herramientas, decide (con la autoridad de permisos del Gateway) si se ejecutan, se piden a Usuario o se rechazan, y
// vuelve a llamar hasta tener una respuesta de texto o una aprobación pendiente.
//
// El módulo no toca red, disco ni procesos por su cuenta: todo llega inyectado (`deps`), así se prueba con un modelo y un
// trabajador falsos. Python queda como «manos»: solo ejecuta la herramienta o la acción concreta que el Gateway le pide.
//
// deps = {
//   model:     { request(provider, payload) }                       // ModelController del Gateway
//   authority: { authorize(tool, action, sid), createApproval(input), descriptor(tool, action), audit(ev, desc, extra) }
//   worker:    { catalog(), tool(name, args), prepare(name, args), action(action, sid, authorization),
//                activity(id, update), saveMessage(sid, message) }  // trabajador Python (server.py)
//   now:       () => "2026-09-26T13:34:14+00:00"
// }

export const LLAMA_MODEL_NAME = "mykos-cuda";
export const MAX_TOOL_ROUNDS = 32;
export const TOOL_CONTEXT_NUM_CTX = 16_384;
export const MAX_WEB_SEARCH_CALLS = 2;
export const MAX_WEB_FETCH_CALLS = 6;
const MAX_SOURCE_CARDS = 12;
const MAX_VERIFIED_TOOL_TRACE = 16;
const MAX_INTEGRITY_GUARD_RETRIES = 2;

const INTEGRITY_GUARD_MESSAGE = "AVISO DEL SISTEMA: en tu respuesta dices que hiciste algo ({claims}), pero en este turno "
  + "{evidence}. Haz UNA de estas dos cosas: "
  + "1) Llama ahora a la herramienta que hace falta (p. ej. find_project_paths, list_project_files o read_project_file). "
  + "2) Responde diciendo claramente que NO lo has hecho todavía. "
  + "No repitas que lo hiciste ni inventes el contenido de ningún archivo.";

const INTEGRITY_UNVERIFIED_NOTE = "\n\n⚠️ Aviso del sistema: esta respuesta dice que se hizo algo, pero MyKOS no registró ninguna "
  + "herramienta que lo confirme. No lo des por hecho.";

const WRITE_CLAIM_VERBS = "guardado|guardada|creado|creada|escrito|escrita|editado|editada|modificado|modificada|"
  + "actualizado|actualizada|borrado|borrada|eliminado|eliminada|instalado|instalada|"
  + "enviado|enviada|movido|movida|renombrado|renombrada|aplicado|aplicada|reiniciado|reiniciada|"
  + "detenido|detenida|lanzado|lanzada|añadido|añadida|registrado|registrada|commiteado";

const CHECK_CLAIM_VERBS = "ejecutado|ejecutada|comprobado|comprobada|verificado|verificada|probado|probada|reproducido|"
  + "revisado|revisada|leído|leida|leido|buscado|localizado|localizada|abierto|abierta|"
  + "consultado|consultada|analizado|analizada|inspeccionado|inspeccionada|listado|listada";

const WRITE_CLAIM_RE = new RegExp(`^(?:${WRITE_CLAIM_VERBS})$`, "i");
const ACTION_CLAIM_RE = new RegExp(
  `(?<![\\wáéíóúñ])(?<neg>no\\s+)?(?:ya\\s+)?(?:(?:te|le|lo|la|los|las|me)\\s+)?`
  + `(?:he|hemos|acabo\\s+de|se\\s+ha|se\\s+han|ya\\s+est[aá]|queda|qued[oó])\\s+`
  + `(?:(?:ya|todo|correctamente)\\s+)?(?<verb>${WRITE_CLAIM_VERBS}|${CHECK_CLAIM_VERBS})\\b`,
  "gi",
);

const INTENT_READ_VERBS = "leer|revisar|buscar|consultar|inspeccionar|listar|abrir|comprobar|verificar|localizar";
const INTENT_WRITE_VERBS = "editar|reescribir|modificar|actualizar|guardar|crear|implementar|aplicar|marcar|escribir|añadir|agregar|corregir";
const PENDING_READ_INTENT_RE = new RegExp(
  `(?:\\bvoy\\s+a\\s+(?:primero\\s+|empezar\\s+por\\s+)?(?:${INTENT_READ_VERBS})\\b`
  + `|\\bnecesito\\s+leer\\b`
  + `|\\bprimero\\s*,?\\s*(?:necesito\\s+|voy\\s+a\\s+)?(?:${INTENT_READ_VERBS}|leo|reviso|busco|abro|consulto)\\b)`,
  "i",
);
const PENDING_WRITE_INTENT_RE = new RegExp(
  `(?:\\bvoy\\s+a\\s+(?:empezar\\s+por\\s+|proceder\\s+a\\s+|pasar\\s+a\\s+)?(?:${INTENT_WRITE_VERBS})\\b`
  + `|\\bprimero\\s*,?\\s*(?:añado|agrego|edito|modifico|reescribo|creo|escribo|actualizo|implemento|aplico)\\b)`,
  "i",
);
const FAKE_LEDGER_RE = /<registro-[^>]*>[\s\S]*?(?:<\/registro[^>]*>|<\/registra[^>]*>|<\/registry[^>]*>|$)/gi;
const FAKE_TOOL_MARKUP_RE = /<registro-[^>]*>|<tool_call>|^\s*\[\s*\{\s*"tool"\s*:/i;
const MAX_SAVED_TOOL_CONTENT_CHARS = 12_000;
const MAX_SAVED_TOOL_EXCHANGE_ITEMS = 12;

export function stripFakeLedgerTags(value) {
  return text(value).replace(FAKE_LEDGER_RE, "").trim();
}

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value) => (value === null || value === undefined ? "" : String(value));
const toInt = (value, fallback = 0) => {
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) ? n : fallback;
};
const toFloat = (value, fallback = 0) => {
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? n : fallback;
};

export function utcNow() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00");
}

// ───────────────────────────── mensajes de herramienta y fuentes ─────────────────────────────

export function toolMessageForResult(result, supportsVision, toolName = "") {
  const publicResult = { ...(isObject(result) ? result : {}) };
  if (toolName && !publicResult.action && !publicResult.tool) publicResult.tool = toolName;
  const imageBase64 = publicResult._image_base64;
  const imageMimeType = publicResult._image_mime_type;
  delete publicResult._image_base64;
  delete publicResult._image_mime_type;
  if (imageBase64) {
    if (supportsVision) {
      publicResult.image_attached = true;
    } else {
      publicResult.image_attached = false;
      publicResult.image_note = "El modelo actual no admite visión; se devuelve únicamente el OCR y los metadatos.";
    }
  }
  const message = { role: "tool", content: JSON.stringify(publicResult) };
  if (imageBase64 && supportsVision) {
    message.images = [imageBase64];
    if (imageMimeType) message.image_mime_type = imageMimeType;
  }
  return message;
}

export function currentTurnToolTrace(messages) {
  let start = 0;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const item = messages[index];
    if (isObject(item) && item.role === "user" && !item.integrity_guard) {
      start = index + 1;
      break;
    }
  }
  const trace = [];
  for (const item of messages.slice(start)) {
    if (!isObject(item) || item.role !== "tool") continue;
    let decoded = null;
    try {
      const parsed = JSON.parse(text(item.content));
      if (isObject(parsed)) decoded = parsed;
    } catch {}
    if (!decoded) {
      trace.push({ tool: "", ok: false });
      continue;
    }
    const name = text(decoded.action || decoded.tool).trim();
    const entry = { tool: name, ok: Boolean(decoded.ok) };
    const error = text(decoded.error).trim();
    if (error) entry.error = error.slice(0, 500);
    trace.push(entry);
  }
  return trace.slice(-MAX_VERIFIED_TOOL_TRACE);
}

export function verifiedToolLedgerForPrompt(message) {
  const rawTrace = isObject(message) ? message.verified_tool_trace : null;
  if (!Array.isArray(rawTrace)) return "";
  const entries = [];
  for (const rawEntry of rawTrace.slice(-MAX_VERIFIED_TOOL_TRACE)) {
    if (!isObject(rawEntry)) continue;
    const name = text(rawEntry.tool).trim();
    if (!name) continue;
    const item = { tool: name, ok: Boolean(rawEntry.ok) };
    const error = text(rawEntry.error).trim();
    if (error) item.error = error.slice(0, 500);
    entries.push(item);
  }
  if (!entries.length) return "";
  return `<registro-verificado-del-host>\n${JSON.stringify(entries)}\n</registro-verificado-del-host>`;
}

export function inlineVerifiedLedger(messages) {
  return messages.map((item) => {
    if (
      !isObject(item)
      || item.role !== "assistant"
      || (Array.isArray(item.tool_calls) && item.tool_calls.length)
      || item.integrity_guard
    ) {
      return item;
    }
    const content = text(item.content);
    if (content.trimStart().startsWith('{"kind"') || content.includes("<registro-verificado-del-host>")) {
      return item;
    }
    const ledger = verifiedToolLedgerForPrompt(item);
    const suffix = ledger || "<registro-verificado-del-host>sin registro de herramientas para este mensaje</registro-verificado-del-host>";
    return { ...item, content: `${content}\n${suffix}` };
  });
}

export function unverifiedActionClaimReason(content, trace, sensitiveTools = new Set()) {
  const rawContent = text(content);
  const normalized = rawContent.replace(/\s+/g, " ").trim();
  if (!normalized) return "";
  if (FAKE_TOOL_MARKUP_RE.test(rawContent)) {
    return "AVISO DEL SISTEMA: has escrito una etiqueta <registro-...> o JSON de herramienta en el texto, pero ESO NO EJECUTA NINGUNA HERRAMIENTA. "
      + "Para usar una herramienta debes invocarla mediante llamada nativa (tool_calls), sin escribir etiquetas <registro-...> en tu respuesta. "
      + "Invoca ahora la herramienta necesaria mediante tool_calls.";
  }
  const okEntries = trace.filter((entry) => isObject(entry) && entry.ok);
  const claimed = [];
  for (const match of normalized.matchAll(ACTION_CLAIM_RE)) {
    if (match.groups?.neg) continue;
    const verb = text(match.groups?.verb).toLowerCase();
    if (verb && !claimed.includes(verb)) claimed.push(verb);
  }
  if (claimed.length) {
    const claimsText = claimed.slice(0, 4).join(", ");
    if (!okEntries.length) {
      return INTEGRITY_GUARD_MESSAGE
        .replace("{claims}", claimsText)
        .replace("{evidence}", "no hay ningún RESULTADO-DE-HERRAMIENTA correcto que lo confirme");
    }
    const writes = claimed.filter((verb) => WRITE_CLAIM_RE.test(verb));
    if (writes.length && sensitiveTools.size && !okEntries.some((entry) => sensitiveTools.has(text(entry.tool)))) {
      const used = [...new Set(okEntries.map((entry) => text(entry.tool)).filter(Boolean))].sort().join(", ") || "ninguna";
      return INTEGRITY_GUARD_MESSAGE
        .replace("{claims}", claimsText)
        .replace("{evidence}", `solo se usaron herramientas de lectura (${used}); ninguna escribió ni cambió nada`);
    }
  }
  if (!normalized.includes("?")) {
    if (PENDING_READ_INTENT_RE.test(normalized) && !okEntries.length) {
      return "AVISO DEL SISTEMA: has anunciado que vas a leer o consultar algo, pero has terminado el turno sin invocar ninguna herramienta (tool_calls). "
        + "No anuncies lo que vas a hacer: invoca directamente la herramienta ahora mismo (p. ej. read_project_file, list_project_files o find_project_paths).";
    }
    if (
      (PENDING_WRITE_INTENT_RE.test(normalized) || normalized.endsWith(":"))
      && sensitiveTools.size
      && !okEntries.some((entry) => sensitiveTools.has(text(entry.tool)))
    ) {
      return "AVISO DEL SISTEMA: has terminado tu mensaje anunciando un cambio o dejándolo cortado en dos puntos («:»), pero NO has invocado ninguna herramienta (tool_calls). "
        + "No anuncies los cambios paso a paso en texto: invoca ahora mismo write_project_file (con el archivo completo actualizado) o edit_project_file mediante tool_calls.";
    }
  }
  return "";
}

function compactToolMessage(item) {
  const raw = text(item.content);
  if (raw.length <= MAX_SAVED_TOOL_CONTENT_CHARS) {
    return pick(item, ["role", "content", "tool_call_id"]);
  }
  try {
    const parsed = JSON.parse(raw);
    if (isObject(parsed)) {
      for (const key of ["content", "stdout", "stderr", "text", "output"]) {
        if (typeof parsed[key] === "string" && parsed[key].length > 8_000) {
          parsed[key] = `${parsed[key].slice(0, 8_000)}\n[... contenido recortado en historial ...]`;
        }
      }
      return { ...pick(item, ["role", "tool_call_id"]), content: JSON.stringify(parsed) };
    }
  } catch {}
  return { ...pick(item, ["role", "tool_call_id"]), content: raw.slice(0, MAX_SAVED_TOOL_CONTENT_CHARS) };
}

export function extractTurnToolExchange(messages) {
  let start = 0;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const item = messages[index];
    if (isObject(item) && item.role === "user" && !item.integrity_guard) {
      start = index + 1;
      break;
    }
  }
  const exchange = [];
  for (const item of messages.slice(start)) {
    if (!isObject(item) || item.integrity_guard) continue;
    if (item.role === "assistant" && Array.isArray(item.tool_calls) && item.tool_calls.length) {
      exchange.push(pick(item, ["role", "content", "tool_calls"]));
    } else if (item.role === "tool") {
      exchange.push(compactToolMessage(item));
    }
  }
  return exchange.slice(-MAX_SAVED_TOOL_EXCHANGE_ITEMS);
}

export function integrityCheckAnswer(messages, content, retries, sensitiveTools = new Set()) {
  const trace = currentTurnToolTrace(messages);
  const reason = unverifiedActionClaimReason(content, trace, sensitiveTools);
  if (!reason) return { action: "ok", trace };
  if (retries >= MAX_INTEGRITY_GUARD_RETRIES) return { action: "warn", trace };
  messages.push({ role: "assistant", content: stripFakeLedgerTags(content), integrity_guard: true });
  messages.push({ role: "user", content: reason, integrity_guard: true });
  return { action: "retry", trace };
}

export function sourceCardsFromToolResult(result) {
  if (!isObject(result) || !result.ok) return [];
  const action = text(result.action);
  const cards = [];
  if (action === "web_search") {
    const consultedAt = text(result.searched_at);
    for (const item of Array.isArray(result.results) ? result.results : []) {
      if (!isObject(item)) continue;
      const title = text(item.title).trim();
      const url = text(item.url).trim();
      if (title && url) {
        cards.push({
          title: title.slice(0, 240),
          url: url.slice(0, 2000),
          snippet: text(item.snippet).trim().slice(0, 360),
          consulted_at: consultedAt,
          kind: "search",
        });
      }
    }
  } else if (action === "web_fetch") {
    const source = isObject(result.source) ? result.source : result;
    const title = text(source.title).trim();
    const url = text(source.url).trim();
    if (title && url) {
      cards.push({
        title: title.slice(0, 240),
        url: url.slice(0, 2000),
        snippet: "Fuente leída por MyKOS.",
        consulted_at: text(source.fetched_at ?? result.fetched_at),
        kind: "page",
      });
    }
  }
  return cards;
}

export function mergeSourceCards(target, result) {
  const seen = new Set(target.map((item) => item.url));
  for (const card of sourceCardsFromToolResult(result)) {
    if (seen.has(card.url)) continue;
    target.push(card);
    seen.add(card.url);
    if (target.length >= MAX_SOURCE_CARDS) break;
  }
}

export function researchSourcesAreVerified(args, sourceCards) {
  const verified = new Set(
    sourceCards
      .filter((card) => isObject(card) && text(card.url).trim())
      .map((card) => text(card.url).trim().replace(/\/+$/, "")),
  );
  const rawSources = isObject(args) ? args.sources : null;
  if (!verified.size || !Array.isArray(rawSources) || !rawSources.length) return false;
  const cited = new Set(
    rawSources
      .filter((item) => isObject(item) && text(item.url).trim())
      .map((item) => text(item.url).trim().replace(/\/+$/, "")),
  );
  if (!cited.size) return false;
  for (const url of cited) if (!verified.has(url)) return false;
  return true;
}

export function sourceCardsFromMessages(messages, currentTurnOnly = false) {
  if (currentTurnOnly) {
    const start = messages.findLastIndex((message) => isObject(message) && message.role === "user") + 1;
    messages = messages.slice(start);
  }
  const cards = [];
  for (const message of messages) {
    if (!isObject(message)) continue;

    if (message.role !== "tool") continue;
    let parsed;
    try {
      parsed = JSON.parse(text(message.content));
    } catch {
      continue;
    }
    mergeSourceCards(cards, parsed);
  }
  return cards;
}

// ───────────────────────────── llamadas al modelo ─────────────────────────────

function pick(item, keys) {
  const out = {};
  for (const key of keys) if (Object.hasOwn(item, key)) out[key] = item[key];
  return out;
}

function cleanAssistantMessage(item) {
  if (!isObject(item)) return item;
  if (item.role !== "assistant" || typeof item.content !== "string" || !item.content.includes("<registro-")) {
    return item;
  }
  return { ...item, content: stripFakeLedgerTags(item.content) };
}

/** Petición al motor Strata (formato OpenAI estándar). */
export function strataPayload(model, messages, conversationId, generation, toolSchemas) {
  const options = isObject(generation?.options) ? generation.options : {};
  const cleaned = messages.filter(isObject).map(cleanAssistantMessage);
  const payload = {
    model: model || "qwen3.8-flash-next-iq2_xs-32k",
    messages: cleaned.map((item) => pick(item, ["role", "content", "tool_calls", "tool_call_id", "images"])),
    stream: false,
    user: `mykos-web-${conversationId}`,
  };
  if (Object.keys(options).length) {
    payload.max_tokens = toInt(options.num_predict ?? 2048, 2048) || 2048;
    payload.temperature = toFloat(options.temperature ?? 0.5, 0.5);
  }
  const effort = text(generation?.effort).trim().toLowerCase();
  if (effort === "off") payload.reasoning_effort = "none";
  else if (["low", "medium", "high"].includes(effort)) payload.reasoning_effort = effort;
  if (toolSchemas.length) {
    payload.tools = toolSchemas;
    payload.tool_choice = "auto";
  }
  payload.stop = ["<|endoftext|>", "<|user|>", "<|assistant|>", "<|observation|>", "<|im_end|>"];
  return payload;
}

/** Petición al motor llama.cpp (formato OpenAI). Igual que mykos_gateway_chat_request() de server.py. */
export function llamaPayload(messages, conversationId, generation, toolSchemas, modelName = LLAMA_MODEL_NAME) {
  const options = isObject(generation?.options) ? generation.options : {};
  // No inyectar <registro-verificado-del-host> en mensajes assistant de modelos locales:
  // los modelos de 35B imitan esa etiqueta XML en vez de usar tool_calls nativos.
  const cleaned = messages.filter(isObject).map(cleanAssistantMessage);
  const payload = {
    model: modelName || LLAMA_MODEL_NAME,
    messages: cleaned.map((item) => pick(item, ["role", "content", "tool_calls", "tool_call_id", "images"])),
    stream: false,
    user: `mykos-web-${conversationId}`,
  };
  if (Object.keys(options).length) {
    payload.max_tokens = toInt(options.num_predict ?? 1024, 1024) || 1024;
    payload.temperature = toFloat(options.temperature ?? 0.5, 0.5);
  }
  const effort = text(generation?.effort).trim().toLowerCase();
  if (effort === "off") payload.reasoning_effort = "none";
  else if (["low", "medium", "high"].includes(effort)) payload.reasoning_effort = effort;
  if (toolSchemas.length) {
    payload.tools = toolSchemas;
    payload.tool_choice = "auto";
  }
  payload.stop = ["<|endoftext|>", "<|user|>", "<|assistant|>", "<|observation|>", "<|im_end|>"];
  return payload;
}

/** Petición a Ollama. Igual que la de la rama local de run_model_until_result(). */
export function ollamaPayload(model, messages, generation, toolSchemas, options) {
  const cleaned = messages.filter(isObject).map(cleanAssistantMessage);
  const payload = {
    model,
    // `sources` es metadato interno para verificar URLs de investigación: no forma parte del esquema de Ollama.
    messages: cleaned.map((item) => pick(item, ["role", "content", "images", "tool_calls", "image_mime_type"])),
    stream: false,
    think: generation?.think ?? false,
    tools: toolSchemas,
    keep_alive: -1,
  };
  if (isObject(options) && Object.keys(options).length) payload.options = options;
  return payload;
}

async function callModel(deps, ctx, messages, options) {
  const started = Date.now();
  if (ctx.useStrata) {
    const cleanModel = ctx.model.startsWith("strata/") ? ctx.model.slice(7) : ctx.model;
    const result = await deps.model.request("strata", strataPayload(cleanModel, messages, ctx.conversationId, ctx.generation, ctx.toolSchemas));
    const durationMs = Date.now() - started;
    const choice = isObject(result?.choices?.[0]) ? result.choices[0] : {};
    let msg = isObject(choice.message) ? { ...choice.message } : {};
    if (msg.content === null || msg.content === undefined) {
      msg.content = msg.reasoning_content || "";
    }
    return {
      result,
      responseMessage: msg,
      doneReason: text(choice.finish_reason ?? "stop"),
      durationMs,
    };
  }
  if (ctx.useLlama) {
    const cleanModel = ctx.model.startsWith("llama_cpp/")
      ? ctx.model.slice("llama_cpp/".length)
      : (ctx.model.startsWith("llamacpp/") ? ctx.model.slice("llamacpp/".length) : ctx.model);
    const result = await deps.model.request("llama_cpp", llamaPayload(messages, ctx.conversationId, ctx.generation, ctx.toolSchemas, cleanModel));
    const durationMs = Date.now() - started;
    const choice = isObject(result?.choices?.[0]) ? result.choices[0] : {};
    let msg = isObject(choice.message) ? { ...choice.message } : {};
    if (msg.content === null || msg.content === undefined || !String(msg.content).trim()) {
      if (msg.reasoning_content) {
        msg.content = msg.reasoning_content;
      }
    }
    return {
      result,
      responseMessage: msg,
      doneReason: text(choice.finish_reason ?? "stop"),
      durationMs,
    };
  }
  const result = await deps.model.request("ollama", ollamaPayload(ctx.model, messages, ctx.generation, ctx.toolSchemas, options));
  const durationMs = Date.now() - started;
  return {
    result,
    responseMessage: isObject(result?.message) ? result.message : {},
    doneReason: text(result?.done_reason ?? "desconocido").trim() || "desconocido",
    durationMs,
  };
}

/** Extrae métricas de telemetría universales (tokens/s, duración, tokens) para cualquier motor. */
export function extractTelemetry(result, durationMs, responseMessage) {
  const tel = {
    duration_ms: Math.max(0, durationMs || 0),
    tokens_out: 0,
    tokens_in: 0,
    tokens_per_second: 0,
    prompt_tokens_per_second: 0,
    ttft_ms: 0,
  };

  if (isObject(result?.timings)) {
    const t = result.timings;
    tel.tokens_out = toInt(t.predicted_n ?? result?.usage?.completion_tokens ?? 0, 0);
    tel.tokens_in = toInt(t.prompt_n ?? result?.usage?.prompt_tokens ?? 0, 0);
    tel.tokens_per_second = toFloat(t.predicted_per_second ?? 0, 0);
    tel.prompt_tokens_per_second = toFloat(t.prompt_per_second ?? 0, 0);
    tel.ttft_ms = toFloat(t.time_to_first_token_ms ?? 0, 0);
  } else if (result && (result.eval_count !== undefined || result.eval_duration !== undefined)) {
    tel.tokens_out = toInt(result.eval_count ?? 0, 0);
    tel.tokens_in = toInt(result.prompt_eval_count ?? 0, 0);
    const evalDurSec = (toInt(result.eval_duration ?? 0, 0) || 0) / 1e9;
    const promptDurSec = (toInt(result.prompt_eval_duration ?? 0, 0) || 0) / 1e9;
    const totalDurSec = (toInt(result.total_duration ?? 0, 0) || 0) / 1e9;
    if (evalDurSec > 0 && tel.tokens_out > 0) {
      tel.tokens_per_second = Math.round((tel.tokens_out / evalDurSec) * 10) / 10;
    }
    if (promptDurSec > 0 && tel.tokens_in > 0) {
      tel.prompt_tokens_per_second = Math.round((tel.tokens_in / promptDurSec) * 10) / 10;
    }
    if (totalDurSec > 0 && !tel.duration_ms) {
      tel.duration_ms = Math.round(totalDurSec * 1000);
    }
  } else if (isObject(result?.usage)) {
    tel.tokens_out = toInt(result.usage.completion_tokens ?? 0, 0);
    tel.tokens_in = toInt(result.usage.prompt_tokens ?? 0, 0);
  }

  if (!tel.tokens_out && responseMessage?.content) {
    tel.tokens_out = Math.max(1, Math.round(text(responseMessage.content).length / 4));
  }
  if (!tel.tokens_per_second && tel.tokens_out > 0 && tel.duration_ms > 0) {
    tel.tokens_per_second = Math.round((tel.tokens_out / (tel.duration_ms / 1000)) * 10) / 10;
  }
  return tel;
}

// ───────────────────────────── utilidades del bucle ─────────────────────────────

async function setActivity(deps, activityId, update) {
  if (!activityId) return;
  try {
    await deps.worker.activity(activityId, update);
  } catch {
    // El estado de la actividad es solo informativo: no puede tumbar el chat.
  }
}

function parseToolCall(toolCall) {
  const fn = isObject(toolCall) && isObject(toolCall.function) ? toolCall.function : {};
  const name = text(fn.name);
  let raw = fn.arguments ?? {};
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      raw = {};
    }
  }
  return { name, args: isObject(raw) ? raw : {} };
}

function bumpContext(generation) {
  generation.options.num_ctx = Math.max(toInt(generation.options.num_ctx, 0), TOOL_CONTEXT_NUM_CTX);
}

const snapshot = (messages, generation) => ({ _messages: messages, _generation: generation });

async function saveAssistant(deps, ctx, sourceCards, content, done, evidenceMessages = [], verifiedTrace = null, telemetry = null) {
  // La veracidad se garantiza por el bucle de herramientas: cada resultado real
  // vuelve al modelo antes de su respuesta. No se debe sustituir aquí el texto
  // del modelo por una coletilla genérica, pues bloquearía la tarea posterior.
  const assistant = { role: "assistant", content: stripFakeLedgerTags(content), created_at: deps.now(), model: ctx.model };
  if (telemetry) assistant.telemetry = telemetry;
  const trace = Array.isArray(verifiedTrace) ? verifiedTrace : currentTurnToolTrace(evidenceMessages);
  if (trace.length) assistant.verified_tool_trace = trace;
  const exchange = extractTurnToolExchange(evidenceMessages);
  if (exchange.length) assistant.tool_exchange = exchange;
  if (sourceCards.length) assistant.sources = sourceCards;
  const saved = await deps.worker.saveMessage(ctx.conversationId, assistant);
  return { message: isObject(saved) ? saved : assistant, done, telemetry };
}

/**
 * Herramienta sensible con permiso ya concedido (permanente): el Gateway la autoriza y el trabajador la ejecuta.
 * Devuelve { result, grant } o { result: null, grant: null } si hay que pedir aprobación.
 */
async function authorizedSensitiveAction(deps, toolName, args, conversationId) {
  const prepared = await deps.worker.prepare(toolName, args);
  if (!isObject(prepared) || !prepared.ok || !isObject(prepared.action)) return { result: null, grant: null };
  const action = prepared.action;
  const descriptor = deps.authority.descriptor(toolName, action);
  const authorization = deps.authority.authorize(toolName, action, conversationId);
  if (!authorization.ok || authorization.decision !== "granted") return { result: null, grant: null };
  const grant = isObject(authorization.grant) ? authorization.grant : { id: "", mode: "once" };
  const result = await deps.worker.action(action, conversationId, authorization.authorization);
  deps.authority.audit("permission_used", descriptor, {
    mode: text(grant.mode),
    status: result?.ok ? "ok" : "failed",
    permission_id: text(grant.id),
    session_id: conversationId,
    detail: text(result?.error),
  });
  return { result, grant };
}

/**
 * Modo "acceso total": si la operación admite permiso permanente, lo concede ahora mismo
 * (queda registrado y auditado) y ejecuta. Las operaciones de mayor riesgo (solo "once" en
 * allowedModes) nunca se auto-conceden aquí; siguen pidiendo aprobación igual que en "supervisado".
 * Devuelve { result, grant } o { result: null, grant: null } si no se puede auto-conceder.
 */
async function autoGrantSensitiveAction(deps, toolName, args, conversationId) {
  const prepared = await deps.worker.prepare(toolName, args);
  if (!isObject(prepared) || !prepared.ok || !isObject(prepared.action)) return { result: null, grant: null };
  const action = prepared.action;
  const grant = deps.authority.grant(toolName, action, conversationId);
  if (!grant) return { result: null, grant: null };
  const descriptor = deps.authority.descriptor(toolName, action);
  const result = await deps.worker.action(action, conversationId, { permission_id: grant.id, scope_key: descriptor.scope_key });
  deps.authority.audit("permission_used", descriptor, {
    mode: "permanent",
    status: result?.ok ? "ok" : "failed",
    permission_id: text(grant.id),
    session_id: conversationId,
    detail: text(result?.error),
  });
  return { result, grant };
}

/** Cierra un bucle largo permitiendo solo la acción de guardar ficha de investigación (con aprobación). */
async function finalizeResearchAfterLimit(deps, ctx, messages, sourceCards, toolNames) {
  const saveSchema = ctx.toolSchemas.find((schema) => isObject(schema) && isObject(schema.function) && schema.function.name === "save_research_note");
  if (!saveSchema) throw new Error("No está disponible la herramienta de fichas de investigación.");

  // No se reenvía la transcripción web completa: puede llenar la ventana y dejar el JSON de la llamada cortado.
  // Las fuentes verificadas bastan para este paso final, que solo pide aprobación.
  const systemMessage = { ...(messages.find((item) => isObject(item) && item.role === "system") ?? { role: "system", content: "Eres MyKOS y debes responder en español." }) };
  const originalRequest = text(messages.find((item) => isObject(item) && item.role === "user" && text(item.content).trim())?.content).trim()
    || "Preparar una ficha con las fuentes consultadas.";
  const sourceLines = [];
  for (const source of sourceCards.slice(0, 6)) {
    const title = text(source.title).trim();
    const url = text(source.url).trim();
    const snippet = text(source.snippet).trim();
    if (title && url) sourceLines.push(`- ${title} | ${url} | ${snippet.slice(0, 240)}`);
  }
  const compactPrompt = "Prepara una única llamada a save_research_note para solicitar la aprobación de una ficha. "
    + "No hagas más búsquedas. Sé conciso: resumen de 2-3 frases, hasta 5 puntos y 2-4 fuentes. "
    + "Usa exclusivamente estas fuentes verificadas y no inventes URLs.\n\n"
    + `Petición original: ${originalRequest.slice(0, 800)}\n\n`
    + `Fuentes verificadas:\n${sourceLines.join("\n")}`;
  const finalMessages = [
    systemMessage,
    { role: "user", content: compactPrompt },
    { role: "user", content: "Ahora ejecuta la llamada a save_research_note. No respondas con una explicación larga ni con texto libre." },
  ];
  const options = { ...(ctx.generation.options ?? {}) };
  options.num_ctx = Math.min(Math.max(toInt(options.num_ctx, 0), TOOL_CONTEXT_NUM_CTX), TOOL_CONTEXT_NUM_CTX);
  // Una llamada de aprobación concisa no debe gastar toda la ventana en prosa o razonamiento antes de sus argumentos.
  options.num_predict = Math.min(Math.max(toInt(options.num_predict, 0), 1536), 2048);
  await setActivity(deps, ctx.activityId, {
    status: "working",
    phase: "model",
    label: "Preparando la ficha…",
    detail: `${ctx.model} · cerrando la investigación con las fuentes ya consultadas.`,
  });

  // Solo se ofrece la herramienta de ficha; se usa el mismo motor que el resto del bucle.
  const finalCtx = { ...ctx, toolSchemas: [saveSchema], generation: { ...ctx.generation, options, think: false } };
  const { result, responseMessage, durationMs } = await callModel(deps, finalCtx, finalMessages, options);
  const toolCalls = Array.isArray(responseMessage.tool_calls) ? responseMessage.tool_calls : [];
  if (toolCalls.length) {
    const { name, args } = parseToolCall(toolCalls[0]);
    if (name === "save_research_note") {
      toolNames.push(name);
      if (!researchSourcesAreVerified(args, [...sourceCards, ...sourceCardsFromMessages(messages)])) {
        throw new Error("La ficha no se puede aprobar porque sus URLs no proceden de fuentes web verificadas.");
      }
      finalMessages.push({ role: "assistant", content: text(responseMessage.content), tool_calls: toolCalls });
      const pending = await createPendingApproval(deps, ctx, finalMessages, name, args);
      if (pending.ok) {
        return {
          pending_action: pending.approval,
          proposal: text(responseMessage.content).trim() || "He preparado la ficha con las fuentes recopiladas. Revisa y aprueba el guardado.",
          tools_used: [...new Set(toolNames)].sort(),
          sources: sourceCards,
          done: false,
          ...snapshot(messages, ctx.generation),
        };
      }
      throw new Error(text(pending.error) || "No se pudo preparar la ficha.");
    }
  }
  const responseText = text(responseMessage.content).trim();
  if (responseText) {
    const telemetry = extractTelemetry(result, durationMs, responseMessage);
    const saved = await saveAssistant(deps, ctx, sourceCards, responseText, result?.done !== false, messages, null, telemetry);
    return { ...saved, tools_used: [...new Set(toolNames)].sort(), sources: sourceCards, telemetry, ...snapshot(messages, ctx.generation) };
  }
  throw new Error("El modelo no pudo cerrar la investigación con las fuentes recopiladas.");
}

async function createPendingApproval(deps, ctx, messages, toolName, args) {
  const prepared = await deps.worker.prepare(toolName, args);
  if (!isObject(prepared) || !prepared.ok) return isObject(prepared) ? prepared : { ok: false, error: "No se pudo preparar la acción." };
  if (!isObject(prepared.action)) return { ok: false, error: "La acción preparada no es válida." };
  return deps.authority.createApproval({
    conversation_id: ctx.conversationId,
    model: ctx.model,
    messages,
    tool_name: toolName,
    action: prepared.action,
    supports_vision: ctx.supportsVision,
    generation: ctx.generation,
    conversation_permission_mode: ctx.permissionMode,
  });
}

// ───────────────────────────── el bucle ─────────────────────────────

/**
 * @param {{model:string, messages:object[], conversation_id:string, supports_vision?:boolean, generation?:object,
 *          activity_id?:string, permission_mode?:"solo_lectura"|"supervisado"|"acceso_total"}} input
 * @returns {Promise<object>} { message, tools_used, sources, done } o { pending_action, proposal, ... }, más
 *          `_messages` y `_generation` (el contexto tal como acaba, para el medidor de la interfaz).
 */
export async function runChatLoop(input, deps) {
  const model = text(input.model).trim();
  const messages = Array.isArray(input.messages) ? input.messages : [];
  const generation = isObject(input.generation) ? input.generation : {};
  if (!isObject(generation.options)) generation.options = {};
  const catalog = await deps.worker.catalog();
  const toolSchemas = Array.isArray(catalog?.schemas) ? catalog.schemas : [];
  const sensitiveTools = new Set(Array.isArray(catalog?.sensitive) ? catalog.sensitive : []);
  const isStrata = model.startsWith("strata/") || model === "strata";
  const isLlama = model.startsWith("llama_cpp/") || model.startsWith("llamacpp/") || model === LLAMA_MODEL_NAME;
  const isOpenAiFormat = isStrata || isLlama;
  const ctx = {
    model,
    useStrata: isStrata,
    useLlama: isLlama,
    isOpenAiFormat,
    conversationId: text(input.conversation_id).trim(),
    supportsVision: Boolean(input.supports_vision),
    activityId: text(input.activity_id).trim(),
    generation,
    toolSchemas,
  };
  // Modo de permisos elegido en la interfaz (desplegable, antes "Auto-Aprobar"): "solo_lectura" bloquea toda
  // acción sensible sin preguntar; "supervisado" (por defecto) pide aprobación cada vez; "acceso_total" concede
  // permiso permanente real la primera vez que ocurre cada acción elegible (queda auditado y revocable). Las
  // operaciones de mayor riesgo (solo "once" en allowedModes) siguen pidiendo aprobación en cualquier modo: ningún
  // modo de la interfaz puede saltarse esa frontera.
  ctx.permissionMode = ["solo_lectura", "acceso_total"].includes(text(input.permission_mode)) ? text(input.permission_mode) : "supervisado";

  const toolNames = [];
  const sourceCards = sourceCardsFromMessages(messages, true);
  let emptyResponseRetries = 0;
  let integrityRetries = 0;
  let webSearchCalls = 0;
  let webFetchCalls = 0;
  if (messages.some((item) => isObject(item) && item.role === "tool")) bumpContext(generation);

  for (let toolRound = 0; toolRound <= MAX_TOOL_ROUNDS; toolRound += 1) {
    await setActivity(deps, ctx.activityId, {
      status: "working",
      phase: "model",
      label: "Trabajando…",
      detail: ctx.useStrata
        ? `${model} · esperando respuesta del motor Strata con GPU CUDA.`
        : (ctx.useLlama
          ? `${model} · esperando respuesta del controlador del Gateway de MyKOS con llama.cpp.`
          : `${model} · esperando respuesta de Ollama local.`),
    });
    const { result, responseMessage, doneReason, durationMs } = await callModel(deps, ctx, messages, generation.options);
    const toolCalls = Array.isArray(responseMessage.tool_calls) ? responseMessage.tool_calls : [];

    if (!toolCalls.length) {
      const responseText = text(responseMessage.content).trim();
      if (!responseText) {
        if (doneReason === "length" && sourceCards.length) {
          return finalizeResearchAfterLimit(deps, ctx, messages, sourceCards, toolNames);
        }
        if (emptyResponseRetries < 1) {
          emptyResponseRetries += 1;
          bumpContext(generation);
          messages.push({
            role: "user",
            content: "La salida anterior llegó vacía. Continúa el trabajo y entrega ahora una respuesta final en español; si falta guardar la ficha, solicita su aprobación.",
          });
          continue;
        }
        // Qwen puede terminar con `done_reason=stop` y contenido vacío tras varias rondas de herramientas. Si ya hay
        // fuentes verificadas no se descarta la investigación: una última llamada con la única acción válida.
        if (sourceCards.length) return finalizeResearchAfterLimit(deps, ctx, messages, sourceCards, toolNames);
        throw new Error(`El modelo terminó sin devolver texto (motivo: ${doneReason}).`);
      }
      const { action: integrityAction, trace: integrityTrace } = integrityCheckAnswer(
        messages,
        responseText,
        integrityRetries,
        sensitiveTools,
      );
      if (integrityAction === "retry") {
        integrityRetries += 1;
        generation.options.num_predict = Math.max(toInt(generation.options.num_predict, 0), 4096);
        continue;
      }
      for (let i = messages.length - 1; i >= 0; i -= 1) {
        if (isObject(messages[i]) && messages[i].integrity_guard) messages.splice(i, 1);
      }
      const cleanedResponse = stripFakeLedgerTags(responseText);
      const hasPastClaim = [...cleanedResponse.replace(/\s+/g, " ").matchAll(ACTION_CLAIM_RE)].some((m) => !m.groups?.neg);
      const finalContent = integrityAction === "warn" && hasPastClaim
        ? `${cleanedResponse}${INTEGRITY_UNVERIFIED_NOTE}`
        : cleanedResponse;
      const telemetry = extractTelemetry(result, durationMs, responseMessage);
      const saved = await saveAssistant(deps, ctx, sourceCards, finalContent, result?.done !== false, messages, integrityTrace, telemetry);
      return { ...saved, tools_used: [...new Set(toolNames)].sort(), sources: sourceCards, telemetry, ...snapshot(messages, generation) };
    }

    if (toolRound >= MAX_TOOL_ROUNDS) return finalizeResearchAfterLimit(deps, ctx, messages, sourceCards, toolNames);

    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (isObject(messages[i]) && messages[i].integrity_guard) messages.splice(i, 1);
    }

    let calls = toolCalls;
    if (ctx.isOpenAiFormat) {
      calls = toolCalls.map((raw, index) => {
        const call = isObject(raw) ? { ...raw } : {};
        call.id = text(call.id) || `call_${toolRound}_${index}`;
        if (call.type === undefined) call.type = "function";
        return call;
      });
    }
    messages.push({ role: "assistant", content: text(responseMessage.content), tool_calls: calls });

    const sensitiveCalls = [];
    for (const toolCall of calls) {
      const { name: toolName, args } = parseToolCall(toolCall);
      const callId = text(toolCall?.id) || `call_${toolRound}_${messages.length}`;
      const withCallId = (message) => {
        if (ctx.isOpenAiFormat) message.tool_call_id = callId;
        return message;
      };

      if (sensitiveTools.has(toolName)) {
        if (ctx.permissionMode === "solo_lectura") {
          toolNames.push(toolName);
          messages.push(withCallId(toolMessageForResult({
            ok: false,
            action: toolName,
            error: `Modo "Solo lectura" activo: no se pueden ejecutar acciones que modifiquen el sistema («${toolName}»). Cambia el modo a Supervisado o Acceso total si quieres continuar.`,
          }, ctx.supportsVision, toolName)));
          continue;
        }
        const { result: autoResult, grant } = await authorizedSensitiveAction(deps, toolName, args, ctx.conversationId);
        if (grant !== null) {
          await setActivity(deps, ctx.activityId, {
            status: "working",
            phase: "tool",
            label: "Permiso concedido; ejecutando.",
            detail: `Se ha reutilizado un permiso ${grant.mode || "activo"} para «${toolName}».`,
          });
          toolNames.push(toolName);
          messages.push(withCallId(toolMessageForResult(autoResult ?? {}, ctx.supportsVision, toolName)));
          continue;
        }
        if (ctx.permissionMode === "acceso_total") {
          const { result: grantedResult, grant: newGrant } = await autoGrantSensitiveAction(deps, toolName, args, ctx.conversationId);
          if (newGrant !== null) {
            await setActivity(deps, ctx.activityId, {
              status: "working",
              phase: "tool",
              label: "Acceso total; permiso concedido y ejecutado.",
              detail: `Se ha concedido permiso permanente a «${toolName}» (modo Acceso total).`,
            });
            toolNames.push(toolName);
            messages.push(withCallId(toolMessageForResult(grantedResult ?? {}, ctx.supportsVision, toolName)));
            continue;
          }
          // La operación solo admite "once" (allowedModes): ni "Acceso total" se la salta. Sigue a aprobación.
        }
        await setActivity(deps, ctx.activityId, {
          status: "waiting",
          phase: "approval",
          label: "Esperando tu aprobación…",
          detail: `El modelo propone la herramienta «${toolName}». Revisa la acción en el panel.`,
        });
        sensitiveCalls.push([toolName, args]);
        continue;
      }

      await setActivity(deps, ctx.activityId, {
        status: "working",
        phase: "tool",
        label: "Consultando una herramienta…",
        detail: `El modelo ha solicitado «${toolName}»; MyKOS la está consultando.`,
      });
      let toolResult;
      if (toolName === "web_search") {
        if (webSearchCalls >= MAX_WEB_SEARCH_CALLS) {
          toolResult = { ok: false, action: "web_search", error: "Ya se han hecho suficientes búsquedas para esta investigación. Lee las fuentes encontradas y prepara la ficha." };
        } else {
          webSearchCalls += 1;
          const limited = { ...args };
          limited.max_results = Math.min(toInt(limited.max_results ?? 5, 5) || 5, 5);
          toolResult = await deps.worker.tool(toolName, limited);
        }
      } else if (toolName === "web_fetch") {
        if (webFetchCalls >= MAX_WEB_FETCH_CALLS) {
          toolResult = { ok: false, action: "web_fetch", error: "Ya se han leído suficientes fuentes para esta investigación. Prepara la ficha con las fuentes disponibles." };
        } else {
          webFetchCalls += 1;
          toolResult = await deps.worker.tool(toolName, args);
        }
      } else {
        toolResult = await deps.worker.tool(toolName, args);
      }
      mergeSourceCards(sourceCards, toolResult);
      if (toolName) toolNames.push(toolName);
      messages.push(withCallId(toolMessageForResult(toolResult, ctx.supportsVision, toolName)));
      if (toolName === "web_search" || toolName === "web_fetch") bumpContext(generation);
    }

    if (sensitiveCalls.length > 1) {
      const errorResult = {
        ok: false,
        requires_approval: true,
        error: "Solo se permite una acción sensible por petición. Solicita una sola escritura o un solo comando y espera la aprobación.",
      };
      for (const [toolName] of sensitiveCalls) {
        toolNames.push(toolName);
        messages.push(toolMessageForResult(errorResult, ctx.supportsVision, toolName));
      }
      continue;
    }

    if (sensitiveCalls.length === 1) {
      const [toolName, args] = sensitiveCalls[0];
      toolNames.push(toolName);
      if (toolName === "save_research_note" && !researchSourcesAreVerified(args, [...sourceCards, ...sourceCardsFromMessages(messages)])) {
        messages.push(toolMessageForResult({
          ok: false,
          requires_approval: true,
          error: "No se puede preparar la ficha todavía: primero debes usar web_search o web_fetch y citar únicamente las URLs que esas herramientas hayan devuelto.",
        }, ctx.supportsVision, toolName));
        continue;
      }
      const pending = await createPendingApproval(deps, ctx, messages, toolName, args);
      if (pending.ok) {
        return {
          pending_action: pending.approval,
          proposal: text(responseMessage.content).trim(),
          tools_used: [...new Set(toolNames)].sort(),
          sources: sourceCards,
          done: false,
          ...snapshot(messages, generation),
        };
      }
      messages.push(toolMessageForResult(pending, ctx.supportsVision, toolName));
    }
  }
  throw new Error("El modelo no terminó dentro del límite de rondas.");
}
