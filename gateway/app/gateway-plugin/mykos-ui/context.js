// Construcción y compactación del contexto de MyKOS propiedad del Gateway.

const CHARS_PER_TOKEN = 4;
const SAFETY_TOKENS = 512;
const COMPACT_RATIO = 0.82;
const WARNING_RATIO = 0.70;
const CRITICAL_RATIO = 0.92;
const IMAGE_RESERVE_TOKENS = 8192;
const MAX_SUMMARY_CHARS = 2400;

const text = (value) => String(value ?? "");

function estimate(value) {
  if (value === null || value === undefined) return 0;
  if (Array.isArray(value)) return value.reduce((sum, item) => sum + estimate(item), 0);
  const raw = text(value);
  return raw ? Math.max(1, Math.ceil(raw.length / CHARS_PER_TOKEN)) : 0;
}

function messageTokens(message) {
  let total = 4 + estimate(message?.content);
  if (message?.tool_calls) total += estimate(message.tool_calls);
  if (Array.isArray(message?.images)) total += IMAGE_RESERVE_TOKENS * message.images.length;
  return total;
}

function messagesTokens(messages) {
  return messages.reduce((sum, message) => sum + messageTokens(message), 0);
}

function info(messages, generation, extra = {}) {
  const options = generation?.options && typeof generation.options === "object" ? generation.options : {};
  const maxTokens = Math.max(1, Number(options.num_ctx || 8192));
  const outputTokens = Math.max(0, Number(options.num_predict || 0));
  const estimatedTokens = messagesTokens(messages);
  const inputBudget = Math.max(512, maxTokens - outputTokens - SAFETY_TOKENS);
  const percent = Math.round(Math.min(100, (estimatedTokens / maxTokens) * 100) * 10) / 10;
  const level = percent >= CRITICAL_RATIO * 100 ? "critical" : percent >= WARNING_RATIO * 100 ? "warning" : "ok";
  return {
    estimated_tokens: estimatedTokens,
    max_tokens: maxTokens,
    input_budget_tokens: inputBudget,
    output_tokens: outputTokens,
    available_tokens: Math.max(0, inputBudget - estimatedTokens),
    percent,
    level,
    source_message_count: extra.source_message_count ?? messages.length,
    sent_message_count: messages.length,
    compacted: Boolean(extra.compacted),
    would_compact: estimatedTokens > inputBudget * COMPACT_RATIO,
    omitted_messages: extra.omitted_messages || 0,
    original_estimated_tokens: extra.original_estimated_tokens || estimatedTokens,
  };
}

function excerpt(message) {
  const labels = { user: "Usuario", assistant: "MyKOS", system: "Sistema" };
  const role = labels[text(message?.role)] || text(message?.role || "mensaje");
  let content = text(message?.content).replace(/\s+/g, " ").trim();
  if (content.length > 280) content = `${content.slice(0, 277)}…`;
  return `- ${role}: ${content || "(sin texto)"}`;
}

function summary(messages) {
  if (!messages.length) return "";
  return [
    "Resumen local del contexto anterior. Se han omitido mensajes antiguos para proteger la ventana del modelo:",
    ...messages.map(excerpt),
  ].join("\n").slice(0, MAX_SUMMARY_CHARS);
}

function truncate(message, maxTokens) {
  const shortened = { ...message };
  const content = text(message?.content);
  const maxChars = Math.max(240, Math.max(32, maxTokens - 12) * CHARS_PER_TOKEN);
  if (content.length > maxChars) shortened.content = `${content.slice(0, maxChars)}\n[… mensaje recortado por seguridad de contexto …]`;
  return shortened;
}

export function prepareContext(systemPrompt, context, generation) {
  const safeContext = Array.isArray(context) ? context.filter((item) => item && typeof item === "object") : [];
  const base = [{ role: "system", content: text(systemPrompt) }, ...safeContext];
  const before = info(base, generation, { source_message_count: safeContext.length });
  before.original_estimated_tokens = before.estimated_tokens;
  if (!before.would_compact || !safeContext.length) {
    before.would_compact = false;
    return { messages: base, context: before };
  }

  const inputBudget = Number(before.input_budget_tokens);
  const summaryReserve = Math.min(650, Math.max(280, Math.floor(inputBudget / 5)));
  const recentBudget = Math.max(256, inputBudget - summaryReserve);
  const recent = [];
  const omitted = [];
  let remaining = recentBudget;
  for (let index = safeContext.length - 1; index >= 0; index -= 1) {
    const message = safeContext[index];
    const cost = messageTokens(message);
    if (!recent.length && cost > remaining) {
      recent.unshift(truncate(message, remaining));
      omitted.unshift(...safeContext.slice(0, index));
      break;
    }
    if (cost <= remaining) {
      recent.unshift(message);
      remaining -= cost;
      continue;
    }
    omitted.unshift(...safeContext.slice(0, index + 1));
    break;
  }
  while (recent.length > 1 && recent[0]?.role === "tool") {
    omitted.push(recent.shift());
  }

  const makePrepared = () => {
    const digest = summary(omitted);
    return [{ role: "system", content: text(systemPrompt) }, ...(digest ? [{ role: "system", content: digest }] : []), ...recent];
  };
  let prepared = makePrepared();
  while (messagesTokens(prepared) > inputBudget && recent.length > 1) {
    omitted.unshift(recent.shift());
    prepared = makePrepared();
  }
  if (messagesTokens(prepared) > inputBudget && recent.length) {
    const available = Math.max(128, inputBudget - messagesTokens(prepared.slice(0, -1)));
    recent[recent.length - 1] = truncate(recent[recent.length - 1], available);
    prepared = makePrepared();
  }
  return {
    messages: prepared,
    context: info(prepared, generation, {
      source_message_count: safeContext.length,
      compacted: Boolean(omitted.length),
      omitted_messages: omitted.length,
      original_estimated_tokens: before.original_estimated_tokens,
    }),
  };
}

