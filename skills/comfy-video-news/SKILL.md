---
name: comfy-video-news
description: Generador autónomo milimétrico de documentales de IA de 3 minutos para YouTube combinando B-roll fotorrealista de ComfyUI (FLUX.1 + Wan 2.1), locución neuronal OmniVoice, control estricto de texto (cero desbordamiento de viñetas) y transiciones cinemáticas fluidas con FFmpeg/NVENC. 100% local en RTX 5060.
metadata:
  version: "1.0.0"
  author: "MyKOS & Antigravity"
  tags: ["youtube", "comfyui", "flux", "wan2.1", "omnivoice", "video-production", "nvenc", "automation"]
---

# Comfy Video News Studio (`comfy-video-news`)
### Generador Autónomo y Milimétrico de Documentales Cinemáticos para "Tu Máquina, Tus Reglas"

> **MANDATO OPERATIVO:**  
> Esta habilidad está diseñada para **ejecución matemática estricta sin improvisación**. El modelo no debe "inventar" coordenadas, ni estimar textos a ojo, ni hacer montajes planos. Debe seguir el protocolo milimétrico de contención de texto, sincronización de audio y transiciones cinemáticas.

---

## 🛡️ Las 4 Reglas de Oro de Seguridad Audiovisual

### 1. Regla de Contención Tipográfica (Cero Desbordamiento de Viñetas)
* **Márgenes de Seguridad Obligatorios:** Toda tarjeta o viñeta HUD debe tener un **colchón interno mínimo de 40 px** en los cuatro costados respecto al texto.
* **Auto-Escalado Dinámico:** Si el texto es largo, el tamaño de la fuente debe reducirse paso a paso hasta encajar en el área disponible. Está terminantemente prohibido que las letras toquen los bordes de la viñeta.
* **Algoritmo Obligatorio (`draw_wrapped_text_fitted`):**
```python
def draw_wrapped_text_fitted(draw, pos, text, font_path, initial_size, fill, max_width, max_height, line_spacing=6):
    """
    Ajusta el texto automáticamente al ancho y alto máximo de la viñeta
    reduciendo el tamaño de la fuente si es necesario.
    """
    cur_size = initial_size
    while cur_size >= 12:
        font = ImageFont.truetype(font_path, cur_size)
        bbox = font.getbbox("AyÁg")
        line_h = (bbox[3] - bbox[1]) + line_spacing
        
        words = text.split(" ")
        lines, current = [], []
        for w in words:
            test_line = " ".join(current + [w])
            if draw.textlength(test_line, font=font) <= max_width:
                current.append(w)
            else:
                if current:
                    lines.append(" ".join(current))
                    current = [w]
                else:
                    lines.append(w)
                    current = []
        if current:
            lines.append(" ".join(current))
            
        total_h = len(lines) * line_h
        if total_h <= max_height or cur_size <= 12:
            x, y = pos
            for i, l in enumerate(lines):
                draw.text((x, y + i * line_h), l, fill=fill, font=font)
            return total_h, cur_size
        cur_size -= 1
```
* **Límite de Densidad:** Máximo 22 palabras por viñeta. Si una idea requiere más palabras, se divide en dos tarjetas o se traslada a la locución oral.

---

### 2. Regla de Conexión Acústica (Cero Cortes Bruscos de Audio)
* **Lead-in (Entrada de voz):** Exactamente **0.50 segundos (15 frames)** de silencio antes de que empiece a hablar Álvaro. La voz NUNCA arranca en el frame 0 de la escena.
* **Lead-out (Salida de voz):** Exactamente **0.80 segundos (24 frames)** de margen tras la última palabra antes de cambiar a la siguiente escena.
* **Normalización:** La pista de voz se normaliza a pico de `0.85` (-1.4 dBFS).
* **Lecho Ambiental (`ambient_pad.wav`):**
  * Mezclado en bucle continuo a **-24 dB**.
  * **Auto-Ducking:** Cuando la voz habla, el lecho ambiental se atenúa automáticamente 6 dB más (a **-30 dB**).
  * **Fade-In Inicial:** 1.5 segundos al inicio del vídeo.
  * **Fade-Out Final:** 2.5 segundos con desvanecimiento suave al cierre.
* **Chime de Apertura (`intro_digital_chime.wav`):** Se reproduce entre `0.0s` y `2.0s` con pico normalizado a `0.35` (-9 dBFS).

---

### 3. Regla de Transición Cinemática (Cero Cortes en Seco / Anti-Jitter)
* **Resolución & Cadencia:** 1920x1080 Full HD sólido a **30.0 FPS exactos**.
* **Transiciones entre Escenas:**
  * **Cosine Cross-Dissolve:** 15 frames (0.5s) de mezcla matemática suave entre fondos de vídeo de ComfyUI.
  * **Dip to Dark Glow:** Se usa exclusivamente en el cambio entre el bloque técnico (Escena 3) y el tutorial práctico (Escena 4).
* **Bucleado de Vídeo Wan 2.1:** Los clips de vídeo de ComfyUI suelen durar entre 2 y 4 segundos (33-65 frames). Para cubrir los 35-40 segundos de cada capítulo de audio, el vídeo se buclea en modo **Ping-Pong suave con Crossfade** de 12 frames, evitando saltos bruscos hacia atrás.

---

### 4. Regla de Generación en ComfyUI (`mykos-media`)
Para generar los fondos cinemáticos fotorrealistas se usa el CLI desacoplado:
1. **Fotogramas Clave con FLUX.1 [schnell] FP8 (16:9 Nativo):**
   ```bash
   mykos-media image \
     --prompt "Ultra-realistic cinematic documentary footage, [DESCRIPCIÓN DE ESCENA], dark mood, cyan and deep amber lighting, 8k, photorealistic --no blurry, cartoon" \
     --width 1024 --height 576 \
     --output /ruta/salida_frame.png
   ```
2. **Clips en Movimiento con Wan 2.1 (T2V o I2V FP8):**
   ```bash
   mykos-media video \
     --prompt "Slow cinematic drone flight inside [ESCENA], glowing lights, 4k photorealistic" \
     --width 832 --height 480 \
     --frames 33 \
     --output /ruta/salida_clip.mp4
   ```
   *(FFmpeg reescala el clip a 1080p con `scale=1920:1080:flags=lanczos` durante el ensamblado).*

---

## ⏱️ Escaleta de Producción (3 Minutos Exactos · 5 Bloques)

```text
0:00 - 0:35 | BLOQUE 1: El Gancho & El Problema de la Nube (75 palabras)
              • Audio: tts_bloque_1.wav (Álvaro OmniVoice)
              • Vídeo ComfyUI: Clip 1 (Gran centro de datos / Torre de PC brillante)
              • HUD: Tarjeta de Titular con margen de 40px y autoescalado

0:35 - 1:15 | BLOQUE 2: La Noticia & Anatomía Técnica (80 palabras)
              • Audio: tts_bloque_2.wav
              • Vídeo ComfyUI: Clip 2 (Circuito cuántico / Núcleos de GPU)
              • HUD: Ficha técnica con specs (594B, 17B activos, 2.9%, Apache 2.0)

1:15 - 1:55 | BLOQUE 3: Comparativa Local vs Nube (80 palabras)
              • Audio: tts_bloque_3.wav
              • Vídeo ComfyUI: Clip 3 (Nube corporativa vs Libertad de hardware propio)
              • HUD: Tarjeta comparativa con colores Cian (#00f0ff) vs Rojo Alerta

1:55 - 2:35 | BLOQUE 4: Cómo se Ejecuta en Casa (80 palabras)
              • Audio: tts_bloque_4.wav
              • Vídeo ComfyUI: Clip 4 (Terminal de Linux con comandos fluyendo)
              • HUD: Cuadro de comandos con flags (`-ngl 99`, `--moe-cache-mib`)

2:35 - 3:05 | BLOQUE 5: Conclusión, Outro YouTube & Lema Soberano (65 palabras)
              • Audio: tts_bloque_5.wav
              • Vídeo ComfyUI: Clip 5 (Avatar MyKOSito despidiéndose / Logo del canal)
              • HUD: Tarjeta final: "TU MÁQUINA, TUS REGLAS" + Fade out a negro
```

---

## 🎛️ Pipeline Automatizado de Ejecución

Cuando el usuario pida un vídeo cinemático con esta skill:
1. **Generar los 5 audios** con OmniVoice y guardar sus duraciones exactas en segundos.
2. **Generar los 5 clips/imágenes de ComfyUI** correspondientes mediante `mykos-media`.
3. **Calcular los fotogramas exactos**: `frames = int(round(duracion_audio * 30.0))`.
4. **Ejecutar el ensamblador Python/FFmpeg**:
   - Superpone las viñetas con `draw_wrapped_text_fitted`.
   - Aplica los fundidos y mezcla el `ambient_pad.wav`.
   - Renderiza a través de tubería hacia `ffmpeg -c:v h264_nvenc -preset p7 -cq 18`.
5. **Depositar el archivo master** en `/home/ruben/Escritorio/[Nombre_Video]_Master.mp4`.
