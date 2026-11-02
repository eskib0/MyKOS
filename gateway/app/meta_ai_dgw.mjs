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
    ...new Set(
      [...text.matchAll(/src="(\/_next\/static\/[^"]+\.js)"/g)].map((m) => m[1])
    ),
  ];
  return {
    accessToken: tempUser.accessToken,
    abraUserId: tempUser.abraUserId,
    cookieHeader,
    scripts,
    acquiredAt: Math.floor(Date.now() / 1000),
  };
}

async function loadChunks(cacheDir, session, forceRefresh = false) {
  const cachePath = cacheDir ? path.join(cacheDir, "chunks-cache.json") : null;
  if (!forceRefresh && cachePath && fs.existsSync(cachePath)) {
    try {
      const cached = JSON.parse(fs.readFileSync(cachePath, "utf8"));
      if (cached.dgwChunkText && cached.wasmChunkText) {
        return cached;
      }
    } catch {}
  }

  let scripts = session?.scripts || [];
  let cookieHeader = session?.cookieHeader || "";
  if (!scripts.length) {
    const fresh = await acquireSession();
    scripts = fresh.scripts;
    cookieHeader = fresh.cookieHeader;
  }

  let dgwChunkText = "";
  let wasmChunkUrl = "/_next/static/immutable/chunks/02h3llx9n0qf1.js";
  for (const sc of scripts) {
    const txt = await (
      await fetch("https://www.meta.ai" + sc, {
        headers: { "User-Agent": UA, Cookie: cookieHeader },
      })
    ).text();
    if (txt.includes("DGWConnectionContext") && txt.includes("createStreamGroup")) {
      dgwChunkText = txt;
    }
    const wm = txt.match(/9658,e=>\{e\.v\(t=>Promise\.all\(\["([^"]+)"\]/);
    if (wm) {
      wasmChunkUrl = "/_next/" + wm[1];
    }
  }
  if (!dgwChunkText) {
    throw new Error("No se encontró el chunk DGW de Meta AI");
  }
  const wasmChunkText = await (
    await fetch("https://www.meta.ai" + wasmChunkUrl, {
      headers: { "User-Agent": UA, Cookie: cookieHeader },
    })
  ).text();

  const result = {
    dgwChunkText,
    wasmChunkText,
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

function initTurbopackRuntime(wasmChunkText, dgwChunkText, cookieHeader) {
  globalThis.TURBOPACK = [];
  vm.runInThisContext(wasmChunkText);
  vm.runInThisContext(dgwChunkText);

  const factories = new Map();
  for (const entry of globalThis.TURBOPACK) {
    let i = 1;
    while (i < entry.length) {
      const ids = [];
      while (i < entry.length && typeof entry[i] === "number") {
        ids.push(entry[i++]);
      }
      const fn = entry[i++];
      if (typeof fn === "function") {
        for (const id of ids) factories.set(id, { ids, fn });
      }
    }
  }

  const moduleCache = new Map();
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

  const DgwClient = requireMod(105667).f;
  const encodeReqProto = requireMod(501697).f;
  const decodeProto = requireMod(70540).f;
  const fileDescProto = requireMod(408787).f;
  const getMsgDesc = requireMod(328693).f;
  const txDep = requireMod(162485).Tx;

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

async function runChat({ prompt, enableThinking, session, cacheDir }) {
  let activeSession = session;
  if (!activeSession?.accessToken || !activeSession?.abraUserId) {
    activeSession = await acquireSession();
  }

  const { wasmChunkText, dgwChunkText } = await loadChunks(cacheDir, activeSession);
  const { DgwClient, encodeReqProto, decodeProto, ResponseDesc } =
    initTurbopackRuntime(wasmChunkText, dgwChunkText, activeSession.cookieHeader);

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
        const messages = [];
        let pos = 0;
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
            if (len <= 0 || pos + read + len > bytes.length) break;
            const slice = bytes.slice(pos + read, pos + read + len);
            messages.push(decodeProto(ResponseDesc, slice));
            pos += read + len;
          } catch {
            break;
          }
        }
        if (messages.length === 0) {
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
              inner.value.errorMessage || "Error devuelto por Meta AI"
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

  if (!responseText && streamErr) {
    throw streamErr instanceof Error ? streamErr : new Error(String(streamErr));
  }
  return {
    response: (responseText || rawAccumulated || "").trim(),
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
      const freshSession = await acquireSession();
      result = await runChat({
        prompt: input.prompt,
        enableThinking: input.enableThinking,
        session: freshSession,
        cacheDir,
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
