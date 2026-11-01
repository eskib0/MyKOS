// Uso: PROJECT_DIR=<copia de prueba> [PYTHON_EXE=...] node probe-watchdog.cjs
//
// Prueba el vigilante del proceso padre de server.py (MYKOS_PARENT_PID) SIN Gateway: el padre es un proceso de
// mentira que este script mata. Ojo: en Windows Node mete a sus hijos directos en un objeto de trabajo que los
// mata si Node muere; aquí el «padre» es un hermano (no el que lanza a Python), así que solo el vigilante puede
// apagar a Python. Se comprueba además que sale limpio (código 0, sin errores) y que el puerto queda libre.
const fs = require("fs");
const http = require("http");
const net = require("net");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");

const project = process.env.PROJECT_DIR;
const python = process.env.PYTHON_EXE || "python3";
if (!project) throw new Error("falta PROJECT_DIR (usa make-project.cjs)");
const PORT = 3278;
const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const alive = (pid) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === "EPERM";
  }
};
const health = () =>
  new Promise((resolve) => {
    const r = http.get({ host: "127.0.0.1", port: PORT, path: "/api/health", agent: false, timeout: 1500 }, (res) => {
      const c = [];
      res.on("data", (d) => c.push(d));
      res.on("end", () => {
        try {
          resolve(JSON.parse(Buffer.concat(c).toString()));
        } catch {
          resolve(null);
        }
      });
    });
    r.on("error", () => resolve(null));
    r.on("timeout", () => {
      r.destroy();
      resolve(null);
    });
  });
const portOpen = () =>
  new Promise((resolve) => {
    const s = net.connect({ host: "127.0.0.1", port: PORT }, () => {
      s.destroy();
      resolve(true);
    });
    s.on("error", () => resolve(false));
  });
async function waitFor(fn, ms, step = 200) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const v = await fn();
    if (v) return v;
    await sleep(step);
  }
  return null;
}
function startPython(parentPid, logName) {
  const logFile = path.join(os.homedir(), "mykos-gateway-test", logName);
  fs.rmSync(logFile, { force: true });
  const fd = fs.openSync(logFile, "a");
  const env = { ...process.env, PYTHONUTF8: "1", PYTHONUNBUFFERED: "1", MYKOS_HOST: "127.0.0.1", MYKOS_PORT: String(PORT), MYKOS_PUBLIC_PORT: "3210", MYKOS_BACKEND_ONLY: "1", MYKOS_PARENT_PID: String(parentPid) };
  const child = spawn(python, [path.join(project, "server.py")], { cwd: project, env, stdio: ["ignore", fd, fd], windowsHide: true });
  fs.closeSync(fd);
  const exited = new Promise((resolve) => child.once("exit", (code, signal) => resolve({ code, signal, at: Date.now() })));
  return { child, exited, logFile, read: () => (fs.existsSync(logFile) ? fs.readFileSync(logFile, "utf8") : "") };
}

(async () => {
  // 1. El padre vive: Python NO debe apagarse; el padre muere: Python se apaga solo y limpio.
  {
    const parent = spawn(process.execPath, ["-e", "setInterval(()=>{},1000)"], { stdio: "ignore" });
    const py = startPython(parent.pid, "watchdog-1.log");
    const up = await waitFor(health, 30000);
    check("el backend arranca con MYKOS_PARENT_PID", up && up.pid === py.child.pid, up ? `PID ${up.pid}` : "no respondió");
    await sleep(6000);
    check("con el padre vivo, el backend sigue en marcha (no se apaga solo)", alive(py.child.pid) && (await health()), "6 s después");
    const tKill = Date.now();
    process.kill(parent.pid);
    const ended = await Promise.race([py.exited, sleep(30000).then(() => null)]);
    check("al morir el padre, el backend se apaga solo", ended, ended ? `en ${((ended.at - tKill) / 1000).toFixed(1)} s, código ${ended.code}` : "sigue vivo tras 30 s");
    check("sale limpio (código 0)", ended && ended.code === 0, `código ${ended?.code}`);
    const log = py.read();
    check("el registro dice por qué se cerró", log.includes("ya no existe; cerrando el backend"), log.split("\n").filter(Boolean).slice(-3).join(" | ").slice(0, 220));
    check("sin errores ni Traceback en el registro", !/Traceback|Error/.test(log.replace(/Ollama: .*/g, "")), /Traceback|Error/.test(log) ? log.slice(-300) : "limpio");
    check("el puerto queda libre", !(await waitFor(portOpen, 1500)), "");
    if (ended === null) py.child.kill();
  }

  // 2. El padre ya no existe al arrancar: se apaga enseguida
  {
    const ghost = spawn(process.execPath, ["-e", "0"], { stdio: "ignore" });
    await new Promise((r) => ghost.once("exit", r));
    const py = startPython(ghost.pid, "watchdog-2.log");
    const ended = await Promise.race([py.exited, sleep(30000).then(() => null)]);
    check("con un padre inexistente, el backend se cierra solo poco después de arrancar", ended && ended.code === 0, ended ? `código ${ended.code}` : "sigue vivo tras 30 s");
    if (ended === null) py.child.kill();
  }

  // 3. Sin MYKOS_PARENT_PID no hay vigilante (uso manual): sigue vivo
  {
    const py = startPython(0, "watchdog-3.log");
    const up = await waitFor(health, 30000);
    await sleep(4000);
    check("sin MYKOS_PARENT_PID no hay vigilante y el backend sigue vivo", up && alive(py.child.pid), "");
    py.child.kill();
    await py.exited;
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
