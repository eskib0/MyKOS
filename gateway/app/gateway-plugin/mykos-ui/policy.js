// Decisión del Gateway para los servicios auxiliares de MyKOS (fase 3, cuarto corte).
//
// El tercer corte consiguió que TODA ruta pública esté enumerada, clasificada y auditada, y que solo el Gateway pueda
// hablar con el trabajador Python. Pero en los dominios auxiliares (benchmark, modelos de Ollama, credenciales OAuth y
// de proveedores, subidas y latidos de nodos) el Gateway se limitaba a anotar la petición y reenviarla: la decisión
// seguía siendo de Python.
//
// Aquí el Gateway DECIDE antes de reenviar:
//   1. Forma exacta del cuerpo y de la consulta (lista blanca de campos; un campo desconocido se rechaza).
//   2. Límites de carga: cuántas de estas acciones pueden estar en marcha a la vez y cuántas por minuto.
//   3. Cabeceras obligatorias (por ejemplo, el token de nodo en un latido).
//   4. Firma de la decisión: el trabajador solo ejecuta estas rutas si llega con una decisión firmada por el Gateway,
//      ligada al método, a la ruta y (cuando el Gateway ha leído el cuerpo) al cuerpo exacto. Sin ella, 403.
//
// Nada de esto sustituye a la cola de aprobaciones: pull/delete de modelos siguen creando una aprobación en el
// Gateway; lo que se añade es que la petición ni siquiera llega a Python si no cumple la política.
//
// Esta tabla y `GATEWAY_DECISION_ROUTES` de server.py deben coincidir: probe-routes.cjs lo comprueba.

import { createHash, createHmac } from "node:crypto";

const MODEL_RE = /^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,119}$/;
const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
const NODE_TOKEN_RE = /^[A-Za-z0-9._~-]{20,300}$/;
const OPAQUE_RE = /^[\x21-\x7e]{16,400}$/; // clave de proveedor: imprimible, sin espacios ni saltos
const CODE_RE = /^[\x21-\x7e]{1,512}$/;
const MULTIPART_RE = /^multipart\/form-data\s*;\s*boundary=/i;

const MAX_UPLOAD_BYTES = 32 * 1024 * 1024; // igual que MAX_UPLOAD_REQUEST_BYTES en server.py
const MAX_QUERY_KEYS = 12;
const MAX_QUERY_VALUE_CHARS = 512;
export const DECISION_HEADER = "x-mykos-gateway-decision";
export const DECISION_TTL_SECONDS = 120;

const oauthProvider = (segment, canonical) => ({ type: "string", enum: [segment, canonical], max: 64 });

/**
 * Cada entrada: método + ruta exacta (las mismas de routes.js), cómo se lee el cuerpo y qué se admite.
 *   body: "json"   el Gateway lee y valida el cuerpo, y lo reenvía tal cual (queda ligado a la firma).
 *   body: "stream" el Gateway NO lee el cuerpo (subidas grandes): decide por cabeceras.
 *   body: "none"   no hay cuerpo (GET).
 *   limits: { concurrent, perMinute } por grupo; group comparte contador entre rutas.
 */
export const POLICY_TABLE = [
  {
    method: "POST", path: "/api/benchmark", group: "benchmark",
    body: "json", maxBytes: 4 * 1024,
    // Una medición ocupa el modelo entero durante minutos: de una en una.
    limits: { concurrent: 1, perMinute: 12 },
    fields: {
      model: { type: "string", required: true, pattern: MODEL_RE, max: 120 },
      profiles: { type: "array", maxItems: 6, items: { type: "string", enum: ["fast", "balanced", "deep", "full", "coding", "quality"] } },
    },
  },
  {
    method: "POST", path: "/api/ollama/pull-request", group: "ollama-models",
    body: "json", maxBytes: 2 * 1024,
    limits: { concurrent: 3, perMinute: 12 },
    fields: {
      model: { type: "string", required: true, pattern: MODEL_RE, max: 120 },
      conversation_id: { type: "string", pattern: ID_RE, max: 64 },
    },
  },
  {
    method: "POST", path: "/api/ollama/delete-request", group: "ollama-models",
    body: "json", maxBytes: 2 * 1024,
    limits: { concurrent: 3, perMinute: 12 },
    fields: {
      model: { type: "string", required: true, pattern: MODEL_RE, max: 120 },
      conversation_id: { type: "string", pattern: ID_RE, max: 64 },
    },
  },
  {
    method: "POST", path: "/api/automations/create-request", group: "automations-panel",
    body: "json", maxBytes: 8 * 1024,
    limits: { concurrent: 3, perMinute: 12 },
    fields: {
      title: { type: "string", required: true, max: 180 },
      message: { type: "string", max: 4000 },
      run_at: { type: "string", required: true, max: 64 },
      repeat_minutes: { type: "number", min: 0, max: 10080 },
      conversation_id: { type: "string", pattern: ID_RE, max: 64 },
    },
  },
  {
    method: "POST", path: "/api/automations/delete-request", group: "automations-panel",
    body: "json", maxBytes: 2 * 1024,
    limits: { concurrent: 3, perMinute: 12 },
    fields: {
      id: { type: "string", required: true, pattern: ID_RE, max: 64 },
      conversation_id: { type: "string", pattern: ID_RE, max: 64 },
    },
  },

  // Credenciales. Un bucle de arranques/cierres de sesión toca ficheros de credenciales y procesos externos:
  // se limita el ritmo y se exige que el proveedor del cuerpo sea el de la propia ruta.
  {
    method: "POST", path: "/api/oauth/openai/start", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["openai", "openai_codex_oauth", "openai_api"], max: 64 }, api_key: { type: "string", required: false, pattern: OPAQUE_RE, max: 400, secret: true } },
  },
  {
    method: "POST", path: "/api/oauth/openai/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["openai", "openai_codex_oauth", "openai_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/oauth/openai/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["openai", "openai_codex_oauth", "openai_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/oauth/claude/start", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: oauthProvider("claude", "anthropic_oauth") },
  },
  {
    method: "POST", path: "/api/oauth/claude/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["claude", "anthropic_oauth", "claude_oauth", "anthropic_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/oauth/claude/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["claude", "anthropic_oauth", "claude_oauth"], max: 64 } },
  },
  {
    method: "POST", path: "/api/oauth/openrouter/start", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["openrouter", "openrouter_oauth", "openrouter_api"], max: 64 }, api_key: { type: "string", required: false, pattern: OPAQUE_RE, max: 400, secret: true } },
  },
  {
    method: "POST", path: "/api/oauth/openrouter/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["openrouter", "openrouter_oauth", "openrouter_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/oauth/openrouter/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["openrouter", "openrouter_oauth", "openrouter_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/oauth/meta/start", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["meta", "meta_ai", "meta_ai_oauth", "meta_ai_api"], max: 64 }, api_key: { type: "string", required: false, pattern: OPAQUE_RE, max: 400, secret: true } },
  },
  {
    method: "POST", path: "/api/oauth/meta/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["meta", "meta_ai", "meta_ai_oauth", "meta_ai_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/oauth/meta/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["meta", "meta_ai", "meta_ai_oauth", "meta_ai_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/oauth/grok/start", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: oauthProvider("grok", "grok_oauth") },
  },
  {
    method: "POST", path: "/api/oauth/grok/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: oauthProvider("grok", "grok_oauth") },
  },
  {
    method: "POST", path: "/api/oauth/grok/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: oauthProvider("grok", "grok_oauth") },
  },
  {
    method: "GET", path: "/api/oauth/openrouter/callback", group: "credentials",
    body: "none", limits: { concurrent: 2, perMinute: 12 },
    // Lo abre el navegador al volver de OpenRouter: se admiten parámetros desconocidos, pero acotados.
    query: {
      allowUnknown: true,
      fields: {
        code: { pattern: CODE_RE },
        state: { pattern: CODE_RE },
        error: { pattern: CODE_RE },
        error_description: { maxChars: MAX_QUERY_VALUE_CHARS },
      },
    },
  },
  {
    method: "POST", path: "/api/providers/nvidia/connect", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: {
      provider: { type: "string", enum: ["nvidia", "nvidia_api"], max: 64 },
      api_key: { type: "string", required: true, pattern: OPAQUE_RE, max: 400, secret: true },
    },
  },
  {
    method: "POST", path: "/api/providers/nvidia/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["nvidia", "nvidia_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/nvidia/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["nvidia", "nvidia_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/kimi/connect", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["kimi", "kimi_api"], max: 64 }, api_key: { type: "string", required: true, pattern: OPAQUE_RE, max: 400, secret: true } },
  },
  {
    method: "POST", path: "/api/providers/kimi/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["kimi", "kimi_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/kimi/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["kimi", "kimi_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/gemini/connect", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["gemini", "gemini_api"], max: 64 }, api_key: { type: "string", required: true, pattern: OPAQUE_RE, max: 400, secret: true } },
  },
  {
    method: "POST", path: "/api/providers/gemini/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["gemini", "gemini_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/gemini/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["gemini", "gemini_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/mistral/connect", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: {
      provider: { type: "string", enum: ["mistral", "mistral_api"], max: 64 },
      api_key: { type: "string", pattern: OPAQUE_RE, max: 400, secret: true },
      link_vibe: { type: "boolean" },
    },
  },
  {
    method: "POST", path: "/api/providers/mistral/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["mistral", "mistral_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/mistral/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["mistral", "mistral_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/anthropic/connect", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: {
      provider: { type: "string", enum: ["anthropic", "anthropic_api"], max: 64 },
      api_key: { type: "string", required: true, pattern: OPAQUE_RE, max: 400, secret: true },
    },
  },
  {
    method: "POST", path: "/api/providers/anthropic/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["anthropic", "anthropic_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/anthropic/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["anthropic", "anthropic_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/antigravity/connect", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["antigravity", "antigravity_cli"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/antigravity/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["antigravity", "antigravity_cli"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/antigravity/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["antigravity", "antigravity_cli"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/qwen/connect", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["qwen", "qwen_cli"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/qwen/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["qwen", "qwen_cli"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/qwen/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["qwen", "qwen_cli"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/grok/connect", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: {
      provider: { type: "string", enum: ["grok", "grok_api"], max: 64 },
      api_key: { type: "string", required: true, pattern: OPAQUE_RE, max: 400, secret: true },
    },
  },
  {
    method: "POST", path: "/api/providers/grok/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["grok", "grok_api"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/grok/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["grok", "grok_api", "grok_oauth"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/openai/connect", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: {
      provider: { type: "string", enum: ["openai", "openai_api"], max: 64 },
      api_key: { type: "string", required: true, pattern: OPAQUE_RE, max: 400, secret: true },
    },
  },
  {
    method: "POST", path: "/api/providers/openai/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["openai", "openai_api", "openai_codex_oauth"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/openai/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["openai", "openai_api", "openai_codex_oauth"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/openrouter/connect", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: {
      provider: { type: "string", enum: ["openrouter", "openrouter_api", "openrouter_oauth"], max: 64 },
      api_key: { type: "string", required: true, pattern: OPAQUE_RE, max: 400, secret: true },
    },
  },
  {
    method: "POST", path: "/api/providers/openrouter/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["openrouter", "openrouter_api", "openrouter_oauth"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/openrouter/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["openrouter", "openrouter_api", "openrouter_oauth"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/meta/connect", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: {
      provider: { type: "string", enum: ["meta", "meta_ai", "meta_ai_api", "meta_ai_oauth"], max: 64 },
      api_key: { type: "string", required: true, pattern: OPAQUE_RE, max: 400, secret: true },
    },
  },
  {
    method: "POST", path: "/api/providers/meta/logout", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 6 },
    fields: { provider: { type: "string", enum: ["meta", "meta_ai", "meta_ai_api", "meta_ai_oauth"], max: 64 } },
  },
  {
    method: "POST", path: "/api/providers/meta/refresh", group: "credentials",
    body: "json", maxBytes: 2 * 1024, limits: { concurrent: 1, perMinute: 12 },
    fields: { provider: { type: "string", enum: ["meta", "meta_ai", "meta_ai_api", "meta_ai_oauth"], max: 64 } },
  },

  // Subidas: el cuerpo puede llegar a 32 MB, así que el Gateway no lo lee; decide por cabeceras.
  {
    method: "POST", path: "/api/uploads", group: "uploads",
    body: "stream", limits: { concurrent: 4, perMinute: 60 },
    requireContentType: MULTIPART_RE,
    maxContentLength: MAX_UPLOAD_BYTES,
  },

  // Latido de nodo: sin token de nodo no se molesta al trabajador.
  {
    method: "POST", path: "/api/nodes/heartbeat", group: "nodes",
    body: "json", maxBytes: 8 * 1024, limits: { concurrent: 4, perMinute: 120 },
    requireHeaders: { "x-mykos-node-token": NODE_TOKEN_RE },
    fields: {
      node_id: { type: "string", required: true, pattern: ID_RE, max: 64 },
      capabilities: { type: "array", maxItems: 32, items: { type: "string", max: 120 } },
      status: { type: "string", max: 32 },
    },
  },
];

const BY_KEY = new Map(POLICY_TABLE.map((entry) => [`${entry.method} ${entry.path}`, entry]));

/** Política de una petición pública ya normalizada, o null si esta ruta no la tiene. */
export function policyFor(method, pathname) {
  return BY_KEY.get(`${String(method || "").toUpperCase()} ${pathname}`) || null;
}

/** Claves «MÉTODO ruta» de la tabla, para comprobar coherencia con server.py. */
export function policyKeys() {
  return POLICY_TABLE.map((entry) => `${entry.method} ${entry.path}`).sort();
}

const deny = (status, reason, message) => ({ ok: false, status, reason, message });

function checkValue(name, value, spec) {
  const type = spec.type || "string";
  if (type === "string") {
    if (typeof value !== "string") return deny(400, "bad_type", `«${name}» debe ser texto.`);
    if (spec.max && value.length > spec.max) return deny(400, "too_long", `«${name}» supera ${spec.max} caracteres.`);
    if (spec.enum && !spec.enum.includes(value)) return deny(400, "bad_value", `«${name}» no es un valor admitido para esta ruta.`);
    if (spec.pattern && !spec.pattern.test(value)) return deny(400, "bad_format", `«${name}» tiene caracteres o una forma que no se admiten.`);
    return null;
  }
  if (type === "array") {
    if (!Array.isArray(value)) return deny(400, "bad_type", `«${name}» debe ser una lista.`);
    if (spec.maxItems && value.length > spec.maxItems) return deny(400, "too_many", `«${name}» admite como máximo ${spec.maxItems} elementos.`);
    for (const [index, item] of value.entries()) {
      const failure = checkValue(`${name}[${index}]`, item, spec.items || { type: "string" });
      if (failure) return failure;
    }
    return null;
  }
  if (type === "boolean") {
    if (typeof value !== "boolean") return deny(400, "bad_type", `«${name}» debe ser verdadero o falso.`);
    return null;
  }
  if (type === "number") {
    if (typeof value !== "number" || !Number.isFinite(value)) return deny(400, "bad_type", `«${name}» debe ser un número.`);
    if (spec.min !== undefined && value < spec.min) return deny(400, "bad_value", `«${name}» es menor que ${spec.min}.`);
    if (spec.max !== undefined && value > spec.max) return deny(400, "bad_value", `«${name}» es mayor que ${spec.max}.`);
    return null;
  }
  return deny(400, "bad_type", `«${name}» tiene un tipo que no se admite.`);
}

/** Valida el cuerpo JSON contra la lista blanca de campos. Devuelve null si está bien. */
export function checkJsonBody(entry, body) {
  const limit = entry.maxBytes || 2 * 1024;
  if (body.length > limit) return deny(413, "body_too_large", `El cuerpo de esta ruta no puede pasar de ${limit} bytes.`);
  if (body.length === 0) return deny(400, "empty_body", "Esta ruta necesita un cuerpo JSON.");
  let parsed;
  try {
    parsed = JSON.parse(body.toString("utf8"));
  } catch {
    return deny(400, "bad_json", "El cuerpo no contiene JSON válido.");
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return deny(400, "bad_json", "El cuerpo debe ser un objeto JSON.");
  }
  const fields = entry.fields || {};
  for (const key of Object.keys(parsed)) {
    if (!Object.hasOwn(fields, key)) return deny(400, "unknown_field", `El campo «${key}» no está permitido en esta ruta.`);
  }
  for (const [name, spec] of Object.entries(fields)) {
    const present = Object.hasOwn(parsed, name) && parsed[name] !== undefined && parsed[name] !== null;
    if (!present) {
      if (spec.required) return deny(400, "missing_field", `Falta «${name}».`);
      continue;
    }
    const failure = checkValue(name, parsed[name], spec);
    if (failure) return failure;
  }
  return null;
}

/** Valida la consulta (?a=b) de una ruta con política. Devuelve null si está bien. */
export function checkQuery(entry, searchParams) {
  const rules = entry.query;
  if (!rules) return null;
  const keys = [...searchParams.keys()];
  if (keys.length > MAX_QUERY_KEYS) return deny(400, "too_many_params", "La consulta lleva demasiados parámetros.");
  for (const key of keys) {
    if (!rules.allowUnknown && !Object.hasOwn(rules.fields || {}, key)) {
      return deny(400, "unknown_param", `El parámetro «${key}» no está permitido en esta ruta.`);
    }
    for (const value of searchParams.getAll(key)) {
      if (value.length > MAX_QUERY_VALUE_CHARS) return deny(400, "param_too_long", `El parámetro «${key}» es demasiado largo.`);
      if (/[\u0000-\u001f\u007f]/.test(value)) return deny(400, "bad_param", `El parámetro «${key}» lleva caracteres de control.`);
      const spec = (rules.fields || {})[key];
      if (!spec) continue;
      if (spec.maxChars && value.length > spec.maxChars) return deny(400, "param_too_long", `El parámetro «${key}» es demasiado largo.`);
      if (spec.pattern && value && !spec.pattern.test(value)) return deny(400, "bad_param", `El parámetro «${key}» tiene una forma que no se admite.`);
    }
  }
  return null;
}

/** Comprueba cabeceras obligatorias y, en rutas de flujo, el tipo y el tamaño declarados. */
export function checkHeaders(entry, headers) {
  for (const [name, pattern] of Object.entries(entry.requireHeaders || {})) {
    const value = String(headers[name] ?? "").trim();
    if (!value) return deny(403, "missing_header", `Esta ruta necesita la cabecera ${name}.`);
    if (pattern && !pattern.test(value)) return deny(403, "bad_header", `La cabecera ${name} no tiene una forma válida.`);
  }
  if (entry.requireContentType) {
    const contentType = String(headers["content-type"] ?? "");
    if (!entry.requireContentType.test(contentType)) {
      return deny(415, "bad_content_type", "Esta ruta solo acepta un formulario multipart con archivos.");
    }
  }
  if (entry.maxContentLength !== undefined) {
    const raw = headers["content-length"];
    if (raw === undefined) return deny(411, "missing_length", "Esta ruta necesita Content-Length.");
    const length = Number(raw);
    if (!Number.isInteger(length) || length <= 0) return deny(400, "bad_length", "El tamaño declarado no es válido.");
    if (length > entry.maxContentLength) {
      return deny(413, "too_large", `La carga supera el límite de ${Math.round(entry.maxContentLength / (1024 * 1024))} MB.`);
    }
  }
  return null;
}

/** Contadores de carga por grupo: cuántas a la vez y cuántas por minuto. */
export class PolicyLimiter {
  constructor(now = () => Date.now()) {
    this.now = now;
    this.running = new Map();
    this.recent = new Map();
  }

  acquire(entry) {
    const group = entry.group || entry.path;
    const limits = entry.limits || {};
    const running = this.running.get(group) || 0;
    if (limits.concurrent && running >= limits.concurrent) {
      return {
        ...deny(429, "busy", limits.concurrent === 1
          ? "Ya hay una acción de este tipo en marcha; espera a que termine."
          : `Hay demasiadas acciones de este tipo en marcha (máximo ${limits.concurrent}).`),
        retryAfter: 5,
      };
    }
    const now = this.now();
    const window = (this.recent.get(group) || []).filter((stamp) => now - stamp < 60_000);
    if (limits.perMinute && window.length >= limits.perMinute) {
      this.recent.set(group, window);
      return { ...deny(429, "rate_limited", `Demasiadas acciones de este tipo en un minuto (máximo ${limits.perMinute}).`), retryAfter: 30 };
    }
    window.push(now);
    this.recent.set(group, window);
    this.running.set(group, running + 1);
    let released = false;
    return {
      ok: true,
      group,
      release: () => {
        if (released) return;
        released = true;
        this.running.set(group, Math.max(0, (this.running.get(group) || 1) - 1));
      },
    };
  }

  snapshot() {
    const now = this.now();
    return Object.fromEntries([...this.running.entries()].map(([group, running]) => [group, {
      running,
      lastMinute: (this.recent.get(group) || []).filter((stamp) => now - stamp < 60_000).length,
    }]));
  }
}

export function bodyHashOf(body) {
  if (body === null || body === undefined) return "-";
  return createHash("sha256").update(Buffer.isBuffer(body) ? body : Buffer.from(String(body), "utf8")).digest("hex");
}

/**
 * Decisión firmada que viaja al trabajador: `v1.<caduca>.<hash del cuerpo>.<firma>`.
 * La firma liga método, ruta, cuerpo (si el Gateway lo ha leído) y caducidad con el token interno del Gateway.
 */
export function decisionHeaderValue(token, method, pathname, body, ttlSeconds = DECISION_TTL_SECONDS) {
  const expires = Math.floor(Date.now() / 1000) + ttlSeconds;
  const hash = bodyHashOf(body);
  const payload = `gateway-decision|${String(method).toUpperCase()} ${pathname}|${hash}|${expires}`;
  const signature = createHmac("sha256", String(token || "")).update(payload, "utf8").digest("hex");
  return `v1.${expires}.${hash}.${signature}`;
}

/**
 * Decide una petición pública con política. No reserva nada si deniega.
 * Devuelve { ok: true, release, bodyHash } o { ok: false, status, reason, message, retryAfter }.
 */
export function decide(entry, { method, pathname, headers, body, searchParams }, limiter) {
  const headerFailure = checkHeaders(entry, headers || {});
  if (headerFailure) return headerFailure;
  const queryFailure = checkQuery(entry, searchParams || new URLSearchParams());
  if (queryFailure) return queryFailure;
  if (entry.body === "json") {
    const bodyFailure = checkJsonBody(entry, Buffer.isBuffer(body) ? body : Buffer.from(body || "", "utf8"));
    if (bodyFailure) return bodyFailure;
  }
  const lease = limiter.acquire(entry);
  if (!lease.ok) return lease;
  return { ok: true, release: lease.release, group: lease.group, bodyHash: bodyHashOf(entry.body === "json" ? body : null) };
}
