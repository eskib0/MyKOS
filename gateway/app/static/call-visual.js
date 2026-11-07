// Visual de la llamada de MyKOS: esfera central y anillo de barras que reaccionan
// al audio real (micrófono y voz de MyKOS). Módulo independiente de app.js:
//   const visual = MyKOSCallVisual.mount(canvas, options);
//   visual.start(); visual.stop();
// options:
//   getMode()          modo declarado por la aplicación: connecting | listening | hearing | thinking | speaking
//   getMicAnalyser()   AnalyserNode del micrófono (o null)
//   getVoiceAnalyser() AnalyserNode de la voz de MyKOS (o null: se anima sin nivel real)
//   deriveMode()       true si el modo debe deducirse de los niveles (llamada Realtime)
//   onMode(mode)       se llama cuando el modo efectivo cambia
(() => {
  "use strict";

  const TAU = Math.PI * 2;
  const BARS = 72;
  const COLORS = {
    connecting: [126, 152, 170],
    listening: [90, 182, 216],
    hearing: [236, 184, 112],
    thinking: [176, 158, 255],
    speaking: [122, 210, 236],
  };

  const lerp = (a, b, t) => a + (b - a) * t;
  const clamp01 = (v) => Math.max(0, Math.min(1, v));
  const follow = (current, target, up, down) => current + (target - current) * (target > current ? up : down);
  const rgba = (c, a) => `rgba(${c[0] | 0}, ${c[1] | 0}, ${c[2] | 0}, ${a})`;

  function analyserLevel(analyser, buffer) {
    if (!analyser || typeof analyser.getByteTimeDomainData !== "function") return null;
    const size = analyser.fftSize || 1024;
    if (!buffer.time || buffer.time.length !== size) buffer.time = new Uint8Array(size);
    analyser.getByteTimeDomainData(buffer.time);
    let total = 0;
    for (let i = 0; i < size; i += 1) {
      const value = (buffer.time[i] - 128) / 128;
      total += value * value;
    }
    return clamp01(Math.sqrt(total / size) * 5.5);
  }

  function analyserBands(analyser, buffer, out) {
    if (!analyser || typeof analyser.getByteFrequencyData !== "function") return false;
    const count = analyser.frequencyBinCount || 512;
    if (!buffer.freq || buffer.freq.length !== count) buffer.freq = new Uint8Array(count);
    analyser.getByteFrequencyData(buffer.freq);
    // Voz humana: se usa solo el tramo bajo del espectro (~0-4 kHz), repartido en la mitad
    // de las barras y reflejado para que el anillo sea simétrico.
    const usable = Math.max(8, Math.floor(count * 0.32));
    const half = BARS / 2;
    for (let i = 0; i < half; i += 1) {
      const from = Math.floor((i / half) * usable);
      const to = Math.max(from + 1, Math.floor(((i + 1) / half) * usable));
      let peak = 0;
      for (let k = from; k < to; k += 1) peak = Math.max(peak, buffer.freq[k]);
      const value = clamp01(peak / 255);
      out[i] = value;
      out[BARS - 1 - i] = value;
    }
    return true;
  }

  function mount(canvas, options = {}) {
    const ctx = canvas.getContext("2d");
    const reduceQuery = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
    const buffers = { mic: {}, voice: {} };
    const bands = new Float32Array(BARS);
    const target = new Float32Array(BARS);
    let color = COLORS.listening.slice();
    let mic = 0;
    let voice = 0;
    let effective = "connecting";
    let holdUntil = 0;
    let frame = 0;
    let size = 0;
    let dpr = 1;
    let lastTick = 0;
    let phase = 0;

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      const css = Math.max(180, Math.round(canvas.clientWidth || 340));
      size = css;
      canvas.width = Math.round(css * dpr);
      canvas.height = Math.round(css * dpr);
    }

    function decideMode(now, base) {
      if (!options.deriveMode || !options.deriveMode()) return base;
      // Deducción por niveles: la voz de MyKOS manda sobre el micrófono, con
      // retención para que el estado no parpadee entre sílabas.
      let wanted = base === "connecting" || base === "thinking" ? base : "listening";
      if (voice > 0.07) wanted = "speaking";
      else if (mic > 0.09 && effective !== "speaking") wanted = "hearing";
      if (wanted === effective) return effective;
      const rank = { listening: 0, connecting: 0, thinking: 1, hearing: 2, speaking: 3 };
      if (rank[wanted] >= rank[effective]) return wanted;
      return now >= holdUntil ? wanted : effective;
    }

    function tick(now) {
      frame = requestAnimationFrame(tick);
      const dt = Math.min(0.05, (now - (lastTick || now)) / 1000);
      lastTick = now;
      const reduced = Boolean(reduceQuery && reduceQuery.matches);
      if (!reduced) phase += dt;
      const t = phase;

      const rawMic = analyserLevel(options.getMicAnalyser?.(), buffers.mic);
      const rawVoice = analyserLevel(options.getVoiceAnalyser?.(), buffers.voice);
      mic = follow(mic, rawMic ?? 0, 0.55, 0.12);
      voice = follow(voice, rawVoice ?? 0, 0.55, 0.1);

      const base = options.getMode ? options.getMode() : "listening";
      const next = decideMode(now, base);
      if (next !== effective) {
        const previous = effective;
        effective = next;
        if (effective === "speaking" || effective === "hearing") holdUntil = now + 450;
        else if (previous === "speaking" || previous === "hearing") holdUntil = now + 450;
        options.onMode?.(effective);
      } else if ((effective === "speaking" || effective === "hearing") && (voice > 0.07 || mic > 0.09)) {
        holdUntil = now + 450;
      }

      // Nivel de energía que mueve la esfera y las barras.
      let energy;
      if (effective === "speaking") {
        // Sin analizador de salida (voz local de reserva) se simula un habla natural.
        energy = rawVoice !== null ? voice : 0.32 + 0.22 * Math.sin(t * 7.3) * Math.sin(t * 2.1 + 1) + 0.12 * Math.sin(t * 13.7);
      } else if (effective === "hearing") {
        energy = mic;
      } else if (effective === "thinking") {
        energy = 0.1;
      } else {
        energy = 0.05;
      }
      energy = clamp01(energy);

      // Espectro objetivo de cada barra.
      const analyser = effective === "speaking" ? options.getVoiceAnalyser?.() : effective === "hearing" ? options.getMicAnalyser?.() : null;
      const real = analyser ? analyserBands(analyser, effective === "speaking" ? buffers.voice : buffers.mic, target) : false;
      for (let i = 0; i < BARS; i += 1) {
        let value;
        if (real) {
          value = target[i];
        } else if (effective === "speaking" || effective === "hearing") {
          const wobble = 0.5 + 0.5 * Math.sin(t * 6 + i * 0.9) * Math.sin(t * 3.1 + i * 0.37);
          value = energy * (0.35 + 0.65 * wobble);
        } else if (effective === "thinking") {
          value = 0.06 + 0.05 * Math.sin(t * 2 + i * 0.5);
        } else if (effective === "connecting") {
          value = 0.04;
        } else {
          value = 0.07 + 0.045 * Math.sin(t * 1.3 + i * 0.32);
        }
        bands[i] = follow(bands[i], clamp01(value), 0.5, 0.14);
      }

      // Color: transición suave entre modos.
      const goal = COLORS[effective] || COLORS.listening;
      const blend = 1 - Math.exp(-dt * 9); // independiente de los fotogramas por segundo
      color = [lerp(color[0], goal[0], blend), lerp(color[1], goal[1], blend), lerp(color[2], goal[2], blend)];

      draw(t, energy, reduced);
    }

    function draw(t, energy, reduced) {
      const s = size;
      const c = s / 2;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, s, s);

      const unit = s / 340;
      const coreBase = 50 * unit;
      const coreRadius = coreBase + energy * 16 * unit + (reduced ? 0 : Math.sin(t * 1.4) * 1.6 * unit);
      const ringRadius = 88 * unit;

      // Resplandor de fondo.
      const halo = ctx.createRadialGradient(c, c, coreBase * 0.6, c, c, s * 0.5);
      halo.addColorStop(0, rgba(color, 0.2 + energy * 0.22));
      halo.addColorStop(0.55, rgba(color, 0.05 + energy * 0.06));
      halo.addColorStop(1, rgba(color, 0));
      ctx.fillStyle = halo;
      ctx.fillRect(0, 0, s, s);

      // Anillos finos.
      ctx.lineWidth = 1;
      ctx.strokeStyle = rgba(color, 0.28);
      ctx.beginPath();
      ctx.arc(c, c, ringRadius - 10 * unit, 0, TAU);
      ctx.stroke();
      ctx.strokeStyle = rgba(color, 0.1 + energy * 0.14);
      ctx.beginPath();
      ctx.arc(c, c, ringRadius + 54 * unit + energy * 10 * unit, 0, TAU);
      ctx.stroke();

      // Conectando / pensando: arcos giratorios.
      if (effective === "connecting" || effective === "thinking") {
        const spin = reduced ? 0 : t * (effective === "connecting" ? 1.6 : 2.4);
        ctx.lineCap = "round";
        ctx.lineWidth = 3 * unit;
        ctx.strokeStyle = rgba(color, 0.85);
        const arcs = effective === "connecting" ? 1 : 3;
        for (let i = 0; i < arcs; i += 1) {
          const start = spin + (i * TAU) / arcs;
          ctx.beginPath();
          ctx.arc(c, c, ringRadius + 34 * unit, start, start + (effective === "connecting" ? 1.5 : 0.7));
          ctx.stroke();
        }
      }

      // Anillo de barras.
      ctx.lineCap = "round";
      ctx.lineWidth = Math.max(2, 3.2 * unit);
      const rotation = reduced ? 0 : t * 0.12;
      for (let i = 0; i < BARS; i += 1) {
        const a = bands[i];
        const angle = (i / BARS) * TAU - Math.PI / 2 + rotation;
        const inner = ringRadius;
        const outer = ringRadius + (3 + a * 46) * unit;
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);
        ctx.strokeStyle = rgba(color, 0.32 + a * 0.68);
        ctx.beginPath();
        ctx.moveTo(c + cos * inner, c + sin * inner);
        ctx.lineTo(c + cos * outer, c + sin * outer);
        ctx.stroke();
      }

      // Esfera central.
      const glow = ctx.createRadialGradient(c, c, coreRadius * 0.4, c, c, coreRadius * 2.1);
      glow.addColorStop(0, rgba(color, 0.42 + energy * 0.3));
      glow.addColorStop(1, rgba(color, 0));
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(c, c, coreRadius * 2.1, 0, TAU);
      ctx.fill();

      const sphere = ctx.createRadialGradient(c - coreRadius * 0.32, c - coreRadius * 0.38, coreRadius * 0.08, c, c, coreRadius);
      sphere.addColorStop(0, rgba([Math.min(255, color[0] + 90), Math.min(255, color[1] + 70), Math.min(255, color[2] + 50)], 0.98));
      sphere.addColorStop(0.55, rgba(color, 0.95));
      sphere.addColorStop(1, rgba([color[0] * 0.45, color[1] * 0.5, color[2] * 0.55], 0.98));
      ctx.fillStyle = sphere;
      ctx.beginPath();
      ctx.arc(c, c, coreRadius, 0, TAU);
      ctx.fill();
    }

    function onResize() { resize(); }

    return {
      start() {
        if (frame) return;
        resize();
        window.addEventListener("resize", onResize);
        lastTick = 0;
        frame = requestAnimationFrame(tick);
        requestAnimationFrame(resize);
      },
      resize,
      stop() {
        if (frame) cancelAnimationFrame(frame);
        frame = 0;
        window.removeEventListener("resize", onResize);
        mic = 0;
        voice = 0;
        bands.fill(0);
        effective = "connecting";
      },
      mode: () => effective,
    };
  }

  window.MyKOSCallVisual = { mount };
})();
