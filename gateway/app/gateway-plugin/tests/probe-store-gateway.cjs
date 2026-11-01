// Uso: node probe-store-gateway.cjs <puertoGateway>
//
// Prueba de integración de las fases 2/2b (el Gateway es dueño de conversaciones, memoria, permisos, auditoría y aprobaciones) contra un Gateway
// DESECHABLE (puerto 18795) con el backend Python REAL y una COPIA de tus datos reales (make-project.cjs <tag> --with-data).
// Variables de entorno:
//   PHASE         import  | restart | corrupt        (qué batería se ejecuta; ver más abajo)
//   TAG           etiqueta de la prueba (S para import/restart, C para corrupt)
//   BACKEND_PORT  puerto interno del backend (3299)
//   PROJECT_DIR   copia del proyecto (make-project.cjs)
//   PYTHON_EXE    intérprete de Python
//
//   import   Estado limpio: el plugin importa los cinco ficheros de data/, y se prueba todo lo demás (seguridad del
//            token, API real, cliente Python, altas en paralelo, caída del backend, vista en un navegador).
//   restart  Mismo estado y mismo proyecto tras reiniciar el Gateway: nada se reimporta ni se pierde; copias,
//            instantáneas, diario, recuperación de un documento dañado.
//   corrupt  Estado limpio pero con conversations.json ESTROPEADO: el almacén no se activa, no se toca ningún fichero
//            y MyKOS sigue funcionando con sus ficheros (modo file).
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");
const { execFileSync } = require("child_process");

const gw = Number(process.argv[2] || 18795);
const phase = process.env.PHASE || "import";
const tag = process.env.TAG || "S";
const be = Number(process.env.BACKEND_PORT || 3299);
const project = process.env.PROJECT_DIR;
const python = process.env.PYTHON_EXE || "python3";
if (!project) throw new Error("falta la variable PROJECT_DIR");

const testRoot = path.join(os.homedir(), "mykos-gateway-test");
const stateDir = path.join(testRoot, `state-${tag}`);
const mykosDir = path.join(stateDir, "mykos");
const dataDir = path.join(project, "data");
const checker = path.join(__dirname, "store_client_check.py");
const snapshotFile = path.join(testRoot, `phase-import-${tag}.json`);
const originals = JSON.parse(fs.readFileSync(path.join(testRoot, `originals-${tag}.json`), "utf8"));
const FILES = { conversations: "conversations.json", memory: "memory.json", "memory-index": "memory_embeddings.json", permissions: "permissions.json", approvals: "approvals.json" };

const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });
const info = (name, detail) => results.push({ name, ok: true, info: true, detail });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sha256 = (buf) => crypto.createHash("sha256").update(buf).digest("hex");
const shaFile = (file) => sha256(fs.readFileSync(file));
const shaJson = (value) => sha256(Buffer.from(JSON.stringify(value)));
const sameSet = (a, b) => a.length === b.length && new Set(a).size === a.length && a.every((x) => new Set(b).has(x));

function request({ method = "GET", path: p, headers = {}, body, port = gw, host, timeoutMs = 60000 }) {
  return new Promise((resolve) => {
    const h = {};
    for (const [k, v] of Object.entries(headers)) h[k.toLowerCase()] = v;
    if (host !== undefined) h.host = host;
    if (body !== undefined && h["content-length"] === undefined) h["content-length"] = Buffer.byteLength(body);
    const chunks = [];
    const t0 = Date.now();
    const fail = (why) => resolve({ status: why, headers: {}, body: Buffer.concat(chunks), ms: Date.now() - t0 });
    const r = http.request({ host: "127.0.0.1", port, method, path: p, headers: h, agent: false }, (res) => {
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks), ms: Date.now() - t0 }));
      res.on("error", (e) => fail("error:" + (e.code || e.message)));
    });
    r.setTimeout(timeoutMs, () => {
      r.destroy();
      fail("timeout");
    });
    r.on("error", (e) => fail("error:" + (e.code || e.message)));
    r.end(body);
  });
}
const asJson = (r) => {
  try {
    return JSON.parse(r.body.toString("utf8"));
  } catch {
    return null;
  }
};
const alive = (pid) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === "EPERM";
  }
};
async function waitFor(fn, ms, step = 250) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const v = await fn();
    if (v) return v;
    await sleep(step);
  }
  return null;
}
const health = async () => {
  const r = await request({ path: "/mykos-health", timeoutMs: 8000 });
  return { status: r.status, json: asJson(r) };
};
const origin = { Origin: `http://127.0.0.1:${gw}` };
const jsonHeaders = { "Content-Type": "application/json", ...origin };
const api = (method, p, payload) => request({ method, path: p, headers: jsonHeaders, ...(payload !== undefined ? { body: JSON.stringify(payload) } : {}) });
const readToken = () => fs.readFileSync(path.join(mykosDir, ".token"), "utf8").trim();
const storeReq = (opts) => request({ ...opts, headers: { "X-MyKOS-Store-Token": readToken(), ...(opts.headers || {}) } });
const getDoc = async (name) => asJson(await storeReq({ path: `/mykos-store/${name}` }));
const listConversations = async () => asJson(await request({ path: "/api/conversations" }))?.conversations ?? [];
const memoryCount = async () => asJson(await request({ path: "/api/memory" }))?.count;
const journalLines = () => {
  const file = path.join(mykosDir, "journal.jsonl");
  if (!fs.existsSync(file)) return [];
  return fs
    .readFileSync(file, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((l) => {
      try {
        return JSON.parse(l);
      } catch {
        return { broken: l };
      }
    });
};
const migratedOf = (file) => (fs.existsSync(dataDir) ? fs.readdirSync(dataDir).filter((f) => f.startsWith(`${file}.migrated-`)) : []);
const countFiles = (dir) => (fs.existsSync(dir) ? fs.readdirSync(dir).length : 0);

function runPython(action, extraEnv = {}) {
  const env = { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8", MYKOS_STORE_MODE: "gateway", MYKOS_STORE_URL: `http://127.0.0.1:${gw}`, MYKOS_STORE_TOKEN: readToken(), MYKOS_STORE_RETRY_SCALE: "0.01", ...extraEnv };
  try {
    const out = execFileSync(python, [checker, action], { cwd: project, env, encoding: "utf8", timeout: 150000, stdio: ["ignore", "pipe", "pipe"] });
    const line = out.trim().split("\n").filter(Boolean).pop() ?? "";
    return { ok: true, json: JSON.parse(line), raw: out };
  } catch (e) {
    return { ok: false, error: String(e.message).slice(0, 300), raw: String(e.stdout || "") + String(e.stderr || "") };
  }
}

function pythonEnv(pid) {
  const out = execFileSync(python, ["-c", "import psutil,json,sys;e=psutil.Process(int(sys.argv[1])).environ();print(json.dumps({k.upper():v for k,v in e.items() if k.upper().startswith('MYKOS_')}))", String(pid)], { encoding: "utf8", timeout: 20000 });
  return JSON.parse(out);
}

// ───────────────────────────────────────────────────────────────────────── import
async function phaseImport() {
  const up = await waitFor(async () => {
    const h = await health();
    return h.status === 200 && h.json?.backend?.up && h.json.backend.phase === "up" && h.json.store?.active ? h.json : null;
  }, 150000);
  if (!up) {
    const h = await health();
    check("el Gateway arrancó con el almacén activo y el backend «up»", false, JSON.stringify(h.json).slice(0, 700));
    return;
  }
  check("el Gateway arrancó con el almacén activo y el backend «up»", true, `Gateway PID ${up.pid}, backend PID ${up.backend.pid}, plugin ${up.version}`);
  const st = up.store;
  check("el plugin cargó store.js desde su copia temporal (almacén habilitado, sin error ni avisos)", st.enabled && st.active && !st.error && !up.warnings, `dir=${st.dir}`);
  const docs = Object.fromEntries(st.docs.map((d) => [d.name, d]));

  // 1. Importación: recuentos, SHA-256 de los originales, originales apartados
  for (const [doc, file] of Object.entries(FILES)) {
    const want = originals[file];
    const imp = st.imports.find((i) => i.name === doc);
    check(`importación de «${doc}»: estado «imported» y ${want.count} elementos`, imp?.status === "imported" && imp.count === want.count, JSON.stringify(imp));
    check(`«${doc}» en el almacén: revisión 1 y ${want.count} elementos`, docs[doc]?.exists && docs[doc].revision === 1 && docs[doc].count === want.count, JSON.stringify(docs[doc]));
    const moved = migratedOf(file);
    check(`original ${file}: apartado como .migrated-* con el MISMO SHA-256 y ya no está en data/`, !fs.existsSync(path.join(dataDir, file)) && moved.length === 1 && shaFile(path.join(dataDir, moved[0])) === want.sha256, `${moved.join(",") || "sin apartar"}`);
    const stored = await getDoc(doc);
    const legacyData = moved.length ? JSON.parse(fs.readFileSync(path.join(dataDir, moved[0]), "utf8")) : null;
    check(`contenido de «${doc}» en el almacén idéntico al original (${want.count} elementos)`, stored?.data && legacyData && JSON.stringify(stored.data) === JSON.stringify(legacyData), `revisión ${stored?.revision}`);
  }

  // 2. Seguridad de la API interna
  {
    const token = readToken();
    check("el token existe (≥ 32 caracteres) y el fichero no está en el almacén de documentos", token.length >= 32 && !fs.existsSync(path.join(mykosDir, "docs", ".token")), `${token.length} caracteres`);
    const noTok = await request({ path: "/mykos-store/" });
    check("sin token: 401", noTok.status === 401, `HTTP ${noTok.status}`);
    const badTok = await request({ path: "/mykos-store/", headers: { "X-MyKOS-Store-Token": "x".repeat(token.length) } });
    const shortTok = await request({ path: "/mykos-store/", headers: { "X-MyKOS-Store-Token": "abc" } });
    check("token equivocado (misma longitud y otra longitud): 401", badTok.status === 401 && shortTok.status === 401, `HTTP ${badTok.status}/${shortTok.status}`);
    const withOrigin = await storeReq({ path: "/mykos-store/", headers: { Origin: "http://evil.example" } });
    const withOwnOrigin = await storeReq({ path: "/mykos-store/", headers: origin });
    check("con token pero desde un navegador (cabecera Origin, ajena o propia): 403", withOrigin.status === 403 && withOwnOrigin.status === 403, `HTTP ${withOrigin.status}/${withOwnOrigin.status}`);
    const badHost = await storeReq({ path: "/mykos-store/", host: "evil.example" });
    check("con token pero con Host ajeno (DNS rebinding): 403", badHost.status === 403, `HTTP ${badHost.status}`);
    const ok = await storeReq({ path: "/mykos-store/" });
    check("con token, Host propio y sin Origin: 200 y lista de documentos", ok.status === 200 && Array.isArray(asJson(ok)?.docs) && asJson(ok).docs.length === 5, `HTTP ${ok.status}`);
    const unknown = await storeReq({ path: "/mykos-store/secreto" });
    const traversal = await storeReq({ path: "/mykos-store/..%2F..%2F.token" });
    const traversal2 = await storeReq({ path: "/mykos-store/%2e%2e/.token" });
    check("documento desconocido y rutas con «..»: error 4xx y nunca devuelven el token", [unknown, traversal, traversal2].every((r) => typeof r.status === "number" && r.status >= 400 && r.status < 500 && !r.body.toString("utf8").includes(token)), `HTTP ${unknown.status}/${traversal.status}/${traversal2.status}`);
    const del = await storeReq({ method: "DELETE", path: "/mykos-store/conversations" });
    const post = await storeReq({ method: "POST", path: "/mykos-store/conversations", body: "{}" });
    check("DELETE y POST sobre un documento: 405 (no se pueden borrar documentos por la API)", del.status === 405 && post.status === 405, `HTTP ${del.status}/${post.status}`);
    const before = await getDoc("conversations");
    const badJson = await storeReq({ method: "PUT", path: "/mykos-store/conversations", body: "{no es json", headers: { "Content-Type": "application/json" } });
    const noData = await storeReq({ method: "PUT", path: "/mykos-store/conversations", body: JSON.stringify({ expectedRevision: 1 }), headers: { "Content-Type": "application/json" } });
    const badShape = await storeReq({ method: "PUT", path: "/mykos-store/conversations", body: JSON.stringify({ data: { conversations: "no soy una lista" } }), headers: { "Content-Type": "application/json" } });
    const shrink = await storeReq({ method: "PUT", path: "/mykos-store/conversations", body: JSON.stringify({ data: { conversations: before.data.conversations.slice(0, 1) } }), headers: { "Content-Type": "application/json" } });
    const after = await getDoc("conversations");
    check("PUT con JSON roto, sin «data», con estructura inválida o con un borrado masivo: 4xx y el documento no cambia", [badJson, noData, badShape, shrink].every((r) => r.status >= 400 && r.status < 500) && after.revision === before.revision && JSON.stringify(after.data) === JSON.stringify(before.data), `HTTP ${badJson.status}/${noData.status}/${badShape.status}/${shrink.status}; revisión ${before.revision}→${after.revision}; borrado masivo: ${asJson(shrink)?.error}`);
    const leaks = [];
    for (const p of ["/mykos-health", "/api/health?gateway=1", "/api/management", "/api/status"]) {
      const r = await request({ path: p });
      if (r.body.toString("utf8").includes(token)) leaks.push(p);
    }
    check("el token no aparece en /mykos-health, /api/health, /api/management ni /api/status", leaks.length === 0, leaks.join(",") || "ninguno");
  }

  // 3. API real de MyKOS a través del Gateway, ya sobre el almacén
  const baseConversations = await listConversations();
  {
    check(`GET /api/conversations: ${originals["conversations.json"].count} conversaciones y los mismos identificadores`, sameSet(baseConversations.map((c) => c.id), originals["conversations.json"].ids), `${baseConversations.length} recibidas`);
    const mem = asJson(await request({ path: "/api/memory" }));
    check(`GET /api/memory: ${originals["memory.json"].count} recuerdos`, mem?.count === originals["memory.json"].count, `count=${mem?.count}`);
    const h = asJson(await request({ path: "/api/health?gateway=1" }));
    check("Python informa de modo «gateway» y alcanza el almacén", h?.store_mode === "gateway" && h.store_reachable === true && h.store_docs?.conversations?.revision >= 1, `store_mode=${h?.store_mode} reachable=${h?.store_reachable}`);
    const mg = asJson(await request({ path: "/api/management" }));
    check("/api/management muestra las conversaciones como guardadas en el Gateway, con su recuento", mg?.files?.conversations?.storage === "gateway" && mg.counts?.conversations === originals["conversations.json"].count, JSON.stringify(mg?.files?.conversations));
    const security = {
      permissions: asJson(await storeReq({ path: "/mykos-store/permissions" })),
      approvals: asJson(await storeReq({ path: "/mykos-store/approvals" })),
    };
    check("permisos, auditoría y aprobaciones se leen desde documentos del Gateway", security.permissions?.data?.grants?.length === JSON.parse(fs.readFileSync(path.join(dataDir, migratedOf("permissions.json")[0]), "utf8")).grants.length && Array.isArray(security.permissions?.data?.audit) && Array.isArray(security.approvals?.data?.approvals), "documentos de seguridad incompletos");
    const approvalApi = asJson(await request({ path: "/api/approvals" }));
    check("la API de aprobaciones responde usando el documento del Gateway", approvalApi && Array.isArray(approvalApi.approvals), JSON.stringify(approvalApi));
  }

  // 4. Alta y baja de una conversación: una revisión por operación y sin recrear el fichero antiguo
  {
    const r0 = (await getDoc("conversations")).revision;
    const created = await api("POST", "/api/conversations/new", { title: "prueba del almacén" });
    const id = asJson(created)?.conversation?.id;
    const r1 = (await getDoc("conversations")).revision;
    const afterCreate = await listConversations();
    check("crear una conversación: aparece exactamente una vez y la revisión sube 1", created.status === 200 && id && afterCreate.filter((c) => c.id === id).length === 1 && afterCreate.length === baseConversations.length + 1 && r1 === r0 + 1, `HTTP ${created.status}; revisión ${r0}→${r1}; total ${afterCreate.length}`);
    check("data/conversations.json NO se ha vuelto a crear", !fs.existsSync(path.join(dataDir, "conversations.json")), "");
    const deleted = await api("DELETE", `/api/conversations?id=${id}`);
    const r2 = (await getDoc("conversations")).revision;
    const afterDelete = await listConversations();
    check("borrar esa conversación: desaparece y la revisión sube 1", deleted.status === 200 && afterDelete.length === baseConversations.length && !afterDelete.some((c) => c.id === id) && r2 === r1 + 1, `HTTP ${deleted.status}; revisión ${r1}→${r2}`);
  }

  // 5. Cargadores REALES de Python (memoria, índice, conversaciones) contra el almacén
  // 5. Compactación manual: Gateway resume el documento, sin pedir modelo ni entrar en Python.
  {
    const created = await api("POST", "/api/conversations/new", {});
    const id = asJson(created)?.conversation?.id;
    const before = await getDoc("conversations");
    const conversation = before?.data?.conversations?.find((item) => item.id === id);
    if (conversation) {
      const now = new Date().toISOString();
      conversation.messages = Array.from({ length: 11 }, (_, index) => ({
        message_id: `compact-${index}`,
        role: index % 2 ? "assistant" : "user",
        content: `mensaje de prueba ${index}`,
        created_at: now,
      }));
      conversation.updated_at = now;
    }
    const seeded = await storeReq({ method: "PUT", path: "/mykos-store/conversations", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expectedRevision: before?.revision, data: before?.data }) });
    const compact = await api("POST", "/api/conversations/compact", { conversation_id: id });
    const opened = await request({ path: `/api/conversation?id=${id}` });
    const compacted = asJson(opened)?.conversation;
    const info = asJson(compact);
    check("compactar una conversación larga: Gateway conserva 10 mensajes y guarda el resumen", created.status === 200 && seeded.status === 200 && compact.status === 200 && info?.compacted === true && info?.omitted_messages === 1 && compacted?.messages?.length === 11 && String(compacted?.context_summary || "").includes("mensaje de prueba 0"), `HTTP ${created.status}/${seeded.status}/${compact.status}; omitidos=${info?.omitted_messages}`);
    const compactAgain = await api("POST", "/api/conversations/compact", { conversation_id: id });
    check("compactar de nuevo conserva el contrato y el historial", compactAgain.status === 200 && asJson(compactAgain)?.compacted === true && (await request({ path: `/api/conversation?id=${id}` })).status === 200, `HTTP ${compactAgain.status}`);
    const deleted = await api("DELETE", `/api/conversations?id=${id}`);
    check("la conversación temporal de compactación se borra al terminar", deleted.status === 200 && !(await listConversations()).some((item) => item.id === id), `HTTP ${deleted.status}`);
  }

  // 6. Cargadores REALES de Python (memoria, índice, conversaciones) contra el almacén
  {
    const memBefore = await getDoc("memory");
    const idxBefore = await getDoc("memory-index");
    const rt = runPython("memory-roundtrip");
    const j = rt.json;
    check("cliente Python en modo gateway: escribe y relee memoria e índice (con ñ, acentos y emoji)", rt.ok && j?.mode === "gateway" && j.memory_after === j.memory_before + 1 && j.memory_text_ok && j.index_after === j.index_before + 1 && j.index_vector_ok, rt.ok ? JSON.stringify(j) : rt.error + " " + rt.raw.slice(-300));
    const memAfter = await getDoc("memory");
    const idxAfter = await getDoc("memory-index");
    check("el almacén refleja esas escrituras: revisión +1 en «memory» y en «memory-index»", memAfter?.revision === memBefore.revision + 1 && idxAfter?.revision === idxBefore.revision + 1 && memAfter.data.entries.some((e) => e.id === "prueba-almacen"), `memory r${memBefore.revision}→${memAfter?.revision}; índice r${idxBefore.revision}→${idxAfter?.revision}`);
    check("el backend en marcha ve el cambio hecho por otro proceso (/api/memory)", (await memoryCount()) === originals["memory.json"].count + 1, `count=${await memoryCount()}`);
    const journal = journalLines();
    check("el diario anota quién escribió (tools.memory y embedding_memory) con SHA-256", journal.some((e) => e.source === "tools.memory" && e.sha256) && journal.some((e) => e.source === "embedding_memory" && e.sha256), `${journal.length} anotaciones`);

    const shrink = runPython("shrink");
    check("un borrado masivo por error desde Python lo rechaza el almacén y nada cambia", shrink.ok && shrink.json.raised === "StoreRejected" && shrink.json.after === shrink.json.before, shrink.ok ? JSON.stringify(shrink.json) : shrink.error);

    const dead = runPython("unavailable", { MYKOS_STORE_URL: "http://127.0.0.1:1" });
    const dj = dead.json;
    check("con el Gateway inaccesible, Python falla EN VOZ ALTA (nunca devuelve datos vacíos que luego se guardarían)", dead.ok && dj.conversations?.raised && dj.memory?.raised && dj.index?.raised && dj.save?.raised, dead.ok ? JSON.stringify(dj) : dead.error);
  }

  // 6. Conflicto de revisión: gana la última escritura, pero queda anotado
  {
    const idx = await getDoc("memory-index");
    const stale = await storeReq({ method: "PUT", path: "/mykos-store/memory-index", body: JSON.stringify({ data: idx.data, expectedRevision: idx.revision - 1, source: "probe-conflict" }), headers: { "Content-Type": "application/json" } });
    const sj = asJson(stale);
    check("escribir con una revisión anticuada: se guarda, pero con conflict=true y anotado en el diario", stale.status === 200 && sj?.conflict === true && sj.revision === idx.revision + 1 && journalLines().some((e) => e.source === "probe-conflict" && e.conflict === true), `HTTP ${stale.status} ${JSON.stringify(sj)}`);
  }

  // 7. Altas y bajas en paralelo: ni se pierde ni se duplica nada
  {
    const r0 = (await getDoc("conversations")).revision;
    const N = 30;
    const t0 = Date.now();
    const creates = await Promise.all(Array.from({ length: N }, (_, i) => api("POST", "/api/conversations/new", { title: `paralela ${i}` })));
    const ids = creates.map((r) => asJson(r)?.conversation?.id);
    const listed = await listConversations();
    check(`${N} altas simultáneas: todas 200, identificadores únicos y ${baseConversations.length + N} conversaciones en total`, creates.every((r) => r.status === 200) && new Set(ids).size === N && listed.length === baseConversations.length + N, `estados ${[...new Set(creates.map((r) => r.status))].join(",")}; total ${listed.length}; ${Date.now() - t0} ms`);
    const deletes = await Promise.all(ids.map((id) => api("DELETE", `/api/conversations?id=${id}`)));
    const after = await listConversations();
    const r1 = (await getDoc("conversations")).revision;
    check(`${N} bajas simultáneas: vuelven exactamente las ${baseConversations.length} originales y la revisión avanzó ${2 * N}`, deletes.every((r) => r.status === 200) && sameSet(after.map((c) => c.id), originals["conversations.json"].ids) && r1 === r0 + 2 * N, `estados ${[...new Set(deletes.map((r) => r.status))].join(",")}; total ${after.length}; revisión ${r0}→${r1}`);
  }

  // 8. La interfaz en un navegador (Edge sin cabeza) muestra las conversaciones que vienen del almacén
  {
    const edge = ["C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe", "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"].find((p) => fs.existsSync(p));
    if (edge) {
      const conv = JSON.parse(fs.readFileSync(path.join(dataDir, migratedOf(FILES.conversations)[0]), "utf8")).conversations;
      const titles = conv.map((c) => String(c.title || "")).filter((t) => t.length >= 4 && !/[<>&"'`]/.test(t));
      const common = ["--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars", `--user-data-dir=${path.join(testRoot, "edge-profile")}`, "--window-size=1440,900", "--virtual-time-budget=12000"];
      let dom = "";
      try {
        dom = execFileSync(edge, [...common, "--dump-dom", `http://127.0.0.1:${gw}/`], { encoding: "utf8", timeout: 120000, maxBuffer: 32 * 1024 * 1024, stdio: ["ignore", "pipe", "ignore"] });
      } catch (e) {
        dom = String(e.stdout || "");
      }
      const shown = titles.filter((t) => dom.includes(t));
      check("la interfaz cargada en un navegador muestra títulos de tus conversaciones importadas", dom.length > 5000 && shown.length >= 1, `${shown.length} de ${titles.length} títulos visibles en un DOM de ${dom.length} caracteres`);
    } else {
      info("Edge no encontrado: se omite la vista en el navegador", "");
    }
  }

  // 9. Caída del backend: el plugin lo relanza con el mismo almacén y el mismo token; los datos siguen
  {
    const before = (await health()).json;
    const oldPid = before.backend.pid;
    const revs = Object.fromEntries((await getDocsList()).map((d) => [d.name, d.revision]));
    process.kill(oldPid);
    const back = await waitFor(async () => {
      const h = await health();
      return h.status === 200 && h.json?.backend?.up && h.json.backend.pid !== oldPid ? h.json : null;
    }, 90000, 500);
    check("tras caer Python, el plugin lo relanza con otro PID", back, back ? `PID ${oldPid} → ${back.backend.pid}` : "no se recuperó en 90 s");
    if (back) {
      const env = pythonEnv(back.backend.pid);
      check("el backend relanzado recibe el modo gateway, la URL y el MISMO token", env.MYKOS_STORE_MODE === "gateway" && env.MYKOS_STORE_URL === `http://127.0.0.1:${gw}` && env.MYKOS_STORE_TOKEN === readToken(), `modo=${env.MYKOS_STORE_MODE} url=${env.MYKOS_STORE_URL} token=${env.MYKOS_STORE_TOKEN === readToken() ? "igual" : "distinto"}`);
      const list = await listConversations();
      const after = Object.fromEntries((await getDocsList()).map((d) => [d.name, d.revision]));
      check("los datos siguen ahí tras el reinicio del backend (mismas conversaciones, revisiones sin cambios)", sameSet(list.map((c) => c.id), originals["conversations.json"].ids) && JSON.stringify(revs) === JSON.stringify(after), `revisiones ${JSON.stringify(after)}`);
      const created = await api("POST", "/api/conversations/new", { title: "tras el reinicio" });
      const id = asJson(created)?.conversation?.id;
      const del = await api("DELETE", `/api/conversations?id=${id}`);
      check("el backend relanzado sigue pudiendo escribir (alta y baja)", created.status === 200 && del.status === 200, `HTTP ${created.status}/${del.status}`);
    }
  }

  // 10. Foto del estado final para la batería «restart»
  {
    const docsNow = await getDocsList();
    const snapshot = { token: sha256(Buffer.from(readToken())), docs: {} };
    for (const d of docsNow) {
      const doc = await getDoc(d.name);
      snapshot.docs[d.name] = { revision: doc.revision, count: d.count, bytes: d.bytes, dataSha: shaJson(doc.data) };
    }
    fs.writeFileSync(snapshotFile, JSON.stringify(snapshot, null, 2));
    info("estado final guardado para la segunda batería", JSON.stringify(Object.fromEntries(Object.entries(snapshot.docs).map(([k, v]) => [k, `r${v.revision}/${v.count}`]))));
  }
}

async function getDocsList() {
  return asJson(await storeReq({ path: "/mykos-store/" }))?.docs ?? [];
}

// ───────────────────────────────────────────────────────────────────────── restart
async function phaseRestart() {
  if (!fs.existsSync(snapshotFile)) {
    check("existe el estado de la primera batería", false, snapshotFile);
    return;
  }
  const snap = JSON.parse(fs.readFileSync(snapshotFile, "utf8"));
  const up = await waitFor(async () => {
    const h = await health();
    return h.status === 200 && h.json?.backend?.up && h.json.backend.phase === "up" && h.json.store?.active ? h.json : null;
  }, 150000);
  if (!up) {
    check("el Gateway rearrancó con el almacén activo y el backend «up»", false, JSON.stringify((await health()).json).slice(0, 700));
    return;
  }
  check("el Gateway rearrancó con el almacén activo y el backend «up»", true, `Gateway PID ${up.pid}, backend PID ${up.backend.pid}`);
  const st = up.store;
  check("ningún documento se reimporta: los cinco «store-exists»", st.imports.length === 5 && st.imports.every((i) => i.status === "store-exists"), JSON.stringify(st.imports.map((i) => `${i.name}:${i.status}`)));
  for (const [doc, file] of Object.entries(FILES)) {
    check(`${file}: sigue habiendo un solo .migrated-* y no ha reaparecido el original`, migratedOf(file).length === 1 && !fs.existsSync(path.join(dataDir, file)), migratedOf(file).join(","));
  }
  for (const [name, want] of Object.entries(snap.docs)) {
    const doc = await getDoc(name);
    check(`«${name}» idéntico tras reiniciar: revisión ${want.revision}, ${want.count} elementos y mismo contenido`, doc?.revision === want.revision && shaJson(doc.data) === want.dataSha && st.docs.find((d) => d.name === name)?.count === want.count, `revisión ${doc?.revision}`);
  }
  check("el token se conserva entre reinicios", sha256(Buffer.from(readToken())) === snap.token, "");
  const j = journalLines();
  check("diario: cinco importaciones (una por documento), ninguna importación fallida, ninguna línea rota", j.filter((e) => e.event === "imported").length === 5 && !j.some((e) => e.event === "import-failed" || e.broken), `${j.length} anotaciones`);
  const convBackups = countFiles(path.join(mykosDir, "backups", "conversations"));
  check("copias de cada revisión: las últimas 40 de «conversations» (con más de 60 escrituras, poda correcta)", convBackups === 40, `${convBackups} ficheros`);
  const snapDirs = fs.existsSync(path.join(mykosDir, "snapshots")) ? fs.readdirSync(path.join(mykosDir, "snapshots")) : [];
  check("instantánea diaria creada (snapshots/AAAAMMDD con los documentos)", snapDirs.length >= 1 && countFiles(path.join(mykosDir, "snapshots", snapDirs[0])) >= 1, snapDirs.join(","));
  const list = await listConversations();
  check("API tras el reinicio: mismas conversaciones que al final de la primera batería", sameSet(list.map((c) => c.id), originals["conversations.json"].ids) && (await memoryCount()) === originals["memory.json"].count + 1, `${list.length} conversaciones, ${await memoryCount()} recuerdos`);
  const h = asJson(await request({ path: "/api/health?gateway=1" }));
  check("Python en modo gateway y sin duplicar el fichero antiguo", h?.store_mode === "gateway" && h.store_reachable === true, `store_mode=${h?.store_mode}`);
  const created = await api("POST", "/api/conversations/new", { title: "tras reiniciar el Gateway" });
  const id = asJson(created)?.conversation?.id;
  const afterCreate = await getDoc("conversations");
  const del = await api("DELETE", `/api/conversations?id=${id}`);
  const afterDelete = await getDoc("conversations");
  check("escribir tras reiniciar: la numeración de revisiones continúa (sin repetir ni saltar)", created.status === 200 && del.status === 200 && afterCreate.revision === snap.docs.conversations.revision + 1 && afterDelete.revision === snap.docs.conversations.revision + 2, `r${snap.docs.conversations.revision}→${afterCreate.revision}→${afterDelete.revision}`);

  // Recuperación: un documento dañado en disco (corte de luz, disco) se restaura desde la última copia válida
  for (const name of ["memory", "memory-index"]) {
    const file = path.join(mykosDir, "docs", `${name}.json`);
    const good = fs.readFileSync(file);
    fs.writeFileSync(file, name === "memory" ? good.subarray(0, Math.floor(good.length / 2)) : Buffer.alloc(0)); // truncado / vacío
    const r = await storeReq({ path: `/mykos-store/${name}` });
    const doc = asJson(r);
    const events = journalLines().filter((e) => e.doc === name && e.event === "recovered");
    check(`«${name}» dañado en disco (${name === "memory" ? "cortado a la mitad" : "vacío"}): se recupera de las copias y queda anotado`, r.status === 200 && doc?.data && doc.revision >= 1 && events.length >= 1, `HTTP ${r.status}; recuperada revisión ${doc?.revision}; ${events.length} anotación(es)`);
    const listed = (await getDocsList()).find((d) => d.name === name);
    check(`«${name}»: la lista de documentos coincide con lo recuperado (revisión ${doc?.revision})`, listed?.revision === doc?.revision, `lista r${listed?.revision}`);
    const rewrite = await storeReq({ method: "PUT", path: `/mykos-store/${name}`, body: JSON.stringify({ data: doc.data, expectedRevision: doc.revision, source: "probe-recovery" }), headers: { "Content-Type": "application/json" } });
    const rj = asJson(rewrite);
    const again = await getDoc(name);
    check(`«${name}»: tras recuperar se puede volver a escribir y la nueva revisión es coherente`, rewrite.status === 200 && rj?.revision === doc.revision + 1 && again?.revision === rj.revision && rj.conflict === false, `HTTP ${rewrite.status}; revisión ${doc.revision}→${rj?.revision}`);
  }
}

// ───────────────────────────────────────────────────────────────────────── corrupt
async function phaseCorrupt() {
  const corrupt = JSON.parse(fs.readFileSync(path.join(testRoot, `corrupt-${tag}.json`), "utf8"));
  const up = await waitFor(async () => {
    const h = await health();
    return h.status === 200 && h.json?.backend?.up && h.json.backend.phase === "up" ? h.json : null;
  }, 150000);
  if (!up) {
    check("el Gateway arrancó y el backend está «up» aunque el almacén no se active", false, JSON.stringify((await health()).json).slice(0, 700));
    return;
  }
  check("el Gateway arrancó y el backend está «up» aunque el almacén no se active", true, `Gateway PID ${up.pid}, backend PID ${up.backend.pid}`);
  const st = up.store;
  check("almacén habilitado pero NO activo, con el motivo explicado y un aviso en /mykos-health", st.enabled && st.active === false && /conversations/.test(st.error) && Array.isArray(up.warnings) && up.warnings.length === 1, `error=${String(st.error).slice(0, 160)}`);
  const conv = st.imports.find((i) => i.name === "conversations");
  const others = st.imports.filter((i) => i.name !== "conversations");
  check("importación: «conversations» falló y los otros cuatro NO se importaron (todo o nada)", conv?.status === "failed" && others.length === 4 && others.every((i) => i.status === "not-imported"), JSON.stringify(st.imports.map((i) => `${i.name}:${i.status}`)));
  check("ningún fichero de data/ tocado: conversations.json (estropeado), memory.json y memory_embeddings.json con su SHA-256 original y sin .migrated-*", shaFile(path.join(dataDir, "conversations.json")) === corrupt.sha256 && shaFile(path.join(dataDir, "memory.json")) === originals["memory.json"].sha256 && shaFile(path.join(dataDir, "memory_embeddings.json")) === originals["memory_embeddings.json"].sha256 && Object.values(FILES).every((f) => migratedOf(f).length === 0), "");
  check("el almacén no ha guardado ningún documento", countFiles(path.join(mykosDir, "docs")) === 0 && st.docs.every((d) => !d.exists), `${countFiles(path.join(mykosDir, "docs"))} ficheros en docs/`);
  const noTok = await request({ path: "/mykos-store/" });
  const withTok = await storeReq({ path: "/mykos-store/" });
  check("la API interna del almacén responde 503 (inactivo), con o sin token", noTok.status === 503 && withTok.status === 503, `HTTP ${noTok.status}/${withTok.status}`);
  const h = asJson(await request({ path: "/api/health?gateway=1" }));
  check("Python arranca en modo «file» y sigue funcionando con sus ficheros", h?.store_mode === "file", `store_mode=${h?.store_mode}`);
  check("la memoria se sigue sirviendo desde el fichero (2 recuerdos)", (await memoryCount()) === originals["memory.json"].count, `count=${await memoryCount()}`);
  const env = pythonEnv(up.backend.pid);
  check("el backend NO recibió ni URL ni token del almacén", env.MYKOS_STORE_MODE === "file" && !env.MYKOS_STORE_TOKEN && !env.MYKOS_STORE_URL, `modo=${env.MYKOS_STORE_MODE}`);
  const kept = shaFile(path.join(dataDir, "memory.json"));
  check("tras todo esto, memory.json sigue intacto", kept === originals["memory.json"].sha256, "");
}

// ───────────────────────────────────────────────────────────────────────── salida
(async () => {
  if (phase === "import") await phaseImport();
  else if (phase === "restart") await phaseRestart();
  else if (phase === "corrupt") await phaseCorrupt();
  else check("fase conocida", false, `PHASE=${phase}`);
  finish();
})().catch((error) => {
  check("la batería terminó sin excepciones", false, String(error && error.stack ? error.stack : error));
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
  console.log(failures ? `\n==> [${phase}] ${failures} de ${counted} comprobaciones FALLARON` : `\n==> [${phase}] ${counted}/${counted} comprobaciones correctas`);
  process.exit(failures ? 1 : 0);
}
