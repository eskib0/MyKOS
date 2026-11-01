// Uso: node fake-upstream.cjs <puerto>
//
// Backend FALSO para probar el proxy del plugin sin depender de Python. Se comporta como el http.server
// de Python: cada respuesta lleva "Connection: close" y Content-Length. Endpoints de prueba bajo /api/__t/;
// cualquier otra ruta responde con un eco JSON (upstream:true, método, ruta, cabeceras, tamaño y SHA-256
// del cuerpo recibido), que es lo que usan las pruebas para saber qué llegó realmente al backend.
const http = require("http");
const crypto = require("crypto");

/** Contenido determinista de n bytes (el test calcula el SHA-256 esperado con la misma función). */
function patternChunk(size = 65536) {
  const b = Buffer.allocUnsafe(size);
  for (let i = 0; i < size; i += 1) b[i] = (i * 31 + 7) % 251;
  return b;
}
function patternSha256(total) {
  const chunk = patternChunk();
  const hash = crypto.createHash("sha256");
  for (let left = total; left > 0; left -= chunk.length) hash.update(left >= chunk.length ? chunk : chunk.subarray(0, left));
  return hash.digest("hex");
}
module.exports = { patternSha256 };

if (require.main === module) {
  const port = Number(process.argv[2] || 3299);
  let aborted = 0;
  let inflight = 0;
  let maxInflight = 0;
  const seen = {}; // peticiones recibidas por valor de la cabecera X-Marker (para comprobar qué NO llegó)

  const json = (res, status, body) => {
    const payload = JSON.stringify(body);
    res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Content-Length": Buffer.byteLength(payload), "Cache-Control": "no-store", Connection: "close" });
    res.end(payload);
  };

  const server = http.createServer((req, res) => {
    inflight += 1;
    maxInflight = Math.max(maxInflight, inflight);
    res.on("close", () => {
      inflight -= 1;
      if (!res.writableFinished) aborted += 1; // el cliente (el proxy) cortó antes de terminar
    });
    const url = new URL(req.url, "http://fake");
    const p = url.pathname;
    const marker = req.headers["x-marker"];
    if (marker) seen[marker] = (seen[marker] || 0) + 1;

    if (p === "/api/__t/seen") return void json(res, 200, { count: seen[url.searchParams.get("marker") || ""] || 0 });
    if (p === "/api/health") return void json(res, 200, { ok: true, service: "mykos-backend", pid: process.pid, fake: true });
    if (p === "/api/__t/stats") return void json(res, 200, { aborted, inflight: inflight - 1, maxInflight });

    if (p === "/api/__t/slow") {
      const ms = Number(url.searchParams.get("ms") || 1000);
      const timer = setTimeout(() => json(res, 200, { ok: true, waited: ms }), ms);
      res.on("close", () => clearTimeout(timer));
      return;
    }
    if (p === "/api/__t/big") {
      const total = Number(url.searchParams.get("bytes") || 1024);
      const chunk = patternChunk();
      res.writeHead(200, { "Content-Type": "application/octet-stream", "Content-Length": total, Connection: "close" });
      let left = total;
      const pump = () => {
        while (left > 0) {
          const piece = left >= chunk.length ? chunk : chunk.subarray(0, left);
          left -= piece.length;
          if (!res.write(piece)) return void res.once("drain", pump);
        }
        res.end();
      };
      return void pump();
    }
    if (p === "/api/__t/binary") {
      const data = Buffer.from(Array.from({ length: 256 }, (_, i) => i));
      res.writeHead(200, { "Content-Type": "audio/wav", "Content-Length": data.length, Connection: "close" });
      return void res.end(data);
    }
    if (p === "/api/__t/headers") {
      res.writeHead(200, {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Disposition": 'attachment; filename="conversacion.json"',
        "Set-Cookie": ["a=1; Path=/", "b=2; Path=/"],
        "X-Custom": "si",
        "Cache-Control": "no-store",
        Connection: "close",
      });
      return void res.end('{"ok":true}');
    }
    if (p === "/api/__t/status") {
      const code = Number(url.searchParams.get("code") || 200);
      if (code === 204) return void res.writeHead(204, { Connection: "close" }).end();
      if (code === 302) return void res.writeHead(302, { Location: "/api/__t/destino", Connection: "close" }).end();
      return void json(res, code, { error: `estado ${code}` });
    }

    // Eco: cuenta y resume el cuerpo mientras llega (sin guardarlo entero).
    const hash = crypto.createHash("sha256");
    let bytes = 0;
    req.on("data", (chunk) => {
      bytes += chunk.length;
      hash.update(chunk);
    });
    req.on("end", () =>
      json(res, 200, { upstream: true, method: req.method, url: req.url, path: p, query: url.search, headers: req.headers, bodyBytes: bytes, bodySha256: hash.digest("hex") }),
    );
  });

  // Cuando lo lanza una prueba con canal IPC, se apaga solo si la prueba desaparece.
  process.on("disconnect", () => process.exit(0));
  server.listen(port, "127.0.0.1", () => {
    if (process.send) process.send({ ready: true, port });
    else console.log(`backend falso escuchando en http://127.0.0.1:${port}`);
  });
}
