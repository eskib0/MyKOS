import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const UA =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";
const META_AI_APP_ID = "1522763855472543";
const META_AI_OIDC_START_URL = "https://www.meta.ai/api/oidc/start";

async function readStdinJson() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf8").trim();
  return raw ? JSON.parse(raw) : {};
}

async function acquireSession() {
  let r = await fetch("https://www.meta.ai/", { headers: { "User-Agent": UA } });
  const cookies = (r.headers.getSetCookie ? r.headers.getSetCookie() : []).map(
    (c) => c.split(";")[0]
  );
  let text = await r.text();
  if (r.status === 403 && text.includes("__rd_verify_")) {
    const m = text.match(/fetch\([\x27"](\/__rd_verify_[^\x27"]+)[\x27"]/);
    if (m) {
      const r2 = await fetch("https://www.meta.ai" + m[1], {
        method: "POST",
        headers: { "User-Agent": UA },
      });
      cookies.push(
        ...(r2.headers.getSetCookie ? r2.headers.getSetCookie() : []).map(
          (c) => c.split(";")[0]
        )
      );
      r = await fetch("https://www.meta.ai/", {
        headers: { "User-Agent": UA, Cookie: cookies.join("; ") },
      });
      text = await r.text();
    }
  }
  const cookieMap = new Map();
  for (const c of cookies) {
    const eq = c.indexOf("=");
    if (eq > 0) cookieMap.set(c.slice(0, eq).trim(), c.trim());
  }
  let cookieHeader = [...cookieMap.values()].join("; ");

  const gqlResp = await fetch("https://www.meta.ai/api/graphql", {
    method: "POST",
    headers: {
      "User-Agent": UA,
      "Content-Type": "application/json",
      Accept: "application/json",
      Cookie: cookieHeader,
    },
    body: JSON.stringify({
      doc_id: "128302cfa314f375be53f53a266699fd",
      variables: {},
    }),
  });
  const gqlCookies = (
    gqlResp.headers.getSetCookie ? gqlResp.headers.getSetCookie() : []
  ).map((c) => c.split(";")[0]);
  for (const c of gqlCookies) {
    const eq = c.indexOf("=");
    if (eq > 0) cookieMap.set(c.slice(0, eq).trim(), c.trim());
  }
  cookieHeader = [...cookieMap.values()].join("; ");
  const gqlJson = await gqlResp.json();
  const tempUser = gqlJson?.data?.createTempUser;
  if (!tempUser?.accessToken || !tempUser?.abraUserId) {
    throw new Error("No se pudo obtener token OAuth de Meta AI (ecto1)");
  }
  const scripts = [
    ...new Set([
      ...[...text.matchAll(/src="(\/_next\/static\/[^"]+\.js)"/g)].map((m) => m[1]),
      ...[...text.matchAll(/href="(\/_next\/static\/[^"]+\.js)"/g)].map((m) => m[1]),
      ...[...text.matchAll(/static\/[^"'\s<>]+\.js/g)].map((m) => "/_next/" + m[0]),
    ]),
  ];
  return {
    accessToken: tempUser.accessToken,
    abraUserId: tempUser.abraUserId,
    cookieHeader,
    scripts,
    acquiredAt: Math.floor(Date.now() / 1000),
  };
}

const CHUNK_CACHE_TTL_SECONDS = 24 * 3600;

async function fetchTextBatch(urls, cookieHeader, concurrency = 12) {
  const results = new Map();
  let cursor = 0;
  async function worker() {
    while (cursor < urls.length) {
      const idx = cursor++;
      const url = urls[idx];
      if (!url || results.has(url)) continue;
      try {
        const res = await fetch("https://www.meta.ai" + url, {
          headers: { "User-Agent": UA, Cookie: cookieHeader || "" },
        });
        if (res.ok) {
          results.set(url, await res.text());
        }
      } catch {}
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, Math.max(1, urls.length)) }, () => worker()));
  return results;
}

function registerTurbopackArray(arr, startIdx, sourceUrl, factories) {
  let i = startIdx;
  while (i < arr.length) {
    if (Array.isArray(arr[i])) {
      registerTurbopackArray(arr[i], 0, sourceUrl, factories);
      i++;
      continue;
    }
    const ids = [];
    while (i < arr.length && typeof arr[i] === "number") {
      ids.push(arr[i++]);
    }
    const fn = arr[i++];
    if (typeof fn === "function") {
      for (const id of ids) factories.set(id, { ids, fn, sourceUrl });
    }
  }
}

function parseAsyncLoaders(chunkTexts) {
  const asyncLoaders = new Map();
  const re = /(\d+),\w+=>\{\w+\.v\(\w+=>Promise\.all\(\[([^\]]+)\].{0,120}?=>\w+\((\d+)\)\)/g;
  for (const txt of chunkTexts) {
    for (const m of txt.matchAll(re)) {
      const urls = [...m[2].matchAll(/"([^"]+\.js)"/g)].map((x) =>
        x[1].startsWith("/") ? x[1] : "/_next/" + x[1]
      );
      asyncLoaders.set(Number(m[1]), { urls, targetId: Number(m[3]) });
    }
  }
  return asyncLoaders;
}

function resolveDgwRootIds(dgwChunkText, factories) {
  const ids = {
    dgwClient: 105667,
    encodeReqProto: 501697,
    decodeProto: 70540,
    fileDescProto: 408787,
    getMsgDesc: 328693,
    txDep: 162485,
  };
  if (!factories.has(ids.dgwClient)) {
    const m = dgwChunkText.match(/get endpoint\(\)\{return [^}]+\}get appId\(\)\{return [^}]+\}\}\],(\d+)\)/);
    if (m) {
      ids.dgwClient = Number(m[1]);
    } else {
      for (const [id, entry] of factories) {
        const src = entry.fn.toString();
        if (src.includes("DGWConnectionContext") && src.includes("createStreamGroup")) {
          ids.dgwClient = id;
          break;
        }
      }
    }
  }
  if (!factories.has(ids.decodeProto) || !factories.has(ids.fileDescProto)) {
    const m = dgwChunkText.match(
      /e\.s\(\["f",0,\w+\],(\d+)\),e\.s\(\["f",0,\w+\],(\d+)\);let \w+=\w+\("ChllY3RvX3JlcXVlc3RfY2xpZW50LnByb3Rv/
    );
    if (m) {
      ids.decodeProto = Number(m[1]);
      ids.fileDescProto = Number(m[2]);
    }
  }
  if (!factories.has(ids.getMsgDesc)) {
    const m = dgwChunkText.match(
      /function \w+\(\w+,\w+,\.\.\.\w+\)\{return \w+\.reduce\(\(\w+,\w+\)=>\w+\.nestedMessages\[\w+\],\w+\.messages\[\w+\]\)\}e\.s\(\["f",0,\w+\],(\d+)\)/
    );
    if (m) ids.getMsgDesc = Number(m[1]);
  }
  if (!factories.has(ids.txDep)) {
    const m = dgwChunkText.match(/e\.s\(\[[^\]]*?"Tx",0,\w+\],(\d+)\)/);
    if (m) ids.txDep = Number(m[1]);
  }
  if (!factories.has(ids.encodeReqProto)) {
    const m = dgwChunkText.match(
      /KADABRA__HOME__UNIFIED_INPUT_BAR[\s\S]{0,600}?return \(0,\w+\.f\)\([^)]+\)\}\],(\d+)\)/
    );
    if (m) ids.encodeReqProto = Number(m[1]);
  }
  return ids;
}

const KNOWN_STUB_IDS = new Set([
  846411,
  724765,
  115212,
  443051,
  892803,
  185870,
  254607,
  840387,
  82833,
  546963,
]);

function collectNeededChunkUrls(fetchedMap, dgwChunkUrl, rootIds, asyncLoaders) {
  const sandbox = Object.create(null);
  Object.assign(sandbox, {
    TURBOPACK: [],
    Object,
    Array,
    Function,
    Number,
    String,
    Boolean,
    Error,
    Math,
    Date,
    RegExp,
    Map,
    Set,
    Promise,
    JSON,
    Symbol,
  });
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  sandbox.window = sandbox;
  const ctxVm = vm.createContext(sandbox);
  const factories = new Map();
  for (const [url, txt] of fetchedMap) {
    if (!txt || !txt.includes("TURBOPACK")) continue;
    const before = sandbox.TURBOPACK.length;
    try {
      vm.runInContext(txt, ctxVm, { timeout: 2000 });
    } catch {
      continue;
    }
    for (let k = before; k < sandbox.TURBOPACK.length; k++) {
      const entry = sandbox.TURBOPACK[k];
      if (Array.isArray(entry)) registerTurbopackArray(entry, 1, url, factories);
    }
  }

  const roots = resolveDgwRootIds(fetchedMap.get(dgwChunkUrl) || "", factories);
  Object.assign(rootIds, roots);
  const queue = [
    roots.dgwClient,
    roots.encodeReqProto,
    roots.decodeProto,
    roots.fileDescProto,
    roots.getMsgDesc,
    roots.txDep,
  ];
  const wasmLoader = asyncLoaders.get(9658);
  if (wasmLoader?.targetId != null) queue.push(wasmLoader.targetId);
  else queue.push(66134);

  const visited = new Set();
  const neededChunks = new Set([dgwChunkUrl]);
  while (queue.length > 0) {
    const id = queue.shift();
    if (visited.has(id) || KNOWN_STUB_IDS.has(id)) continue;
    visited.add(id);
    const factory = factories.get(id);
    if (!factory) continue;
    neededChunks.add(factory.sourceUrl);
    const src = factory.fn.toString();
    for (const m of src.matchAll(/\b[a-zA-Z_$]\w*\.(?:i|r)\((\d+)\)/g)) {
      const depId = Number(m[1]);
      if (!visited.has(depId) && !KNOWN_STUB_IDS.has(depId)) queue.push(depId);
    }
    for (const m of src.matchAll(/\b[a-zA-Z_$]\w*\.A\((\d+)\)/g)) {
      const loader = asyncLoaders.get(Number(m[1]));
      if (loader) {
        for (const u of loader.urls) neededChunks.add(u);
        if (loader.targetId != null && !visited.has(loader.targetId)) queue.push(loader.targetId);
      }
    }
  }
  return neededChunks;
}

async function loadChunks(cacheDir, session, forceRefresh = false) {
  const cachePath = cacheDir ? path.join(cacheDir, "chunks-cache.json") : null;
  if (forceRefresh && cachePath && fs.existsSync(cachePath)) {
    try {
      fs.unlinkSync(cachePath);
    } catch {}
  }
  if (!forceRefresh && cachePath && fs.existsSync(cachePath)) {
    try {
      const cached = JSON.parse(fs.readFileSync(cachePath, "utf8"));
      const ageSeconds = Math.floor(Date.now() / 1000) - Number(cached.cachedAt || 0);
      if (
        cached.dgwChunkText &&
        cached.wasmChunkText &&
        Array.isArray(cached.extraChunkTexts) &&
        cached.cachedAt &&
        ageSeconds >= 0 &&
        ageSeconds < CHUNK_CACHE_TTL_SECONDS
      ) {
        return cached;
      }
      try {
        fs.unlinkSync(cachePath);
      } catch {}
    } catch {}
  }

  let scripts = session?.scripts || [];
  let cookieHeader = session?.cookieHeader || "";
  if (!scripts.length) {
    const fresh = await acquireSession();
    scripts = fresh.scripts;
    cookieHeader = fresh.cookieHeader;
  }

  const candidateUrls = scripts.filter((u) => !u.includes("turbopack-"));
  const fetchedMap = await fetchTextBatch(candidateUrls, cookieHeader, 12);

  let dgwChunkUrl = "";
  let dgwChunkText = "";
  for (const [url, txt] of fetchedMap) {
    if (txt.includes("DGWConnectionContext") && txt.includes("createStreamGroup")) {
      dgwChunkUrl = url;
      dgwChunkText = txt;
      break;
    }
  }
  if (!dgwChunkText) {
    throw new Error("No se encontró el chunk DGW de Meta AI");
  }

  const asyncLoaders = parseAsyncLoaders(fetchedMap.values());
  const defaultWasmUrl = "/_next/static/immutable/chunks/02h3llx9n0qf1.js";
  const asyncUrls = new Set();
  for (const loader of asyncLoaders.values()) {
    for (const u of loader.urls) asyncUrls.add(u);
  }
  const wasmLoader = asyncLoaders.get(9658);
  const wasmChunkUrl = wasmLoader?.urls?.[0] || defaultWasmUrl;
  asyncUrls.add(wasmChunkUrl);

  const missingAsyncUrls = [...asyncUrls].filter((u) => !fetchedMap.has(u));
  if (missingAsyncUrls.length) {
    const extraAsync = await fetchTextBatch(missingAsyncUrls, cookieHeader, 8);
    for (const [u, t] of extraAsync) fetchedMap.set(u, t);
  }
  const wasmChunkText = fetchedMap.get(wasmChunkUrl) || "";
  if (!wasmChunkText) {
    throw new Error("No se encontró el chunk WASM de Meta AI");
  }

  const rootIds = {};
  const neededChunkUrls = collectNeededChunkUrls(fetchedMap, dgwChunkUrl, rootIds, asyncLoaders);
  const extraChunkTexts = [...neededChunkUrls]
    .filter((u) => u !== dgwChunkUrl && u !== wasmChunkUrl)
    .map((u) => fetchedMap.get(u))
    .filter(Boolean);

  const result = {
    dgwChunkText,
    wasmChunkText,
    extraChunkTexts,
    asyncLoaders: [...asyncLoaders.entries()],
    cachedAt: Math.floor(Date.now() / 1000),
  };
  if (cachePath) {
    try {
      fs.mkdirSync(path.dirname(cachePath), { recursive: true, mode: 0o700 });
      fs.writeFileSync(cachePath, JSON.stringify(result), { mode: 0o600 });
    } catch {}
  }
  return result;
}

function initTurbopackRuntime(chunkBundle, cookieHeader) {
  const { wasmChunkText, dgwChunkText, extraChunkTexts = [], asyncLoaders: rawAsyncLoaders = [] } = chunkBundle;
  const asyncLoaders = new Map(Array.isArray(rawAsyncLoaders) ? rawAsyncLoaders : []);
  class CustomWS extends WebSocket {
    constructor(url) {
      super(url, {
        headers: {
          Origin: "https://www.meta.ai",
          "User-Agent": UA,
          Cookie: cookieHeader || "",
        },
      });
    }
  }
  const sandbox = Object.create(null);
  Object.assign(sandbox, {
    TURBOPACK: [],
    Object,
    Array,
    String,
    Number,
    Boolean,
    Symbol,
    BigInt,
    Math,
    Date,
    RegExp,
    Error,
    TypeError,
    RangeError,
    SyntaxError,
    URIError,
    EvalError,
    ReferenceError,
    Map,
    Set,
    WeakMap,
    WeakSet,
    Promise,
    Proxy,
    Reflect,
    JSON,
    ArrayBuffer,
    SharedArrayBuffer,
    DataView,
    Int8Array,
    Uint8Array,
    Uint8ClampedArray,
    Int16Array,
    Uint16Array,
    Int32Array,
    Uint32Array,
    Float32Array,
    Float64Array,
    BigInt64Array,
    BigUint64Array,
    TextEncoder,
    TextDecoder,
    URL,
    URLSearchParams,
    WebAssembly,
    Buffer,
    crypto,
    WebSocket: CustomWS,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    queueMicrotask,
    atob,
    btoa,
    console: { log: () => {}, info: () => {}, warn: () => {}, error: () => {} },
  });
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  sandbox.window = sandbox;
  const vmContext = vm.createContext(sandbox, {
    codeGeneration: { strings: false, wasm: true },
  });
  for (const chunkText of [wasmChunkText, dgwChunkText, ...extraChunkTexts]) {
    if (chunkText) {
      vm.runInContext(chunkText, vmContext, { timeout: 5000 });
    }
  }

  const factories = new Map();
  for (const entry of sandbox.TURBOPACK) {
    if (Array.isArray(entry)) {
      registerTurbopackArray(entry, 1, "bundle", factories);
    }
  }

  const moduleCache = new Map();
  const stubs = {
    846411: { default: { env: {}, versions: { node: "24.0.0" } } },
    724765: CustomWS,
    115212: { f: () => {} },
    443051: {
      I: (u8) => Buffer.from(u8).toString("base64"),
      E: (u8) => Buffer.from(u8).toString("base64"),
      W: () => Math.random(),
      V: () => crypto.randomUUID(),
      K: (err) => (err instanceof Error ? err : new Error(String(err))),
    },
    892803: { T: () => {}, z: () => {}, P: () => {} },
    185870: { f: (_meta, fn) => fn() },
    254607: {
      Z: {
        ABNORMAL_CLOSURE: 1,
        SERVER_INTERNAL_ERROR: 2,
        GOING_AWAY: 3,
        UNAUTHORIZED: 4,
        REJECTED: 5,
        BAD_REQUEST: 6,
        DGW_SERVER_ERROR: 7,
        UNKNOWN_ERROR: 8,
        KEEPALIVE_TIMEOUT: 9,
        TRANSPORT_ESTABLISHMENT_TIMEOUT: 10,
        ESTABLISHMENT_ERROR: 11,
        TRANSPORT_CLOSED_BEFORE_STREAM_INIT: 12,
        PREMATURE_CLOSE: 13,
      },
      q: () => true,
    },
    840387: {
      createClientLogger: () => ({
        info: () => {},
        warn: () => {},
        error: () => {},
      }),
    },
    82833: { C: () => null, g: () => 0n },
    546963: {
      q: () => null,
      k: () => ({ pendingPatches: new Map() }),
      Q: () => ({ pendingPatchCount: 0, blockedSeq: null }),
    },
  };

  function requireMod(id) {
    if (moduleCache.has(id)) return moduleCache.get(id);
    if (stubs[id]) {
      moduleCache.set(id, stubs[id]);
      return stubs[id];
    }
    const entry = factories.get(id);
    if (!entry) throw new Error("Missing module " + id);
    const groupExports = new Map();
    for (const gid of entry.ids) {
      const obj = {};
      groupExports.set(gid, obj);
      moduleCache.set(gid, obj);
    }
    const ctx = {
      i: (depId) => requireMod(depId),
      r: (depId) => requireMod(depId),
      A: async (asyncId) => {
        const loader = asyncLoaders.get(asyncId);
        if (loader?.targetId != null) return requireMod(loader.targetId);
        if (asyncId === 9658) return requireMod(66134);
        throw new Error("Unknown async module " + asyncId);
      },
      s: (arr, targetId) => {
        const tid = targetId ?? entry.ids[0];
        const exp = groupExports.get(tid) || {};
        let j = 0;
        while (j < arr.length) {
          const name = arr[j];
          if (typeof arr[j + 1] === "function") {
            const getter = arr[j + 1];
            Object.defineProperty(exp, name, {
              get: getter,
              enumerable: true,
              configurable: true,
            });
            j += 2;
          } else {
            const val = arr[j + 2];
            Object.defineProperty(exp, name, {
              value: val,
              enumerable: true,
              configurable: true,
              writable: true,
            });
            j += 3;
          }
        }
        groupExports.set(tid, exp);
        moduleCache.set(tid, exp);
      },
    };
    entry.fn(ctx);
    return moduleCache.get(id);
  }

  const rootIds = resolveDgwRootIds(dgwChunkText, factories);
  const DgwClient = requireMod(rootIds.dgwClient).f;
  const encodeReqProto = requireMod(rootIds.encodeReqProto).f;
  const decodeProto = requireMod(rootIds.decodeProto).f;
  const fileDescProto = requireMod(rootIds.fileDescProto).f;
  const getMsgDesc = requireMod(rootIds.getMsgDesc).f;
  const txDep = requireMod(rootIds.txDep).Tx;

  const respProtoB64Match = dgwChunkText.match(
    /"(ChplY3RvX3Jlc3BvbnNlX2NsaWVudC5wcm90bx[^"]+)"/
  );
  if (!respProtoB64Match) {
    throw new Error("No se encontró el descriptor Protobuf de respuesta");
  }
  const respFileDesc = fileDescProto(respProtoB64Match[1], [txDep]);
  const ResponseDesc = getMsgDesc(respFileDesc, 0);

  return { DgwClient, encodeReqProto, decodeProto, ResponseDesc };
}

function extractTextFromUnifiedResponse(rawUnified) {
  if (!rawUnified || typeof rawUnified !== "string") return "";
  try {
    const doc = JSON.parse(rawUnified);
    const texts = [];
    const visit = (node) => {
      if (!node || typeof node !== "object") return;
      if (Array.isArray(node)) {
        for (const item of node) visit(item);
        return;
      }
      if (typeof node.text === "string" && node.text.trim()) {
        const t = String(node.__typename || "");
        if (!t || t.includes("Markdown") || t.includes("Text") || t.includes("Primitive")) {
          texts.push(node.text.trim());
        }
      }
      if (node.view_model) visit(node.view_model);
      if (node.primitive) visit(node.primitive);
      if (node.primitives) visit(node.primitives);
      if (node.sections) visit(node.sections);
    };
    visit(doc);
    return texts.join("\n\n").trim();
  } catch {
    return "";
  }
}

async function runChat({ prompt, enableThinking, session, cacheDir, forceRefresh = false }) {
  let activeSession = session;
  if (!activeSession?.accessToken || !activeSession?.abraUserId) {
    activeSession = await acquireSession();
  }

  const chunkBundle = await loadChunks(cacheDir, activeSession, forceRefresh);
  const { DgwClient, encodeReqProto, decodeProto, ResponseDesc } =
    initTurbopackRuntime(chunkBundle, activeSession.cookieHeader);

  const client = new DgwClient({
    authToken: activeSession.accessToken,
    appId: META_AI_APP_ID,
  });

  const convId = crypto.randomUUID();
  const requestId = crypto.randomUUID();
  const turnId = crypto.randomUUID();
  const uniqueMessageId = String(Date.now());

  let responseText = "";
  let rawAccumulated = "";
  let unifiedFallback = "";
  let streamErr = null;
  let doneResolve;
  const donePromise = new Promise((r) => {
    doneResolve = r;
  });

  const streamGroup = client.createStreamGroup({
    serviceId: "clippy",
    connectTimeoutMs: 25000,
    keepAliveMs: 30000,
    headers: {
      origin: "meta.ai",
      "clippy-request-id": crypto.randomUUID(),
    },
    wsCompression: false,
    onStreamGroupError: (err) => {
      streamErr = err;
      doneResolve();
    },
    onStreamGroupMustDrain: () => {},
    onStreamGroupTransportClose: () => {
      doneResolve();
    },
  });

  await streamGroup.initTransport();

  const stream = await streamGroup.establishStream(
    {
      loggingId: `conv-${convId.slice(0, 8)}-${Date.now()}`,
      groupedStreamHeaders: {
        "x-ecto-conversation-id": convId,
        "client-payload-type": "PROTO_INSIDE_JSON",
      },
    },
    {
      onDataReceived: (bytes) => {
        if (bytes.length > 0 && bytes[0] === 123) {
          return;
        }
        let messages = [];
        let pos = 0;
        let framedOk = true;
        while (pos < bytes.length) {
          try {
            let len = 0,
              shift = 0,
              read = 0;
            while (pos + read < bytes.length) {
              const b = bytes[pos + read];
              read++;
              len |= (b & 127) << shift;
              if ((b & 128) === 0) break;
              if ((shift += 7) > 35) throw new Error("Varint overflow");
            }
            if (len <= 0 || pos + read + len > bytes.length) {
              framedOk = false;
              break;
            }
            const slice = bytes.slice(pos + read, pos + read + len);
            messages.push(decodeProto(ResponseDesc, slice));
            pos += read + len;
          } catch {
            framedOk = false;
            break;
          }
        }
        if (!framedOk || pos !== bytes.length || messages.length === 0) {
          messages = [];
          try {
            messages.push(decodeProto(ResponseDesc, bytes));
          } catch {}
        }
        for (const msg of messages) {
          const inner = msg?.piece?.piece || msg?.piece;
          if (inner?.case === "modelResponse" && inner.value) {
            if (inner.value.rawChunk) {
              rawAccumulated += inner.value.rawChunk;
            }
            if (inner.value.ppResponseSoFar) {
              responseText = inner.value.ppResponseSoFar;
            } else if (rawAccumulated) {
              responseText = rawAccumulated;
            }
            if (!responseText && inner.value.rawUnifiedResponse) {
              const extracted = extractTextFromUnifiedResponse(inner.value.rawUnifiedResponse);
              if (extracted) unifiedFallback = extracted;
            }
            if (inner.value.isFinalChunk || msg.isFinalChunk) {
              doneResolve();
            }
          } else if (inner?.case === "staticResponse" && inner.value) {
            if (inner.value.text) {
              responseText = inner.value.text;
            }
            if (msg.isFinalChunk) {
              doneResolve();
            }
          } else if (inner?.case === "error" && inner.value) {
            streamErr = new Error(
              inner.value.message || inner.value.errorMessage || "Error devuelto por Meta AI"
            );
            doneResolve();
          } else if (msg?.isFinalChunk) {
            doneResolve();
          }
        }
      },
      onServerHasFinishedSendingData: () => {
        doneResolve();
      },
      onError: (err) => {
        streamErr = err;
        doneResolve();
      },
      onClose: () => {
        doneResolve();
      },
      onStreamMustDrain: () => {},
    }
  );

  const reqObj = {
    conversationId: convId,
    promptContent: String(prompt || ""),
    userId: activeSession.abraUserId,
    appId: META_AI_APP_ID,
    requestId,
    uniqueMessageId,
    turnId,
    isEmployee: false,
    isLoggedOut: true,
    agentTypeValue: 1000,
    enableThinking: Boolean(enableThinking),
    entryPoint: "KADABRA__HOME__UNIFIED_INPUT_BAR",
    promptType: "user_input",
    developerOverrides: {},
    isNewConversation: true,
    sessionId: crypto.randomUUID(),
    locationData: { timezone: "Europe/Madrid" },
    localeInfo: { userLocale: "es-ES" },
    traceContext: {
      clippyPayloadPublishTimestampMs: Date.now(),
      wwwRequestStartTimestampMs: Date.now(),
    },
    currentBranchPath: "0",
    promptEditType: "new_message",
    userAgent: UA,
  };

  const protoPayload = encodeReqProto(reqObj);
  const wireBytes = new TextEncoder().encode(
    JSON.stringify({
      "req-id": requestId,
      payload: Buffer.from(protoPayload).toString("base64"),
    })
  );

  await stream.send(wireBytes);

  const timeoutHandle = setTimeout(() => {
    doneResolve();
  }, 60000);
  await donePromise;
  clearTimeout(timeoutHandle);
  try {
    streamGroup.close();
  } catch {}

  const finalResponse = (responseText || rawAccumulated || unifiedFallback || "").trim();
  if (!finalResponse && streamErr) {
    throw streamErr instanceof Error ? streamErr : new Error(String(streamErr));
  }
  return {
    response: finalResponse,
    session: activeSession,
  };
}

async function main() {
  try {
    const input = await readStdinJson();
    const action = input.action || "chat";
    const cacheDir = input.cacheDir || null;

    if (action === "auth") {
      const session = await acquireSession();
      await loadChunks(cacheDir, session);
      process.stdout.write(
        JSON.stringify({
          ok: true,
          session: {
            accessToken: session.accessToken,
            abraUserId: session.abraUserId,
            cookieHeader: session.cookieHeader,
            acquiredAt: session.acquiredAt,
          },
          loginUrl: META_AI_OIDC_START_URL,
        }) + "\n"
      );
      process.exit(0);
    }

    let result;
    try {
      result = await runChat({
        prompt: input.prompt,
        enableThinking: input.enableThinking,
        session: input.session,
        cacheDir,
      });
    } catch {
      if (cacheDir) {
        try {
          fs.unlinkSync(path.join(cacheDir, "chunks-cache.json"));
        } catch {}
      }
      const freshSession = await acquireSession();
      result = await runChat({
        prompt: input.prompt,
        enableThinking: input.enableThinking,
        session: freshSession,
        cacheDir,
        forceRefresh: true,
      });
    }

    process.stdout.write(
      JSON.stringify({
        ok: true,
        response: result.response,
        session: {
          accessToken: result.session.accessToken,
          abraUserId: result.session.abraUserId,
          cookieHeader: result.session.cookieHeader,
          acquiredAt: result.session.acquiredAt,
        },
      }) + "\n"
    );
    process.exit(0);
  } catch (err) {
    process.stdout.write(
      JSON.stringify({
        ok: false,
        error: err instanceof Error ? err.message : String(err),
      }) + "\n"
    );
    process.exit(1);
  }
}

main();
