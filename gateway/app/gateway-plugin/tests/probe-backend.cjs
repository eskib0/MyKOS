// Uso: node probe-backend.cjs <puertoGateway>
//   Variables: BACKEND_PORT (puerto interno del backend, 3299), PROJECT_DIR (copia de prueba del proyecto, de
//   make-project.cjs) y PYTHON_EXE. Van por entorno porque las rutas llevan espacios («Program Files»).
//
// El Gateway de prueba debe llevar el plugin con backend.spawn=true: es el PLUGIN quien lanza y supervisa el
// server.py REAL (de la copia con datos vacíos). Comprueba arranque, API real a través del Gateway, aislamiento
// del entorno, reinicio tras caída del backend y apagado automático si el Gateway muere.
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

const gw = Number(process.argv[2] || 18795);
const be = Number(process.env.BACKEND_PORT || 3299);
const project = process.env.PROJECT_DIR;
const python = process.env.PYTHON_EXE || "python3";
if (!project) throw new Error("falta la variable PROJECT_DIR");

const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });
const info = (name, detail) => results.push({ name, ok: true, info: true, detail });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function request({ method = "GET", path: p, headers = {}, body, port = gw, host, timeoutMs = 30000 }) {
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
  const r = await request({ path: "/mykos-health", timeoutMs: 5000 });
  return { status: r.status, json: asJson(r) };
};
const portListening = (port) =>
  new Promise((resolve) => {
    const s = require("net").connect({ host: "127.0.0.1", port }, () => {
      s.destroy();
      resolve(true);
    });
    s.on("error", () => resolve(false));
  });

(async () => {
  // 1. Arranque supervisado
  const up = await waitFor(async () => {
    const h = await health();
    return h.status === 200 && h.json?.backend?.up && h.json.backend.phase === "up" ? h.json : null;
  }, 120000);
  check("el plugin lanzó server.py y el backend está «up»", up, up ? `Gateway PID ${up.pid}, backend PID ${up.backend.pid}, tardó ${up.backend.uptimeSec}+ s` : "no llegó a estar listo en 120 s");
  if (!up) return finish();
  const gwPid = up.pid;
  let pyPid = up.backend.pid;
  check("el backend que responde es el proceso hijo lanzado", up.backend.backendPid === pyPid && up.backend.spawn === true, `respondedor=${up.backend.backendPid} hijo=${pyPid}`);

  // 2. Entorno del backend (psutil lee el entorno del proceso real)
  try {
    const out = execFileSync(python, ["-c", "import psutil,json,sys;e=psutil.Process(int(sys.argv[1])).environ();print(json.dumps({k:v for k,v in e.items() if k.upper().startswith(('MYKOS_','PYTHONUTF8','PYTHONIOENCODING'))}))", String(pyPid)], { encoding: "utf8", timeout: 20000 });
    const env = JSON.parse(out);
    const upper = Object.fromEntries(Object.entries(env).map(([k, v]) => [k.toUpperCase(), v]));
    check("entorno del backend: puerto interno, puerto público, Gateway, modo backend y padre", upper.MYKOS_PORT === String(be) && upper.MYKOS_PUBLIC_PORT === String(gw) && upper.MYKOS_GATEWAY_URL === `http://127.0.0.1:${gw}` && upper.MYKOS_BACKEND_ONLY === "1" && upper.MYKOS_PARENT_PID === String(gwPid), JSON.stringify(upper));
    check("el backend NO hereda variables MYKOS_* del Gateway", !Object.keys(upper).some((k) => k.startsWith("MYKOS_")), Object.keys(upper).filter((k) => k.startsWith("MYKOS_")).join(",") || "ninguna");
    check("UTF-8 forzado en el backend", upper.PYTHONUTF8 === "1" && upper.PYTHONIOENCODING === "utf-8");
  } catch (e) {
    check("lectura del entorno del backend", false, String(e.message).slice(0, 200));
  }

  // 3. API real a través del Gateway
  {
    const h = await request({ path: "/api/health?gateway=1" });
    const j = asJson(h);
    check("/api/health por el Gateway: backend_only y puertos correctos", h.status === 200 && j?.backend_only === true && j.port === be && j.public_port === gw && j.pid === pyPid, JSON.stringify(j));
    check("desde Python se ve el Gateway (MYKOS_GATEWAY_URL/health)", j?.gateway_reachable === true, `gateway_url=${j?.gateway_url} reachable=${j?.gateway_reachable}`);

    const direct = await request({ port: be, path: "/" });
    check("el backend NO sirve interfaz propia (404 con aviso al puerto público)", direct.status === 404 && String(asJson(direct)?.error).includes(String(gw)), `HTTP ${direct.status} ${asJson(direct)?.error}`);
    const directStatic = await request({ port: be, path: "/static/app.js" });
    check("tampoco /static/ en el backend", directStatic.status === 404, `HTTP ${directStatic.status}`);
    const ui = await request({ path: "/" });
    check("la interfaz la sirve el Gateway", ui.status === 200 && ui.body.toString("utf8").includes("<title>"), `HTTP ${ui.status} ${ui.body.length} B`);

    const list0 = await request({ path: "/api/conversations" });
    check("GET /api/conversations (almacén del Gateway)", list0.status === 200 && Array.isArray(asJson(list0)?.conversations), `HTTP ${list0.status} ${list0.body.toString("utf8").slice(0, 80)}`);
    const file = path.join(project, "data", "conversations.json");
    const legacyBefore = fs.existsSync(file) ? fs.readFileSync(file) : null;
    const created = await request({ method: "POST", path: "/api/conversations/new", headers: { "Content-Type": "application/json", Origin: `http://127.0.0.1:${gw}` }, body: JSON.stringify({ title: "prueba del proxy" }) });
    const cj = asJson(created);
    check("POST /api/conversations/new (cuerpo JSON en el Gateway)", created.status === 200 && cj && (cj.id || cj.conversation?.id), `HTTP ${created.status} ${created.body.toString("utf8").slice(0, 120)}`);
    const list1 = await request({ path: "/api/conversations" });
    check("la conversación creada aparece en la lista", (asJson(list1)?.conversations ?? []).length === (asJson(list0)?.conversations ?? []).length + 1, `antes=${(asJson(list0)?.conversations ?? []).length} después=${(asJson(list1)?.conversations ?? []).length}`);
    const legacyAfter = fs.existsSync(file) ? fs.readFileSync(file) : null;
    check("las conversaciones no reescriben data/ del worker", up.store?.active === true && ((legacyBefore === null && legacyAfter === null) || (legacyBefore !== null && legacyAfter !== null && Buffer.compare(legacyBefore, legacyAfter) === 0)), `${file}; almacén activo=${up.store?.active}`);

    const evil = await request({ method: "POST", path: "/api/conversations/new", headers: { "Content-Type": "application/json", Origin: "http://evil.example" }, body: JSON.stringify({ title: "desde otra web" }) });
    const list2 = await request({ path: "/api/conversations" });
    check("una web ajena no puede crear conversaciones (403 y nada se guarda)", evil.status === 403 && (asJson(list2)?.conversations ?? []).length === (asJson(list1)?.conversations ?? []).length, `HTTP ${evil.status}; conversaciones=${(asJson(list2)?.conversations ?? []).length}`);

    const libraryList = await request({ path: "/api/library/list?root=mykos&path=" });
    check("GET /api/library/list lo resuelve el Gateway", libraryList.status === 200 && Array.isArray(asJson(libraryList)?.items), `HTTP ${libraryList.status} ${libraryList.body.toString("utf8").slice(0, 120)}`);
    const librarySearch = await request({ path: "/api/library/search?root=mykos&path=&query=library_list" });
    check("GET /api/library/search conserva resultados del worker", librarySearch.status === 200 && Array.isArray(asJson(librarySearch)?.matches), `HTTP ${librarySearch.status} ${librarySearch.body.toString("utf8").slice(0, 120)}`);
    const libraryPreview = await request({ path: "/api/library/preview?root=mykos&path=server.py" });
    check("GET /api/library/preview conserva la vista previa", libraryPreview.status === 200 && typeof asJson(libraryPreview)?.text === "string" && asJson(libraryPreview).text.includes("library_list"), `HTTP ${libraryPreview.status} ${libraryPreview.body.toString("utf8").slice(0, 120)}`);
    const directLibrary = await request({ port: be, path: "/api/library/list?root=mykos&path=" });
    check("el worker rechaza el acceso directo a /api/library/list", directLibrary.status === 403, `HTTP ${directLibrary.status} ${directLibrary.body.toString("utf8").slice(0, 120)}`);

    const bad = await request({ method: "POST", path: "/api/chat", headers: { "Content-Type": "application/json" }, body: "{}" });
    check("POST /api/chat sin datos: el error viene de Python (JSON con «error»)", bad.status >= 400 && bad.status < 500 && typeof asJson(bad)?.error === "string", `HTTP ${bad.status} ${bad.body.toString("utf8").slice(0, 120)}`);

    for (const route of ["/api/memory", "/api/tools", "/api/permissions", "/api/approvals", "/api/audit", "/api/automations", "/api/nodes", "/api/media", "/api/management"]) {
      const r = await request({ path: route });
      info(`GET ${route}`, `HTTP ${r.status} ${r.body.length} B ${asJson(r) ? "JSON" : "NO-JSON"}`);
      if (!asJson(r)) check(`GET ${route} devuelve JSON`, false, `HTTP ${r.status} ${r.body.toString("utf8").slice(0, 100)}`);
    }
    const st = await request({ path: "/api/status" });
    const statusBody = asJson(st);
    check("GET /api/status lo resuelve el Gateway y conserva su contrato", st.status === 200 && statusBody?.ok === true && Array.isArray(statusBody.models) && Array.isArray(statusBody.tools) && Array.isArray(statusBody.allowed_roots) && Array.isArray(statusBody.benchmark_profiles) && typeof statusBody.memory === "object", `HTTP ${st.status} ${st.body.toString("utf8").slice(0, 160)}`);
    const directStatus = await request({ port: be, path: "/api/status" });
    check("el worker rechaza el acceso directo a /api/status", directStatus.status === 403, `HTTP ${directStatus.status} ${directStatus.body.toString("utf8").slice(0, 120)}`);
    const ollamaJobs = await request({ path: "/api/ollama/jobs" });
    check("GET /api/ollama/jobs lo resuelve el Gateway", ollamaJobs.status === 200 && Array.isArray(asJson(ollamaJobs)?.jobs), `HTTP ${ollamaJobs.status} ${ollamaJobs.body.toString("utf8").slice(0, 120)}`);
    const directOllamaJobs = await request({ port: be, path: "/api/ollama/jobs" });
    check("el worker rechaza el acceso directo a /api/ollama/jobs", directOllamaJobs.status === 403, `HTTP ${directOllamaJobs.status} ${directOllamaJobs.body.toString("utf8").slice(0, 120)}`);
  }

  // 4. Registro del backend (sin búfer: se lee en tiempo real) y la interfaz cargada de verdad en un navegador
  {
    const log = path.join(project, "data", "mykos-backend.log");
    const text = fs.existsSync(log) ? fs.readFileSync(log, "utf8") : "";
    check("el registro del backend se escribe en tiempo real y muestra el arranque", text.includes(`escuchando en http://127.0.0.1:${be}`), text.split("\n").filter(Boolean).slice(-2).join(" | ").slice(0, 200));

    const edge = ["C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe", "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"].find((p) => fs.existsSync(p));
    if (edge) {
      const testRoot = path.join(os.homedir(), "mykos-gateway-test");
      const shot = path.join(testRoot, "logs", "ui-B.png");
      const common = ["--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars", `--user-data-dir=${path.join(testRoot, "edge-profile")}`, "--window-size=1440,900", "--virtual-time-budget=12000"];
      fs.rmSync(shot, { force: true });
      try {
        execFileSync(edge, [...common, `--screenshot=${shot}`, `http://127.0.0.1:${gw}/`], { timeout: 120000, stdio: "ignore" });
      } catch (e) {
        info("Edge (captura) terminó con aviso", String(e.message).slice(0, 120));
      }
      check("captura de la interfaz servida por el Gateway (Edge sin cabeza)", fs.existsSync(shot) && fs.statSync(shot).size > 20000, fs.existsSync(shot) ? `${shot} (${fs.statSync(shot).size} B)` : "no se generó");
      let dom = "";
      try {
        dom = execFileSync(edge, [...common, "--dump-dom", `http://127.0.0.1:${gw}/`], { encoding: "utf8", timeout: 120000, maxBuffer: 32 * 1024 * 1024, stdio: ["ignore", "pipe", "ignore"] });
      } catch (e) {
        dom = String(e.stdout || "");
      }
      check("el JavaScript de la interfaz se ejecutó y cargó los modelos desde /api/status (aparece «llama.cpp» en la página)", dom.includes("llama.cpp"), `DOM de ${dom.length} caracteres`);
      const uploadsSeen = fs.readFileSync(log, "utf8");
      check("el navegador llegó a Python a través del Gateway (peticiones /api/* en el registro del backend)", /"GET \/api\/(status|conversations|models)/.test(uploadsSeen), (uploadsSeen.match(/"GET \/api\/[a-z\/]+/g) || []).slice(0, 4).join(" "));
    } else {
      info("Edge no encontrado: se omite la captura", "");
    }
  }

  // 5. Caída del backend: el plugin lo relanza solo
  {
    process.kill(pyPid); // como si Python se cayera
    const seen = await waitFor(async () => {
      const h = await health();
      return h.json?.backend?.phase === "restarting" || h.json?.backend?.phase === "starting" ? h.json : null;
    }, 8000, 100);
    const during = await request({ path: "/api/conversations" });
    info("durante el reinicio, la API responde", `HTTP ${during.status} ${during.headers["retry-after"] ? "Retry-After=" + during.headers["retry-after"] : ""} ${asJson(during)?.error ?? ""}`);
    const back = await waitFor(async () => {
      const h = await health();
      return h.status === 200 && h.json?.backend?.up && h.json.backend.pid !== pyPid ? h.json : null;
    }, 60000, 500);
    check("tras caer Python, el plugin lo relanza con otro PID", back, back ? `PID ${pyPid} -> ${back.backend.pid}; restarts=${back.backend.restarts}${seen ? "; se vio la fase «" + seen.backend.phase + "»" : ""}` : "no se recuperó en 60 s");
    if (back) {
      pyPid = back.backend.pid;
      const list = await request({ path: "/api/conversations" });
      check("los datos siguen ahí tras el reinicio (almacén Gateway)", list.status === 200 && (asJson(list)?.conversations ?? []).length >= 1, `HTTP ${list.status} conversaciones=${(asJson(list)?.conversations ?? []).length}`);
    }
  }

  // 6. Si el Gateway MUERE sin avisar (caída, kill), el backend no queda huérfano. En Windows lo garantiza el objeto
  //    de trabajo de Node (los hijos directos mueren con el padre); el vigilante de Python es la segunda red y se
  //    prueba aparte en probe-watchdog.cjs.
  {
    info("matando el Gateway sin cerrar a sus hijos", `Gateway PID ${gwPid}; el backend (PID ${pyPid}) no debe quedar vivo`);
    process.kill(gwPid);
    const gwGone = await waitFor(async () => !alive(gwPid), 10000, 200);
    check("el Gateway murió", gwGone, "");
    const t0 = Date.now();
    const pyGone = await waitFor(async () => !alive(pyPid), 30000, 250);
    check("el backend no queda huérfano al morir el Gateway", pyGone, pyGone ? `apagado ${((Date.now() - t0) / 1000).toFixed(1)} s después` : "sigue vivo tras 30 s");
    const free = await waitFor(async () => !(await portListening(be)), 10000, 250);
    check(`el puerto ${be} quedó libre`, free, "");
  }
  finish();
})().catch((error) => {
  check("la batería terminó sin excepciones", false, String(error && error.stack ? error.stack : error));
  finish();
});

function finish() {
  const width = Math.max(...results.map((r) => r.name.length));
  let failures = 0;
  for (const r of results) {
    if (!r.ok) failures += 1;
    console.log(`${r.info ? "INFO " : r.ok ? "OK   " : "FALLA"}  ${r.name.padEnd(width)}  ${r.detail}`);
  }
  const counted = results.filter((r) => !r.info).length;
  console.log(failures ? `\n==> ${failures} de ${counted} comprobaciones FALLARON` : `\n==> ${counted}/${counted} comprobaciones correctas`);
  process.exit(failures ? 1 : 0);
}
