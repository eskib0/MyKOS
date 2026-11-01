// Uso: node make-config.cjs <tag> [opciones]
//
// Crea  <home>/mykos-gateway-test/state-<tag>/mykos-gateway.json  a partir de la configuración REAL
// de MyKOS (solo lectura) para lanzar un Gateway desechable. No modifica nada del Gateway real.
//
//   --port <n>          puerto del Gateway de prueba (por defecto 18795)
//   --no-plugin         no carga ningún plugin
//   --plugin <ruta>     carpeta del plugin mykos-ui (por defecto: el del repositorio)
//   --static <ruta>     plugins.entries.mykos-ui.config.staticDir
//   --project <ruta>    config.projectDir (carpeta con server.py; por defecto, la de staticDir)
//   --backend <url>     config.backend.url, p. ej. http://127.0.0.1:3299
//   --spawn             config.backend.spawn=true: el plugin lanza y supervisa server.py
//   --python <exe>      config.backend.python
//   --script <ruta>     config.backend.script (solo para backends de prueba)
//   --allow-origin <o>  añade un origin a config.allowedOrigins (repetible)
//   --store             config.store.enabled=true: el Gateway es dueño de las conversaciones y la memoria (fase 2).
//                       La carpeta del almacén es <estado>/mykos y el origen de la importación <projectDir>/data.
//   --lax-routes        config.routes.strict=false: el Gateway reenvía también rutas /api/* que no están en la tabla
//                       (solo para probar el proxy contra un backend falso, que inventa rutas /api/__t/...).
//   --lax-policy        config.policy.strict=false: el Gateway no valida ni limita los servicios auxiliares y no firma
//                       la decisión (solo para el proxy con backend falso, que responde a POST inventados).
//   --chat-loop         config.chatLoop.enabled=true: el bucle de chat con herramientas del modelo local lo ejecuta el
//                       Gateway (chat-loop.js) y Python solo ejecuta las herramientas y acciones que este le pide.
const fs = require("fs");
const path = require("path");
const os = require("os");

const args = process.argv.slice(2);
const tag = args.shift();
if (!tag || tag.startsWith("--")) throw new Error("falta <tag>");

const opt = { port: 18795, plugin: undefined, noPlugin: false, static: undefined, project: undefined, backend: undefined, spawn: false, python: undefined, script: undefined, origins: [], store: false, laxRoutes: false, laxPolicy: false, chatLoop: false };
for (let i = 0; i < args.length; i += 1) {
  const a = args[i];
  if (a === "--no-plugin") opt.noPlugin = true;
  else if (a === "--lax-routes") opt.laxRoutes = true;
  else if (a === "--lax-policy") opt.laxPolicy = true;
  else if (a === "--chat-loop") opt.chatLoop = true;
  else if (a === "--store") opt.store = true;
  else if (a === "--spawn") opt.spawn = true;
  else if (a === "--port") opt.port = Number(args[++i]);
  else if (a === "--plugin") opt.plugin = args[++i];
  else if (a === "--static") opt.static = args[++i];
  else if (a === "--project") opt.project = args[++i];
  else if (a === "--backend") opt.backend = args[++i];
  else if (a === "--python") opt.python = args[++i];
  else if (a === "--script") opt.script = args[++i];
  else if (a === "--allow-origin") opt.origins.push(args[++i]);
  else throw new Error(`opción desconocida: ${a}`);
}

const slash = (p) => String(p).replace(/\\/g, "/");
const home = slash(os.homedir());
const test = `${home}/.mykos/gateway-test`;
const live = `${home}/.mykos/gateway-state/mykos-gateway.json`;
const repo = slash(path.resolve(__dirname, "..", ".."));
const stateDir = `${test}/state-${tag}`;
const wsDir = `${test}/workspace-${tag}`;
fs.mkdirSync(stateDir, { recursive: true });
fs.mkdirSync(wsDir, { recursive: true });

const cfg = JSON.parse(fs.readFileSync(live, "utf8"));
delete cfg.plugins; // la config real puede llevar ya el plugin: la prueba decide qué carga
cfg.gateway.port = opt.port;
cfg.agents.defaults.workspace = wsDir;

if (!opt.noPlugin) {
  const pluginCfg = {};
  if (opt.static) pluginCfg.staticDir = slash(opt.static);
  if (opt.project) pluginCfg.projectDir = slash(opt.project);
  if (opt.origins.length) pluginCfg.allowedOrigins = opt.origins;
  if (opt.store) pluginCfg.store = { enabled: true };
  if (opt.laxRoutes) pluginCfg.routes = { strict: false };
  if (opt.laxPolicy) pluginCfg.policy = { strict: false };
  if (opt.chatLoop) pluginCfg.chatLoop = { enabled: true };
  if (opt.backend) {
    pluginCfg.backend = { url: opt.backend, spawn: opt.spawn };
    if (opt.python) pluginCfg.backend.python = slash(opt.python);
    if (opt.script) pluginCfg.backend.script = slash(opt.script);
  }
  cfg.plugins = {
    load: { paths: [slash(opt.plugin || `${repo}/gateway-plugin/mykos-ui`)] },
    entries: { "mykos-ui": { enabled: true, ...(Object.keys(pluginCfg).length ? { config: pluginCfg } : {}) } },
  };
}

const out = path.join(stateDir, "mykos-gateway.json");
fs.writeFileSync(out, JSON.stringify(cfg, null, 2));
console.log(JSON.stringify({ out, port: cfg.gateway.port, plugins: cfg.plugins ?? null }));
