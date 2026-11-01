#!/usr/bin/env node
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const require = createRequire(import.meta.url);

function parseCliArgs(argv) {
  const opts = { port: null, host: null, configPath: null };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--port" && argv[i + 1]) {
      opts.port = Number(argv[++i]);
    } else if (arg === "--host" && argv[i + 1]) {
      opts.host = String(argv[++i]);
    } else if (arg === "--config" && argv[i + 1]) {
      opts.configPath = path.resolve(argv[++i]);
    }
  }
  return opts;
}

const cli = parseCliArgs(process.argv.slice(2));
const homeDir = os.homedir();
const stateDir = path.resolve(
  process.env.MYKOS_GATEWAY_STATE_DIR || path.join(homeDir, ".mykos", "gateway-state"),
);
const workspaceDir = path.resolve(
  process.env.MYKOS_GATEWAY_WORKSPACE_DIR || path.join(homeDir, ".mykos", "workspace"),
);
const configPath = path.resolve(
  cli.configPath || process.env.MYKOS_GATEWAY_CONFIG || path.join(stateDir, "mykos-gateway.json"),
);

process.env.MYKOS_GATEWAY_STATE_DIR = stateDir;
process.env.MYKOS_GATEWAY_WORKSPACE_DIR = workspaceDir;
process.env.MYKOS_GATEWAY_CONFIG = configPath;

fs.mkdirSync(stateDir, { recursive: true, mode: 0o700 });
fs.mkdirSync(workspaceDir, { recursive: true, mode: 0o700 });

const defaultAppDir = path.resolve(__dirname, "..", "app");
const defaultPluginDir = path.join(defaultAppDir, "gateway-plugin", "mykos-ui");

function loadOrCreateConfig(filePath) {
  if (fs.existsSync(filePath)) {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  }
  const venvPython = process.platform === "win32"
    ? path.join(homeDir, ".mykos", "venv", "Scripts", "python.exe")
    : path.join(homeDir, ".mykos", "venv", "bin", "python");
  const defaultPython = process.env.MYKOS_BACKEND_PYTHON
    || (fs.existsSync(venvPython) ? venvPython : (process.platform === "win32" ? "python" : "python3"));
  const initialConfig = {
    gateway: {
      host: "127.0.0.1",
      port: Number(process.env.MYKOS_GATEWAY_PORT || 3210),
    },
    agents: {
      defaults: {
        workspace: workspaceDir,
      },
    },
    plugins: {
      load: {
        paths: [defaultPluginDir],
      },
      entries: {
        "mykos-ui": {
          enabled: true,
          config: {
            projectDir: defaultAppDir,
            staticDir: path.join(defaultAppDir, "static"),
            store: {
              enabled: true,
            },
            chatLoop: {
              enabled: true,
            },
            backend: {
              url: `http://127.0.0.1:${Number(process.env.MYKOS_BACKEND_PORT || 3211)}`,
              spawn: true,
              python: defaultPython,
              script: path.join(defaultAppDir, "server.py"),
            },
          },
        },
      },
    },
  };
  fs.mkdirSync(path.dirname(filePath), { recursive: true, mode: 0o700 });
  fs.writeFileSync(filePath, `${JSON.stringify(initialConfig, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  return initialConfig;
}

const config = loadOrCreateConfig(configPath);
const port = Number(
  cli.port || process.env.MYKOS_GATEWAY_PORT || config?.gateway?.port || 3210,
);
const host = String(
  cli.host || process.env.MYKOS_GATEWAY_HOST || config?.gateway?.host || "127.0.0.1",
);
process.env.MYKOS_GATEWAY_PORT = String(port);

function createLogger(prefix) {
  const stamp = () => new Date().toISOString();
  return {
    info: (msg, ...rest) => console.log(`[${stamp()}] [INFO] [${prefix}] ${msg}`, ...rest),
    warn: (msg, ...rest) => console.warn(`[${stamp()}] [WARN] [${prefix}] ${msg}`, ...rest),
    error: (msg, ...rest) => console.error(`[${stamp()}] [ERROR] [${prefix}] ${msg}`, ...rest),
  };
}

const gatewayLogger = createLogger("mykos-gateway");
const routes = [];
const services = [];

function registerPlugin(pluginDir, entryId, entryConfig) {
  const resolvedDir = path.resolve(pluginDir);
  const pkgPath = path.join(resolvedDir, "package.json");
  let entryFile = path.join(resolvedDir, "index.js");
  if (fs.existsSync(pkgPath)) {
    const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
    const configuredMain = pkg?.mykos?.extensions?.[0] || pkg?.main;
    if (configuredMain) {
      entryFile = path.resolve(resolvedDir, configuredMain);
    }
  }
  const mod = require(entryFile);
  const plugin = mod?.default || mod;
  if (!plugin || typeof plugin.register !== "function") {
    throw new Error(`El plugin en ${resolvedDir} no exporta register(api)`);
  }
  const pluginId = plugin.id || entryId || path.basename(resolvedDir);
  const api = {
    id: pluginId,
    rootDir: resolvedDir,
    source: entryFile,
    registrationMode: "full",
    pluginConfig: entryConfig || {},
    config,
    runtime: {
      state: {
        resolveStateDir: () => stateDir,
      },
    },
    logger: createLogger(pluginId),
    registerHttpRoute(route) {
      if (!route || typeof route.path !== "string" || typeof route.handler !== "function") {
        throw new Error(`Ruta inválida registrada por ${pluginId}`);
      }
      routes.push({
        path: route.path,
        match: route.match === "prefix" ? "prefix" : "exact",
        auth: route.auth || "none",
        handler: route.handler,
      });
    },
    registerService(service) {
      if (!service || typeof service.start !== "function") return;
      services.push({
        id: service.id || `${pluginId}-service`,
        start: service.start.bind(service),
        stop: typeof service.stop === "function" ? service.stop.bind(service) : async () => {},
        logger: api.logger,
      });
    },
  };
  plugin.register(api);
}

const loadPaths = Array.isArray(config?.plugins?.load?.paths) ? config.plugins.load.paths : [];
const entries = config?.plugins?.entries && typeof config.plugins.entries === "object" ? config.plugins.entries : {};

for (const pluginPath of loadPaths) {
  const manifestPath = path.join(pluginPath, "mykos.plugin.json");
  let pluginId = path.basename(pluginPath);
  if (fs.existsSync(manifestPath)) {
    try {
      const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
      if (manifest?.id) pluginId = manifest.id;
    } catch {}
  }
  const entry = entries[pluginId] ?? { enabled: true, config: {} };
  if (entry.enabled === false) continue;
  registerPlugin(pluginPath, pluginId, entry.config || {});
}

// Ordenar rutas: primero exactas, luego prefijos de mayor a menor longitud
routes.sort((a, b) => {
  if (a.match !== b.match) return a.match === "exact" ? -1 : 1;
  return b.path.length - a.path.length;
});

function matchRoute(pathname) {
  for (const route of routes) {
    if (route.match === "exact" && pathname === route.path) return route;
  }
  for (const route of routes) {
    if (route.match === "prefix" && pathname.startsWith(route.path)) return route;
  }
  return null;
}

const server = http.createServer(async (req, res) => {
  try {
    const rawUrl = req.url || "/";
    const qIdx = rawUrl.indexOf("?");
    const pathname = qIdx >= 0 ? rawUrl.slice(0, qIdx) : rawUrl;

    if (pathname === "/health" || pathname === "/healthz") {
      const body = JSON.stringify({ ok: true, status: "live", service: "mykos-gateway" });
      res.writeHead(200, {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": Buffer.byteLength(body),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      });
      res.end(body);
      return;
    }

    const route = matchRoute(pathname);
    if (!route) {
      const body = JSON.stringify({ ok: false, error: "Ruta no encontrada" });
      res.writeHead(404, {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": Buffer.byteLength(body),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      });
      res.end(body);
      return;
    }

    await route.handler(req, res);
  } catch (err) {
    gatewayLogger.error(`Error procesando ${req.method} ${req.url}: ${err?.stack || err}`);
    if (!res.headersSent) {
      const body = JSON.stringify({ ok: false, error: "Error interno en MyKOS Gateway" });
      res.writeHead(500, {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": Buffer.byteLength(body),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      });
      res.end(body);
    } else if (!res.writableEnded) {
      res.end();
    }
  }
});

async function startGateway() {
  for (const svc of services) {
    const ctx = {
      serviceHealth: {
        clearFailure: () => {},
        reportFailure: (err) => svc.logger.error(`Fallo en servicio ${svc.id}: ${err?.message || err}`),
      },
    };
    await svc.start(ctx);
  }

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => {
      server.removeListener("error", reject);
      resolve();
    });
  });

  gatewayLogger.info(`MyKOS Gateway escuchando en http://${host}:${port} (estado: ${stateDir})`);
}

let shuttingDown = false;
async function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  gatewayLogger.info(`Recibida señal ${signal}, cerrando MyKOS Gateway...`);
  const timeoutMs = Number(process.env.MYKOS_GATEWAY_SHUTDOWN_TIMEOUT_MS || 5000);
  const timer = setTimeout(() => {
    gatewayLogger.warn("Tiempo de apagado agotado, forzando salida.");
    process.exit(0);
  }, timeoutMs);
  timer.unref?.();

  try {
    await new Promise((resolve) => server.close(() => resolve()));
  } catch {}

  for (const svc of services) {
    try {
      await svc.stop({});
    } catch (err) {
      svc.logger.warn(`Error deteniendo servicio ${svc.id}: ${err?.message || err}`);
    }
  }
  process.exit(0);
}

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGHUP", () => shutdown("SIGHUP"));

startGateway().catch((err) => {
  gatewayLogger.error(`No se pudo iniciar MyKOS Gateway: ${err?.stack || err}`);
  process.exit(1);
});
