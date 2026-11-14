// Almacén de documentos de MyKOS, propiedad del Gateway (fase 2 de la hoja de ruta).
//
// Qué guarda: las conversaciones, la memoria y su índice, como documentos JSON completos dentro del estado del
// Gateway (<estado>/mykos/). Solo el Gateway toca esos ficheros; el backend Python los pide y los guarda por HTTP.
//
// Garantías
//   - Escritura atómica: fichero temporal + fsync + renombrado. Nunca queda un documento a medio escribir.
//   - Cada documento lleva una revisión que sube en cada escritura; si el que escribe partía de otra revisión se
//     anota como conflicto (last-write-wins, igual que antes) pero la escritura se acepta.
//   - Copia de la versión anterior en cada escritura (enlace duro, sin copiar bytes), las últimas N revisiones.
//   - Instantánea diaria de todos los documentos (la primera escritura de cada día), las últimas M jornadas.
//   - Diario de escrituras (journal.jsonl): hora, documento, revisión, tamaño, SHA-256 y quién escribió.
//   - Protección contra borrados masivos por error: se rechaza una escritura que reduzca el número de elementos
//     de un documento a menos del 40 % (con al menos 5 elementos antes).
//   - Importación única desde los ficheros antiguos de data/, verificada releyendo, y con el original conservado.
//
// Sin dependencias fuera de Node. Todo es síncrono a propósito: en un proceso de un solo hilo no hay huecos entre
// leer, comparar y escribir, así que no hacen falta cerrojos.

import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import {
  appendFileSync, closeSync, copyFileSync, existsSync, fsyncSync, linkSync, mkdirSync, openSync,
  readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync, writeSync,
} from "node:fs";
import path from "node:path";

export class StoreError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

const isObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const NAME_RE = /^[a-z][a-z0-9-]{0,39}$/;
const JOURNAL_ROTATE_BYTES = 5 * 1024 * 1024;

/** Documentos que el almacén conoce: de qué fichero antiguo vienen, cómo se validan y cómo se cuentan. */
export const DOCUMENTS = {
  conversations: {
    legacyFile: "conversations.json",
    label: "conversaciones",
    validate: (d) => isObject(d) && Array.isArray(d.conversations),
    count: (d) => d.conversations.length,
    guarded: true,
  },
  memory: {
    legacyFile: "memory.json",
    label: "entradas de memoria",
    validate: (d) => isObject(d) && Array.isArray(d.entries),
    count: (d) => d.entries.length,
    guarded: true,
  },
  "memory-index": {
    legacyFile: "memory_embeddings.json",
    label: "vectores de memoria",
    validate: (d) => isObject(d) && isObject(d.entries),
    count: (d) => Object.keys(d.entries).length,
    guarded: false, // índice derivado: se puede reconstruir
  },
  permissions: {
    legacyFile: "permissions.json",
    label: "permisos y auditoría",
    validate: (d) => isObject(d) && Array.isArray(d.grants) && Array.isArray(d.audit),
    count: (d) => d.grants.length + d.audit.length,
    guarded: true,
  },
  approvals: {
    legacyFile: "approvals.json",
    label: "aprobaciones pendientes",
    validate: (d) => isObject(d) && Array.isArray(d.approvals),
    count: (d) => d.approvals.length,
    // Las aprobaciones se consumen al resolverlas y caducan; no aplicar el guard de reducción.
    guarded: false,
  },
  automations: {
    legacyFile: "automations.json",
    label: "recordatorios y eventos",
    validate: (d) => isObject(d) && Array.isArray(d.automations) && Array.isArray(d.events),
    count: (d) => d.automations.length + d.events.length,
    guarded: false,
  },
  subagents: {
    legacyFile: "subagents.json",
    label: "trabajos de subagentes",
    validate: (d) => isObject(d) && Array.isArray(d.jobs),
    count: (d) => d.jobs.length,
    guarded: false,
  },
  nodes: {
    legacyFile: "nodes.json",
    label: "nodos emparejados",
    validate: (d) => isObject(d) && Array.isArray(d.nodes),
    count: (d) => d.nodes.length,
    // Un nodo puede revocarse; no aplicar el guard de reducción.
    guarded: false,
  },
  swarm: {
    legacyFile: "swarm.json",
    label: "motor multi-agente Swarm",
    validate: (d) => isObject(d) && isObject(d.members) && Array.isArray(d.messages),
    count: (d) => d.messages.length,
    // El coordinador puede reiniciar el Swarm limpiando el tablón; no aplicar el guard de reducción.
    guarded: false,
  },
};

const sha256 = (buffer) => createHash("sha256").update(buffer).digest("hex");

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/** Renombra con reintentos: en Windows un antivirus o el indexador pueden tener el fichero abierto un instante. */
function renameWithRetry(from, to, attempts = 8) {
  for (let i = 0; ; i += 1) {
    try {
      renameSync(from, to);
      return;
    } catch (error) {
      if (i >= attempts - 1 || !["EPERM", "EBUSY", "EACCES"].includes(error.code)) throw error;
      sleepSync(25 * (i + 1));
    }
  }
}

function readFileRetry(file, attempts = 4) {
  for (let i = 0; ; i += 1) {
    try {
      return readFileSync(file);
    } catch (error) {
      if (i >= attempts - 1 || !["EPERM", "EBUSY", "EACCES"].includes(error.code)) throw error;
      sleepSync(25 * (i + 1));
    }
  }
}

function writeDurable(file, text) {
  const fd = openSync(file, "w");
  try {
    writeSync(fd, text);
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
}

function localStamp(date = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}${p(date.getMonth() + 1)}${p(date.getDate())}-${p(date.getHours())}${p(date.getMinutes())}${p(date.getSeconds())}`;
}
const localDay = (date = new Date()) => localStamp(date).slice(0, 8);

export class DocumentStore {
  /**
   * @param {{ dir: string, logger?: any, backupsKeep?: number, snapshotDays?: number, maxDocBytes?: number }} options
   */
  constructor({ dir, logger, backupsKeep = 40, snapshotDays = 14, maxDocBytes = 64 * 1024 * 1024 }) {
    this.dir = path.resolve(dir);
    this.logger = logger;
    this.backupsKeep = backupsKeep;
    this.snapshotDays = snapshotDays;
    this.maxDocBytes = maxDocBytes;
    this.docsDir = path.join(this.dir, "docs");
    this.backupsDir = path.join(this.dir, "backups");
    this.snapshotsDir = path.join(this.dir, "snapshots");
    this.journalFile = path.join(this.dir, "journal.jsonl");
    this.tokenFile = path.join(this.dir, ".token");
    this.meta = new Map(); // name -> { revision, bytes, updatedAt, count }
    this.token = "";
    this.imports = []; // resultado de la última importación, para /mykos-health
    this.ready = false;
  }

  info(message) {
    this.logger?.info?.(`mykos-ui: almacén: ${message}`);
  }

  /** Crea las carpetas, el token y la caché de metadatos. Idempotente. */
  ensure() {
    if (this.ready) return this;
    for (const d of [this.dir, this.docsDir, this.backupsDir, this.snapshotsDir]) mkdirSync(d, { recursive: true });
    this.token = this.loadOrCreateToken();
    for (const name of Object.keys(DOCUMENTS)) {
      try {
        this.refreshMeta(name);
      } catch (error) {
        this.logger?.error?.(`mykos-ui: almacén: no se pudo leer «${name}»: ${error.message}`);
      }
    }
    this.ready = true;
    return this;
  }

  loadOrCreateToken() {
    if (existsSync(this.tokenFile)) {
      const t = readFileSync(this.tokenFile, "utf8").trim();
      if (/^[0-9a-f]{64}$/.test(t)) return t;
    }
    const t = randomBytes(32).toString("hex");
    writeFileSync(this.tokenFile, `${t}\n`, { mode: 0o600 });
    return t;
  }

  checkToken(candidate) {
    if (typeof candidate !== "string" || candidate.length !== this.token.length) return false;
    return timingSafeEqual(Buffer.from(candidate), Buffer.from(this.token));
  }

  spec(name) {
    if (typeof name !== "string" || !NAME_RE.test(name) || !Object.hasOwn(DOCUMENTS, name)) {
      throw new StoreError(404, "unknown_document", `Documento desconocido: «${String(name).slice(0, 40)}».`);
    }
    return DOCUMENTS[name];
  }

  docFile(name) {
    return path.join(this.docsDir, `${name}.json`);
  }

  // ---------------------------------------------------------------- lectura

  /** Lee un documento. Si el fichero está dañado, recupera la última copia válida y lo anota. */
  readDoc(name) {
    this.spec(name);
    const file = this.docFile(name);
    if (!existsSync(file)) return null;
    try {
      return this.parseDoc(name, readFileRetry(file));
    } catch (error) {
      const recovered = this.recoverFromBackup(name);
      if (recovered) {
        this.logger?.error?.(`mykos-ui: almacén: «${name}» estaba dañado (${error.message}); recuperada la revisión ${recovered.revision} de las copias.`);
        this.journal({ doc: name, event: "recovered", rev: recovered.revision, reason: String(error.message).slice(0, 120) });
        writeDurable(`${file}.tmp`, JSON.stringify(recovered));
        renameWithRetry(`${file}.tmp`, file);
        // La lista de documentos (y /mykos-health) debe reflejar lo recuperado, no la revisión que se perdió.
        this.meta.set(name, { revision: recovered.revision, bytes: statSync(file).size, updatedAt: recovered.updatedAt, count: DOCUMENTS[name].count(recovered.data) });
        return recovered;
      }
      throw new StoreError(500, "corrupt", `El documento «${name}» está dañado y no hay copia válida: ${error.message}`);
    }
  }

  parseDoc(name, buffer) {
    const doc = JSON.parse(buffer.toString("utf8"));
    if (!isObject(doc) || doc.format !== 1 || doc.name !== name || !Number.isInteger(doc.revision) || !DOCUMENTS[name].validate(doc.data)) {
      throw new Error("cabecera o contenido no válidos");
    }
    return doc;
  }

  recoverFromBackup(name) {
    const dir = path.join(this.backupsDir, name);
    if (!existsSync(dir)) return null;
    const files = readdirSync(dir)
      .map((f) => ({ f, rev: Number((/\.r(\d+)\.json$/.exec(f) || [])[1]) }))
      .filter((x) => Number.isInteger(x.rev))
      .sort((a, b) => b.rev - a.rev);
    for (const { f } of files) {
      try {
        return this.parseDoc(name, readFileSync(path.join(dir, f)));
      } catch {}
    }
    return null;
  }

  refreshMeta(name) {
    const doc = this.readDoc(name);
    if (!doc) {
      this.meta.delete(name);
      return null;
    }
    const meta = { revision: doc.revision, bytes: statSync(this.docFile(name)).size, updatedAt: doc.updatedAt, count: DOCUMENTS[name].count(doc.data) };
    this.meta.set(name, meta);
    return meta;
  }

  get(name) {
    return this.readDoc(name);
  }

  list() {
    return Object.keys(DOCUMENTS).map((name) => ({
      name,
      label: DOCUMENTS[name].label,
      exists: this.meta.has(name),
      ...(this.meta.get(name) ?? { revision: 0, bytes: 0, updatedAt: null, count: 0 }),
    }));
  }

  // ---------------------------------------------------------------- escritura

  /**
   * Guarda el documento completo. Devuelve { revision, previousRevision, conflict, bytes, sha256 }.
   * @param {string} name
   * @param {any} data
   * @param {{ expectedRevision?: number|null, source?: string, allowShrink?: boolean }} [opts]
   */
  put(name, data, opts = {}) {
    const spec = this.spec(name);
    this.ensure();
    if (!spec.validate(data)) throw new StoreError(400, "invalid_document", `El documento «${name}» no tiene el formato esperado.`);
    const current = this.readDoc(name);
    const previousRevision = current?.revision ?? 0;
    const conflict = opts.expectedRevision !== undefined && opts.expectedRevision !== null && Number(opts.expectedRevision) !== previousRevision;

    if (current && spec.guarded && !opts.allowShrink) {
      const before = spec.count(current.data);
      const after = spec.count(data);
      if (before >= 5 && after < before * 0.4) {
        this.journal({ doc: name, event: "shrink-rejected", rev: previousRevision, before, after, source: opts.source });
        throw new StoreError(409, "shrink_guard", `Escritura rechazada: «${name}» pasaría de ${before} a ${after} ${spec.label}. Parece un error; si es a propósito, hay que permitirlo expresamente.`);
      }
    }

    const revision = previousRevision + 1;
    const text = JSON.stringify({ format: 1, name, revision, updatedAt: new Date().toISOString(), data });
    const bytes = Buffer.byteLength(text);
    if (bytes > this.maxDocBytes) throw new StoreError(413, "too_large", `El documento «${name}» ocuparía ${bytes} bytes (máximo ${this.maxDocBytes}).`);

    if (current) this.snapshotIfNeeded();
    const file = this.docFile(name);
    const tmp = `${file}.tmp`;
    writeDurable(tmp, text);
    if (current) this.backupCurrent(name, file, previousRevision);
    renameWithRetry(tmp, file);
    if (current) this.pruneBackups(name);

    const digest = sha256(Buffer.from(text));
    this.meta.set(name, { revision, bytes, updatedAt: new Date().toISOString(), count: spec.count(data) });
    this.journal({ doc: name, rev: revision, prev: previousRevision, bytes, sha256: digest, source: opts.source, ...(conflict ? { conflict: true, expected: Number(opts.expectedRevision) } : {}) });
    return { revision, previousRevision, conflict, bytes, sha256: digest };
  }

  /** Guarda la versión que se va a sustituir con un enlace duro (sin copiar bytes); si no se puede, copia. */
  backupCurrent(name, file, revision) {
    const dir = path.join(this.backupsDir, name);
    mkdirSync(dir, { recursive: true });
    const target = path.join(dir, `${name}.r${revision}.json`);
    if (existsSync(target)) return;
    try {
      linkSync(file, target);
    } catch {
      copyFileSync(file, target);
    }
  }

  pruneBackups(name) {
    const dir = path.join(this.backupsDir, name);
    const revs = readdirSync(dir)
      .map((f) => ({ f, rev: Number((/\.r(\d+)\.json$/.exec(f) || [])[1]) }))
      .filter((x) => Number.isInteger(x.rev))
      .sort((a, b) => b.rev - a.rev);
    for (const { f } of revs.slice(this.backupsKeep)) rmSync(path.join(dir, f), { force: true });
  }

  /** Primera escritura de cada día: copia de todos los documentos tal como estaban. */
  snapshotIfNeeded() {
    const dir = path.join(this.snapshotsDir, localDay());
    if (existsSync(dir)) return;
    mkdirSync(dir, { recursive: true });
    for (const name of Object.keys(DOCUMENTS)) {
      const file = this.docFile(name);
      if (existsSync(file)) copyFileSync(file, path.join(dir, `${name}.json`));
    }
    const days = readdirSync(this.snapshotsDir).filter((d) => /^\d{8}$/.test(d)).sort();
    for (const d of days.slice(0, Math.max(0, days.length - this.snapshotDays))) rmSync(path.join(this.snapshotsDir, d), { recursive: true, force: true });
    this.info(`instantánea diaria en snapshots/${localDay()}`);
  }

  journal(entry) {
    try {
      if (existsSync(this.journalFile) && statSync(this.journalFile).size > JOURNAL_ROTATE_BYTES) renameWithRetry(this.journalFile, `${this.journalFile}.1`);
      appendFileSync(this.journalFile, `${JSON.stringify({ ts: new Date().toISOString(), ...entry })}\n`);
    } catch (error) {
      this.logger?.warn?.(`mykos-ui: almacén: no se pudo anotar en el diario: ${error.message}`);
    }
  }

  // ---------------------------------------------------------------- importación única

  /**
   * Importa todos los documentos conocidos desde la carpeta data/ antigua, TODO O NADA:
   *   1. se validan todos los ficheros antiguos; si alguno es inválido no se toca nada;
   *   2. se importa y se verifica cada uno releyendo; si alguno falla se deshace todo lo importado en esta pasada;
   *   3. solo entonces se apartan los originales (renombrados a «.migrated-<fecha>»).
   * Así nunca queda un estado a medias en el que unos datos estén en el almacén y otros en ficheros que ya no existen.
   */
  importAll(legacyDir) {
    this.ensure();
    const results = [];
    const candidates = [];
    for (const name of Object.keys(DOCUMENTS)) {
      const spec = DOCUMENTS[name];
      const legacy = path.join(legacyDir, spec.legacyFile);
      const base = { name, legacy };
      try {
        if (this.readDoc(name)) {
          results.push({ ...base, status: existsSync(legacy) ? "store-exists-legacy-ignored" : "store-exists" });
        } else if (!existsSync(legacy)) {
          results.push({ ...base, status: "no-legacy" });
        } else {
          const raw = readFileRetry(legacy);
          let data;
          try {
            data = JSON.parse(raw.toString("utf8"));
          } catch (error) {
            throw new Error(`el fichero antiguo no es JSON válido: ${error.message}`);
          }
          if (!spec.validate(data)) throw new Error("el fichero antiguo no tiene el formato esperado");
          const result = { ...base, status: "pending", count: spec.count(data), bytes: raw.length, sha256: sha256(raw) };
          candidates.push({ name, spec, legacy, data, result });
          results.push(result);
        }
      } catch (error) {
        results.push({ ...base, status: "failed", error: error.message });
      }
    }

    if (results.some((r) => r.status === "failed")) {
      for (const c of candidates) c.result.status = "not-imported"; // no se ha tocado nada
    } else {
      const created = [];
      try {
        for (const c of candidates) {
          const written = this.put(c.name, c.data, { source: `import:${path.basename(c.legacy)}`, allowShrink: true });
          created.push(c.name);
          const back = this.readDoc(c.name);
          if (!back || JSON.stringify(back.data) !== JSON.stringify(c.data) || c.spec.count(back.data) !== c.result.count) throw new Error(`lo releído de «${c.name}» no coincide con lo importado`);
          c.result.revision = written.revision;
        }
      } catch (error) {
        for (const name of created) {
          rmSync(this.docFile(name), { force: true });
          this.meta.delete(name);
        }
        this.journal({ event: "import-failed", error: String(error.message).slice(0, 160), rolledBack: created });
        for (const c of candidates) Object.assign(c.result, { status: "failed", error: `verificación fallida: ${error.message}` });
      }
      if (candidates.every((c) => c.result.status === "pending")) {
        for (const c of candidates) {
          const moved = `${c.legacy}.migrated-${localStamp()}`;
          try {
            renameWithRetry(c.legacy, moved);
            c.result.movedTo = moved;
          } catch (error) {
            this.logger?.warn?.(`mykos-ui: almacén: importado «${c.name}» pero no se pudo apartar ${c.legacy}: ${error.message}`);
          }
          c.result.status = "imported";
          this.journal({ doc: c.name, event: "imported", rev: c.result.revision, count: c.result.count, legacySha256: c.result.sha256, legacyBytes: c.result.bytes, legacyMovedTo: c.result.movedTo ? path.basename(c.result.movedTo) : null });
          this.info(`importado «${c.name}»: ${c.result.count} ${c.spec.label} (${c.result.bytes} B); original conservado como ${c.result.movedTo ? path.basename(c.result.movedTo) : c.legacy}`);
        }
      }
    }

    this.imports = results;
    for (const r of results) {
      if (r.status === "failed") this.logger?.error?.(`mykos-ui: almacén: importación de «${r.name}» fallida: ${r.error}`);
      else if (r.status === "store-exists-legacy-ignored") this.logger?.warn?.(`mykos-ui: almacén: «${r.name}» ya existe en el almacén; se ignora ${r.legacy} (no se ha tocado)`);
    }
    return results;
  }
}
