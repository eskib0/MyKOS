// Pruebas de la limpieza del texto hablado: envoltorio JSON del modelo y símbolos.
//   - Gateway: unwrapAnswer (voice-engine.js) y su uso al guardar y al reinyectar el historial.
//   - Navegador: unwrapJsonAnswer / speakableText de static/app.js (se extraen del fichero y se ejecutan).
const os = require("os");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { pathToFileURL } = require("url");

const repo = path.resolve(__dirname, "..", "..");
let passed = 0;
let failed = 0;
function check(label, value, detail = "") {
  if (value) { passed += 1; console.log(`OK     ${label}${detail ? `  ${detail}` : ""}`); }
  else { failed += 1; console.log(`FALLA  ${label}${detail ? `  ${detail}` : ""}`); }
}

const REAL = '{"respuesta":"Entendido, Usuario. A partir de ahora responderé de forma limpia y natural, sin mostrar comillas, etiquetas ni instrucciones internas."}';
const CLEAN = "Entendido, Usuario. A partir de ahora responderé de forma limpia y natural, sin mostrar comillas, etiquetas ni instrucciones internas.";

(async () => {
  const { unwrapAnswer } = await import(pathToFileURL(path.join(repo, "gateway-plugin", "mykos-ui", "voice-engine.js")).href);

  check("Gateway: quita {\"respuesta\":…} (caso real)", unwrapAnswer(REAL) === CLEAN);
  check("Gateway: JSON dentro de bloque de código", unwrapAnswer("```json\n" + REAL + "\n```") === CLEAN);
  check("Gateway: cadena JSON entre comillas", unwrapAnswer(JSON.stringify(CLEAN)) === CLEAN);
  check("Gateway: envoltorio doble", unwrapAnswer(JSON.stringify({ answer: REAL })) === CLEAN);
  check("Gateway: clave en inglés", unwrapAnswer('{"answer":"Hola"}') === "Hola");
  check("Gateway: texto normal intacto", unwrapAnswer("Hola, ¿qué tal?") === "Hola, ¿qué tal?");
  check("Gateway: JSON legítimo con varias claves intacto", unwrapAnswer('{"nombre":"Usuario","edad":40}') === '{"nombre":"Usuario","edad":40}');
  check("Gateway: JSON de una clave no reconocida intacto", unwrapAnswer('{"nombre":"Usuario"}') === '{"nombre":"Usuario"}');
  check("Gateway: JSON roto intacto", unwrapAnswer('{"respuesta":"falta el cierre') === '{"respuesta":"falta el cierre');
  check("Gateway: valor no textual intacto", unwrapAnswer('{"respuesta":{"a":1}}') === '{"respuesta":{"a":1}}');
  check("Gateway: vacío", unwrapAnswer("") === "" && unwrapAnswer(null) === "");

  // Se extraen las funciones del navegador de static/app.js y se ejecutan aisladas.
  const app = fs.readFileSync(path.join(repo, "static", "app.js"), "utf8");
  const start = app.indexOf("const ANSWER_WRAPPER_KEYS");
  const end = app.indexOf("async function handleRealtimeDelegation");
  check("navegador: bloque de limpieza presente", start > 0 && end > start);
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(app.slice(start, end) + "\nthis.speakableText = speakableText; this.unwrapJsonAnswer = unwrapJsonAnswer;", sandbox);
  const { speakableText, unwrapJsonAnswer } = sandbox;

  check("navegador: quita el envoltorio JSON", unwrapJsonAnswer(REAL) === CLEAN);
  check("navegador: la voz recibe la frase sin comillas ni llaves", speakableText(REAL) === CLEAN, JSON.stringify(speakableText(REAL)));
  const markdown = "## Resumen\n- **Entendido**, mira `esto` y [este enlace](https://x.com/a?b=1).\n> «Cita» (entre paréntesis) y \"comillas\" & 50%.";
  const spoken = speakableText(markdown);
  check("navegador: quita markdown, enlaces y símbolos", !/[*_`#>{}\[\]()"«»\\/]|https?:/.test(spoken), JSON.stringify(spoken));
  check("navegador: el título queda separado por una pausa", spoken.startsWith("Resumen. Entendido"), JSON.stringify(spoken));
  check("navegador: conserva las palabras y la puntuación", /Entendido, mira esto y este enlace\./.test(spoken) && /Cita/.test(spoken) && /por ciento/.test(spoken), JSON.stringify(spoken));
  check("navegador: los emojis no se leen", speakableText("Listo ✅ hecho 🍄") === "Listo hecho", JSON.stringify(speakableText("Listo ✅ hecho 🍄")));
  check("navegador: nunca deja la frase vacía por un error de formato", speakableText("Hola.") === "Hola.");

  console.log(`\n==> ${passed}/${passed + failed} comprobaciones correctas`);
  process.exit(failed ? 1 : 0);
})();
