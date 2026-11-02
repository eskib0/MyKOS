// Autoridad de permisos y aprobaciones de MyKOS.
// Este módulo vive en MyKOS Gateway: Python solo prepara la acción y ejecuta
// físicamente una acción que el Gateway ya ha autorizado.

import { createHash, randomUUID } from "node:crypto";

export const PERMISSION_MODES = new Set(["once", "permanent"]);
const MAX_AUDIT_ENTRIES = 2000;
const MAX_GRANTS = 200;
const APPROVAL_TTL_MS = 10 * 60 * 1000;

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, "Z");

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (!isObject(value)) return value;
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
}

function scopeKey(value) {
  return createHash("sha256")
    .update(JSON.stringify(canonical(value)), "utf8")
    .digest("hex");
}

export function permissionDescriptor(toolName, action) {
  const safe = isObject(action) ? action : {};
  const kind = String(safe.kind || toolName || "").trim();
  let category = "action";
  let resource = kind;
  let match = { kind };
  let summary = kind;

  if (["write_file", "edit_file", "research_note"].includes(kind)) {
    category = "filesystem";
    const root = String(safe.root || "").trim();
    const path = String(safe.path || "").trim();
    resource = `${root}/${path}`.replace(/^\/+|\/+$/g, "");
    match = { kind, root, path, overwrite: Boolean(safe.overwrite) };
    summary = `${kind} · ${resource}`;
  } else if (kind === "run_powershell") {
    category = "shell";
    const root = String(safe.cwd_root || "").trim();
    const cwdPath = String(safe.cwd_path || ".").trim() || ".";
    const command = String(safe.command || "").trim();
    resource = `${root}/${cwdPath}`.replace(/^\/+|\/+$/g, "");
    match = { kind, cwd_root: root, cwd_path: cwdPath, command };
    summary = `PowerShell · ${resource} · ${command.slice(0, 180)}`;
  } else if (["start_service", "stop_service"].includes(kind)) {
    category = "service";
    resource = String(safe.service || "").trim();
    match = { kind, service: resource };
    summary = `${kind} · servicio ${resource}`;
  } else if (kind === "stop_process") {
    category = "process";
    const pid = Number(safe.pid || 0);
    const name = String(safe.name || "").trim();
    resource = `${name} · PID ${pid}`;
    match = { kind, pid, name, create_time_epoch: safe.create_time_epoch || 0 };
    summary = `Detener proceso · ${resource}`;
  } else if (["pull_ollama_model", "delete_ollama_model"].includes(kind)) {
    category = "model";
    resource = String(safe.model || "").trim();
    match = { kind, model: resource };
    summary = `${kind} · modelo ${resource}`;
  } else if (["save_memory", "delete_memory"].includes(kind)) {
    category = "memory";
    const memoryId = String(safe.memory_id || "").trim();
    resource = kind === "save_memory" ? String(safe.category || "memory") : memoryId;
    match = { kind, memory_id: memoryId, category: String(safe.category || "fact") };
    summary = `${kind} · ${resource}`;
  } else if (kind === "git_commit") {
    category = "git";
    resource = String(safe.root || "").trim();
    match = {
      kind,
      root: resource,
      message: String(safe.message || ""),
      paths: Array.isArray(safe.paths) ? safe.paths : [],
      stage_all: Boolean(safe.stage_all),
    };
    summary = `Commit Git · ${resource}`;
  } else {
    match = Object.fromEntries(Object.entries(safe).filter(([key]) => key !== "content"));
    if (!Object.hasOwn(match, "kind")) match.kind = kind;
    summary = `${kind} · acción exacta`;
  }

  return {
    category,
    resource,
    operation: kind,
    summary,
    scope_key: scopeKey(match),
  };
}

export function allowedModes(descriptor) {
  const operation = String(descriptor?.operation || "");
  if (new Set([
    "run_powershell", "delete_memory", "delete_ollama_model", "git_commit",
    "stop_process", "start_service", "stop_service", "create_reminder",
    "delete_reminder", "spawn_subagent", "git_branch", "git_remote_fetch",
    "git_remote_pull", "git_remote_push", "text_to_speech", "generate_image", "pair_node", "revoke_node",
  ]).has(operation)) return ["once"];
  return ["once", "permanent"];
}

export function permissionRequestView(toolName, action) {
  const descriptor = permissionDescriptor(toolName, action);
  const labels = {
    once: ["Supervisado", "Pide tu aprobación cada vez."],
    permanent: ["Acceso total", "No vuelve a preguntar; queda registrado como permiso concedido."],
  };
  return {
    ...descriptor,
    modes: allowedModes(descriptor).map((mode) => ({ id: mode, label: labels[mode][0], description: labels[mode][1] })),
  };
}

function active(grant, sessionId) {
  if (!isObject(grant) || String(grant.status || "active") !== "active") return false;
  const mode = String(grant.mode || "");
  return mode === "permanent" || (mode === "session" && Boolean(sessionId) && grant.session_id === sessionId);
}

function readData(store, name, fallback) {
  const doc = store?.get(name);
  return isObject(doc?.data) ? doc.data : fallback;
}

function putData(store, name, data, source) {
  if (!store) throw new Error("El almacén del Gateway no está disponible.");
  store.put(name, data, { source, allowShrink: name === "approvals" });
}

function publicGrant(grant) {
  const result = { ...grant };
  delete result.scope_key;
  delete result.session_id;
  delete result.approval_id;
  return result;
}

export class PermissionAuthority {
  constructor(store, logger) {
    this.store = store;
    this.logger = logger;
  }

  readPermissions() {
    return readData(this.store, "permissions", { grants: [], audit: [] });
  }

  writePermissions(state, source) {
    state.grants = Array.isArray(state.grants) ? state.grants : [];
    state.audit = Array.isArray(state.audit) ? state.audit : [];
    state.grants = state.grants.slice(-MAX_GRANTS);
    state.audit = state.audit.slice(-MAX_AUDIT_ENTRIES);
    putData(this.store, "permissions", state, source);
  }

  descriptor(toolName, action) {
    return permissionDescriptor(toolName, action);
  }

  findGrant(descriptor, sessionId = "") {
    const state = this.readPermissions();
    for (let i = state.grants.length - 1; i >= 0; i -= 1) {
      const grant = state.grants[i];
      if (grant?.scope_key === descriptor.scope_key && active(grant, sessionId)) return { ...grant };
    }
    return null;
  }

  authorize(toolName, action, sessionId = "") {
    const descriptor = this.descriptor(toolName, action);
    const grant = this.findGrant(descriptor, sessionId);
    return grant
      ? { ok: true, decision: "granted", descriptor, permission: permissionRequestView(toolName, action), grant: publicGrant(grant), authorization: { permission_id: grant.id, scope_key: grant.scope_key } }
      : { ok: true, decision: "approval_required", descriptor, permission: permissionRequestView(toolName, action) };
  }

  /**
   * Concede un permiso "permanente" directamente, sin pasar por una ficha de aprobación pendiente.
   * Solo para el modo "acceso total": la operación debe admitir el modo "permanent"
   * (allowedModes); las acciones de mayor riesgo (solo "once") nunca llegan aquí.
   * Devuelve el grant (nuevo o el ya existente si la autoridad coincide).
   */
  grant(toolName, action, sessionId, approvalId = "auto:acceso_total") {
    const descriptor = this.descriptor(toolName, action);
    if (!allowedModes(descriptor).includes("permanent")) return null;
    const state = this.readPermissions();
    const existing = state.grants.find((item) => item.scope_key === descriptor.scope_key && item.mode === "permanent" && active(item, sessionId));
    if (existing) {
      existing.last_used_at = nowIso();
      this.writePermissions(state, "gateway.permissions.auto_grant");
      return publicGrant(existing);
    }
    const grant = {
      id: randomUUID().replaceAll("-", ""),
      status: "active",
      mode: "permanent",
      session_id: "",
      category: descriptor.category,
      resource: descriptor.resource,
      operation: descriptor.operation,
      summary: descriptor.summary,
      scope_key: descriptor.scope_key,
      created_at: nowIso(),
      last_used_at: nowIso(),
      approval_id: approvalId,
    };
    state.grants.push(grant);
    this.writePermissions(state, "gateway.permissions.auto_grant");
    this.audit("permission_granted", descriptor, { mode: "permanent", approval_id: approvalId, permission_id: grant.id, session_id: sessionId });
    return publicGrant(grant);
  }

  createApproval(input) {
    const action = isObject(input.action) ? input.action : {};
    const toolName = String(input.tool_name || action.kind || "").trim();
    const permission = permissionRequestView(toolName, action);
    const now = Date.now();
    const state = readData(this.store, "approvals", { approvals: [] });
    state.approvals = Array.isArray(state.approvals) ? state.approvals : [];
    this.purge(state);
    const record = {
      id: randomUUID().replaceAll("-", ""),
      status: "pending",
      conversation_id: String(input.conversation_id || ""),
      model: String(input.model || ""),
      supports_vision: Boolean(input.supports_vision),
      generation: isObject(input.generation) ? input.generation : {},
      conversation_permission_mode: String(input.conversation_permission_mode || "supervisado"),
      tool_name: toolName,
      action,
      permission,
      messages: Array.isArray(input.messages) ? input.messages : [],
      created_at: nowIso(),
      expires_at: new Date(now + APPROVAL_TTL_MS).toISOString().replace(/\.\d{3}Z$/, "Z"),
      expires_at_epoch: now / 1000 + APPROVAL_TTL_MS / 1000,
    };
    state.approvals.push(record);
    putData(this.store, "approvals", state, "gateway.approvals.create");
    this.audit("approval_created", permission, { approval_id: record.id, session_id: record.conversation_id, status: "ok" });
    return { ok: true, approval: publicApproval(record) };
  }

  purge(state) {
    const now = Date.now() / 1000;
    state.approvals = (Array.isArray(state.approvals) ? state.approvals : []).filter((item) => (
      isObject(item) && item.status === "pending" && Number(item.expires_at_epoch || 0) > now
    ));
  }

  listApprovals(sessionId = "") {
    const state = readData(this.store, "approvals", { approvals: [] });
    const before = state.approvals?.length || 0;
    this.purge(state);
    if (state.approvals.length !== before) putData(this.store, "approvals", state, "gateway.approvals.purge");
    return state.approvals.filter((item) => !sessionId || item.conversation_id === sessionId).map(publicApproval);
  }

  listPermissions(sessionId = "") {
    const state = this.readPermissions();
    return state.grants.filter((grant) => active(grant, sessionId)).map(publicGrant).reverse();
  }

  listAudit(limit = 100, sessionId = "") {
    const state = this.readPermissions();
    const bounded = Math.max(1, Math.min(500, Number(limit) || 100));
    return state.audit.filter((item) => !sessionId || item.session_id === sessionId).slice().reverse().slice(0, bounded).map((item) => {
      const copy = { ...item };
      delete copy.session_id;
      return copy;
    });
  }

  revoke(permissionId) {
    const state = this.readPermissions();
    const grant = state.grants.find((item) => item?.id === permissionId && item.status === "active");
    if (!grant) return null;
    grant.status = "revoked";
    grant.revoked_at = nowIso();
    const descriptor = { category: grant.category, resource: grant.resource, operation: grant.operation, summary: grant.summary, scope_key: grant.scope_key };
    this.writePermissions(state, "gateway.permissions.revoke");
    this.audit("permission_revoked", descriptor, { permission_id: permissionId, status: "ok" });
    return publicGrant(grant);
  }

  verifyAuthorization(toolName, action, sessionId, authorization) {
    const descriptor = this.descriptor(toolName, action);
    const permissionId = String(authorization?.permission_id || "");
    const scope = String(authorization?.scope_key || "");
    const grant = this.findGrant(descriptor, sessionId);
    if (!grant || grant.id !== permissionId || scope !== descriptor.scope_key) {
      return { ok: false, error: "action_not_authorized", message: "El Gateway no ha autorizado esta acción o el permiso ya no está activo." };
    }
    return { ok: true, descriptor, grant };
  }

  audit(event, descriptor, extra = {}) {
    const state = this.readPermissions();
    state.audit = Array.isArray(state.audit) ? state.audit : [];
    state.audit.push({
      id: randomUUID().replaceAll("-", ""),
      at: nowIso(),
      event,
      status: extra.status || "ok",
      mode: extra.mode || "once",
      permission_id: extra.permission_id || "",
      approval_id: extra.approval_id || "",
      session_id: extra.session_id || "",
      category: descriptor?.category || "action",
      resource: descriptor?.resource || "",
      operation: descriptor?.operation || "",
      summary: descriptor?.summary || "",
      detail: String(extra.detail || "").slice(0, 500),
    });
    this.writePermissions(state, "gateway.permissions.audit");
  }

  async resolveApproval(approvalId, decision, permissionMode, execute) {
    const state = readData(this.store, "approvals", { approvals: [] });
    // Igual que listApprovals(): solo se escribe si la purga ha quitado algo de verdad. Antes se escribía siempre,
    // incluso al resolver un id inexistente (404 sin cambios): un bucle de intentos fallidos (un id caducado, o
    // simplemente uno que no existe) subía la revisión del documento en cada llamada sin necesidad.
    const before = state.approvals?.length || 0;
    this.purge(state);
    if (state.approvals.length !== before) putData(this.store, "approvals", state, "gateway.approvals.purge");
    const index = state.approvals.findIndex((item) => item?.id === approvalId);
    if (index < 0) {
      return { ok: false, status: 404, error: "La solicitud no existe o ha caducado." };
    }
    const record = state.approvals[index];
    if (decision === "reject") {
      this.audit("approval_rejected", record.permission, { approval_id: approvalId, session_id: record.conversation_id, status: "rejected" });
      state.approvals.splice(index, 1);
      putData(this.store, "approvals", state, "gateway.approvals.reject");
      return { ok: true, approved: false, rejected: true, action: publicApproval(record), conversation_id: record.conversation_id };
    }
    const modes = allowedModes(record.permission);
    const mode = modes.includes(permissionMode) ? permissionMode : "once";
    let permissionId = "";
    if (mode !== "once") {
      const permissions = this.readPermissions();
      const descriptor = permissionDescriptor(record.tool_name, record.action);
      const existing = permissions.grants.find((item) => item.scope_key === descriptor.scope_key && item.mode === mode && active(item, record.conversation_id));
      const grant = existing || {
        id: randomUUID().replaceAll("-", ""), status: "active", mode,
        session_id: mode === "session" ? record.conversation_id : "",
        category: descriptor.category, resource: descriptor.resource, operation: descriptor.operation,
        summary: descriptor.summary, scope_key: descriptor.scope_key, created_at: nowIso(), last_used_at: nowIso(), approval_id: approvalId,
      };
      if (!existing) permissions.grants.push(grant);
      this.writePermissions(permissions, "gateway.approvals.grant");
      permissionId = grant.id;
    }
    record.status = "executing";
    record.permission_mode = mode;
    record.decision_at = nowIso();
    putData(this.store, "approvals", state, "gateway.approvals.execute");
    this.audit(mode === "once" ? "approval_approved" : "permission_granted", record.permission, { mode, approval_id: approvalId, permission_id: permissionId, session_id: record.conversation_id });
    let actionResult;
    try {
      actionResult = await execute(record.action, record.conversation_id, record);
    } catch (error) {
      actionResult = { ok: false, error: String(error?.message || error) };
    }
    state.approvals = state.approvals.filter((item) => item?.id !== approvalId);
    putData(this.store, "approvals", state, "gateway.approvals.finish");
    this.audit(actionResult?.ok ? "execution_succeeded" : "execution_failed", record.permission, { mode, approval_id: approvalId, permission_id: permissionId, session_id: record.conversation_id, status: actionResult?.ok ? "ok" : "failed", detail: actionResult?.error });
    return {
      ok: true,
      approved: true,
      executed: Boolean(actionResult?.ok),
      permission_mode: mode,
      permission_id: permissionId,
      action: publicApproval(record),
      action_result: actionResult,
      conversation_id: record.conversation_id,
      _record: record,
    };
  }
}

function publicApproval(record) {
  const action = isObject(record.action) ? record.action : {};
  const kind = String(action.kind || record.tool_name || "");
  const publicRecord = {
    id: record.id,
    kind,
    title: kind,
    created_at: record.created_at,
    expires_at: record.expires_at,
    permission: record.permission || {},
  };
  for (const [key, value] of Object.entries(action)) {
    if (key === "content") {
      const content = String(value || "");
      publicRecord.content_preview = content.slice(0, 12_000);
      publicRecord.content_truncated = content.length > 12_000;
      publicRecord.content_bytes = Buffer.byteLength(content, "utf8");
    } else if (key === "id") {
      // El id de esta respuesta identifica la APROBACIÓN. Las acciones como
      // delete_reminder también tienen su propio id; no puede sobrescribirlo
      // o el navegador intentará resolver el recurso equivocado.
      publicRecord.target_id = value;
    } else if (key !== "messages") {
      publicRecord[key] = value;
    }
  }
  if (kind === "edit_file" && ("old_text" in action || "new_text" in action || "summary" in action || "preview_row" in action)) {
    const diffText = ("old_text" in action || "new_text" in action)
      ? `--- Fragmento actual ---\n${String(action.old_text || "")}\n--- Se sustituirá por ---\n${String(action.new_text || "")}`
      : String(action.summary || action.preview_row || "Edición estructurada del archivo.");
    publicRecord.content_preview = diffText.slice(0, 8_000);
    publicRecord.content_truncated = diffText.length > 8_000;
  }
  if (kind === "research_note" && action.title && !publicRecord.research_title) {
    publicRecord.research_title = action.title;
  }
  if ((kind === "save_memory" || kind === "delete_memory") && action.title && !publicRecord.memory_title) {
    publicRecord.memory_title = action.title;
  }
  if (kind === "stop_process" && action.name && !publicRecord.process_name) {
    publicRecord.process_name = action.name;
  }
  const titles = {
    write_file: "Crear archivo",
    edit_file: "Editar archivo",
    research_note: "Guardar ficha de investigación",
    run_powershell: "Ejecutar comando de terminal",
    save_memory: action.memory_id ? "Actualizar memoria" : "Guardar memoria",
    delete_memory: "Eliminar memoria",
    stop_process: "Detener proceso",
    start_service: "Iniciar servicio",
    stop_service: "Detener servicio",
    git_commit: "Crear commit Git",
    git_branch: "Operación de rama Git",
    git_remote_fetch: "Git fetch desde remoto",
    git_remote_pull: "Git pull desde remoto",
    git_remote_push: "Git push a remoto",
    pull_ollama_model: "Descargar o actualizar modelo Ollama",
    delete_ollama_model: "Eliminar modelo Ollama",
    create_reminder: "Crear recordatorio",
    delete_reminder: "Eliminar recordatorio",
    spawn_subagent: "Iniciar subagente local",
    text_to_speech: "Generar audio (TTS)",
    generate_image: "Generar imagen (Difusión)",
    pair_node: "Emparejar nodo",
    revoke_node: "Revocar nodo",
  };
  if (titles[kind]) publicRecord.title = titles[kind];
  return publicRecord;
}
