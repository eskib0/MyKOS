// Tabla de rutas públicas de MyKOS (fase 3, tercer corte).
//
// El Gateway ya no reenvía «lo que llegue» al trabajador Python: cada ruta pública /api/* está aquí, con su método, su
// dominio, su acción y su nivel de riesgo. Lo que no está en la tabla se rechaza en el Gateway (404 si la ruta no
// existe, 405 si existe con otro método) y queda anotado en el diario de control. Además, cada petición que sí se
// reenvía se anota con esos datos, de modo que el diario dice QUÉ se hizo y no solo «POST /api/...».
//
// Riesgo:
//   read       solo lee.
//   write      cambia datos de MyKOS (conversaciones, subidas, permisos, latidos de nodos).
//   sensitive  credenciales, ejecución de acciones aprobadas, modelo y herramientas (chat), descargas de modelos,
//              cargas de trabajo pesadas o medios.
// Propietario:
//   gateway    lo resuelve el propio Gateway (con el almacén) o lo reenvía por una frontera interna propia.
//   worker     lo atiende el trabajador Python, ya detrás del Gateway y con su token.
//
// Esta tabla es la única fuente: probe-routes.cjs comprueba que las rutas del trabajador coinciden con server.py y que
// las rutas propias del Gateway (permisos, medios y llamadas) quedan separadas y no se reenvían por accidente.

export const ROUTE_TABLE = [
  // Sistema y estado
  { method: "GET", pattern: "/api/health", domain: "system", action: "health", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/status", domain: "models", action: "status", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/models", domain: "models", action: "list", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/tools", domain: "tools", action: "catalog", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/management", domain: "management", action: "status", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/activity", domain: "chat", action: "activity", risk: "read", owner: "gateway" },

  // Conversaciones, contexto y chat
  { method: "GET", pattern: "/api/conversations", domain: "conversations", action: "list", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/conversation", domain: "conversations", action: "open", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/conversations/export", domain: "conversations", action: "export", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/conversations/compact", domain: "conversations", action: "compact-info", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/context", domain: "conversations", action: "context", risk: "read", owner: "gateway" },
  { method: "POST", pattern: "/api/sessions/:sessionid/realtime", domain: "realtime", action: "create", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/sessions/:sessionid/gemini-live", domain: "gemini_live", action: "create", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/calls/:callid/gemini-tools", domain: "gemini_live", action: "tool", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/sessions/:sessionid/calls", domain: "calls", action: "create", risk: "write", owner: "gateway" },
  { method: "GET", pattern: "/api/calls/:callid", domain: "calls", action: "status", risk: "read", owner: "gateway" },
  { method: "DELETE", pattern: "/api/calls/:callid", domain: "calls", action: "end", risk: "write", owner: "gateway" },
  { method: "POST", pattern: "/api/calls/:callid/turn", domain: "calls", action: "turn", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/calls/:callid/interrupt", domain: "calls", action: "interrupt", risk: "write", owner: "gateway" },
  { method: "POST", pattern: "/api/calls/:callid/transcript", domain: "realtime", action: "transcript", risk: "write", owner: "gateway" },
  { method: "POST", pattern: "/api/conversations/new", domain: "conversations", action: "create", risk: "write", owner: "gateway" },
  { method: "POST", pattern: "/api/conversations/compact", domain: "conversations", action: "compact", risk: "write", owner: "gateway" },
  { method: "POST", pattern: "/api/chat", domain: "chat", action: "send", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/session/diary", domain: "sessions", action: "diary", risk: "write", owner: "gateway" },
  { method: "DELETE", pattern: "/api/conversations", domain: "conversations", action: "delete", risk: "write", owner: "gateway" },
  { method: "DELETE", pattern: "/api/conversations/messages", domain: "conversations", action: "delete-message", risk: "write", owner: "gateway" },

  // Memoria y biblioteca de documentos
  { method: "GET", pattern: "/api/memory", domain: "memory", action: "catalog", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/library/list", domain: "library", action: "list", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/library/search", domain: "library", action: "search", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/library/preview", domain: "library", action: "preview", risk: "read", owner: "gateway" },

  // Permisos, aprobaciones y auditoría (los decide y guarda el Gateway)
  { method: "GET", pattern: "/api/permissions", domain: "permissions", action: "list", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/audit", domain: "permissions", action: "audit", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/approvals", domain: "approvals", action: "list", risk: "read", owner: "gateway" },
  { method: "POST", pattern: "/api/permissions/:id/revoke", domain: "permissions", action: "revoke", risk: "write", owner: "gateway" },
  { method: "POST", pattern: "/api/approvals/:id/(approve|reject)", domain: "approvals", action: "decide", risk: "sensitive", owner: "gateway" },

  // Modo de la llamada de voz: local (motor propio) o nube (Realtime), lo decide y guarda el Gateway
  { method: "GET", pattern: "/api/voice/mode", domain: "voice", action: "mode_get", risk: "read", owner: "gateway" },
  { method: "POST", pattern: "/api/voice/mode", domain: "voice", action: "mode_set", risk: "sensitive", owner: "gateway" },

  // Modelos locales y remotos
  { method: "GET", pattern: "/api/ollama/catalog", domain: "ollama", action: "catalog", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/ollama/jobs", domain: "ollama", action: "jobs", risk: "read", owner: "gateway" },
  { method: "POST", pattern: "/api/ollama/pull-request", domain: "ollama", action: "pull-request", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/ollama/delete-request", domain: "ollama", action: "delete-request", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/benchmark", domain: "benchmark", action: "run", risk: "sensitive", owner: "gateway" },

  // Proveedores y credenciales (OAuth y claves)
  { method: "GET", pattern: "/api/oauth/status", domain: "oauth", action: "status", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/oauth/openrouter/callback", domain: "oauth", action: "callback", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/oauth/openai/start", domain: "oauth", action: "start-openai", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/oauth/openai/logout", domain: "oauth", action: "logout-openai", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/oauth/claude/start", domain: "oauth", action: "start-claude", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/oauth/claude/logout", domain: "oauth", action: "logout-claude", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/oauth/openrouter/start", domain: "oauth", action: "start-openrouter", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/oauth/openrouter/refresh", domain: "oauth", action: "refresh-openrouter", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/oauth/openrouter/logout", domain: "oauth", action: "logout-openrouter", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/oauth/meta/start", domain: "oauth", action: "start-meta", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/oauth/meta/refresh", domain: "oauth", action: "refresh-meta", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/oauth/meta/logout", domain: "oauth", action: "logout-meta", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/nvidia/connect", domain: "providers", action: "connect-nvidia", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/nvidia/logout", domain: "providers", action: "logout-nvidia", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/nvidia/refresh", domain: "providers", action: "refresh-nvidia", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/kimi/connect", domain: "providers", action: "connect-kimi", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/kimi/logout", domain: "providers", action: "logout-kimi", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/kimi/refresh", domain: "providers", action: "refresh-kimi", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/gemini/connect", domain: "providers", action: "connect-gemini", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/gemini/logout", domain: "providers", action: "logout-gemini", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/gemini/refresh", domain: "providers", action: "refresh-gemini", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/mistral/connect", domain: "providers", action: "connect-mistral", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/mistral/logout", domain: "providers", action: "logout-mistral", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/mistral/refresh", domain: "providers", action: "refresh-mistral", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/anthropic/connect", domain: "providers", action: "connect-anthropic", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/anthropic/logout", domain: "providers", action: "logout-anthropic", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/anthropic/refresh", domain: "providers", action: "refresh-anthropic", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/antigravity/connect", domain: "providers", action: "connect-antigravity", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/antigravity/logout", domain: "providers", action: "logout-antigravity", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/providers/antigravity/refresh", domain: "providers", action: "refresh-antigravity", risk: "sensitive", owner: "gateway" },

  // Automatizaciones, subagentes, nodos y medios
  { method: "GET", pattern: "/api/automations", domain: "automations", action: "list", risk: "read", owner: "gateway" },
  { method: "POST", pattern: "/api/automations/clear-events", domain: "automations", action: "clear-events", risk: "write", owner: "gateway" },
  { method: "POST", pattern: "/api/automations/create-request", domain: "automations", action: "create-request", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/automations/delete-request", domain: "automations", action: "delete-request", risk: "sensitive", owner: "gateway" },
  { method: "GET", pattern: "/api/subagents", domain: "subagents", action: "list", risk: "read", owner: "gateway" },
  { method: "GET", pattern: "/api/nodes", domain: "nodes", action: "list", risk: "read", owner: "gateway" },
  { method: "POST", pattern: "/api/nodes/heartbeat", domain: "nodes", action: "heartbeat", risk: "write", owner: "gateway" },
  { method: "GET", pattern: "/api/media", domain: "media", action: "status", risk: "read", owner: "gateway" },
  { method: "POST", pattern: "/api/uploads", domain: "uploads", action: "upload", risk: "write", owner: "gateway" },
  { method: "POST", pattern: "/api/transcribe", domain: "media", action: "transcribe", risk: "sensitive", owner: "gateway" },
  { method: "POST", pattern: "/api/tts", domain: "media", action: "tts", risk: "sensitive", owner: "gateway" },
];

const COMPILED = ROUTE_TABLE.map((route) => ({ ...route, regex: new RegExp(`^${route.pattern.replace(/:[a-z]+/g, "[^/]+")}$`) }));

/**
 * Clasifica una petición pública.
 *   { known: false }                                   la ruta no existe con ningún método
 *   { known: true, methodAllowed: false, allow: [...] } existe, pero no con este método
 *   { known: true, methodAllowed: true, domain, action, risk, owner }
 * `pathname` es la ruta YA normalizada (sin consulta); se compara exacta, como hace server.py.
 */
export function classifyRoute(method, pathname) {
  const matches = COMPILED.filter((route) => route.regex.test(pathname));
  if (matches.length === 0) return { known: false };
  const hit = matches.find((route) => route.method === method);
  if (!hit) return { known: true, methodAllowed: false, allow: [...new Set(matches.map((route) => route.method))].sort() };
  return { known: true, methodAllowed: true, domain: hit.domain, action: hit.action, risk: hit.risk, owner: hit.owner };
}
