// Uso: node make-project.cjs <tag> [--with-data]
//
// Copia el CÓDIGO de MyKOS (server.py y módulos, static/, config/) a
// <home>/mykos-gateway-test/project-<tag>/ con data/ y workspace/ VACÍOS, para probar el backend real
// sin tocar conversaciones, memoria, permisos ni credenciales. Imprime la ruta creada.
//
// Con --with-data copia además, COMO COPIA, los cinco ficheros que migra la fase 2/2b (conversations.json, memory.json,
// memory_embeddings.json, permissions.json y approvals.json) y escribe <test>/originals-<tag>.json con su SHA-256 y sus recuentos, para comprobar después
// que la importación no perdió ni cambió nada. Los originales de data/ no se tocan nunca.
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const args = process.argv.slice(2);
const tag = args.find((a) => !a.startsWith("--"));
const withData = args.includes("--with-data");
if (!tag) throw new Error("falta <tag>");
const src = path.resolve(__dirname, "..", "..");
const testRoot = path.join(os.homedir(), "mykos-gateway-test");
const dst = path.join(testRoot, `project-${tag}`);
if (path.dirname(dst) !== testRoot) throw new Error("ruta de destino inesperada");

fs.rmSync(dst, { recursive: true, force: true });
fs.mkdirSync(dst, { recursive: true });
for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
  if (entry.isFile() && (entry.name.endsWith(".py") || entry.name === "requirements.txt")) fs.copyFileSync(path.join(src, entry.name), path.join(dst, entry.name));
}
fs.cpSync(path.join(src, "static"), path.join(dst, "static"), { recursive: true });
fs.cpSync(path.join(src, "config"), path.join(dst, "config"), { recursive: true });
fs.mkdirSync(path.join(dst, "data"), { recursive: true });
fs.mkdirSync(path.join(dst, "workspace"), { recursive: true });

if (withData) {
  const originals = {};
  const counters = {
    "conversations.json": (d) => d.conversations.length,
    "memory.json": (d) => d.entries.length,
    "memory_embeddings.json": (d) => Object.keys(d.entries).length,
    "permissions.json": (d) => d.grants.length + d.audit.length,
    "approvals.json": (d) => d.approvals.length,
  };
  for (const file of Object.keys(counters)) {
    const canonical = path.join(src, "data", file);
    // Tras activar la fase 2, conversaciones/memoria ya no tienen nombre canónico:
    // usa su copia .migrated-* más reciente para que las pruebas sigan trabajando
    // con una copia completa de los datos reales.
    let from = canonical;
    if (!fs.existsSync(from)) {
      const candidate = fs.readdirSync(path.dirname(canonical)).filter((name) => name.startsWith(`${file}.migrated-`)).sort().pop();
      if (candidate) from = path.join(path.dirname(canonical), candidate);
    }
    if (!fs.existsSync(from)) continue;
    const raw = fs.readFileSync(from);
    fs.writeFileSync(path.join(dst, "data", file), raw);
    const data = JSON.parse(raw.toString("utf8"));
    originals[file] = {
      sha256: crypto.createHash("sha256").update(raw).digest("hex"),
      bytes: raw.length,
      count: counters[file](data),
      ids: file === "conversations.json" ? data.conversations.map((c) => c.id) : file === "memory.json" ? data.entries.map((e) => e.id) : file === "memory_embeddings.json" ? Object.keys(data.entries) : [],
    };
  }
  fs.writeFileSync(path.join(testRoot, `originals-${tag}.json`), JSON.stringify(originals, null, 2));
}
console.log(dst);
