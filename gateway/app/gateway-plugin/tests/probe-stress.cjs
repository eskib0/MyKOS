// Uso: node probe-stress.cjs <puertoGateway> [puertoBackendFalso=3299]
//   Variables: N (peticiones por fase, 3000), WORKERS (concurrencia de la última fase, 30)
//
// Mide latencias y errores de conexión en fases comparables para localizar DÓNDE aparece un fallo:
//   A  backend falso directo (referencia: cliente + sistema operativo)
//   B  Gateway, ruta del núcleo  /health            (sin plugin)
//   C  Gateway -> plugin -> backend falso  GET  /api/echo
//   D  Gateway -> plugin -> backend falso  POST /api/echo (cuerpo {})
//   E  como C con concurrencia
const http = require("http");
const path = require("path");
const { spawn } = require("child_process");

const gw = Number(process.argv[2] || 18795);
const fakePort = Number(process.argv[3] || 3299);
const N = Number(process.env.N || 3000);
const WORKERS = Number(process.env.WORKERS || 30);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function once(port, method, p, body) {
  return new Promise((resolve) => {
    const t0 = process.hrtime.bigint();
    const done = (status) => resolve({ status, ms: Number(process.hrtime.bigint() - t0) / 1e6 });
    const headers = body ? { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) } : {};
    const r = http.request({ host: "127.0.0.1", port, method, path: p, headers, agent: false }, (res) => {
      res.resume();
      res.on("end", () => done(res.statusCode));
      res.on("error", (e) => done("error:" + (e.code || e.message)));
    });
    r.setTimeout(45000, () => {
      r.destroy();
      done("timeout45s");
    });
    r.on("error", (e) => done("error:" + (e.code || e.message)));
    r.end(body);
  });
}

function summarize(name, samples, wallMs) {
  const ms = samples.map((s) => s.ms).sort((a, b) => a - b);
  const q = (p) => ms[Math.min(ms.length - 1, Math.floor(ms.length * p))];
  const errors = {};
  for (const s of samples) if (s.status !== 200) errors[s.status] = (errors[s.status] || 0) + 1;
  const slow = samples.filter((s) => s.ms > 250).length;
  console.log(
    `${name.padEnd(46)} n=${String(samples.length).padStart(5)}  p50=${q(0.5).toFixed(2)} p99=${q(0.99).toFixed(2)} max=${ms[ms.length - 1].toFixed(1)} ms  >250ms=${slow}  ${wallMs ? `(${Math.round(samples.length / (wallMs / 1000))}/s)  ` : ""}errores=${JSON.stringify(errors)}`,
  );
  return { errors: Object.keys(errors).length, slow };
}

async function sequential(name, port, method, p, body) {
  const t0 = Date.now();
  const samples = [];
  for (let i = 0; i < N; i += 1) samples.push(await once(port, method, p, body));
  return summarize(name, samples, Date.now() - t0);
}

(async () => {
  const fake = spawn(process.execPath, [path.join(__dirname, "fake-upstream.cjs"), String(fakePort)], { stdio: ["ignore", "inherit", "inherit", "ipc"] });
  await new Promise((resolve, reject) => {
    fake.once("message", (m) => (m && m.ready ? resolve() : undefined));
    fake.once("error", reject);
  });
  for (let i = 0; i < 100; i += 1) {
    const r = await once(gw, "GET", "/api/echo");
    if (r.status === 200) break;
    await sleep(500);
  }
  await sleep(4000); // deja terminar los servicios que el Gateway arranca justo después de «ready»

  const out = [];
  out.push(await sequential("A  backend falso directo (GET)", fakePort, "GET", "/api/echo"));
  out.push(await sequential("B  Gateway /health (núcleo, sin plugin)", gw, "GET", "/health"));
  out.push(await sequential("C  proxy GET /api/echo", gw, "GET", "/api/echo"));
  out.push(await sequential("D  proxy POST /api/echo", gw, "POST", "/api/echo", "{}"));

  const t0 = Date.now();
  const all = [];
  await Promise.all(
    Array.from({ length: WORKERS }, async () => {
      for (let i = 0; i < Math.floor(N / WORKERS); i += 1) all.push(await once(gw, "GET", "/api/echo"));
    }),
  );
  out.push(summarize(`E  proxy GET /api/echo, ${WORKERS} a la vez`, all, Date.now() - t0));

  fake.kill();
  const bad = out.reduce((n, o) => n + o.errors, 0);
  console.log(bad ? "\n==> HAY ERRORES DE CONEXIÓN (ver fases)" : "\n==> sin errores en ninguna fase");
  process.exit(bad ? 1 : 0);
})();
