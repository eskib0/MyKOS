// Uso: node probe-proxy.cjs <puertoGateway> [puertoBackendFalso=3299]
//   Variables: SLOW_MS (respuesta lenta que debe sobrevivir al proxy; por defecto 100000)
//
// Batería del proxy /api/* del plugin mykos-ui contra un backend FALSO (fake-upstream.cjs) que este script
// lanza y controla. El Gateway debe estar arrancado con el plugin y  backend.url = http://127.0.0.1:<puertoBackendFalso>,
// backend.spawn = false.
const http = require("http");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");
const { patternSha256 } = require("./fake-upstream.cjs");

const gw = Number(process.argv[2] || 18795);
const fakePort = Number(process.argv[3] || 3299);
const SLOW_MS = Number(process.env.SLOW_MS || 100000);
const repo = path.resolve(__dirname, "..", "..");

const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: Boolean(ok), detail });
const info = (name, detail) => results.push({ name, ok: true, info: true, detail });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sha = (buf) => crypto.createHash("sha256").update(buf).digest("hex");

function request({ method = "GET", path: p, headers = {}, body, port = gw, timeoutMs = 60000, host }) {
  return new Promise((resolve) => {
    const h = {};
    for (const [k, v] of Object.entries(headers)) h[k.toLowerCase()] = v;
    if (host !== undefined) h.host = host;
    if ((typeof body === "string" || Buffer.isBuffer(body)) && h["content-length"] === undefined && h["transfer-encoding"] === undefined) h["content-length"] = Buffer.byteLength(body);
    const t0 = Date.now();
    const chunks = [];
    const fail = (why) => resolve({ status: why, headers: {}, body: Buffer.concat(chunks), ms: Date.now() - t0 });
    const r = http.request({ host: "127.0.0.1", port, method, path: p, headers: h, agent: false }, (res) => {
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks), ms: Date.now() - t0 }));
      res.on("error", (e) => fail("error:" + (e.code || e.message)));
      res.on("aborted", () => fail("aborted"));
    });
    r.setTimeout(timeoutMs, () => {
      r.destroy();
      fail("timeout");
    });
    r.on("error", (e) => fail("error:" + (e.code || e.message)));
    if (typeof body === "function") body(r);
    else r.end(body);
  });
}
const asJson = (r) => {
  try {
    return JSON.parse(r.body.toString("utf8"));
  } catch {
    return null;
  }
};

let fake = null;
function startFake() {
  return new Promise((resolve, reject) => {
    fake = spawn(process.execPath, [path.join(__dirname, "fake-upstream.cjs"), String(fakePort)], { stdio: ["ignore", "inherit", "inherit", "ipc"] });
    fake.once("message", (m) => (m && m.ready ? resolve() : undefined));
    fake.once("error", reject);
    fake.once("exit", (code) => reject(new Error(`el backend falso terminó (código ${code})`)));
  });
}
async function stopFake() {
  if (!fake) return;
  const f = fake;
  fake = null;
  f.removeAllListeners("exit");
  f.kill();
  await new Promise((r) => (f.exitCode !== null ? r() : f.once("exit", r)));
}
async function waitFor(fn, ms, step = 250) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const v = await fn();
    if (v) return v;
    await sleep(step);
  }
  return null;
}
function mykosRoutes() {
  const src = fs.readFileSync(path.join(repo, "server.py"), "utf8");
  const set = new Set();
  for (const m of src.matchAll(/"(\/api\/[A-Za-z0-9_\/\-]*)"/g)) set.add(m[1].endsWith("/") ? m[1] + "muestra" : m[1]);
  set.add("/api/approvals/muestra/resolve");
  return [...set].sort();
}

(async () => {
  await startFake();
  const ready = await waitFor(async () => {
    const r = await request({ path: "/mykos-health", timeoutMs: 5000 });
    const j = asJson(r);
    return r.status === 200 && j?.backend?.up ? j : null;
  }, 90000);
  check("Gateway + plugin listos con el backend falso", ready, ready ? `phase=${ready.backend.phase} url=${ready.backend.url}` : "no llegó a estar listo en 90 s");
  if (!ready) return finish();

  // Respuesta lenta: arranca ya y se comprueba al final (debe sobrevivir a todo lo demás).
  const slow = request({ path: `/api/__t/slow?ms=${SLOW_MS}`, timeoutMs: SLOW_MS + 60000 });

  // 1. Ruta y consulta exactas
  {
    const p = "/api/echo?x=1&y=%C3%A9+z&sp=a%20b&vacio=";
    const r = await request({ path: p });
    const j = asJson(r);
    check("GET: ruta y consulta llegan idénticas", r.status === 200 && j?.upstream && j.url === p, `HTTP ${r.status} url=${j?.url}`);
  }

  // 2. Métodos con cuerpo
  const payload = JSON.stringify({ a: 1, texto: "café" });
  for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
    const r = await request({ method, path: "/api/echo", headers: { "Content-Type": "application/json" }, body: payload });
    const j = asJson(r);
    check(`${method} con cuerpo JSON`, r.status === 200 && j?.method === method && j.bodyBytes === Buffer.byteLength(payload) && j.bodySha256 === sha(Buffer.from(payload)), `HTTP ${r.status} bytes=${j?.bodyBytes}`);
  }
  {
    const r = await request({ method: "HEAD", path: "/api/echo" });
    check("HEAD: estado y cabeceras, sin cuerpo", r.status === 200 && r.body.length === 0 && Number(r.headers["content-length"]) > 0, `HTTP ${r.status} content-length=${r.headers["content-length"]} cuerpo=${r.body.length}`);
    const o = await request({ method: "OPTIONS", path: "/api/echo" });
    check("OPTIONS llega al backend", o.status === 200 && asJson(o)?.method === "OPTIONS", `HTTP ${o.status}`);
  }

  // 3. Cabeceras
  {
    const r = await request({ path: "/api/echo", headers: { "X-Test": "hola", Origin: `http://127.0.0.1:${gw}` } });
    const j = asJson(r);
    check("cabecera de la petición llega al backend", j?.headers?.["x-test"] === "hola", `x-test=${j?.headers?.["x-test"]}`);
    check("Host que ve el backend es el suyo", j?.headers?.host === `127.0.0.1:${fakePort}`, `host=${j?.headers?.host}`);
    check("Origin propio se conserva", j?.headers?.origin === `http://127.0.0.1:${gw}`, `origin=${j?.headers?.origin}`);
    const h = await request({ path: "/api/__t/headers" });
    check("cabeceras de la respuesta (Content-Disposition, X-Custom, Cache-Control)", h.headers["content-disposition"]?.includes("conversacion.json") && h.headers["x-custom"] === "si" && h.headers["cache-control"] === "no-store", JSON.stringify({ cd: h.headers["content-disposition"], x: h.headers["x-custom"], cc: h.headers["cache-control"] }));
    check("dos Set-Cookie se conservan", Array.isArray(h.headers["set-cookie"]) && h.headers["set-cookie"].length === 2, `set-cookie=${JSON.stringify(h.headers["set-cookie"])}`);
  }

  // 4. Códigos de estado
  for (const code of [404, 418, 500]) {
    const r = await request({ path: `/api/__t/status?code=${code}` });
    check(`estado ${code} y cuerpo JSON`, r.status === code && asJson(r)?.error === `estado ${code}`, `HTTP ${r.status}`);
  }
  {
    const r = await request({ path: "/api/__t/status?code=204" });
    check("estado 204 sin cuerpo", r.status === 204 && r.body.length === 0, `HTTP ${r.status}`);
    const s = await request({ path: "/api/__t/status?code=302" });
    check("redirección 302 con Location, sin seguirla", s.status === 302 && s.headers.location === "/api/__t/destino", `HTTP ${s.status} location=${s.headers.location}`);
  }

  // 5. Binario y descarga grande
  {
    const r = await request({ path: "/api/__t/binary" });
    const exact = r.body.length === 256 && r.body.every((b, i) => b === i);
    check("binario (0..255) byte a byte", r.status === 200 && exact && r.headers["content-type"] === "audio/wav" && r.headers["content-length"] === "256", `HTTP ${r.status} ${r.body.length} B ct=${r.headers["content-type"]}`);
    const N = 20 * 1024 * 1024;
    const big = await request({ path: `/api/__t/big?bytes=${N}` });
    check("descarga de 20 MB íntegra (SHA-256)", big.status === 200 && big.body.length === N && sha(big.body) === patternSha256(N), `HTTP ${big.status} ${big.body.length} B en ${big.ms} ms`);
  }

  // 6. Subidas
  for (const mb of [1, 30]) {
    const data = crypto.randomBytes(mb * 1024 * 1024);
    const r = await request({ method: "POST", path: "/api/uploads", headers: { "Content-Type": "application/octet-stream" }, body: data, timeoutMs: 120000 });
    const j = asJson(r);
    check(`subida de ${mb} MB íntegra (SHA-256)`, r.status === 200 && j?.bodyBytes === data.length && j.bodySha256 === sha(data), `HTTP ${r.status} ${j?.bodyBytes} B en ${r.ms} ms`);
  }
  {
    const parts = [crypto.randomBytes(70000), crypto.randomBytes(1), crypto.randomBytes(131072)];
    const total = parts.reduce((n, b) => n + b.length, 0);
    const r = await request({
      method: "POST",
      path: "/api/uploads",
      headers: { "Transfer-Encoding": "chunked" },
      body: (req) => {
        req.write(parts[0]);
        req.write(parts[1]);
        req.end(parts[2]);
      },
    });
    const j = asJson(r);
    check("subida chunked: el backend recibe Content-Length y el cuerpo íntegro", r.status === 200 && j?.bodyBytes === total && j.bodySha256 === sha(Buffer.concat(parts)) && j.headers?.["content-length"] === String(total) && j.headers?.["transfer-encoding"] === undefined, `HTTP ${r.status} bytes=${j?.bodyBytes} cl=${j?.headers?.["content-length"]} te=${j?.headers?.["transfer-encoding"]}`);
  }

  // 7. Concurrencia y capacidad de respuesta mientras hay una petición lenta abierta
  {
    const jobs = Array.from({ length: 40 }, (_, i) => {
      const body = crypto.randomBytes(65536);
      return request({ method: "POST", path: `/api/echo?i=${i}`, body }).then((r) => ({ r, body, i }));
    });
    const done = await Promise.all(jobs);
    const bad = done.filter(({ r, body, i }) => { const j = asJson(r); return !(r.status === 200 && j?.query === `?i=${i}` && j.bodySha256 === sha(body)); });
    check("40 peticiones simultáneas correctas", bad.length === 0, bad.length ? `fallan: ${bad.map((b) => b.i).join(",")}` : "40/40");
    const h = await request({ path: "/health" });
    check("el Gateway responde rápido con una petición lenta abierta", h.status === 200 && h.ms < 2000, `/health HTTP ${h.status} en ${h.ms} ms`);
    // Paralelismo real: 20 peticiones que el backend retiene 400 ms cada una. En paralelo tardan ~0,4 s; en serie, 8 s.
    const t0 = Date.now();
    const holds = await Promise.all(Array.from({ length: 20 }, () => request({ path: "/api/__t/slow?ms=400" })));
    const elapsed = Date.now() - t0;
    const stats = asJson(await request({ port: fakePort, path: "/api/__t/stats" }));
    check("20 peticiones retenidas 400 ms se atienden en paralelo", holds.every((r) => r.status === 200) && elapsed < 3000 && stats?.maxInflight >= 15, `total ${elapsed} ms; el backend llegó a tener ${stats?.maxInflight} a la vez`);
  }

  // 8. Cancelación del navegador
  {
    const before = asJson(await request({ port: fakePort, path: "/api/__t/stats" }))?.aborted ?? 0;
    await new Promise((resolve) => {
      const r = http.request({ host: "127.0.0.1", port: gw, path: "/api/__t/slow?ms=60000", agent: false }, () => {});
      r.on("error", () => {});
      r.end();
      setTimeout(() => {
        r.destroy();
        resolve();
      }, 400);
    });
    const after = await waitFor(async () => {
      const a = asJson(await request({ port: fakePort, path: "/api/__t/stats" }))?.aborted ?? 0;
      return a > before ? a : null;
    }, 8000);
    check("si el navegador cancela, el proxy corta la petición al backend", after, `abortadas antes=${before} después=${after}`);
  }

  // 9. Protección frente a otras páginas web (Host y Origin)
  {
    const post = (extra) => request({ method: "POST", path: "/api/echo", body: "{}", headers: { "Content-Type": "application/json", ...(extra.headers || {}) }, host: extra.host });
    const cases = [
      ["Origin ajeno bloqueado", { headers: { Origin: "http://evil.example", "X-Marker": "evil-origin" } }, 403],
      ["Origin «null» bloqueado", { headers: { Origin: "null", "X-Marker": "null-origin" } }, 403],
      ["Origin de otro puerto local bloqueado", { headers: { Origin: `http://127.0.0.1:${gw + 1}`, "X-Marker": "other-port" } }, 403],
      ["Host ajeno (DNS rebinding) bloqueado", { host: `evil.example:${gw}`, headers: { "X-Marker": "evil-host" } }, 403],
      ["Host sin puerto bloqueado", { host: "127.0.0.1", headers: { "X-Marker": "no-port" } }, 403],
      ["Origin 127.0.0.1 propio permitido", { headers: { Origin: `http://127.0.0.1:${gw}` } }, 200],
      ["Origin localhost propio permitido", { headers: { Origin: `http://localhost:${gw}` }, host: `localhost:${gw}` }, 200],
      ["sin Origin (curl, Node, Python) permitido", { headers: {} }, 200],
    ];
    for (const [name, extra, expected] of cases) {
      const r = await post(extra);
      check(name, r.status === expected, `HTTP ${r.status}`);
    }
    const g = await request({ path: "/api/echo", headers: { Origin: "http://evil.example", "X-Marker": "evil-get" } });
    check("GET entre sitios (fetch con Origin ajeno) bloqueado", g.status === 403, `HTTP ${g.status}`);
    for (const marker of ["evil-origin", "null-origin", "other-port", "evil-host", "no-port", "evil-get"]) {
      const seen = asJson(await request({ port: fakePort, path: `/api/__t/seen?marker=${marker}` }))?.count;
      check(`lo bloqueado no llega al backend (${marker})`, seen === 0, `llegadas=${seen}`);
    }
    const page = await request({ path: "/", headers: { Origin: "http://evil.example" } });
    check("la página estática no se ve afectada por el bloqueo", page.status === 200, `HTTP ${page.status}`);
  }

  // 10. Todas las rutas de MyKOS llegan al backend (ninguna la captura el núcleo del Gateway)
  {
    const routes = mykosRoutes();
    const wrong = [];
    for (const route of routes) {
      for (const method of ["GET", "POST"]) {
        const r = await request({ method, path: route, body: method === "POST" ? "{}" : undefined, headers: method === "POST" ? { "Content-Type": "application/json" } : {} });
        const j = asJson(r);
        // Voz: el Gateway reenvía POST /api/transcribe y /api/tts por su frontera interna autenticada (/mykos-control/...).
        const expected = method === "POST" && (route === "/api/transcribe" || route === "/api/tts") ? `/mykos-control/${route.slice(5)}` : route;
        const fromBackend = r.status === 200 && (j?.upstream === true ? j.path === expected && j.method === method : j?.fake === true);
        if (!fromBackend) wrong.push(`${method} ${route} -> HTTP ${r.status}`);
      }
    }
    check(`las ${routes.length} rutas /api/* de server.py (GET y POST) llegan al backend`, wrong.length === 0, wrong.length ? wrong.slice(0, 6).join(" | ") : `${routes.length * 2}/${routes.length * 2}`);
    info("rutas comprobadas", routes.join("  "));
  }

  // 11. El resto del Gateway sigue intacto
  {
    const [h, m, c, jh] = await Promise.all([request({ path: "/health" }), request({ path: "/v1/models" }), request({ method: "POST", path: "/v1/chat/completions", body: "{}", headers: { "Content-Type": "application/json" } }), request({ path: "/mykos-health" })]);
    check("/health y /v1/models del Gateway responden 200", h.status === 200 && m.status === 200, `health=${h.status} models=${m.status}`);
    check("POST /v1/chat/completions lo atiende el núcleo (400 de validación)", c.status === 400, `HTTP ${c.status}`);
    const j = asJson(jh);
    check("/mykos-health: backend externo activo", jh.status === 200 && j?.backend?.phase === "external" && j.backend.up === true, `HTTP ${jh.status} phase=${j?.backend?.phase} up=${j?.backend?.up}`);
    const raw = await request({ path: "/api/..%2f..%2fetc%2fpasswd" });
    info("ruta con «..%2f» (se pasa tal cual; el backend solo compara rutas exactas)", `HTTP ${raw.status} url=${asJson(raw)?.url}`);
    const bare = await request({ path: "/api" });
    info("«/api» sin barra final", `HTTP ${bare.status} (MyKOS nunca la usa)`);
  }

  // 12. La petición lenta: debe terminar sin cortes y, mientras dura, el resto de /api/* y del Gateway sigue respondiendo
  //     (es lo que pasa en MyKOS: la interfaz consulta /api/activity mientras un chat tarda minutos).
  {
    let finished = false;
    const slowDone = slow.then((r) => {
      finished = true;
      return r;
    });
    let probes = 0;
    let slowest = 0;
    const late = [];
    while (!finished) {
      await Promise.race([sleep(5000), slowDone]);
      if (finished) break;
      const [a, h] = await Promise.all([request({ path: "/api/echo?soak=1" }), request({ path: "/health" })]);
      probes += 1;
      slowest = Math.max(slowest, a.ms, h.ms);
      if (a.status !== 200 || h.status !== 200 || a.ms > 1000 || h.ms > 1000) late.push(`sondeo ${probes}: api=${a.status}/${a.ms} ms health=${h.status}/${h.ms} ms`);
    }
    const r = await slowDone;
    const j = asJson(r);
    check(`respuesta lenta de ${Math.round(SLOW_MS / 1000)} s completada sin cortes`, r.status === 200 && j?.waited === SLOW_MS && r.ms >= SLOW_MS - 500, `HTTP ${r.status} en ${(r.ms / 1000).toFixed(1)} s`);
    check(`durante esa espera, ${probes} sondeos intermedios de /api/* y /health respondieron a tiempo`, probes > 0 && late.length === 0, late.length ? late.slice(0, 3).join(" | ") : `latencia máxima ${slowest} ms`);
  }

  // 13. Backend caído y recuperado: 502 claro, el Gateway sigue vivo y se recupera solo
  {
    await stopFake();
    const r = await waitFor(async () => {
      const x = await request({ path: "/api/echo" });
      return x.status === 502 ? x : null;
    }, 10000);
    check("backend caído -> 502 con mensaje en español", r && typeof asJson(r)?.error === "string" && asJson(r).error.includes("MyKOS"), r ? `HTTP ${r.status} «${asJson(r)?.error}»` : "no devolvió 502");
    const h = await request({ path: "/health" });
    const jh = await request({ path: "/mykos-health" });
    check("con el backend caído el Gateway sigue vivo y /mykos-health lo indica (503)", h.status === 200 && jh.status === 503 && asJson(jh)?.backend?.up === false, `health=${h.status} mykos-health=${jh.status}`);
    await startFake();
    const back = await waitFor(async () => {
      const x = await request({ path: "/api/echo" });
      return x.status === 200 ? x : null;
    }, 10000);
    check("al volver el backend, el proxy se recupera sin reiniciar nada", back, back ? "HTTP 200" : "no se recuperó");
  }
  finish();
})().catch((error) => {
  check("la batería terminó sin excepciones", false, String(error && error.stack ? error.stack : error));
  finish();
});

async function finish() {
  await stopFake();
  const width = Math.max(...results.map((r) => r.name.length));
  let failures = 0;
  for (const r of results) {
    if (!r.ok) failures += 1;
    const tag = r.info ? "INFO " : r.ok ? "OK   " : "FALLA";
    console.log(`${tag}  ${r.name.padEnd(width)}  ${r.detail}`);
  }
  const counted = results.filter((r) => !r.info).length;
  console.log(failures ? `\n==> ${failures} de ${counted} comprobaciones FALLARON` : `\n==> ${counted}/${counted} comprobaciones correctas`);
  process.exit(failures ? 1 : 0);
}
