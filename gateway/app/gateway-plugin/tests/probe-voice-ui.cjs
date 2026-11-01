// Comprobación estática de la interfaz de llamada manos libres: no conserva el Gateway principal
// ni exige pulsar un botón para cerrar/enviar cada turno.
const fs = require("fs");
const os = require("os");
const path = require("path");

const repo = path.resolve(__dirname, "..", "..");
const app = fs.readFileSync(path.join(repo, "static", "app.js"), "utf8");
const html = fs.readFileSync(path.join(repo, "static", "index.html"), "utf8");
const gateway = fs.readFileSync(path.join(repo, "gateway-plugin", "mykos-ui", "index.js"), "utf8");
let passed = 0;
let failed = 0;
function check(label, value) { if (value) { passed += 1; console.log(`OK     ${label}`); } else { failed += 1; console.log(`FALLA  ${label}`); } }

check("la interfaz crea llamadas en el Gateway de MyKOS", app.includes("/api/sessions/") && app.includes("/api/calls/") && app.includes("/interrupt"));
check("la interfaz transcribe con la frontera local de Whisper", app.includes("/api/transcribe"));
check("la interfaz reproduce los fragmentos de audio devueltos por la llamada", app.includes("playVoiceAudio") && app.includes("content_type") && app.includes("state.localVoiceAudio"));
check("abre el micrófono una sola vez para la llamada", app.includes("openHandsFreeMicrophone") && app.includes("echoCancellation") && app.includes("createMediaStreamSource"));
check("delimita turnos automáticamente por voz y silencio", app.includes("monitorVoiceActivity") && app.includes("VOICE_VAD") && app.includes("beginAutomaticVoiceRecording"));
check("interrumpir hablando corta audio y cancela el turno", app.includes("interruptVoiceForBargeIn") && app.includes("localVoiceTurnAbort?.abort()"));
check("la llamada sustituye visualmente al chat mientras está activa", html.includes('id="voice-call-stage"') && app.includes("setVoiceCallUi") && !app.includes('"Enviar turno"'));
check("existe un control separado para colgar", html.includes('id="voice-hangup-button"') && html.includes('id="voice-stage-hangup-button"'));
check("Realtime de OpenAI usa WebRTC propio de MyKOS y no el camino heredado de MyKOS", app.includes("startRealtimeVoiceCall") && app.includes("/realtime") && app.includes("RTCPeerConnection") && !/ws_url|openai\/realtime\/calls|disabled-voice-auth/.test(app));
check("Gemini Live es un tercer modo y usa WebSocket con token efímero", html.includes('id="voice-mode-gemini"') && app.includes('setVoiceMode("gemini")') && app.includes("startGeminiLiveVoiceCall") && gateway.includes("BidiGenerateContentConstrained") && app.includes("access_token"));
check("Gemini Live declara herramientas y las retransmite al Gateway de MyKOS", app.includes("functionDeclarations") && app.includes("/gemini-tools") && gateway.includes("runGeminiLiveFunctionCalls"));
check("la API key de Gemini no llega al navegador", !/AIza[A-Za-z0-9_-]{20,}/.test(app) && app.includes("/gemini-live") && gateway.includes("auth_tokens/"));
check("Realtime devuelve cada delegación al motor, permisos y memoria de MyKOS", app.includes("handleRealtimeDelegation") && app.includes("delegation.context.append") && app.includes("synthesize: false"));
check("el chat escrito no llama a TTS por su cuenta", !app.includes("speakAssistantResponse") && !/sendMessage[\s\S]{0,12000}\/api\/tts/.test(app));

console.log(`\n==> ${passed}/${passed + failed} comprobaciones correctas`);
process.exitCode = failed ? 1 : 0;
