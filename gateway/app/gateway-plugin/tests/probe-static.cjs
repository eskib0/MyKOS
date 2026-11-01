// Uso: node probe-static.cjs <puerto>
// Comprueba que el plugin sirve la interfaz MyKOS byte a byte y que no deja escapar ficheros fuera de static/.
// Usa http.request con la ruta cruda (fetch normalizaria los ".." y no probaria nada).
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");

const port = Number(process.argv[2] || 18795);
const repo = path.resolve(__dirname, "..", "..");
const S = (f) => fs.readFileSync(path.join(repo, "static", f));

function req(method, rawPath, body) {
  return new Promise((resolve) => {
    const headers = body ? { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) } : {};
    const r = http.request({ host: "127.0.0.1", port, method, path: rawPath, headers, timeout: 8000 }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
    });
    r.on("timeout", () => { r.destroy(); resolve({ status: "timeout", headers: {}, body: Buffer.alloc(0) }); });
    r.on("error", (e) => resolve({ status: "error:" + e.code, headers: {}, body: Buffer.alloc(0) }));
    r.end(body);
  });
}

const results = [];
function check(name, ok, detail) { results.push({ name, ok, detail }); }

(async () => {
  // 1. Contenido servido = ficheros del repositorio
  for (const [p, f, ct] of [
    ["/", "index.html", "text/html"],
    ["/static/app.js?v=20260925-44", "app.js", "text/javascript"],
    ["/static/styles.css?v=20260924-39", "styles.css", "text/css"],
    ["/static/logo-mykos.jpg?v=20260924-1", "logo-mykos.jpg", "image/jpeg"],
  ]) {
    const r = await req("GET", p);
    const same = r.status === 200 && Buffer.compare(r.body, S(f)) === 0;
    check(`GET ${p}`, same && String(r.headers["content-type"]).startsWith(ct) && r.headers["cache-control"] === "no-store",
      `HTTP ${r.status} ${r.headers["content-type"]} ${r.body.length} B ${same ? "== fichero" : "DISTINTO"}`);
  }
  // 2. HEAD
  const h = await req("HEAD", "/static/app.js");
  check("HEAD /static/app.js", h.status === 200 && Number(h.headers["content-length"]) === S("app.js").length && h.body.length === 0,
    `HTTP ${h.status} content-length=${h.headers["content-length"]} cuerpo=${h.body.length} B`);
  // 3. Ficheros que NO se pueden servir
  const secret = fs.readFileSync(path.join(repo, "server.py")).subarray(0, 40);
  for (const bad of [
    "/static/../server.py",
    "/static/%2e%2e/server.py",
    "/static/..%5cserver.py",
    "/static/%2e%2e%2f%2e%2e%2fdata%2fmemory.json",
    "/static/../data/memory.json",
    "/static/app.js:stream",
    "/static/.gitkeep",
    "/static/%00",
  ]) {
    const r = await req("GET", bad);
    const leaked = r.status === 200 && r.body.length > 0;
    check(`BLOQUEA ${bad}`, !leaked && r.status !== "timeout", `HTTP ${r.status} ${r.body.length} B`);
  }
  const nf = await req("GET", "/static/no-existe.js");
  check("404 en fichero inexistente", nf.status === 404, `HTTP ${nf.status}`);
  const post = await req("POST", "/");
  check("POST / -> 405", post.status === 405, `HTTP ${post.status}`);
  // 4. Rutas del propio Gateway intactas (no las tapa el plugin)
  for (const p of ["/health", "/v1/models", "/mykos-health"]) {
    const r = await req("GET", p);
    check(`Gateway ${p}`, r.status === 200, `HTTP ${r.status}`);
  }
  // 4b. La ruta que usa MyKOS hoy para el chat sigue existiendo (cuerpo vacio => error de validacion 4xx del Gateway, no 404 del plugin)
  const cc = await req("POST", "/v1/chat/completions", "{}");
  check("Gateway POST /v1/chat/completions existe", typeof cc.status === "number" && cc.status >= 400 && cc.status < 500 && cc.status !== 404 && cc.status !== 405,
    "HTTP " + cc.status + " " + cc.body.toString("utf8").slice(0, 90).replace(/\s+/g, " "));

  // 5. Cabeceras de seguridad que el Gateway pone a "/" (una CSP o Permissions-Policy estrictas romperian la UI o el microfono)
  const top = await req("GET", "/");
  const sec = ["content-security-policy", "permissions-policy", "x-frame-options", "referrer-policy", "cross-origin-opener-policy", "cross-origin-embedder-policy", "cross-origin-resource-policy"];
  console.log("\nCabeceras de GET / :");
  for (const h of sec) console.log(`  ${h.padEnd(30)} ${top.headers[h] ?? "(no presente)"}`);
  const html = S("index.html").toString("utf8");
  const inlineScripts = (html.match(/<script(?![^>]*\bsrc=)[^>]*>/gi) || []).length;
  const inlineHandlers = (html.match(/\son[a-z]+\s*=/gi) || []).length;
  const inlineStyles = (html.match(/<style[\s>]/gi) || []).length + (html.match(/\sstyle\s*=/gi) || []).length;
  console.log(`index.html: <script> inline=${inlineScripts}, atributos on*=${inlineHandlers}, estilos inline=${inlineStyles}\n`);

  const w = Math.max(...results.map((r) => r.name.length));
  let fail = 0;
  for (const r of results) { if (!r.ok) fail++; console.log(`${r.ok ? "OK   " : "FALLA"}  ${r.name.padEnd(w)}  ${r.detail}`); }
  console.log(fail ? `\n==> ${fail} comprobaciones FALLARON` : `\n==> ${results.length}/${results.length} comprobaciones correctas`);
  process.exit(fail ? 1 : 0);
})();
