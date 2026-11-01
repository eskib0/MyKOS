// Uso: node corrupt-legacy.cjs <tag>
// Estropea (en la COPIA de prueba project-<tag>) el fichero data/conversations.json, como si se hubiera cortado la
// escritura, y guarda su SHA-256 en <test>/corrupt-<tag>.json para que la batería «corrupt» compruebe que no se tocó.
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const tag = process.argv[2];
if (!tag) throw new Error("falta <tag>");
const testRoot = path.join(os.homedir(), "mykos-gateway-test");
const file = path.join(testRoot, `project-${tag}`, "data", "conversations.json");
if (!fs.existsSync(file)) throw new Error(`no existe ${file}; ejecuta antes make-project.cjs ${tag} --with-data`);
const good = fs.readFileSync(file);
const broken = good.subarray(0, Math.floor(good.length * 0.6)); // cortado a mitad de la escritura
fs.writeFileSync(file, broken);
const sha256 = crypto.createHash("sha256").update(broken).digest("hex");
fs.writeFileSync(path.join(testRoot, `corrupt-${tag}.json`), JSON.stringify({ sha256, bytes: broken.length }, null, 2));
console.log(`conversations.json estropeado: ${good.length} → ${broken.length} B, sha256 ${sha256.slice(0, 12)}…`);
