// store-cli.mjs - herramienta de línea de comandos para el almacén de datos de MyKOS (fase 2).
//
//   node store-cli.mjs status               estado del almacén y de la configuración (no cambia nada)
//   node store-cli.mjs verify               relee y valida cada documento, con sus copias (no cambia nada)
//   node store-cli.mjs export --to <carpeta> [--json]
//                                           escribe los documentos del almacén como los ficheros de siempre
//                                           (conversations.json, memory.json, memory_embeddings.json). NO borra nada:
//                                           si en la carpeta ya hay un fichero, lo aparta como «.antes-de-exportar-<fecha>».
//   node store-cli.mjs retire               aparta la carpeta del almacén («mykos» -> «mykos.retirado-<fecha>»), sin
//                                           borrar nada. Solo con MyKOS parado. Lo usa «mykos store off» tras exportar.
//
// Carpeta del almacén: --dir, o MYKOS_STORE_DIR, o ~/.mykos/gateway-state/mykos
// Configuración real: MYKOS_GATEWAY_CONFIG, o ~/.mykos/gateway-state/mykos-gateway.json
// Códigos de salida: 0 correcto, 1 error o fallo de verificación.
import { createHash } from "node:crypto";
import { closeSync, existsSync, fsyncSync, openSync, readFileSync, readdirSync, renameSync, statSync, writeSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { DOCUMENTS, DocumentStore } from "./mykos-ui/store.js";

const args = process.argv.slice(2);
const command = args[0] ?? "status";
const option = (name) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : undefined;
};
const asJson = args.includes("--json");
const stateDir = process.env.MYKOS_GATEWAY_STATE_DIR || path.join(os.homedir(), ".mykos", "gateway-state");
const dir = path.resolve(option("dir") || process.env.MYKOS_STORE_DIR || path.join(stateDir, "mykos"));
const configFile = process.env.MYKOS_GATEWAY_CONFIG || path.join(stateDir, "mykos-gateway.json");

const sha256 = (buffer) => createHash("sha256").update(buffer).digest("hex");
const stamp = () => {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
};
const fail = (message) => {
  console.error(`Error: ${message}`);
  process.exit(1);
};

function storeEnabledInConfig() {
  try {
    const cfg = JSON.parse(readFileSync(configFile, "utf8"));
    return cfg?.plugins?.entries?.["mykos-ui"]?.config?.store?.enabled === true;
  } catch {
    return null; // no se pudo leer
  }
}

function openStore() {
  if (!existsSync(path.join(dir, "docs"))) return null;
  return new DocumentStore({ dir, logger: { error: (m) => console.error(m), warn: (m) => console.error(m) } }).ensure();
}

function status() {
  const enabled = storeEnabledInConfig();
  const store = openStore();
  const info = { configured: enabled, dir, exists: Boolean(store), docs: [] };
  if (store) {
    info.docs = store.list().map((d) => ({ name: d.name, label: d.label, exists: d.exists, revision: d.revision, count: d.count, bytes: d.bytes, updatedAt: d.updatedAt }));
    const count = (sub) => (existsSync(path.join(dir, sub)) ? readdirSync(path.join(dir, sub)).length : 0);
    info.backups = Object.fromEntries(Object.keys(DOCUMENTS).map((n) => [n, count(path.join("backups", n))]));
    info.snapshots = count("snapshots");
    const journal = path.join(dir, "journal.jsonl");
    info.journalBytes = existsSync(journal) ? statSync(journal).size : 0;
  }
  if (asJson) {
    console.log(JSON.stringify(info, null, 2));
    return;
  }
  console.log(`Datos de MyKOS: ${enabled === true ? "los guarda el Gateway (almacén activado en la configuración)" : enabled === false ? "ficheros de data/ (almacén desactivado en la configuración)" : "configuración ilegible"}`);
  console.log(`Carpeta del almacén: ${dir}${store ? "" : "  (todavía no existe)"}`);
  for (const d of info.docs) {
    console.log(`  ${d.name.padEnd(13)} ${d.exists ? `revisión ${String(d.revision).padEnd(5)} ${String(d.count).padStart(5)} ${d.label}  ${String(d.bytes).padStart(9)} B  ${d.updatedAt}` : "sin datos"}`);
  }
  if (store) console.log(`Copias por documento: ${Object.entries(info.backups).map(([n, c]) => `${n} ${c}`).join(", ")}; instantáneas diarias: ${info.snapshots}`);
}

function verify() {
  const store = openStore();
  if (!store) fail(`no hay almacén en ${dir}`);
  let failures = 0;
  for (const name of Object.keys(DOCUMENTS)) {
    try {
      const doc = store.get(name);
      if (!doc) {
        console.log(`  ${name.padEnd(13)} sin datos`);
        continue;
      }
      const backups = path.join(dir, "backups", name);
      const nCopies = existsSync(backups) ? readdirSync(backups).length : 0;
      console.log(`  ${name.padEnd(13)} OK  revisión ${doc.revision}, ${DOCUMENTS[name].count(doc.data)} ${DOCUMENTS[name].label}, ${nCopies} copias`);
    } catch (error) {
      failures += 1;
      console.log(`  ${name.padEnd(13)} FALLA  ${error.message}`);
    }
  }
  process.exit(failures ? 1 : 0);
}

function repair() {
  const store = new DocumentStore({ dir, logger: { error: (m) => console.error(m), warn: (m) => console.error(m) } }).ensure();
  const docsDir = path.join(dir, "docs");
  let fixedTmp = 0;
  if (existsSync(docsDir)) {
    for (const f of readdirSync(docsDir)) {
      if (f.endsWith(".tmp") || f.includes(".tmp-")) {
        const corruptPath = path.join(docsDir, f);
        renameSync(corruptPath, `${corruptPath}.apartado-${stamp()}`);
        fixedTmp += 1;
      }
    }
  }
  let restored = 0;
  let unrecoverable = 0;
  for (const name of Object.keys(DOCUMENTS)) {
    try {
      store.get(name);
    } catch (error) {
      const backupDir = path.join(dir, "backups", name);
      let recovered = false;
      if (existsSync(backupDir)) {
        const candidates = readdirSync(backupDir).filter((f) => f.endsWith(".json")).sort().reverse();
        for (const candidate of candidates) {
          try {
            const raw = readFileSync(path.join(backupDir, candidate), "utf8");
            const parsed = JSON.parse(raw);
            const payload = parsed && typeof parsed === "object" && "data" in parsed ? parsed.data : parsed;
            if (DOCUMENTS[name].validate(payload)) {
              const docFile = path.join(docsDir, `${name}.json`);
              if (existsSync(docFile)) {
                renameSync(docFile, `${docFile}.corrupto-${stamp()}`);
              }
              store.put(name, payload, { source: "doctor-repair", actor: "mykos-doctor" });
              console.log(`  ${name.padEnd(13)} REPARADO desde copia ${candidate}`);
              restored += 1;
              recovered = true;
              break;
            }
          } catch {}
        }
      }
      if (!recovered) {
        console.log(`  ${name.padEnd(13)} FALLA sin copia válida (${error.message})`);
        unrecoverable += 1;
      }
    }
  }
  console.log(`Almacén revisado: ${fixedTmp} temporales limpiados, ${restored} documentos restaurados, ${unrecoverable} fallos pendientes.`);
  process.exit(unrecoverable ? 1 : 0);
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

function exportDocs() {
  const to = option("to");
  if (!to) fail("falta --to <carpeta> (normalmente la carpeta data/ de MyKOS)");
  const target = path.resolve(to);
  const store = openStore();
  if (!store) fail(`no hay almacén en ${dir}`);
  // Todo o nada: primero se leen y validan TODOS los documentos; si alguno no se puede leer, no se escribe ningún fichero.
  const docs = [];
  for (const name of Object.keys(DOCUMENTS)) {
    try {
      const doc = store.get(name);
      if (doc) docs.push({ name, doc });
    } catch (error) {
      fail(`no se puede leer «${name}»: ${error.message}. No se ha exportado nada.`);
    }
  }
  const report = [];
  for (const { name, doc } of docs) {
    const spec = DOCUMENTS[name];
    const file = path.join(target, spec.legacyFile);
    // Mismo formato que escribe Python: sangría de 2 espacios (el índice, compacto) y sin escapar los acentos.
    const text = name === "memory-index" ? JSON.stringify(doc.data) : JSON.stringify(doc.data, null, 2);
    let movedTo = null;
    if (existsSync(file)) {
      movedTo = `${file}.antes-de-exportar-${stamp()}`;
      renameSync(file, movedTo);
    }
    writeDurable(`${file}.tmp`, text);
    renameSync(`${file}.tmp`, file);
    const back = readFileSync(file);
    let ok = false;
    try {
      const parsed = JSON.parse(back.toString("utf8"));
      ok = JSON.stringify(parsed) === JSON.stringify(doc.data) && spec.validate(parsed) && spec.count(parsed) === spec.count(doc.data);
    } catch {}
    report.push({ name, file, revision: doc.revision, count: spec.count(doc.data), bytes: back.length, sha256: sha256(back), verified: ok, previousMovedTo: movedTo });
  }
  if (asJson) console.log(JSON.stringify(report, null, 2));
  else {
    for (const r of report) console.log(`  ${r.name.padEnd(13)} ${r.verified ? "OK   " : "FALLA"} revisión ${r.revision}, ${r.count} elementos, ${r.bytes} B, sha256 ${r.sha256.slice(0, 16)}…  -> ${r.file}${r.previousMovedTo ? `\n${" ".repeat(20)}(el que había se conserva como ${path.basename(r.previousMovedTo)})` : ""}`);
    if (!report.length) console.log("  El almacén no tiene ningún documento que exportar.");
  }
  process.exit(report.every((r) => r.verified) ? 0 : 1);
}

function retire() {
  if (!existsSync(dir)) fail(`no hay almacén en ${dir}`);
  const to = `${dir}.retirado-${stamp()}`;
  renameSync(dir, to);
  console.log(`Almacén apartado (no borrado): ${to}`);
}

switch (command) {
  case "status":
    status();
    break;
  case "verify":
    verify();
    break;
  case "repair":
  case "fix":
    repair();
    break;
  case "export":
    exportDocs();
    break;
  case "retire":
    retire();
    break;
  default:
    fail(`comando desconocido «${command}». Usa: status | verify | repair | export --to <carpeta> | retire`);
}
