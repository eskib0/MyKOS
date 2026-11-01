// Prueba unitaria del motor de turnos de voz (fase 5.2), con modelos de prueba.
const os = require("os");
const path = require("path");
const { pathToFileURL } = require("url");

const repo = path.resolve(__dirname, "..", "..");
let passed = 0;
let failed = 0;
function check(label, value, detail = "") {
  if (value) { passed += 1; console.log(`OK     ${label}${detail ? `  ${detail}` : ""}`); }
  else { failed += 1; console.log(`FALLA  ${label}${detail ? `  ${detail}` : ""}`); }
}
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

(async () => {
  const { CallRegistry } = await import(pathToFileURL(path.join(repo, "gateway-plugin", "mykos-ui", "calls.js")).href);
  const { VoiceCallEngine, VoiceEngineError, splitVoicePhrases } = await import(pathToFileURL(path.join(repo, "gateway-plugin", "mykos-ui", "voice-engine.js")).href);
  const doc = { revision: 1, data: { conversations: [{ id: "session-voice", title: "Voz", messages: [] }] } };
  const store = {
    get(name) { return name === "conversations" ? doc : null; },
    put(name, data, options) {
      if (name !== "conversations" || options.expectedRevision !== doc.revision) throw new Error("revisión inesperada");
      doc.revision += 1;
      doc.data = data;
      return { revision: doc.revision };
    },
  };
  const registry = new CallRegistry({ store, isActive: () => true });
  const spoken = [];
  const responses = [];
  const engine = new VoiceCallEngine({
    registry,
    store,
    contextBuilder: (messages) => messages,
    responder: async ({ messages, signal }) => {
      if (messages.at(-1)?.content === "interrumpe") {
        await new Promise((resolve, reject) => {
          const timer = setTimeout(resolve, 200);
          signal.addEventListener("abort", () => { clearTimeout(timer); reject(new Error("cancelado")); }, { once: true });
        });
      }
      responses.push(messages.at(-1)?.content);
      return { text: "Primera frase. Segunda frase." };
    },
    synthesizer: async (phrase, { signal }) => {
      if (signal.aborted) throw new Error("cancelado");
      spoken.push(phrase);
      return { ok: true, audio: `audio:${phrase}` };
    },
  });

  check("divide la respuesta en frases para TTS", JSON.stringify(splitVoicePhrases("Una. Dos? Tres!")) === JSON.stringify(["Una.", "Dos?", "Tres!"]));
  const call = registry.create({ sessionId: "session-voice" });
  const first = await engine.turn(call.callId, { turnId: "turn-1", transcript: "Hola MyKOS" });
  check("un turno activa la llamada", first.ok && first.call.state === "active");
  check("pasa el contexto al modelo", responses.length === 1 && responses[0] === "Hola MyKOS");
  check("guarda usuario y asistente en la conversación", doc.data.conversations[0].messages.map((m) => m.role).join(",") === "user,assistant");
  check("sintetiza por frases y conserva el orden", spoken.join("|") === "Primera frase.|Segunda frase.");
  check("devuelve audio separado por frases", first.audio.length === 2 && first.audio[0].audio === "audio:Primera frase.");
  const repeated = await engine.turn(call.callId, { turnId: "turn-1", transcript: "no debe repetirse" });
  check("un turnId repetido es idempotente", repeated.text === first.text && doc.data.conversations[0].messages.length === 2);

  const second = await engine.turn(call.callId, { turnId: "turn-2", transcript: "otra pregunta" });
  check("el segundo turno reutiliza la misma llamada", second.ok && second.call.callId === call.callId && doc.data.conversations[0].messages.length === 4);

  const onPhraseSeen = [];
  const third = await engine.turn(call.callId, {
    turnId: "turn-onphrase",
    transcript: "una tercera",
    onPhrase: async (piece) => { onPhraseSeen.push(`${piece.index}/${piece.total}:${piece.phrase}`); },
  });
  check(
    "onPhrase avisa en orden antes de terminar el turno, sin cambiar el resultado",
    JSON.stringify(onPhraseSeen) === JSON.stringify(["0/2:Primera frase.", "1/2:Segunda frase."])
      && third.audio.length === 2 && third.audio[0].audio === "audio:Primera frase.",
  );

  const pending = new VoiceCallEngine({
    registry,
    store,
    contextBuilder: (messages) => messages,
    responder: async () => ({ text: "Necesito permiso.", pending_action: { id: "approval-1" } }),
    synthesizer: async () => { throw new Error("no debe locutar una aprobación"); },
  });
  const approval = await pending.turn(call.callId, { turnId: "turn-approval", transcript: "crea un archivo" });
  check("una acción sensible vuelve como aprobación", approval.pending_action?.id === "approval-1" && approval.audio.length === 0);

  registry.end(call.callId);
  const interruptCall = registry.create({ sessionId: "session-voice" });
  const interrupting = new VoiceCallEngine({ registry, store, responder: engine.responder, synthesizer: engine.synthesizer });
  const interruptedPromise = interrupting.turn(interruptCall.callId, { turnId: "turn-interrupt", transcript: "interrumpe" }).catch((error) => error);
  await wait(20);
  const interruptedState = interrupting.interrupt(interruptCall.callId);
  const interrupted = await interruptedPromise;
  check("interrumpir aborta el modelo pendiente", interrupted instanceof VoiceEngineError && interrupted.code === "turn_interrupted");
  check("la llamada queda marcada como interrupted", interruptedState.state === "interrupted");
  check("no hay audio después de una interrupción", spoken.filter((item) => item.includes("Primera")).length === 3);

  console.log(`\n==> ${passed}/${passed + failed} comprobaciones correctas`);
  process.exitCode = failed ? 1 : 0;
})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
