// Uso: node check-real-store.cjs
//
// Comprobación SOBRE EL GATEWAY REAL tras activar el almacén (mykos store on): la API de MyKOS devuelve las mismas
// conversaciones y recuerdos que había en la copia previa, la interfaz cargada en un navegador los muestra, y una
// conversación temporal se crea y se borra a través del almacén (sin dejar rastro salvo dos revisiones más).
// Lee de architecture-backup/2026-09-25-phase2/data (la copia previa) y no modifica nada más.
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

const PUB = 3210;
const repo = path.resolve(__dirname, "..", "..");
const storeDocsDir = path.join(os.homedir(), ".mykos", "gateway-state", "mykos", "docs");
const controlTokenFile = path.join(os.homedir(), ".mykos", "gateway-state", "mykos", "control.token");
const controlToken = fs.existsSync(controlTokenFile) ? fs.readFileSync(controlTokenFile, "utf8").trim() : "";
const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });
const info = (name, detail) => results.push({ name, ok: true, info: true, detail });

function request(method, p, payload) {
  return new Promise((resolve) => {
    const body = payload === undefined ? undefined : JSON.stringify(payload);
    const headers = { Origin: `http://127.0.0.1:${PUB}`, ...(controlToken ? { "X-MyKOS-Control-Token": controlToken } : {}), ...(body ? { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) } : {}) };
    const r = http.request({ host: "127.0.0.1", port: PUB, path: p, method, headers, agent: false, timeout: 30000 }, (res) => {
      const c = [];
      res.on("data", (d) => c.push(d));
      res.on("end", () => {
        let json = null;
        try {
          json = JSON.parse(Buffer.concat(c).toString("utf8"));
        } catch {}
        resolve({ status: res.statusCode, json });
      });
    });
    r.on("error", () => resolve({ status: "error", json: null }));
    r.on("timeout", () => {
      r.destroy();
      resolve({ status: "timeout", json: null });
    });
    r.end(body);
  });
}
const sameSet = (a, b) => a.length === b.length && new Set(a).size === a.length && a.every((x) => new Set(b).has(x));

(async () => {
  const stored = (name) => JSON.parse(fs.readFileSync(path.join(storeDocsDir, `${name}.json`), "utf8"));
  const origConv = stored("conversations").data.conversations || [];
  const origMem = stored("memory").data.entries || [];
  const origIdx = stored("memory-index").data.entries || {};

  const h = (await request("GET", "/mykos-health")).json;
  check("Gateway y backend en marcha y almacén activo sin avisos", h?.ok && h.backend?.up && h.store?.enabled && h.store.active && !h.warnings, `plugin ${h?.version}, revisiones ${JSON.stringify(h?.store?.docs?.filter((d) => d.exists).map((d) => `${d.name} r${d.revision}`))}`);
  const api = (await request("GET", "/api/health?gateway=1")).json;
  check("Python en modo gateway y alcanza el almacén", api?.store_mode === "gateway" && api.store_reachable === true, `store_mode=${api?.store_mode}`);

  const list = (await request("GET", "/api/conversations")).json?.conversations ?? [];
  check(`la API devuelve las ${origConv.length} conversaciones del almacén, mismos identificadores`, sameSet(list.map((c) => c.id), origConv.map((c) => c.id)), `${list.length} recibidas`);
  let identical = 0;
  for (const c of origConv) {
    const r = await request("GET", `/api/conversation?id=${c.id}`);
    const got = r.json?.conversation ?? r.json;
    const same = got && Array.isArray(got.messages) && got.messages.length === c.messages.length && got.messages.every((m, i) => m.role === c.messages[i].role && m.content === c.messages[i].content);
    if (same) identical += 1;
  }
  check(`las ${origConv.length} conversaciones se abren completas, con los mismos mensajes (rol y texto) que en el almacén`, identical === origConv.length, `${identical} de ${origConv.length}`);

  const mem = (await request("GET", "/api/memory")).json;
  check(`la memoria devuelve los ${origMem.length} recuerdos (${origMem.map((e) => e.id).join(", ")})`, mem?.count === origMem.length, `count=${mem?.count}`);
  const mg = (await request("GET", "/api/management")).json;
  check("/api/management: conversaciones guardadas en el Gateway y con el recuento correcto", mg?.files?.conversations?.storage === "gateway" && mg.counts?.conversations === origConv.length, JSON.stringify(mg?.files?.conversations));

  check("el índice de vectores conserva sus claves", sameSet(Object.keys(stored("memory-index").data.entries), Object.keys(origIdx)), `${Object.keys(origIdx).length} vectores`);

  // Escritura de prueba
  const before = (await request("GET", "/mykos-health")).json.store.docs.find((d) => d.name === "conversations").revision;
  const created = await request("POST", "/api/conversations/new", { title: "prueba de activación del almacén" });
  const id = created.json?.conversation?.id;
  const afterCreate = (await request("GET", "/api/conversations")).json?.conversations ?? [];
  const r1 = (await request("GET", "/mykos-health")).json.store.docs.find((d) => d.name === "conversations").revision;
  check("crear una conversación temporal: se guarda en el Gateway (una revisión más) y aparece una vez", created.status === 200 && id && afterCreate.filter((c) => c.id === id).length === 1 && r1 === before + 1 && !fs.existsSync(path.join(repo, "data", "conversations.json")), `revisión ${before}→${r1}`);
  const del = await request("DELETE", `/api/conversations?id=${id}`);
  const afterDel = (await request("GET", "/api/conversations")).json?.conversations ?? [];
  const r2 = (await request("GET", "/mykos-health")).json.store.docs.find((d) => d.name === "conversations").revision;
  check("borrarla: desaparece y las demás siguen ahí", del.status === 200 && sameSet(afterDel.map((c) => c.id), origConv.map((c) => c.id)) && r2 === r1 + 1, `revisión ${r1}→${r2}; ${afterDel.length} conversaciones`);

  // Interfaz real en un navegador (perfil aparte, sin cabeza): debe mostrar títulos de las conversaciones
  const edge = ["C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe", "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"].find((p) => fs.existsSync(p));
  if (edge) {
    const titles = origConv.map((c) => String(c.title || "")).filter((t) => t.length >= 4 && !/[<>&"'`]/.test(t));
    const profile = path.join(os.homedir(), "mykos-gateway-test", "edge-profile-real");
    const common = ["--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars", `--user-data-dir=${profile}`, "--window-size=1440,900", "--virtual-time-budget=12000"];
    let dom = "";
    try {
      dom = execFileSync(edge, [...common, "--dump-dom", `http://127.0.0.1:${PUB}/`], { encoding: "utf8", timeout: 120000, maxBuffer: 32 * 1024 * 1024, stdio: ["ignore", "pipe", "ignore"] });
    } catch (e) {
      dom = String(e.stdout || "");
    }
    const shown = titles.filter((t) => dom.includes(t));
    check("la interfaz real cargada en un navegador muestra los títulos de tus conversaciones", dom.length > 5000 && shown.length >= 1, `${shown.length} de ${titles.length} títulos visibles`);
  } else info("Edge no encontrado: se omite la vista en el navegador", "");
  finish();
})().catch((error) => {
  check("la comprobación terminó sin excepciones", false, String(error && error.stack ? error.stack : error));
  finish();
});

function finish() {
  const width = Math.min(150, Math.max(...results.map((r) => r.name.length)));
  let failures = 0;
  for (const r of results) {
    if (!r.ok) failures += 1;
    console.log(`${r.info ? "INFO " : r.ok ? "OK   " : "FALLA"}  ${r.name.padEnd(width)}  ${r.detail}`);
  }
  const counted = results.filter((r) => !r.info).length;
  console.log(failures ? `\n==> ${failures} de ${counted} comprobaciones FALLARON` : `\n==> ${counted}/${counted} comprobaciones correctas`);
  process.exit(failures ? 1 : 0);
}
