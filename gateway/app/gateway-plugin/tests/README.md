# Pruebas del plugin `mykos-ui` y del lanzador `mykos`

Todo se prueba en un **MyKOS desechable** antes de tocar el real: Gateway de prueba en el puerto `18795`, backend de
prueba en `3299`, y estado, datos y copia del proyecto propios en `~/mykos-gateway-test\`
(carpeta temporal: cada prueba la crea y se puede borrar entera). No tocan el MyKOS real (`3210`/`3211`), sus datos
ni el MyKOS principal (`18789`). Solo `e2e-chat.cjs` se ejecuta contra el MyKOS real (y no deja rastro).

Los `probe-*.cjs` imprimen `OK` / `FALLA` por comprobación y terminan con código distinto de 0 si algo falla.

## Cómo ejecutarlas

Desde `~/mykos\gateway-plugin\tests`. Las que necesitan un Gateway lo lanzan con
`run-isolated-test.ps1` (arranca el Gateway desechable, espera a que esté estable, ejecuta el script y lo cierra
siempre, aunque el script falle):

```powershell
# Proxy /api/* contra un backend falso (52 comprobaciones; SLOW_MS = duración de la respuesta lenta)
node make-config.cjs P1 --backend http://127.0.0.1:3299 --static "C:/Users/Usuario/mykos/static" --lax-routes
$env:SLOW_MS = 100000
powershell -NoProfile -ExecutionPolicy Bypass -File .\run-isolated-test.ps1 -Tag P1 `
  -Extra "$PWD\probe-proxy.cjs" -ExtraArgs 3299 -ExtraTimeoutSec 300

# Interfaz estática sin backend (19 comprobaciones)
node make-config.cjs S1 --static "C:/Users/Usuario/mykos/static"
powershell -NoProfile -ExecutionPolicy Bypass -File .\run-isolated-test.ps1 -Tag S1 -Extra "$PWD\probe-static.cjs"

# Backend Python REAL supervisado por el plugin, sobre una copia con datos vacíos (25 comprobaciones)
$proj = node make-project.cjs B
node make-config.cjs B --spawn --backend http://127.0.0.1:3299 --project $proj --static "$proj/static" --python "C:/Program Files/Python314/python.exe"
$env:BACKEND_PORT = 3299; $env:PROJECT_DIR = $proj
powershell -NoProfile -ExecutionPolicy Bypass -File .\run-isolated-test.ps1 -Tag B -Extra "$PWD\probe-backend.cjs" -ExtraTimeoutSec 400
```

Sin Gateway (se ejecutan directamente con `node`):

```powershell
node probe-supervisor.cjs                                   # supervisión del backend, 27 comprobaciones
$env:PROJECT_DIR = (node make-project.cjs W); node probe-watchdog.cjs   # vigilante del padre en Python, 9
node probe-launcher.cjs             # mykos start/stop/restart/status con Gateway oculto, 22
node probe-launcher.cjs --visible   # ídem abriendo la ventana real unos segundos, 27
node probe-ctrlc.cjs --break        # cierre con Ctrl+Break (ver «Sin verificar»)
node probe-stress.cjs               # con run-isolated-test.ps1: 15.000 peticiones, latencias y errores por fase
node e2e-chat.cjs                   # SOBRE EL GATEWAY REAL: chat con el modelo local, crea y borra una conversación
node probe-store.cjs                # unitarias del almacén de datos (store.js), 47
node probe-routes.cjs               # tabla de rutas del Gateway (83 rutas), 25 comprobaciones
node probe-store-launcher.cjs       # mykos store on/off/status/verify de ida y vuelta con un MyKOS desechable, 31
node probe-remote-control.cjs       # frontera de modelos remotos: proxy permitido y URL arbitraria bloqueada, 2
node probe-media-routing.cjs        # /api/tts entra por el Gateway y llega al backend con token, 2
powershell -NoProfile -ExecutionPolicy Bypass -File .\run-phase5-regression.ps1  # contrato de llamadas 5.1, 30 comprobaciones
powershell -NoProfile -ExecutionPolicy Bypass -File .\run-phase5.2-regression.ps1 # turnos, frases TTS e interrupción, 29 comprobaciones
powershell -NoProfile -ExecutionPolicy Bypass -File .\run-phase5.3-regression.ps1 # interfaz nueva sin Talk/WebRTC heredado, 6 + 19 comprobaciones
powershell -NoProfile -ExecutionPolicy Bypass -File .\run-phase5.4-regression.ps1 # audio sintético -> transcripción -> llamada -> Luna/TTS falsos -> interrupción, 10 comprobaciones
```

**Almacén de datos del Gateway (fases 2a/2b).** Necesita una copia de tus datos y dos ejecuciones seguidas del mismo Gateway desechable (misma etiqueta `S`; para `corrupt`, la `C`). Todo sobre copias: los datos reales no se tocan.

```powershell
$t = "$HOME\mykos-gateway-test"; $p = "C:/Users/Usuario/mykos-gateway-test/project-S"
node make-project.cjs S --with-data                       # copia el código y COPIAS de los cinco documentos de MyKOS
node make-config.cjs S --spawn --backend http://127.0.0.1:3299 --project $p --static "$p/static" --python "C:/Program Files/Python314/python.exe" --store
$env:TAG = 'S'; $env:BACKEND_PORT = 3299; $env:PROJECT_DIR = $p
foreach ($ph in 'import', 'restart') {                   # import: 55 comprobaciones; restart: 25 (mismo estado, Gateway reiniciado)
  $env:PHASE = $ph
  powershell -NoProfile -ExecutionPolicy Bypass -File .\run-isolated-test.ps1 -Tag S -Extra "$PWD\probe-store-gateway.cjs" -ExtraTimeoutSec 400
}
# corrupt (10): un fichero antiguo cortado no debe activar el almacén ni tocar nada
node make-project.cjs C --with-data; node corrupt-legacy.cjs C
node make-config.cjs C --spawn --backend http://127.0.0.1:3299 --project "C:/Users/Usuario/mykos-gateway-test/project-C" --static "C:/Users/Usuario/mykos-gateway-test/project-C/static" --python "C:/Program Files/Python314/python.exe" --store
$env:TAG = 'C'; $env:PHASE = 'corrupt'; $env:PROJECT_DIR = "C:/Users/Usuario/mykos-gateway-test/project-C"
powershell -NoProfile -ExecutionPolicy Bypass -File .\run-isolated-test.ps1 -Tag C -Extra "$PWD\probe-store-gateway.cjs" -ExtraTimeoutSec 300
```

Antes de repetir `import` hay que empezar de cero: `node make-project.cjs S --with-data` y borrar `state-S`.

## Qué comprueba cada fichero

| Fichero | Función |
|---|---|
| `make-config.cjs` | Genera `state-<tag>/mykos-gateway.json` desde la config real (solo lectura). Opciones: `--port`, `--plugin`, `--static`, `--project`, `--backend`, `--spawn`, `--python`, `--allow-origin`, `--no-plugin`, `--store`, `--lax-routes` (el Gateway reenvía también rutas fuera de la tabla: solo para el proxy contra un backend falso). **Con `--store` pasa siempre `--project` de una copia de prueba.** |
| `make-project.cjs` | Copia el código de MyKOS con `data/` y `workspace/` vacíos, para probar el backend real sin tocar tus datos. Con `--with-data` copia además, COMO COPIA, los cinco documentos (`conversations.json`, `memory.json`, `memory_embeddings.json`, `permissions.json` y `approvals.json`) y guarda sus SHA-256 y recuentos (`originals-<tag>.json`). |
| `fake-upstream.cjs` | Backend falso con el comportamiento de `http.server` (HTTP/1.0, `Connection: close`), con endpoints de prueba en `/api/__t/`. |
| `fake-backend-child.cjs`, `exit-now.cjs` | Backends de mentira para la supervisión (con proceso nieto, arranque lento, caída inmediata). |
| `probe-static.cjs` | La interfaz servida es idéntica byte a byte a `static/`; `HEAD`, `404`, `405`; bloqueo de `..`, `%2e%2e`, `\`, `:flujo`, ocultos y `%00`; rutas del Gateway intactas; cabeceras. |
| `probe-proxy.cjs` | Ruta y consulta exactas; métodos; cabeceras y `Set-Cookie`; estados 204/302/4xx/5xx; binario y descarga de 20 MB; subidas de 1 y 30 MB y `chunked`; 40 peticiones simultáneas y 20 retenidas en paralelo; cancelación del navegador; bloqueo por `Host`/`Origin`; **las 83 rutas del Gateway**, GET y POST; 502 con el backend caído y recuperación; respuesta lenta con sondeos intermedios. |
| `probe-stress.cjs` | Latencia y errores por fases: backend directo, núcleo del Gateway, proxy GET/POST y concurrencia. Sirve para saber DÓNDE aparece un fallo. |
| `probe-backend.cjs` | El plugin lanza el `server.py` real: entorno del hijo, `/api/health`, API real, datos en la copia, web ajena rechazada, interfaz cargada en Edge sin cabeza, relanzado tras caer, y backend que no queda huérfano si muere el Gateway. |
| `probe-supervisor.cjs` | Clase `Backend` sin Gateway: arranque, parada de todo el árbol, reinicios con espera, límite de caídas, puerto ocupado por otro backend, sustitución, parada en pleno arranque, Python inexistente, tiempo de espera. |
| `probe-watchdog.cjs` | `MYKOS_PARENT_PID` en `server.py`: sigue vivo con el padre vivo, se apaga solo y limpio (código 0) cuando muere, y con un padre inexistente. |
| `probe-launcher.cjs` | `mykos.ps1`: start, status, start repetido, stop, restart, puertos ocupados por otros programas (no los toca), backend suelto de una ejecución anterior, ventana visible y ventana vacía tras caer el Gateway. Comprueba que el Gateway real y su ventana quedan intactos. |
| `send-ctrlc.ps1`, `probe-ctrlc.cjs` | Envían Ctrl+C / Ctrl+Break a la consola de un Gateway de prueba. |
| `e2e-chat.cjs` | Recorrido completo sobre el MyKOS real con el modelo local (`Gateway → proxy → Python → Gateway → llama.cpp → modelo`). Crea y borra una conversación temporal. |
| `probe-control.cjs` | Fase 3 en un MyKOS desechable: token interno, herramienta de lectura, rechazo de shell sin autorización y diario de solicitudes/resultados (8 comprobaciones). Usa `MYKOS_CONTROL_TOKEN` y `MYKOS_CONTROL_AUDIT_FILE` solo durante la prueba. |
| `probe-authority.cjs` | Segundo corte de fase 3: decisión de permiso, creación/rechazo de aprobación, cola, rutas públicas y compactación de contexto (10 comprobaciones). |
| `probe-authority-exec.cjs` | Segundo corte con backend Python real: aprobación, ejecución posterior a la decisión del Gateway y auditoría completa (4 comprobaciones). |
| `probe-remote-control.cjs` | Comprueba que un modelo remoto permitido usa el endpoint interno del Gateway y que no se puede convertir en un proxy hacia una URL arbitraria (2 comprobaciones). |
| `probe-media-routing.cjs` | Comprueba que TTS público se enruta al endpoint interno autenticado y no se ejecuta como una ruta pública directa del backend (2 comprobaciones). |
| `probe-calls.cjs` | Unitarias del registro de llamadas: sesión compartida, `callId`, estados, persistencia, duplicados y cierre idempotente (15 comprobaciones). |
| `probe-calls-gateway.cjs` | Gateway desechable con backend Python y almacén aislado: crear/leer/colgar llamada, límites, errores y limpieza de sesión (15 comprobaciones). |
| `fake-model.cjs`, `probe-model-control.cjs` | Motor falso y prueba del controlador de modelos sin cargar CUDA: selección llama.cpp, respuesta y diario (4 comprobaciones). |
| `probe-store.cjs` | Unitarias de `store.js`: token, revisiones, copias por enlace duro y poda, conflictos, validación de nombres y estructura, protección contra borrados masivos, atomicidad, recuperación de ficheros dañados, instantáneas, diario con SHA-256, documento de 8,8 MB, Unicode, importación todo o nada con deshacer y 300 escrituras seguidas. |
| `probe-store-gateway.cjs` | Almacén dentro de un Gateway desechable con el backend Python real y una copia de tus datos. `PHASE=import`: importación con SHA-256 idéntico, token/Host/Origin, rutas con `..`, API real, cargadores de Python, altas y bajas simultáneas, caída del backend, interfaz en Edge. `restart`: nada se reimporta ni se pierde, poda de copias, recuperación de documentos dañados. `corrupt`: fichero antiguo cortado, almacén inactivo y nada tocado. |
| `store_client_check.py` | Lo ejecuta `probe-store-gateway.cjs` en un proceso Python aparte con los cargadores REALES de MyKOS (`memory-roundtrip`, `unavailable`, `shrink`). |
| `corrupt-legacy.cjs` | Corta `conversations.json` de la copia de prueba y guarda su SHA-256, para la fase `corrupt`. |
| `check-real-store.cjs` | **Sobre el MyKOS real**, tras `mykos store on`: la API devuelve las conversaciones y la memoria de la copia previa (`architecture-backup/2026-09-25-phase2/data`), las conversaciones se abren completas, el contenido del almacén es idéntico, una conversación temporal se crea y se borra a través del almacén y la interfaz en un navegador muestra los títulos. |
| `probe-routes.cjs` | Sin Gateway: las 0 rutas de trabajador y las 83 propias del Gateway (83 entradas en total); cada ruta tiene dominio, acción, riesgo y propietario; `classifyRoute` clasifica bien parámetros, métodos, barras finales, mayúsculas y codificaciones raras (25 comprobaciones). |
| `test_antigravity_safety.py` | Suite de seguridad y robustez en Python: perfil aislado, validación de prompts, despacho remoto sin herramientas, inmutabilidad de archivos core en `allowedModes` (solo `once`), clasificación sensible de `rea_call_tool`, soporte estructurado de `store_corrupt` en `/api/chat` y medidor de contexto, y purga estricta de credenciales en subprocesos (8 comprobaciones). |
| `probe-worker-guard.cjs` | Gateway desechable con el `server.py` real: el trabajador responde 403 a todo `/api/*` sin token (19 rutas, web ajena, `Host` de «rebinding», 5 tokens erróneos), 200 con el token verdadero; el Gateway responde 404/405 a rutas inexistentes o métodos no permitidos sin llegar a Python; latido de nodo y retorno de OAuth atraviesan el Gateway; el diario clasifica cada petición y no guarda token ni cuerpos; relanzado del backend; arranque manual de `server.py` con y sin la puerta (30 comprobaciones). Necesita `CONTROL_TOKEN` = `MYKOS_CONTROL_TOKEN` del Gateway de prueba y `TAG`. |
| `probe-policy.cjs` | Sin Gateway: unitarias de `policy.js` (lista blanca de campos, tipos, formatos, tamaños, cabeceras obligatorias, límites concurrentes y por minuto, firma de la decisión ligada a método, ruta y cuerpo; 68 comprobaciones). |
| `probe-policy-gateway.cjs` | Gateway desechable con el `server.py` real (se lanza con `run-policy-test.ps1`): rechazos 400/403/411/413/415/429 en el Gateway sin llegar a Python, el trabajador rechaza 403 una decisión ausente, manipulada, caducada, de otra ruta o método, de formato desconocido o sin ligar al cuerpo en una ruta JSON, y 400 una decisión válida para otro cuerpo; las peticiones válidas atraviesan; el diario anota rechazos y decisiones sin token, claves ni cuerpos (52 comprobaciones). |
| `probe-payloads.cjs` | Gateway desechable con el `server.py` real: cargas malformadas (Unicode raro, anidados, cadenas de 3 MB) sobre el plano de control y la API pública, consultas GET hostiles (incluida la biblioteca de ficheros) y cabeceras hostiles: siempre un error limpio en JSON, sin trazas, sin caídas y sin escrituras en memoria, índice, permisos ni aprobaciones (13 comprobaciones). El canario de la biblioteca lleva un contenido distinto del nombre del fichero, para no confundir un eco de la ruta con una fuga. |
| `run-phase3d-regression.ps1` | Regresión por lotes: `-Batch A` (sin Gateway), `B` (backend falso), `C` (backend real, puerta y payloads), `D` (control, autoridad, ejecución de aprobación), `E` (bucle de chat del Gateway). |
| `run-phase5-regression.ps1` | Regresión de la fase 5.1: unitarias e integración desechable del contrato de llamadas, sin audio ni realtime (30 comprobaciones). |
| `probe-voice-engine.cjs` | Unitarias del motor de turnos: contexto compartido, respuestas por frases, TTS ordenado, idempotencia, aprobaciones e interrupción cancelable (12 comprobaciones). |
| `run-phase5.2-regression.ps1` | Regresión de la fase 5.2: unitarias del motor e integración del Gateway desechable (12 + 17 = 29 comprobaciones). No llama al MyKOS real ni a Luna. |
| `probe-voice-ui.cjs` | Comprueba que la interfaz usa las rutas de llamada de MyKOS, transcribe por la frontera local, reproduce el audio por frases, tiene Colgar y no conserva WebSocket/WebRTC/Talk ni TTS automático del chat escrito (6 comprobaciones). |
| `run-phase5.3-regression.ps1` | Regresión de la fase 5.3: prueba estática de la interfaz e integración de los ficheros servidos por un Gateway desechable (6 + 19 comprobaciones). |
| `fake-voice-backend.cjs` | Backend falso supervisado para 5.4: crea una conversación en el almacén de prueba y simula Whisper, Luna, Kokoro y las rutas mínimas de conversación; nunca usa credenciales ni el MyKOS real. |
| `probe-voice-synthetic.cjs` | Recorrido 5.4 por HTTP: audio sintético, transcripción, turno con dos audios, interrupción, colgado, persistencia y limpieza (10 comprobaciones). |
| `run-phase5.4-regression.ps1` | Lanza el Gateway y el backend falso como procesos supervisados en estado/puertos desechables y ejecuta la prueba sintética. |
| `probe-chat-loop.cjs` | Sin Gateway ni Python: unitarias de `chat-loop.js` con modelo, autoridad y trabajador falsos (respuesta directa, llama.cpp y Ollama, herramientas de lectura, acción sensible con y sin permiso, dos sensibles a la vez, límites web, respuesta vacía, ficha de investigación, límite de rondas, visión, argumentos rotos; 35 comprobaciones). |
| `probe-chat-loop-gateway.cjs` | Gateway desechable con el `server.py` real y un Ollama falso con guion (puerto 3301). `EXPECT=on` (27): operación `loop` directa, `/api/chat` completo, aprobación y continuación, permiso de sesión reutilizado y no heredado, errores del modelo, peticiones falsificadas. `EXPECT=off` (9): la operación responde 409 y el bucle de Python sigue funcionando, incluida la aprobación. Se lanza con `run-chat-loop-test.ps1 -Mode on|off`. |
| `check-real-guard.cjs` | **Sobre el MyKOS real**, tras activar el tercer corte: el trabajador (`:3211`) responde 403 a lo directo (sin token, `Host`/`Origin` ajenos, un POST simple que no debe crear nada); por el Gateway funcionan lectura y alta/baja de una conversación temporal, 404/405 en rutas o métodos inexistentes y 403 a webs ajenas; la interfaz real en un navegador no provoca ningún rechazo; el diario clasifica las peticiones. No modifica nada salvo esa conversación temporal. |
| `probe-store-launcher.cjs` | `mykos store on/off/status/verify` con un MyKOS desechable: ida y vuelta, exportación imposible que aborta sin cambiar nada, importación imposible que arranca con aviso, configuración del Gateway intacta salvo `store.enabled`. |

## Verificación real más reciente

Tras activar `mykos-ui` v0.5.0 en el MyKOS real: `/mykos-health` correcto, chat temporal con respuesta `OK` y borrado posterior, TTS local real con WAV, catálogo de proveedores autenticado y credenciales seleccionadas desde el estado de MyKOS. El corte de firmas de ejecución también está activo tras reinicio: el backend interno sin concesión devuelve `403`. La llamada local manos libres está implementada en la interfaz, pero el micrófono del navegador y una llamada Realtime/WebRTC aún no tienen prueba extremo a extremo.

## Reglas aprendidas (obligatorias al tocar el plugin)

1. **No importar el SDK por ruta relativa** (`../../dist/plugin-sdk/core.js`): el Gateway pasó de ~6 s a ~105 s de arranque y `/health` dejó de responder. La entrada del plugin es un objeto plano con `register(api)`.
2. **No localizar ficheros con `import.meta.url`**: el Gateway carga el plugin desde una copia temporal (`<estado>/tmp/plugin-captures/...`). Las rutas salen de `plugins.entries.mykos-ui.config`.
3. `register(api)` se ejecuta más de una vez por arranque: sin efectos al registrar. Los procesos se lanzan solo desde el servicio (`registerService`, modo `full`).
4. **Cambiar el plugin o su configuración requiere `mykos restart`.** El Gateway detecta el cambio pero rechaza la recarga en caliente mientras el servicio corre («Plugin mykos-ui still has active retained work»).
5. **Redirigir la salida de un proceso hijo a un pipe hace que quien captura `mykos start` se quede esperando** mientras el Gateway siga vivo. `mykos.ps1` lanza el Gateway con `ShellExecute` (sin heredar tuberías) por eso; no volver a `Start-Process -RedirectStandard*`.
6. Los ficheros de prueba se crean con el editor, no con `cat <<EOF`/`printf` desde la consola: se comen las barras invertidas y `\t` acaba siendo un tabulador.
7. Cambiar el plugin siempre se prueba primero aquí, nunca contra el Gateway real.

### Fase 3: plano de control

El plugin genera un token efímero por proceso para `mykos-control`; se lo entrega al backend mediante el entorno del hijo y no se guarda en `mykos-gateway.json`. `MYKOS_CONTROL_TOKEN` solo sirve para pruebas repetibles. El diario de control se escribe en `<estado de MyKOS>/mykos/control-journal.jsonl` o en la ruta indicada por `MYKOS_CONTROL_AUDIT_FILE`.

## Sin verificar (dicho con franqueza)

- **Ctrl+C real en la ventana del Gateway: verificado a mano por Usuario (26/09/2026): funciona y MyKOS se para.** Lo que sigue es por qué no se puede probar de forma automática. En este entorno automático Ctrl+C llega deshabilitado (la cadena de procesos lo hereda así) y no se puede inyectar; Ctrl+Break sí llega, pero el Gateway lo trata como muerte súbita. Comprobado en el código del Gateway que registra manejadores de `SIGINT`/`SIGTERM` que llaman a su cierre ordenado, y que la parada del servicio (`stop()`) funciona (probe-supervisor). Por cualquier otra vía (matar el Gateway, Ctrl+Break, cerrar la ventana, `mykos stop`) el backend no queda vivo.
- **Bloqueos del bucle de eventos del Gateway.** Aparecen a lo largo del día (5–30 s, algunos provocados por pruebas de carga o recarga) en los Gateways de esta máquina. Un `ETIMEDOUT` suelto en los primeros segundos tras arrancar no se pudo reproducir en 3 repeticiones ni en 15.000 peticiones. Como MyKOS ahora pasa por el Gateway, sus peticiones se quedarían esperando durante un bloqueo.
