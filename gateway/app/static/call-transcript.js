// Transcripción en vivo de la llamada de MyKOS. Módulo de DOM independiente de app.js:
//   const transcript = MyKOSCallTranscript.mount(listElement, { emptyText });
//   transcript.appendDelta("user" | "assistant", "texto parcial");   // streaming
//   transcript.addLine("user" | "assistant", "frase completa");      // turno ya terminado
//   transcript.reset();  transcript.finish();
// Los fragmentos seguidos del mismo interlocutor forman una sola burbuja; cambia de
// interlocutor (o pasa una pausa larga) y se abre otra. Solo escribe con textContent.
(() => {
  "use strict";

  const LABELS = { user: "Tú", assistant: "MyKOS" };
  const GAP_MS = 6000;
  const MAX_LINES = 200;

  function mount(list, options = {}) {
    const emptyText = options.emptyText || "La transcripción aparecerá aquí.";
    let current = null;

    const nearBottom = () => list.scrollHeight - list.scrollTop - list.clientHeight < 60;
    const stick = (follow) => { if (follow) list.scrollTop = list.scrollHeight; };

    function showEmpty() {
      const p = document.createElement("p");
      p.className = "voice-transcript-empty";
      p.textContent = emptyText;
      list.appendChild(p);
    }

    function closeCurrent() {
      if (current) current.el.classList.remove("live");
      current = null;
    }

    function createLine(role, text, live) {
      list.querySelector(".voice-transcript-empty")?.remove();
      const el = document.createElement("div");
      el.className = `voice-transcript-line ${role}${live ? " live" : ""}`;
      const who = document.createElement("span");
      who.className = "who";
      who.textContent = LABELS[role] || role;
      const body = document.createElement("p");
      body.className = "text";
      body.textContent = text;
      el.append(who, body);
      list.appendChild(el);
      const lines = list.querySelectorAll(".voice-transcript-line");
      for (let i = 0; i < lines.length - MAX_LINES; i += 1) lines[i].remove();
      return { role, el, body, text, at: Date.now() };
    }

    showEmpty();

    return {
      reset() {
        closeCurrent();
        list.replaceChildren();
        showEmpty();
      },
      addLine(role, text) {
        const clean = String(text || "").trim();
        if (!clean) return;
        const follow = nearBottom();
        closeCurrent();
        createLine(role, clean, false);
        stick(follow);
      },
      appendDelta(role, delta) {
        if (typeof delta !== "string" || !delta) return;
        const follow = nearBottom();
        const now = Date.now();
        if (!current || current.role !== role || now - current.at > GAP_MS) {
          closeCurrent();
          current = createLine(role, "", true);
        }
        current.text += delta;
        current.body.textContent = current.text.replace(/^\s+/, "");
        current.at = now;
        stick(follow);
      },
      finish() {
        closeCurrent();
      },
    };
  }

  window.MyKOSCallTranscript = { mount };
})();
