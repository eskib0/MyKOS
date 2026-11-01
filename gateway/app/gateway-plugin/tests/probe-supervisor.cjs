// Uso: node probe-supervisor.cjs
//
// Prueba la SUPERVISIÓN del backend que hace el plugin (clase Backend) sin necesidad de un Gateway: importa el
// plugin real, le pasa un objeto «api» falso y usa backends de mentira (fake-backend-child.cjs, exit-now.cjs).
// Las esperas entre reintentos se acortan con backend.supervision para que dure segundos.
const fs = require("fs");
const http = require("http");
const net = require("net");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");
const { pathToFileURL } = require("url");

const repo = path.resolve(__dirname, "..", "..");
const tmp = path.join(os.homedir(), "mykos-gateway-test", "supervisor");
fs.mkdirSync(tmp, { recursive: true });
const GW_PORT = 18795;
const BASE_PORT = 3280;

const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const alive = (pid) => {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === "EPERM";
  }
};
const killTree = (pid) => pid && spawnSync("taskkill.exe", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
async function waitFor(fn, ms, step = 100) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const v = await fn();
    if (v) return v;
    await sleep(step);
  }
  return null;
}
const portOpen = (port) =>
  new Promise((resolve) => {
    const s = net.connect({ host: "127.0.0.1", port }, () => {
      s.destroy();
      resolve(true);
    });
    s.on("error", () => resolve(false));
  });

let plugin;
const leftovers = new Set();

/** Crea un «api» falso y registra el plugin. Devuelve utilidades para pedir rutas y arrancar/parar el servicio. */
function makePlugin(name, port, backend = {}, extraEnv = {}) {
  const logs = [];
  const routes = [];
  const services = [];
  const pidFile = path.join(tmp, `${name}.grandchild.pid`);
  fs.rmSync(pidFile, { force: true });
  const api = {
    id: "mykos-ui",
    registrationMode: "full",
    pluginConfig: {
      staticDir: path.join(repo, "static"),
      projectDir: tmp,
      gatewayPort: GW_PORT,
      backend: {
        url: `http://127.0.0.1:${port}`,
        python: process.execPath,
        script: path.join(__dirname, "fake-backend-child.cjs"),
        logFile: path.join(tmp, `${name}.log`),
        supervision: { delaysMs: [100, 200, 300], maxQuickFailures: 3, stableRunMs: 60000, readyTimeoutMs: 8000 },
        env: { FAKE_CHILD_PIDFILE: pidFile, ...extraEnv },
        ...backend,
      },
    },
    config: { gateway: { port: GW_PORT } },
    logger: { info: (m) => logs.push(["info", m]), warn: (m) => logs.push(["warn", m]), error: (m) => logs.push(["error", m]) },
    registerHttpRoute: (r) => routes.push(r),
    registerService: (s) => services.push(s),
  };
  fs.rmSync(api.pluginConfig.backend.logFile, { force: true });
  plugin.register(api);
  const ctx = { failures: [], cleared: 0, serviceHealth: { clearFailure: () => (ctx.cleared += 1), reportFailure: (e) => ctx.failures.push(e.message) } };
  const svc = services[0];
  const call = async (routePath, { method = "GET", headers = {} } = {}) => {
    const route = routes.find((r) => r.path === routePath) ?? routes.find((r) => r.match === "prefix" && routePath.startsWith(r.path));
    const req = { method, url: routePath, headers: { host: `127.0.0.1:${GW_PORT}`, ...headers }, socket: { localPort: GW_PORT } };
    const res = { statusCode: 0, headers: {}, headersSent: false, destroyed: false, body: "", setHeader(k, v) { this.headers[k.toLowerCase()] = v; }, end(b) { this.body += b ?? ""; this.headersSent = true; } };
    await route.handler(req, res);
    let json = null;
    try {
      json = JSON.parse(res.body);
    } catch {}
    return { status: res.statusCode, headers: res.headers, json };
  };
  const state = async () => (await call("/mykos-health")).json?.backend;
  const spawnCount = () => logs.filter(([, m]) => m.includes("arrancando el backend")).length;
  const grandchild = () => (fs.existsSync(pidFile) ? Number(fs.readFileSync(pidFile, "utf8")) : 0);
  const cleanup = async () => {
    const s = await state();
    if (s?.pid) killTree(s.pid);
    if (grandchild()) killTree(grandchild());
    await sleep(200);
  };
  return { api, ctx, svc, services, routes, logs, call, state, spawnCount, grandchild, cleanup, port };
}

(async () => {
  plugin = (await import(pathToFileURL(path.join(repo, "gateway-plugin", "mykos-ui", "index.js")).href)).default;

  // Registro
  {
    const p = makePlugin("reg", BASE_PORT);
    check("el plugin registra el servicio «mykos-backend» en modo full", p.services.length === 1 && p.svc.id === "mykos-backend", `servicios=${p.services.map((s) => s.id)}`);
    const routes = [];
    const services = [];
    plugin.register({ ...p.api, registrationMode: "setup-runtime", registerHttpRoute: (r) => routes.push(r), registerService: (s) => services.push(s) });
    check("en modo no-full registra las rutas pero NO el servicio (nada se lanza al registrar)", routes.length === 4 && services.length === 0, `rutas=${routes.length} servicios=${services.length}`);
    check("las rutas registradas son /mykos-health, /, /static/ y /api/", ["/mykos-health", "/", "/static/", "/api/"].every((x) => routes.some((r) => r.path === x)), routes.map((r) => r.path).join(" "));
  }

  // S1. Arranque, árbol de procesos y parada
  {
    const p = makePlugin("s1", BASE_PORT + 2);
    await p.svc.start(p.ctx);
    const up = await waitFor(async () => {
      const s = await p.state();
      return s?.phase === "up" && s.up ? s : null;
    }, 10000);
    check("S1 el servicio arranca y el backend queda «up»", up, up ? `PID ${up.pid}` : JSON.stringify(await p.state()));
    const health = await p.call("/mykos-health");
    check("S1 /mykos-health = 200 y ok:true con el backend arriba", health.status === 200 && health.json?.ok === true, `HTTP ${health.status}`);
    const gc = await waitFor(() => p.grandchild() || null, 3000);
    const pid = up?.pid;
    check("S1 el backend tiene un proceso nieto vivo (para probar el árbol)", gc && alive(gc), `nieto=${gc}`);
    const t0 = Date.now();
    await p.svc.stop();
    const after = await p.state();
    check("S1 stop(): el backend muere", !alive(pid), `PID ${pid} vivo=${alive(pid)} en ${Date.now() - t0} ms`);
    check("S1 stop(): también muere su proceso nieto (árbol entero)", !alive(gc), `nieto ${gc} vivo=${alive(gc)}`);
    check("S1 stop(): fase «stopped» y puerto libre", after?.phase === "stopped" && !(await portOpen(p.port)), `fase=${after?.phase}`);
    const h2 = await p.call("/mykos-health");
    check("S1 parado: /mykos-health = 503", h2.status === 503 && h2.json?.ok === false, `HTTP ${h2.status}`);
    await p.svc.stop();
    check("S1 stop() repetido no falla", true);
    await p.cleanup();
  }

  // S2. Caída y reinicio
  {
    const p = makePlugin("s2", BASE_PORT + 3);
    await p.svc.start(p.ctx);
    const up = await waitFor(async () => ((await p.state())?.phase === "up" ? await p.state() : null), 10000);
    const oldPid = up?.pid;
    process.kill(oldPid);
    const back = await waitFor(async () => {
      const s = await p.state();
      return s?.phase === "up" && s.pid !== oldPid ? s : null;
    }, 10000);
    check("S2 tras matar el backend, el plugin lo relanza con otro PID", back, back ? `PID ${oldPid} -> ${back.pid}; restarts=${back.restarts}` : JSON.stringify(await p.state()));
    check("S2 el contador de reinicios sube y se anota en el registro", back?.restarts === 1 && p.logs.some(([lvl, m]) => lvl === "warn" && m.includes("reintento")), `restarts=${back?.restarts}`);
    await p.svc.stop();
    await p.cleanup();
  }

  // S3. Se cae al arrancar: reintentos limitados
  {
    const p = makePlugin("s3", BASE_PORT + 4, { script: path.join(__dirname, "exit-now.cjs") });
    await p.svc.start(p.ctx);
    const failed = await waitFor(async () => ((await p.state())?.phase === "failed" ? await p.state() : null), 10000);
    const spawns = p.spawnCount();
    await sleep(1200);
    check("S3 un backend que se cae al arrancar acaba en «failed»", failed, failed ? failed.lastError : JSON.stringify(await p.state()));
    check("S3 reintenta exactamente maxQuickFailures+1 veces (4) y para", spawns === 4 && p.spawnCount() === 4, `lanzamientos=${spawns} → ${p.spawnCount()} tras esperar`);
    check("S3 avisa al Gateway (serviceHealth.reportFailure)", p.ctx.failures.length >= 1, p.ctx.failures[0] ?? "");
    const api = await p.call("/api/memory");   // una ruta REAL: las inventadas se rechazan antes (404) con la tabla de rutas
    check("S3 con el backend en «failed», /api/* responde 503 con el motivo", api.status === 503 && typeof api.json?.error === "string" && api.json.error.length > 10, `HTTP ${api.status} ${api.json?.error}`);
    await p.svc.stop();
  }

  // S4. Puerto ocupado por OTRO backend: no lo adopta ni lo mata
  {
    const { spawn } = require("child_process");
    const port = BASE_PORT + 5;
    const foreign = spawn(process.execPath, [path.join(__dirname, "fake-upstream.cjs"), String(port)], { stdio: ["ignore", "ignore", "ignore", "ipc"] });
    await new Promise((r) => foreign.once("message", r));
    const p = makePlugin("s4", port);
    await p.svc.start(p.ctx);
    const failed = await waitFor(async () => ((await p.state())?.phase === "failed" ? await p.state() : null), 10000);
    check("S4 con el puerto ocupado por otro backend, el plugin acaba en «failed»", failed, failed ? failed.lastError : JSON.stringify(await p.state()));
    check("S4 no mata ni sustituye al backend ajeno", alive(foreign.pid) && (await portOpen(port)), `ajeno PID ${foreign.pid} vivo=${alive(foreign.pid)}`);
    const s = await p.state();
    check("S4 no da por bueno el backend ajeno (up=false o pid distinto)", !s.up || s.pid !== s.backendPid, `up=${s.up} pid=${s.pid} backendPid=${s.backendPid}`);
    await p.svc.stop();
    foreign.kill();
    await p.cleanup();
  }

  // S5. Sustitución: arrancar una segunda instancia detiene la primera
  {
    const port = BASE_PORT + 6;
    const a = makePlugin("s5a", port);
    await a.svc.start(a.ctx);
    const upA = await waitFor(async () => ((await a.state())?.phase === "up" ? await a.state() : null), 10000);
    const b = makePlugin("s5b", port);
    await b.svc.start(b.ctx);
    const upB = await waitFor(async () => ((await b.state())?.phase === "up" ? await b.state() : null), 10000);
    check("S5 al arrancar una segunda instancia, la primera se detiene y la segunda queda «up»", upA && upB && !alive(upA.pid) && alive(upB.pid) && upA.pid !== upB.pid, `A=${upA?.pid} vivo=${alive(upA?.pid)}; B=${upB?.pid} vivo=${alive(upB?.pid)}`);
    check("S5 la primera instancia queda «stopped» y no se reinicia sola", (await a.state()).phase === "stopped", `fase A=${(await a.state()).phase}`);
    await b.svc.stop();
    await a.cleanup();
    await b.cleanup();
  }

  // S6. Parar mientras arranca
  {
    const p = makePlugin("s6", BASE_PORT + 7, {}, { FAKE_START_DELAY_MS: "6000" });
    await p.svc.start(p.ctx);
    await sleep(500);
    const s0 = await p.state();
    await p.svc.stop();
    await sleep(2500);
    check("S6 parar en pleno arranque mata el proceso y no lo relanza", s0?.phase === "starting" && !alive(s0.pid) && p.spawnCount() === 1 && (await p.state()).phase === "stopped", `fase previa=${s0?.phase}; lanzamientos=${p.spawnCount()}; vivo=${alive(s0?.pid)}`);
    await p.cleanup();
  }

  // S7. Ejecutable inexistente
  {
    const p = makePlugin("s7", BASE_PORT + 8, { python: "definitivamente-no-existe.exe" });
    await p.svc.start(p.ctx);
    const failed = await waitFor(async () => ((await p.state())?.phase === "failed" ? await p.state() : null), 10000);
    check("S7 Python inexistente: acaba en «failed» diciendo que no encuentra el ejecutable", failed && /no se encuentra el ejecutable de Python/.test(failed.lastError), failed ? failed.lastError.slice(0, 200) : JSON.stringify(await p.state()));
    await p.svc.stop();
  }

  // S8. Tiempo de espera del arranque
  {
    const p = makePlugin("s8", BASE_PORT + 9, { supervision: { delaysMs: [100], maxQuickFailures: 1, stableRunMs: 60000, readyTimeoutMs: 1500 } }, { FAKE_START_DELAY_MS: "60000" });
    await p.svc.start(p.ctx);
    const s0 = await waitFor(async () => (await p.state())?.pid || null, 3000);
    const failed = await waitFor(async () => ((await p.state())?.phase === "failed" ? await p.state() : null), 8000);
    check("S8 si el backend no responde a tiempo: «failed» y se mata el proceso", failed && /no respondió/.test(failed.lastError) && !alive(s0), failed ? failed.lastError.slice(0, 120) : JSON.stringify(await p.state()));
    await p.svc.stop();
    await p.cleanup();
  }

  // S9. Configuración
  {
    let threw = "";
    try {
      const api = { id: "mykos-ui", registrationMode: "full", pluginConfig: { staticDir: path.join(repo, "static"), backend: { url: "esto no es una url" } }, config: {}, logger: {}, registerHttpRoute() {}, registerService() {} };
      plugin.register(api);
    } catch (e) {
      threw = e.message;
    }
    check("S9 una backend.url inválida se rechaza al cargar con un mensaje claro", /backend\.url/.test(threw), threw || "no lanzó error");
    const api2 = { id: "mykos-ui", registrationMode: "full", pluginConfig: { staticDir: path.join(repo, "static") }, config: {}, logger: {}, routes: [], registerHttpRoute(r) { this.routes.push(r); }, registerService() { throw new Error("no debería registrar servicio"); } };
    plugin.register(api2);
    check("S9 sin backend configurado solo sirve la interfaz (sin /api/ ni servicio)", api2.routes.length === 3 && !api2.routes.some((r) => r.path === "/api/"), `rutas=${api2.routes.map((r) => r.path)}`);
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
    console.log(`${r.ok ? "OK   " : "FALLA"}  ${r.name.padEnd(width)}  ${r.detail}`);
  }
  console.log(failures ? `\n==> ${failures} de ${results.length} comprobaciones FALLARON` : `\n==> ${results.length}/${results.length} comprobaciones correctas`);
  process.exit(failures ? 1 : 0);
}
