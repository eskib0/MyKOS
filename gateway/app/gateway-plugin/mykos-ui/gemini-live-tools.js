// Puente mínimo y deliberadamente acotado entre Gemini Live y las herramientas de MyKOS.
//
// El WebSocket Live es directo navegador <-> Google para poder usar un token efímero. Por
// ello el navegador solo retransmite las function calls: el Gateway valida la llamada,
// decide la lista blanca y ejecuta el trabajo en el backend privado. Nunca se entrega una
// herramienta, una credencial ni una autorización al navegador ni a Gemini.

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const MAX_CALLS_PER_MESSAGE = 4;
const MAX_RESULT_BYTES = 12_000;

export const GEMINI_LIVE_FUNCTION_DECLARATIONS = [
  {
    name: "get_local_status",
    description: "Consulta el estado básico de solo lectura de MyKOS y del equipo. No modifica nada.",
    parameters: { type: "OBJECT", properties: {} },
  },
  {
    name: "search_memory",
    description: "Busca recuerdos persistentes de MyKOS por palabras clave. Solo lectura.",
    parameters: {
      type: "OBJECT",
      properties: {
        query: { type: "STRING", description: "Palabras o frase que se quieren buscar." },
        category: { type: "STRING", description: "Categoría opcional: fact, preference, project, decision, task o reference." },
        max_results: { type: "INTEGER", description: "Máximo de resultados entre 1 y 6." },
      },
      required: ["query"],
    },
  },
  {
    name: "list_automations",
    description: "Lista los recordatorios locales de MyKOS. Solo lectura.",
    parameters: { type: "OBJECT", properties: {} },
  },
  {
    name: "create_reminder",
    description: "Prepara un recordatorio local. MyKOS siempre pedirá aprobación explícita antes de crearlo.",
    parameters: {
      type: "OBJECT",
      properties: {
        title: { type: "STRING", description: "Título breve del recordatorio." },
        message: { type: "STRING", description: "Texto opcional que se mostrará al activarse." },
        run_at: { type: "STRING", description: "Fecha ISO futura con zona horaria, por ejemplo 2026-10-03T18:30:00+02:00." },
        repeat_minutes: { type: "INTEGER", description: "0 para una vez o minutos de repetición, hasta 10080." },
      },
      required: ["title", "run_at"],
    },
  },
];

const NAMES = new Set(GEMINI_LIVE_FUNCTION_DECLARATIONS.map((item) => item.name));
const CATEGORIES = new Set(["fact", "preference", "project", "decision", "task", "reference"]);
const APPROVAL_TOOLS = new Set(["create_reminder"]);

function failure(id, name, error) {
  return { id, name, response: { result: { ok: false, error: String(error || "La herramienta no se pudo ejecutar.").slice(0, 800) } } };
}

function compact(result) {
  let encoded = "";
  try { encoded = JSON.stringify(result); } catch { return { ok: false, error: "La herramienta devolvió un resultado no serializable." }; }
  if (encoded.length <= MAX_RESULT_BYTES) return result;
  return {
    ok: Boolean(result?.ok),
    truncated: true,
    preview: encoded.slice(0, MAX_RESULT_BYTES),
    message: "El resultado se ha recortado para la llamada de voz.",
  };
}

function objectArguments(value) {
  if (!isObject(value)) throw new Error("Los argumentos de la herramienta no son válidos.");
  return value;
}

function onlyKeys(args, allowed) {
  for (const key of Object.keys(args)) if (!allowed.has(key)) throw new Error(`El campo «${key}» no está permitido.`);
}

function boundedString(value, label, max = 500) {
  if (typeof value !== "string" || !(value = value.trim()) || value.length > max) throw new Error(`«${label}» no es válido.`);
  return value;
}

function cleanArguments(name, raw) {
  const args = objectArguments(raw);
  if (name === "get_local_status" || name === "list_automations") {
    onlyKeys(args, new Set());
    return {};
  }
  if (name === "search_memory") {
    onlyKeys(args, new Set(["query", "category", "max_results"]));
    const result = { query: boundedString(args.query, "query") };
    if (args.category !== undefined) {
      const category = boundedString(args.category, "category", 40);
      if (!CATEGORIES.has(category)) throw new Error("La categoría no está permitida.");
      result.category = category;
    }
    if (args.max_results !== undefined) {
      if (!Number.isInteger(args.max_results) || args.max_results < 1 || args.max_results > 6) throw new Error("max_results debe estar entre 1 y 6.");
      result.max_results = args.max_results;
    }
    return result;
  }
  if (name === "create_reminder") {
    onlyKeys(args, new Set(["title", "message", "run_at", "repeat_minutes"]));
    const result = {
      title: boundedString(args.title, "title", 160),
      run_at: boundedString(args.run_at, "run_at", 80),
    };
    if (args.message !== undefined) result.message = boundedString(args.message, "message", 800);
    if (args.repeat_minutes !== undefined) {
      if (!Number.isInteger(args.repeat_minutes) || args.repeat_minutes < 0 || args.repeat_minutes > 10080) throw new Error("repeat_minutes debe estar entre 0 y 10080.");
      result.repeat_minutes = args.repeat_minutes;
    }
    return result;
  }
  throw new Error("La herramienta no está permitida en una llamada Gemini.");
}

async function one(call, deps) {
  const id = typeof call?.id === "string" ? call.id.trim().slice(0, 160) : "";
  const name = typeof call?.name === "string" ? call.name.trim() : "";
  if (!id || !NAMES.has(name)) return failure(id || "unknown", name || "unknown", "La llamada de función no está permitida.");
  let args;
  try { args = cleanArguments(name, call.args); } catch (error) { return failure(id, name, error?.message); }
  try {
    if (!APPROVAL_TOOLS.has(name)) return { id, name, response: { result: compact(await deps.worker.tool(name, args)) } };

    if (deps.permissionMode === "solo_lectura") {
      return failure(id, name, `Modo «Solo lectura» activo: no se pueden ejecutar acciones que modifiquen el sistema («${name}»).`);
    }

    const prepared = await deps.worker.prepare(name, args);
    if (!prepared?.ok || !isObject(prepared.action)) return failure(id, name, prepared?.error || "MyKOS no pudo preparar la propuesta.");
    const descriptor = deps.authority.descriptor?.(name, prepared.action);
    const authorization = deps.authority.authorize?.(name, prepared.action, deps.call.sessionId);
    if (authorization?.ok && authorization.decision === "granted" && authorization.grant) {
      const actionResult = await deps.worker.action(prepared.action, deps.call.sessionId, authorization.authorization);
      deps.authority.audit?.("permission_used", descriptor, {
        mode: String(authorization.grant.mode || "permanent"),
        status: actionResult?.ok ? "ok" : "failed",
        permission_id: String(authorization.grant.id || ""),
        session_id: deps.call.sessionId,
        detail: String(actionResult?.error || ""),
      });
      return { id, name, response: { result: compact(actionResult) } };
    }
    if (deps.permissionMode === "acceso_total") {
      const grant = deps.authority.grant?.(name, prepared.action, deps.call.sessionId);
      if (grant) {
        const actionResult = await deps.worker.action(prepared.action, deps.call.sessionId, { permission_id: grant.id, scope_key: descriptor.scope_key });
        deps.authority.audit?.("permission_used", descriptor, {
          mode: "permanent",
          status: actionResult?.ok ? "ok" : "failed",
          permission_id: String(grant.id || ""),
          session_id: deps.call.sessionId,
          detail: String(actionResult?.error || ""),
        });
        return { id, name, response: { result: compact(actionResult) } };
      }
    }
    const pending = deps.authority.createApproval({
      conversation_id: deps.call.sessionId,
      model: deps.call.model,
      messages: [],
      tool_name: name,
      action: prepared.action,
      supports_vision: false,
      generation: {},
      conversation_permission_mode: deps.permissionMode,
    });
    if (!pending?.ok || !pending.approval) return failure(id, name, pending?.error || "MyKOS no pudo solicitar la aprobación.");
    return {
      id,
      name,
      response: { result: {
        ok: true,
        pending_approval: true,
        approval_id: String(pending.approval.id || ""),
        expires_at: String(pending.approval.expires_at || ""),
        message: "Recordatorio preparado. Debe aprobarse en el panel de MyKOS antes de crearlo.",
      } },
    };
  } catch (error) {
    return failure(id, name, error?.message || error);
  }
}

/** Ejecuta una tanda de function calls únicamente si proceden de una llamada Gemini Live activa. */
export async function runGeminiLiveFunctionCalls(callId, functionCalls, { registry, worker, authority, permissionMode = "supervisado" } = {}) {
  const call = registry?.getInternal?.(callId);
  if (!call || call.provider !== "gemini_api" || call.state !== "active") throw new Error("La llamada Gemini Live no está activa.");
  if (!Array.isArray(functionCalls) || functionCalls.length < 1 || functionCalls.length > MAX_CALLS_PER_MESSAGE) {
    throw new Error(`La llamada debe contener entre 1 y ${MAX_CALLS_PER_MESSAGE} funciones.`);
  }
  const mode = ["solo_lectura", "acceso_total"].includes(String(permissionMode || "")) ? String(permissionMode) : "supervisado";
  const responses = [];
  for (const item of functionCalls) responses.push(await one(item, { call, worker, authority, permissionMode: mode }));
  return { functionResponses: responses };
}
