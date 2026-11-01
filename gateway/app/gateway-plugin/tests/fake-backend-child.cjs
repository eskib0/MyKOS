// Backend falso para probar la SUPERVISIÓN del plugin (lo lanza el plugin como si fuera server.py).
// Lee el puerto de MYKOS_PORT (lo pone el plugin). Opciones por entorno:
//   FAKE_START_DELAY_MS   espera antes de empezar a escuchar (simula un arranque lento)
//   FAKE_CHILD_PIDFILE    lanza un proceso NIETO y escribe su PID aquí (para comprobar que se mata el árbol entero)
const http = require("http");
const fs = require("fs");
const { spawn } = require("child_process");

const port = Number(process.env.MYKOS_PORT);
const delay = Number(process.env.FAKE_START_DELAY_MS || 0);

if (process.env.FAKE_CHILD_PIDFILE) {
  const grandchild = spawn(process.execPath, ["-e", "setInterval(()=>{},1000)"], { stdio: "ignore" });
  fs.writeFileSync(process.env.FAKE_CHILD_PIDFILE, String(grandchild.pid));
}

const server = http.createServer((req, res) => {
  if (req.url.startsWith("/api/health")) {
    const body = JSON.stringify({ ok: true, service: "mykos-backend", pid: process.pid, fake: true });
    res.writeHead(200, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body), Connection: "close" });
    return void res.end(body);
  }
  res.writeHead(404, { Connection: "close" }).end();
});
server.on("error", (error) => {
  console.error("fake-backend-child:", error.code || error.message);
  process.exit(3);
});
setTimeout(() => server.listen(port, "127.0.0.1", () => console.log("fake backend listo", process.pid)), delay);
