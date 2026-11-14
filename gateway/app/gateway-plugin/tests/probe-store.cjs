// Uso: node probe-store.cjs
//
// Prueba el módulo del almacén (store.js) por sí solo, sin Gateway: escritura atómica, revisiones, copias,
// instantánea diaria, diario, recuperación de ficheros dañados, protección contra borrados masivos, importación
// verificada desde los ficheros antiguos y token. Trabaja en una carpeta temporal propia.
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { pathToFileURL } = require("url");

const repo = path.resolve(__dirname, "..", "..");
const root = path.join(os.homedir(), "mykos-gateway-test", "store-unit");
const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });
const sha = (b) => crypto.createHash("sha256").update(b).digest("hex");
const conv = (n, text = "hola") => ({ conversations: Array.from({ length: n }, (_, i) => ({ id: `c${i}`, title: `Conversación ${i}`, messages: [{ role: "user", content: `${text} ${i}` }] })) });
const mem = (n) => ({ entries: Array.from({ length: n }, (_, i) => ({ id: `m${i}`, title: `Recuerdo ${i}`, content: "texto" })) });

let mod;
let n = 0;
const fresh = (opts = {}) => {
  const dir = path.join(root, `t${(n += 1)}`);
  const logs = [];
  const logger = { info: (m) => logs.push(["info", m]), warn: (m) => logs.push(["warn", m]), error: (m) => logs.push(["error", m]) };
  const store = new mod.DocumentStore({ dir, logger, ...opts }).ensure();
  return { store, dir, logs };
};
const throwsCode = (fn) => {
  try {
    fn();
    return null;
  } catch (e) {
    return e.code ?? e.message;
  }
};
const readJsonl = (f) => fs.readFileSync(f, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));

(async () => {
  fs.rmSync(root, { recursive: true, force: true });
  fs.mkdirSync(root, { recursive: true });
  mod = await import(pathToFileURL(path.join(repo, "gateway-plugin", "mykos-ui", "store.js")).href);

  // 1. Arranque y token
  {
    const { store, dir } = fresh();
    check("ensure() crea las carpetas y un token de 64 hex", /^[0-9a-f]{64}$/.test(store.token) && ["docs", "backups", "snapshots"].every((d) => fs.existsSync(path.join(dir, d))), store.token.slice(0, 8) + "…");
    const again = new mod.DocumentStore({ dir }).ensure();
    check("el token persiste entre arranques", again.token === store.token, "");
    check("token: solo el correcto vale (y no vale vacío, corto, largo ni no-cadena)", store.checkToken(store.token) && !store.checkToken("") && !store.checkToken(store.token.slice(1)) && !store.checkToken(store.token + "0") && !store.checkToken(undefined) && !store.checkToken(12345), "");
  }

  // 2-4. Escritura, revisiones, copias y conflictos
  {
    const { store, dir } = fresh();
    const r1 = store.put("conversations", conv(3), { source: "test" });
    const doc = store.get("conversations");
    check("primera escritura: revisión 1 y se lee idéntica", r1.revision === 1 && r1.previousRevision === 0 && JSON.stringify(doc.data) === JSON.stringify(conv(3)), `rev ${r1.revision}, ${r1.bytes} B`);
    check("cabecera del documento (formato, nombre, revisión, fecha)", doc.format === 1 && doc.name === "conversations" && doc.revision === 1 && !Number.isNaN(Date.parse(doc.updatedAt)), "");
    const r2 = store.put("conversations", conv(4));
    check("segunda escritura: revisión 2", r2.revision === 2 && r2.previousRevision === 1 && !r2.conflict, "");
    const b1 = path.join(dir, "backups", "conversations", "conversations.r1.json");
    check("la revisión 1 quedó como copia con su contenido", fs.existsSync(b1) && JSON.parse(fs.readFileSync(b1, "utf8")).revision === 1 && JSON.parse(fs.readFileSync(b1, "utf8")).data.conversations.length === 3, "");
    const r3 = store.put("conversations", conv(4, "otro"), { expectedRevision: 1, source: "test-conflicto" });
    check("expectedRevision distinto: conflicto anotado pero escritura aceptada (igual que antes)", r3.conflict === true && r3.revision === 3, `rev ${r3.revision}`);
    const r4 = store.put("conversations", conv(4, "ok"), { expectedRevision: 3 });
    check("expectedRevision correcto: sin conflicto", r4.conflict === false && r4.revision === 4, "");
    const list = store.list();
    const c = list.find((x) => x.name === "conversations");
    check("list(): revisión, tamaño y recuento de cada documento (los ausentes a 0)", c.exists && c.revision === 4 && c.count === 4 && c.bytes > 0 && list.find((x) => x.name === "memory").exists === false && list.find((x) => x.name === "memory").revision === 0, JSON.stringify(c));
    store.put("memory", mem(2));
    check("los documentos son independientes", store.get("memory").revision === 1 && store.get("conversations").revision === 4, "");
  }

  // 5-6. Nombres y estructura
  {
    const { store } = fresh();
    const bad = ["../x", "..\\x", "Conversations", "unknown", "", "constructor", "__proto__", "conversations/../memory", "a".repeat(80), null, 7];
    const wrong = bad.filter((name) => throwsCode(() => store.put(name, conv(1))) !== "unknown_document");
    check("nombres no permitidos rechazados (rutas, mayúsculas, prototipos, desconocidos)", wrong.length === 0, wrong.length ? `aceptados: ${wrong.join(",")}` : `${bad.length}/${bad.length}`);
    const badDocs = [{}, [], null, "texto", { conversations: "no" }, { conversations: {} }, 5];
    const accepted = badDocs.filter((d) => throwsCode(() => store.put("conversations", d)) !== "invalid_document");
    check("estructuras no válidas rechazadas con 400", accepted.length === 0, accepted.length ? `aceptadas: ${JSON.stringify(accepted)}` : `${badDocs.length}/${badDocs.length}`);
    check("la memoria exige «entries» (lista) y el índice «entries» (objeto)", throwsCode(() => store.put("memory", { entries: {} })) === "invalid_document" && throwsCode(() => store.put("memory-index", { entries: [] })) === "invalid_document" && store.put("memory-index", { entries: {} }).revision === 1, "");
    check("un rechazo no crea ningún documento", store.get("conversations") === null, "");
  }

  // 7. Protección contra borrados masivos
  {
    const { store, dir } = fresh();
    store.put("conversations", conv(10));
    check("borrado masivo (10 → 3) rechazado con 409", throwsCode(() => store.put("conversations", conv(3), { source: "bug" })) === "shrink_guard" && store.get("conversations").data.conversations.length === 10, "");
    check("borrado moderado (10 → 6) permitido", store.put("conversations", conv(6)).revision === 2, "");
    check("con allowShrink se permite (10 → 1)", store.put("conversations", conv(1), { allowShrink: true }).revision === 3, "");
    const small = fresh().store;
    small.put("conversations", conv(4));
    check("con menos de 5 elementos no se aplica la protección (4 → 0)", small.put("conversations", conv(0)).revision === 2, "");
    const idx = fresh().store;
    idx.put("memory-index", { entries: Object.fromEntries(Array.from({ length: 20 }, (_, i) => [`k${i}`, {}])) });
    check("el índice (derivado) no tiene protección: se puede vaciar y reconstruir", idx.put("memory-index", { entries: {} }).revision === 2, "");
    check("el rechazo queda en el diario", readJsonl(path.join(dir, "journal.jsonl")).some((e) => e.event === "shrink-rejected" && e.before === 10 && e.after === 3), "");
  }

  // 8. Ficheros temporales y dañados
  {
    const { store, dir, logs } = fresh();
    store.put("conversations", conv(5));
    store.put("conversations", conv(5, "v2"));
    fs.writeFileSync(path.join(dir, "docs", "conversations.json.tmp"), "{basura a medias");
    check("un .tmp abandonado no afecta a la lectura ni a la siguiente escritura", store.get("conversations").revision === 2 && store.put("conversations", conv(5, "v3")).revision === 3 && !fs.existsSync(path.join(dir, "docs", "conversations.json.tmp")), "");
    const main = path.join(dir, "docs", "conversations.json");
    fs.writeFileSync(main, fs.readFileSync(main, "utf8").slice(0, 40)); // fichero truncado
    const rec = store.get("conversations");
    check("fichero truncado: se recupera la última copia válida y se anota", rec && rec.revision === 2 && logs.some(([l, m]) => l === "error" && m.includes("dañado")) && readJsonl(path.join(dir, "journal.jsonl")).some((e) => e.event === "recovered"), `revisión recuperada ${rec?.revision}`);
    check("tras recuperar, el fichero principal vuelve a ser válido", JSON.parse(fs.readFileSync(main, "utf8")).revision === 2, "");
    check("tras recuperar, list() muestra la revisión recuperada (no la que se perdió)", store.list().find((d) => d.name === "conversations").revision === 2, `revisión en la lista ${store.list().find((d) => d.name === "conversations").revision}`);
    check("se puede seguir escribiendo desde la revisión recuperada", store.put("conversations", conv(5, "v4")).revision === 3, "");
    const lone = fresh().store;
    lone.put("conversations", conv(2));
    fs.writeFileSync(path.join(lone.dir, "docs", "conversations.json"), "no es json");
    check("dañado y sin copias: error 500 claro (no se inventa un documento vacío)", throwsCode(() => lone.get("conversations")) === "corrupt", "");
    const mismatch = fresh().store;
    mismatch.put("memory", mem(2));
    fs.copyFileSync(path.join(mismatch.dir, "docs", "memory.json"), path.join(mismatch.dir, "docs", "conversations.json"));
    check("un fichero con la cabecera de otro documento se trata como dañado", throwsCode(() => mismatch.get("conversations")) === "corrupt", "");
  }

  // 9-11. Copias, instantáneas y diario
  {
    const { store, dir } = fresh({ backupsKeep: 5 });
    for (let i = 0; i < 12; i += 1) store.put("memory", mem(i + 1));
    const kept = fs.readdirSync(path.join(dir, "backups", "memory")).map((f) => Number(/\.r(\d+)\./.exec(f)[1])).sort((a, b) => a - b);
    check("solo se guardan las últimas 5 copias (r7..r11)", JSON.stringify(kept) === JSON.stringify([7, 8, 9, 10, 11]), `copias: ${kept.join(",")}`);
    const day = fs.readdirSync(path.join(dir, "snapshots")).filter((d) => /^\d{8}$/.test(d));
    check("instantánea diaria creada una sola vez", day.length === 1 && fs.existsSync(path.join(dir, "snapshots", day[0], "memory.json")), `carpetas: ${day.join(",")}`);
    const j = readJsonl(path.join(dir, "journal.jsonl")).filter((e) => e.rev);
    const last = j[j.length - 1];
    const onDisk = fs.readFileSync(path.join(dir, "docs", "memory.json"));
    check("el diario anota cada escritura con el SHA-256 real del fichero", j.length === 12 && last.rev === 12 && last.sha256 === sha(onDisk) && last.doc === "memory", `${j.length} entradas`);
    const old = fresh({ snapshotDays: 2 });
    for (const d of ["20200101", "20200102", "20200103"]) fs.mkdirSync(path.join(old.dir, "snapshots", d), { recursive: true });
    old.store.put("memory", mem(1));
    old.store.put("memory", mem(2));
    const days = fs.readdirSync(path.join(old.dir, "snapshots")).sort();
    check("las instantáneas antiguas se podan (quedan las 2 últimas jornadas)", days.length === 2 && days[0] === "20200103", days.join(","));
  }

  // 12-14. Tamaño y texto
  {
    const { store } = fresh();
    const big = conv(2000, "x".repeat(4500)); // ~9 MB
    const t0 = Date.now();
    const r = store.put("conversations", big);
    const t1 = Date.now();
    const back = store.get("conversations");
    check(`documento de ${(r.bytes / 1048576).toFixed(1)} MB: escribe y lee íntegro`, back.data.conversations.length === 2000 && sha(Buffer.from(JSON.stringify(back.data))) === sha(Buffer.from(JSON.stringify(big))), `escritura ${t1 - t0} ms, lectura ${Date.now() - t1} ms`);
    const text = "Acentos áéíóúñü, ¿qué?, emojis 🍄🛠️🇪🇸, salto de línea, \u0000 nulo, comillas \" y \\, tab\t, 𝒳 (par suplente)";
    store.put("memory", { entries: [{ id: "u", content: text }] });
    check("texto con acentos, emojis, U+2028, nulos y pares suplentes: ida y vuelta exacta", store.get("memory").data.entries[0].content === text, "");
    const tiny = fresh({ maxDocBytes: 1000 }).store;
    check("un documento demasiado grande se rechaza con 413", throwsCode(() => tiny.put("conversations", conv(50))) === "too_large", "");
  }

  // 15. Importación desde los ficheros antiguos
  {
    const { store, dir, logs } = fresh();
    const legacyDir = path.join(root, "legacy Usuario ñ"); // con acento, espacio y eñe, como la ruta real
    fs.mkdirSync(legacyDir, { recursive: true });
    const legacyConv = Buffer.from(JSON.stringify(conv(7), null, 2), "utf8");
    fs.writeFileSync(path.join(legacyDir, "conversations.json"), legacyConv);
    fs.writeFileSync(path.join(legacyDir, "memory.json"), JSON.stringify(mem(3), null, 2));
    const res = store.importAll(legacyDir);
    const byName = Object.fromEntries(res.map((r) => [r.name, r]));
    check("importa conversaciones y memoria; el índice, sin fichero antiguo, se salta", byName.conversations.status === "imported" && byName.memory.status === "imported" && byName["memory-index"].status === "no-legacy", res.map((r) => `${r.name}:${r.status}`).join(" "));
    check("lo importado coincide con el original (recuento, contenido y revisión 1)", store.get("conversations").revision === 1 && JSON.stringify(store.get("conversations").data) === JSON.stringify(conv(7)) && byName.conversations.count === 7, "");
    const files = fs.readdirSync(legacyDir);
    const moved = files.find((f) => f.startsWith("conversations.json.migrated-"));
    check("el original se conserva renombrado a «.migrated-<fecha>» con los mismos bytes", !files.includes("conversations.json") && moved && sha(fs.readFileSync(path.join(legacyDir, moved))) === sha(legacyConv), moved);
    const ev = readJsonl(path.join(dir, "journal.jsonl")).find((e) => e.event === "imported" && e.doc === "conversations");
    check("el diario guarda el SHA-256 del original y el recuento", ev && ev.legacySha256 === sha(legacyConv) && ev.count === 7, "");
    const again = store.importAll(legacyDir);
    check("una segunda importación no hace nada (idempotente)", again.every((r) => ["store-exists", "no-legacy"].includes(r.status)), again.map((r) => r.status).join(","));
    fs.writeFileSync(path.join(legacyDir, "conversations.json"), JSON.stringify(conv(99)));
    const third = store.importAll(legacyDir).find((r) => r.name === "conversations");
    check("un fichero antiguo que reaparece NO sobrescribe el almacén ni se toca", third.status === "store-exists-legacy-ignored" && store.get("conversations").data.conversations.length === 7 && fs.existsSync(path.join(legacyDir, "conversations.json")) && logs.some(([l, m]) => l === "warn" && m.includes("se ignora")), third.status);
  }
  {
    const { store, dir } = fresh();
    const legacyDir = path.join(root, "legacy-malo");
    fs.mkdirSync(legacyDir, { recursive: true });
    fs.writeFileSync(path.join(legacyDir, "conversations.json"), "{ esto no es json");
    fs.writeFileSync(path.join(legacyDir, "memory.json"), JSON.stringify({ entries: "no es lista" }));
    const res = Object.fromEntries(store.importAll(legacyDir).map((r) => [r.name, r]));
    check("fichero antiguo inválido (JSON roto o forma errónea): fallo claro, sin renombrar ni crear nada", res.conversations.status === "failed" && res.memory.status === "failed" && fs.existsSync(path.join(legacyDir, "conversations.json")) && fs.existsSync(path.join(legacyDir, "memory.json")) && store.get("conversations") === null && store.get("memory") === null, `${res.conversations.error} | ${res.memory.error}`);
  }
  {
    // TODO O NADA: uno válido y otro inválido -> no se importa ni se aparta NINGUNO
    const { store } = fresh();
    const legacyDir = path.join(root, "legacy-mixto");
    fs.mkdirSync(legacyDir, { recursive: true });
    fs.writeFileSync(path.join(legacyDir, "conversations.json"), JSON.stringify(conv(6)));
    fs.writeFileSync(path.join(legacyDir, "memory.json"), "{ roto");
    const res = Object.fromEntries(store.importAll(legacyDir).map((r) => [r.name, r]));
    check("todo o nada: si un fichero antiguo es inválido, tampoco se importa el válido ni se aparta ninguno", res.memory.status === "failed" && res.conversations.status === "not-imported" && fs.existsSync(path.join(legacyDir, "conversations.json")) && fs.existsSync(path.join(legacyDir, "memory.json")) && store.get("conversations") === null && fs.readdirSync(legacyDir).every((f) => !f.includes(".migrated-")), `${res.conversations.status} / ${res.memory.status}`);
  }
  for (const [label, failAtCall, imported] of [
    // Hay nueve documentos conocidos: las comprobaciones iniciales pasan tras conversations, memory,
    // memory-index, permissions, approvals, automations, subagents, nodes y swarm.
    ["falla la verificación del primero (ya escrito: se deshace)", 11, ["conversations"]],
    ["falla la verificación del segundo (el primero ya estaba verificado y también se deshace)", 13, ["conversations", "memory"]],
  ]) {
    const { store, dir } = fresh();
    const legacyDir = path.join(root, `legacy-verif-${failAtCall}`);
    fs.mkdirSync(legacyDir, { recursive: true });
    fs.writeFileSync(path.join(legacyDir, "conversations.json"), JSON.stringify(conv(5)));
    fs.writeFileSync(path.join(legacyDir, "memory.json"), JSON.stringify(mem(2)));
    const orig = store.readDoc.bind(store);
    let calls = 0;
    store.readDoc = (name) => {
      calls += 1;
      const d = orig(name);
      return calls === failAtCall && d ? { ...d, data: { ...d.data, [name === "memory" ? "entries" : "conversations"]: [] } } : d; // la relectura «sale» distinta
    };
    const res = store.importAll(legacyDir);
    store.readDoc = orig;
    check(`todo o nada: ${label}: se deshace todo y los originales quedan intactos`, res.some((r) => r.status === "failed" && /verificación/.test(r.error)) && !res.some((r) => r.status === "imported") && ["conversations.json", "memory.json"].every((f) => fs.existsSync(path.join(legacyDir, f))) && store.get("conversations") === null && store.get("memory") === null && readJsonl(path.join(dir, "journal.jsonl")).some((e) => e.event === "import-failed" && JSON.stringify(e.rolledBack) === JSON.stringify(imported)), res.map((r) => r.status).join(","));
  }
  {
    const { store } = fresh();
    const legacyDir = path.join(root, "legacy-ok2");
    fs.mkdirSync(legacyDir, { recursive: true });
    fs.writeFileSync(path.join(legacyDir, "conversations.json"), JSON.stringify(conv(3)));
    fs.writeFileSync(path.join(legacyDir, "memory.json"), JSON.stringify(mem(2)));
    fs.writeFileSync(path.join(legacyDir, "memory_embeddings.json"), JSON.stringify({ version: 1, entries: { m0: { v: [0.1, 0.2] } } }));
    fs.writeFileSync(path.join(legacyDir, "permissions.json"), JSON.stringify({ grants: [{ id: "g1" }], audit: [{ id: "a1" }] }));
    fs.writeFileSync(path.join(legacyDir, "approvals.json"), JSON.stringify({ approvals: [{ id: "p1", status: "pending" }] }));
    fs.writeFileSync(path.join(legacyDir, "automations.json"), JSON.stringify({ automations: [{ id: "r1" }], events: [] }));
    fs.writeFileSync(path.join(legacyDir, "subagents.json"), JSON.stringify({ jobs: [{ id: "j1" }] }));
    fs.writeFileSync(path.join(legacyDir, "nodes.json"), JSON.stringify({ nodes: [{ id: "n1", token_hash: "hash" }] }));
    fs.writeFileSync(path.join(legacyDir, "swarm.json"), JSON.stringify({ title: "Swarm Test", head: 1, permission_mode: "supervisado", members: { coordinator: { name: "coordinator" } }, messages: [{ seq: 1, agent: "coordinator", text: "Hola" }] }));
    const res = store.importAll(legacyDir);
    check("los nueve documentos se importan juntos y los nueve originales se apartan", res.every((r) => r.status === "imported") && fs.readdirSync(legacyDir).filter((f) => f.includes(".migrated-")).length === 9 && store.list().every((d) => d.exists && d.revision === 1), res.map((r) => `${r.name}:${r.status}`).join(" "));
  }

  // 16. Muchas escrituras seguidas
  {
    const { store, dir } = fresh({ backupsKeep: 3 });
    for (let i = 1; i <= 300; i += 1) store.put("conversations", conv(5 + (i % 3), `v${i}`), { source: "carga" }); // 5..7: sin borrados masivos
    const doc = store.get("conversations");
    check("300 escrituras seguidas: revisión 300, fichero válido y diario completo", doc.revision === 300 && readJsonl(path.join(dir, "journal.jsonl")).filter((e) => e.rev).length === 300 && fs.readdirSync(path.join(dir, "backups", "conversations")).length === 3, `rev ${doc.revision}`);
  }

  finish();
})().catch((error) => {
  check("la batería terminó sin excepciones", false, String(error && error.stack ? error.stack : error));
  finish();
});

function finish() {
  fs.rmSync(root, { recursive: true, force: true });
  const width = Math.max(...results.map((r) => r.name.length));
  let failures = 0;
  for (const r of results) {
    if (!r.ok) failures += 1;
    console.log(`${r.ok ? "OK   " : "FALLA"}  ${r.name.padEnd(width)}  ${r.detail}`);
  }
  console.log(failures ? `\n==> ${failures} de ${results.length} comprobaciones FALLARON` : `\n==> ${results.length}/${results.length} comprobaciones correctas`);
  process.exit(failures ? 1 : 0);
}
