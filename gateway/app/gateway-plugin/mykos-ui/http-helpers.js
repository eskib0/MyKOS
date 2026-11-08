// Utilidades HTTP, estáticos, proxy inverso y formato de conversaciones para mykos-ui.

import { appendFileSync, createReadStream, mkdirSync, readdirSync, statSync } from "node:fs";
import { stat } from "node:fs/promises";
import { createHmac } from "node:crypto";
import http from "node:http";
import path from "node:path";
import { pipeline } from "node:stream";

export const MAX_CHUNKED_BODY_BYTES = 40 * 1024 * 1024;
export const PROBE_TIMEOUT_MS = 1_500;

export const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

export const HOP_BY_HOP = new Set([
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
  "te", "trailer", "trailers", "transfer-encoding", "upgrade",
]);

export const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".wav": "audio/wav",
};

export const BASE_HEADERS = {
  // Sin caché: la interfaz se edita a diario y una pestaña con JS viejo ya nos costó horas.
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "no-referrer",
  "Content-Security-Policy":
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' data: blob:; connect-src 'self' ws: wss:; font-src 'self'; object-src 'none'; frame-ancestors 'none';",
};

export function mediaLibrary(projectDir, limit) {
  const baseDataDir = process.env.MYKOS_DATA_DIR
    ? path.resolve(process.env.MYKOS_DATA_DIR)
    : path.join(projectDir, "data");
  const dir = path.join(baseDataDir, "media");
  const rows = [];
  try {
    for (const name of readdirSync(dir)) {
      const file = path.join(dir, name);
      const st = statSync(file);
      if (st.isFile() && /\.(wav|mp3|mp4|webm|m4a|ogg)$/i.test(name)) {
        rows.push({
          name,
          path: `data/media/${name}`,
          bytes: st.size,
          modified_at: new Date(st.mtimeMs).toISOString(),
        });
      }
    }
  } catch {}
  return rows.sort((a, b) => b.modified_at.localeCompare(a.modified_at)).slice(0, limit);
}

export function sendJson(res, status, body, extraHeaders = {}) {
  if (res.destroyed || res.headersSent) return;
  const payload = JSON.stringify(body);
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Content-Length", Buffer.byteLength(payload));
  for (const [k, v] of Object.entries({ ...BASE_HEADERS, ...extraHeaders })) res.setHeader(k, v);
  res.end(payload);
}

export function onlyGetHead(req, res) {
  if (req.method === "GET" || req.method === "HEAD") return true;
  res.setHeader("Allow", "GET, HEAD");
  sendJson(res, 405, { ok: false, error: "method_not_allowed" });
  return false;
}

/** GET a una URL local devolviendo { status, json } o null si no responde a tiempo. */
export function probeJson(urlString, timeoutMs = PROBE_TIMEOUT_MS) {
  return new Promise((resolve) => {
    let target;
    try {
      target = new URL(urlString);
    } catch {
      resolve(null);
      return;
    }
    const request = http.request(
      { hostname: target.hostname, port: target.port, path: target.pathname + target.search, method: "GET", agent: false, timeout: timeoutMs },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("error", () => resolve(null));
        response.on("end", () => {
          let json = null;
          try {
            json = JSON.parse(Buffer.concat(chunks).toString("utf8"));
          } catch {}
          resolve({ status: response.statusCode ?? 0, json });
        });
      },
    );
    request.on("timeout", () => {
      request.destroy();
      resolve(null);
    });
    request.on("error", () => resolve(null));
    request.end();
  });
}

export function readBody(req, limitBytes) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > limitBytes) {
        reject(Object.assign(new Error("body_too_large"), { code: "BODY_TOO_LARGE" }));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

export function conversationSummary(conversation) {
  const messages = Array.isArray(conversation?.messages) ? conversation.messages : [];
  const last = messages.at(-1) ?? {};
  return {
    id: String(conversation?.id ?? ""),
    title: String(conversation?.title ?? "Nueva conversación"),
    created_at: String(conversation?.created_at ?? ""),
    updated_at: String(conversation?.updated_at ?? ""),
    message_count: messages.length,
    preview: String(last?.content ?? "").replace(/\n/g, " ").trim().slice(0, 120),
  };
}

export function conversationById(data, id) {
  return Array.isArray(data?.conversations) ? data.conversations.find((row) => String(row?.id ?? "") === id) : null;
}

export function conversationMarkdown(conversation) {
  const title = String(conversation?.title ?? "Nueva conversación").trim() || "Nueva conversación";
  const messages = Array.isArray(conversation?.messages) ? conversation.messages : [];
  const lines = [
    `# ${title}`,
    "",
    `- Creada: ${String(conversation?.created_at ?? "")}`,
    `- Actualizada: ${String(conversation?.updated_at ?? "")}`,
    `- Mensajes: ${messages.length}`,
    "",
  ];
  const summary = String(conversation?.context_summary ?? "").trim();
  if (summary) lines.push("## Resumen de contexto", "", summary, "");
  lines.push("## Conversación", "");
  const labels = { user: "Usuario", assistant: "MyKOS", system: "Sistema", tool: "Herramienta" };
  messages.forEach((message, index) => {
    const role = labels[String(message?.role ?? "")] ?? String(message?.role ?? "Mensaje");
    const at = String(message?.created_at ?? "").trim();
    lines.push(`### ${index + 1}. ${role}${at ? ` — ${at}` : ""}`, "", String(message?.content ?? "").trim() || "_(sin texto)_");
    if (Array.isArray(message?.sources) && message.sources.length) {
      lines.push("", "Fuentes:");
      for (const source of message.sources) if (isObject(source) && source.url) lines.push(`- [${source.title || source.url}](${source.url})`);
    }
    lines.push("");
  });
  return `${lines.join("\n").trimEnd()}\n`;
}

export function conversationSummaryExcerpt(message) {
  const labels = { user: "Usuario", assistant: "MyKOS", system: "Sistema" };
  const role = labels[String(message?.role ?? "")] ?? String(message?.role ?? "mensaje");
  let content = String(message?.content ?? "").replace(/\s+/g, " ").trim();
  if (content.length > 280) content = `${content.slice(0, 277)}…`;
  return `- ${role}: ${content || "(sin texto)"}`;
}

export function compactedConversationSummary(messages) {
  if (!messages.length) return "";
  return [
    "Resumen local del contexto anterior. Se han omitido mensajes antiguos para proteger la ventana del modelo:",
    ...messages.map(conversationSummaryExcerpt),
  ].join("\n").slice(0, 2400);
}

/** Ruta relativa ya decodificada -> ruta absoluta dentro de root, o null si no está permitida. */
export function resolveInside(root, relPath) {
  if (!relPath || relPath.includes("\0") || relPath.includes(":")) return null;
  const abs = path.resolve(root, relPath);
  if (abs !== root && !abs.startsWith(root + path.sep)) return null;
  const rel = path.relative(root, abs);
  if (!rel || rel.split(path.sep).some((seg) => seg.startsWith("."))) return null;
  return abs;
}

export async function sendFile(req, res, absPath) {
  let st;
  try {
    st = await stat(absPath);
  } catch {
    return sendJson(res, 404, { ok: false, error: "not_found" });
  }
  if (!st.isFile()) return sendJson(res, 404, { ok: false, error: "not_found" });

  res.statusCode = 200;
  res.setHeader("Content-Type", MIME[path.extname(absPath).toLowerCase()] ?? "application/octet-stream");
  res.setHeader("Content-Length", st.size);
  for (const [k, v] of Object.entries(BASE_HEADERS)) res.setHeader(k, v);
  if (req.method === "HEAD") return res.end();

  await new Promise((resolve) => {
    const stream = createReadStream(absPath);
    stream.on("error", () => {
      if (!res.headersSent) sendJson(res, 500, { ok: false, error: "read_error" });
      else res.destroy();
      resolve();
    });
    res.on("close", () => {
      stream.destroy();
      resolve();
    });
    stream.pipe(res);
  });
}

export function isLoopbackAddress(addr) {
  if (!addr) return false;
  const clean = String(addr).toLowerCase().trim();
  return clean === "127.0.0.1" || clean === "::1" || clean === "::ffff:127.0.0.1" || clean === "localhost";
}

export function isOwnRequest(req, extraOrigins) {
  const remote = req.socket?.remoteAddress;
  // Si la conexión TCP no proviene de loopback (p. ej. peticiones desde la LAN con --host 0.0.0.0),
  // no se considera petición propia del usuario local sin autenticación previa.
  if (remote && !isLoopbackAddress(remote)) {
    return false;
  }

  const port = req.socket?.localPort;
  const hosts = [`127.0.0.1:${port}`, `localhost:${port}`, `[::1]:${port}`];
  const host = String(req.headers.host ?? "").toLowerCase();
  if (!hosts.includes(host)) return false;
  const secFetchSite = String(req.headers["sec-fetch-site"] ?? "").toLowerCase();
  if (secFetchSite && secFetchSite !== "same-origin" && secFetchSite !== "none") {
    const originHeader = String(req.headers.origin ?? "").toLowerCase().replace(/\/+$/, "");
    if (!originHeader || !extraOrigins.has(originHeader)) return false;
  }
  const origin = req.headers.origin;
  if (origin === undefined) return true;
  const normalized = String(origin).toLowerCase().replace(/\/+$/, "");
  return hosts.some((h) => normalized === `http://${h}`) || extraOrigins.has(normalized);
}

export function proxyRequest(req, res, backendUrl, bufferedBodyOverride = null, pathOverride = null, extraHeaders = {}) {
  return new Promise((resolve) => {
    const target = new URL(backendUrl);
    const headers = {};
    for (const [key, value] of Object.entries(req.headers)) {
      const k = key.toLowerCase();
      if (HOP_BY_HOP.has(k) || k === "expect") continue;
      headers[k] = value;
    }
    Object.assign(headers, extraHeaders);
    headers.host = target.host;

    let settled = false;
    let responseStatus = 502;
    const done = () => {
      if (!settled) {
        settled = true;
        resolve(responseStatus);
      }
    };

    const forward = (bufferedBody) => {
      if (bufferedBody) headers["content-length"] = String(bufferedBody.length);
      const upstream = http.request(
        { hostname: target.hostname, port: target.port, method: req.method, path: pathOverride || req.url, headers, agent: false },
        (upstreamRes) => {
          responseStatus = upstreamRes.statusCode ?? 502;
          const out = {};
          for (const [key, value] of Object.entries(upstreamRes.headers)) {
            if (!HOP_BY_HOP.has(key.toLowerCase())) out[key] = value;
          }
          res.writeHead(upstreamRes.statusCode ?? 502, upstreamRes.statusMessage || undefined, out);
          pipeline(upstreamRes, res, () => done());
        },
      );
      upstream.on("error", (error) => {
        sendJson(res, 502, {
          error: "El servidor interno de MyKOS no responde. Si acaba de arrancar, espera unos segundos; si no, reinicia MyKOS Gateway.",
          code: error.code ?? "UPSTREAM_ERROR",
        });
        if (res.headersSent && !res.writableEnded) res.destroy();
        done();
      });
      res.on("close", () => {
        if (!res.writableFinished) upstream.destroy();
        done();
      });
      if (bufferedBody) upstream.end(bufferedBody);
      else pipeline(req, upstream, () => {});
    };

    if (bufferedBodyOverride !== null) {
      forward(bufferedBodyOverride);
      return;
    }

    const chunked = /\bchunked\b/i.test(String(req.headers["transfer-encoding"] ?? "")) && req.headers["content-length"] === undefined;
    if (!chunked) {
      forward(null);
      return;
    }
    readBody(req, MAX_CHUNKED_BODY_BYTES).then(forward, (error) => {
      if (error.code === "BODY_TOO_LARGE") sendJson(res, 413, { error: "La petición es demasiado grande." });
      else sendJson(res, 400, { error: "No se pudo leer la petición." });
      done();
    });
  });
}

export function controlAudit(file, event) {
  try {
    mkdirSync(path.dirname(file), { recursive: true });
    appendFileSync(file, `${JSON.stringify({ at: new Date().toISOString(), ...event })}\n`, "utf8");
  } catch {
    // El diario no puede tumbar una respuesta de modelo o una herramienta.
  }
}

export function actionRouteSignature(token, rawBody) {
  return createHmac("sha256", String(token || ""))
    .update("gateway-action\0", "utf8")
    .update(Buffer.isBuffer(rawBody) ? rawBody : Buffer.from(String(rawBody || ""), "utf8"))
    .digest("hex");
}

export function executionGrant(token, approvalId, conversationId, descriptor) {
  const expiresAt = Math.floor(Date.now() / 1000) + 90;
  const scopeKey = String(descriptor?.scope_key || "");
  const payload = `approval|${approvalId}|${conversationId}|${scopeKey}|${expiresAt}`;
  const signature = createHmac("sha256", String(token || "")).update(payload, "utf8").digest("hex");
  return {
    approval_id: String(approvalId || ""),
    conversation_id: String(conversationId || ""),
    scope_key: scopeKey,
    expires_at: expiresAt,
    signature,
  };
}

export function jsonRequest(urlString, payload, timeoutMs = 900_000, extraHeaders = {}, signal = null) {
  return new Promise((resolve, reject) => {
    let target;
    try {
      target = new URL(urlString);
    } catch (error) {
      reject(new Error(`URL interna no válida: ${error.message}`));
      return;
    }
    const body = Buffer.from(JSON.stringify(payload), "utf8");
    const request = http.request(
      {
        hostname: target.hostname,
        port: target.port,
        path: `${target.pathname}${target.search}`,
        method: "POST",
        agent: false,
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "Content-Length": String(body.length),
          ...extraHeaders,
        },
      },
      (response) => {
        const chunks = [];
        let size = 0;
        response.on("data", (chunk) => {
          size += chunk.length;
          if (size <= MAX_CHUNKED_BODY_BYTES) chunks.push(chunk);
          else response.destroy(new Error("Respuesta interna demasiado grande."));
        });
        response.on("error", reject);
        response.on("end", () => {
          let parsed;
          try {
            parsed = JSON.parse(Buffer.concat(chunks).toString("utf8"));
          } catch {
            parsed = { ok: false, error: "El motor interno devolvió una respuesta no JSON." };
          }
          resolve({ status: response.statusCode ?? 502, body: parsed });
        });
      },
    );
    request.setTimeout(timeoutMs, () => request.destroy(new Error("Tiempo agotado esperando al motor interno.")));
    if (signal) {
      const abort = () => request.destroy(new Error("Solicitud interna cancelada."));
      if (signal.aborted) abort();
      else signal.addEventListener("abort", abort, { once: true });
    }
    request.on("error", (error) => {
      resolve({
        status: 503,
        body: {
          ok: false,
          error: error.code === "ECONNREFUSED" ? "backend_unavailable" : "backend_error",
          detail: error.message,
          code: error.code || "REQUEST_FAILED",
        },
      });
    });
    request.end(body);
  });
}
