---
name: video-news
description: Generador autónomo y cinematográfico de mini-documentales y vídeos de noticias de IA de 3 minutos para YouTube. Locución nativa en español con OmniVoice, calibración acústica de estudio, motor visual V4 en 1080p con cero temblores y auto-escalado de texto. 100% local en GPU RTX 5060.
metadata:
  version: "1.0.0"
  author: "MyKOS & Antigravity"
  tags: ["youtube", "video-generation", "ai-news", "omnivoice", "nvenc", "v4-engine"]
---

# Video News Studio (`video-news`)
### Generador Cinematográfico de Noticias de Inteligencia Artificial para YouTube

Esta habilidad permite a MyKOS y a los agentes generar de forma 100% autónoma un vídeo documental completo de **3 minutos exactos (Full HD 1080p, 30 FPS)** para YouTube a partir del titular, artículo o enlace de cualquier noticia de IA.

Todo el proceso corre localmente sobre la GPU NVIDIA GeForce RTX 5060, sin llamadas a nubes de pago ni servicios externos.

---

## 🛡️ Las 3 Reglas de Oro Anti-Errores

1. **Cero Temblores (Anti-Jitter):**  
   - Queda estrictamente prohibido recortar y reescalar (`crop + resize`) imágenes con texto rasterizado para simular zooms (`Ken Burns`).  
   - Cada escena se renderiza en **1080p nativo sólido**, conectando las etapas mediante transiciones cinemáticas matemáticas (`Cosine Cross-Dissolve`, `Smoothstep Slide` y `Dip to Dark Glow`).
2. **Cero Desbordamiento (Bound Safety):**  
   - Prohibido el texto estático sin control de límites.
   - Obligatorio el uso de `draw_wrapped_text_fitted`, reduciendo el tamaño de fuente paso a paso hasta garantizar un margen mínimo de 30-40 px respecto a los bordes de la tarjeta.
3. **Fidelidad Editorial Estricta:**  
   - El vídeo debe tratar **100% sobre la noticia**, cubriendo con rigor: autor, métricas, arquitectura, ventajas, demostración práctica y repositorio de código abierto.

---

## ⏱️ Escaleta de Producción (3 Minutos · 6 Capítulos)

```
0:00 - 0:35 | CAPÍTULO 1: El Gancho & La Paradoja de la Nube (75-85 palabras)
0:35 - 1:05 | CAPÍTULO 2: Anatomía & Ficha de Ingeniería (65-75 palabras)
1:05 - 1:35 | CAPÍTULO 3: El Motor Tecnológico (WebGPU / Shaders) (65-75 palabras)
1:35 - 2:05 | CAPÍTULO 4: Demostración en Tiempo Real & Privacidad (70-80 palabras)
2:05 - 2:35 | CAPÍTULO 5: Casos de Uso Críticos & Soberanía (70-80 palabras)
2:35 - 3:00 | CAPÍTULO 6: Código Abierto, Outro YouTube & Lema Soberano (60-70 palabras)
```

---

## 🎙️ Configuración Acústica Oficial (Álvaro OmniVoice)

- **Voz de referencia:** Álvaro (español de España, tono documental riguroso, asertivo y cercano).
- **Entorno Python:** `/home/ruben/.config/VoiceStudio/runtime/project/.venv/bin/python`.
- **Motor:** `MyKOSVoiceStudio` con modelo OmniVoice sobre `cuda:0`.
- **Parámetros:** `seed=42`, `speed=1.05`, `guidance_scale=2.2`.
- **Mezcla Máster a 48.000 Hz:**
  - Locución normalizada a pico `0.85`.
  - Chime inicial (`intro_digital_chime.wav`) entre `0.0s` y `2.0s` (pico `0.35`).
  - Lecho ambiental (`ambient_pad.wav`) calibrado a `-27 dB` (factor `0.045`) en bucle continuo.
  - Lead-in: `2.0s` en Capítulo 1; `0.33s` (10 frames) en Capítulos 2 a 6.

---

## 🎨 Paleta Cromática V4 (HUD Técnico)

```python
BG_DARK       = (9, 13, 22)      # Fondo espacial profundo
BG_CARD       = (15, 21, 34)     # Tarjeta HUD primaria
BG_CARD_LIGHT = (22, 30, 48)     # Tarjeta secundaria
BORDER_DARK   = (36, 48, 72)     # Bordes técnicos
CYAN          = (0, 240, 255)    # Acento primario / Titulares
EMERALD       = (52, 211, 153)   # Datos locales / Rendimiento positivo
AMBER         = (245, 158, 11)   # Destacados / Alertas de atención
PURPLE        = (168, 85, 247)   # Hardware / Novedades de arquitectura
RED_ALERT     = (239, 68, 68)    # La nube / Cuotas / Monopolio
TEXT_WHITE    = (248, 250, 252)  # Texto destacado
TEXT_MUTED    = (148, 163, 184)  # Datos secundarios / Leyendas
```

---

## 🚀 Flujo de Ejecución Automatizado

1. **Recepción del Tema:** MyKOS extrae los datos clave de la noticia de IA.
2. **Generación del Guion:** Redacta los 6 bloques ajustados a ~450 palabras en total.
3. **Síntesis de Audio:** Lanza `generate_audio_woof.py` o módulo equivalente en VoiceStudio para obtener los 6 archivos WAV y sus duraciones exactas.
4. **Cálculo de Fotogramas:** Multiplica la duración de cada escena en segundos por `30.0` para calcular los frames requeridos con precisión milimétrica.
5. **Renderizado NVENC:** Ejecuta el motor V4 (`render_woof_v4.py`) pasando frames RGB por tubería a `ffmpeg` con `h264_nvenc` (`preset p7`, `cq 18`).
6. **Muxing y Depósito:** Concatena escenas, ensambla el audio de 48 kHz y deposita el archivo `.mp4` terminado en `/home/ruben/Escritorio/` listo para visualizar.

---

## 📂 Recursos de Referencia en el Sistema

- **Plantilla base de render V4:** `/home/ruben/MyKOS/promo_v2/documentary_woof_3min/render_woof_v4.py`
- **Generador de voz por lotes:** `/home/ruben/MyKOS/promo_v2/documentary_woof_3min/generate_audio_woof.py`
- **Manual completo y Hoja de Ruta:** `/home/ruben/MyKOS/docs/HOJA_DE_RUTA_SKILL_YOUTUBE_NOTICIAS_IA.md`
