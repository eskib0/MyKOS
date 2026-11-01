// Uso: node probe-voice-mode.cjs <puerto> <con_credencial:0|1>
// Comprueba GET/POST /api/voice/mode: modo local por defecto, rechazo a la nube sin credencial (409),
// cambio a la nube cuando sí la hay (200, sin reiniciar), vuelta a local, y persistencia en disco.
const http = require("http");
const fs = require("fs");
const path = require("path");

const port = Number(process.argv[2] || 18795);
const withCredential = process.argv[3] === "1";
const stateDir = process.env.MYKOS_GATEWAY_STATE_DIR;
if (!stateDir) throw new Error("MYKOS_GATEWAY_STATE_DIR no está definido (lo pone run-isolated-test.ps1)");
const configFile = path.join(stateDir, "mykos-gateway.json");

let passed = 0;
let failed = 0;
function check(label, value, detail = "") {
  if (value) { passed += 1; console.log(`OK     ${label}${detail ? `  ${detail}` : ""}`); }
  else { failed += 1; console.log(`FALLA  ${label}${detail ? `  ${detail}` : ""}`); }
}

function req(method, rawPath, body) {
  return new Promise((resolve) => {
    const payload = body ? JSON.stringify(body) : null;
    const headers = payload ? { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) } : {};
    const r = http.request({ host: "127.0.0.1", port, method, path: rawPath, headers, timeout: 8000 }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => {
        let json = null;
        try { json = JSON.parse(Buffer.concat(chunks).toString("utf8")); } catch {}
        resolve({ status: res.statusCode, json });
      });
    });
    r.on("timeout", () => { r.destroy(); resolve({ status: "timeout", json: null }); });
    r.on("error", (e) => resolve({ status: "error:" + e.code, json: null }));
    r.end(payload);
  });
}

(async () => {
  const before = await req("GET", "/api/voice/mode");
  check("modo por defecto: local", before.json?.mode === "local", JSON.stringify(before.json));
  check("informa si la nube está disponible", before.json?.cloud?.available === withCredential, JSON.stringify(before.json?.cloud));

  const badMode = await req("POST", "/api/voice/mode", { mode: "satelite" });
  check("modo inválido: 400", badMode.status === 400, `HTTP ${badMode.status}`);

  const toCloud = await req("POST", "/api/voice/mode", { mode: "cloud" });
  if (withCredential) {
    check("con credencial: cambia a la nube (200)", toCloud.status === 200 && toCloud.json?.mode === "cloud", JSON.stringify(toCloud.json));
    check("el cambio se guarda en disco", toCloud.json?.persisted === true, JSON.stringify(toCloud.json));

    const afterGet = await req("GET", "/api/voice/mode");
    check("GET refleja el cambio sin reiniciar", afterGet.json?.mode === "cloud", JSON.stringify(afterGet.json));

    const onDisk = JSON.parse(fs.readFileSync(configFile, "utf8"));
    check("el fichero del Gateway queda con realtime.enabled=true", onDisk.plugins?.entries?.["mykos-ui"]?.config?.realtime?.enabled === true);

    const backToLocal = await req("POST", "/api/voice/mode", { mode: "local" });
    check("vuelve a local (200)", backToLocal.status === 200 && backToLocal.json?.mode === "local", JSON.stringify(backToLocal.json));
    const finalGet = await req("GET", "/api/voice/mode");
    check("GET confirma la vuelta a local", finalGet.json?.mode === "local", JSON.stringify(finalGet.json));
  } else {
    check("sin credencial: rechaza la nube (409) y no cambia nada", toCloud.status === 409 && toCloud.json?.code === "realtime_not_configured", JSON.stringify(toCloud.json));
    const afterGet = await req("GET", "/api/voice/mode");
    check("sigue en local tras el rechazo", afterGet.json?.mode === "local", JSON.stringify(afterGet.json));
  }

  console.log(`\n==> ${passed}/${passed + failed} comprobaciones correctas`);
  process.exit(failed ? 1 : 0);
})();
