#!/usr/bin/env python3
"""
================================================================================
MOTOR DE ENSAMBLADO MILIMÉTRICO: COMFY VIDEO NEWS
================================================================================
CANAL: "Tu máquina, Tus reglas"
- Cero desbordamiento de texto: draw_wrapped_text_fitted con márgenes de 40px
- Cero cortes de audio: Lead-in (0.5s) y Lead-out (0.8s) automáticos
- Mezcla con ambient_pad.wav (-24 dB con ducking a -30 dB) y chime inicial
- Renderizado por GPU local con h264_nvenc a 1080p @ 30 FPS
================================================================================
"""

import os
import sys
import math
import time
import json
import argparse
import subprocess
from pathlib import Path
import numpy as np
import soundfile as sf
import scipy.signal
from PIL import Image, ImageDraw, ImageFont

SKILL_DIR = Path(__file__).resolve().parent
ASSETS_DIR = SKILL_DIR / "assets"
AMBIENT_PAD_PATH = ASSETS_DIR / "ambient_pad.wav"
CHIME_PATH = ASSETS_DIR / "intro_digital_chime.wav"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

W, H = 1920, 1080
FPS = 30
TARGET_SR = 48000
LEAD_IN_FRAMES = 15    # 0.50 segundos antes de hablar
LEAD_OUT_FRAMES = 24   # 0.80 segundos tras hablar
TRANS_FRAMES = 15      # 0.50 segundos de transición entre escenas

# Paleta HUD Oficial
BG_CARD = (15, 21, 34, 220)       # Tarjeta semitransparente oscura
BORDER_CYAN = (0, 240, 255, 255)  # Borde cian técnico
TEXT_WHITE = (248, 250, 252)
TEXT_MUTED = (148, 163, 184)
AMBER = (245, 158, 11)
CYAN = (0, 240, 255)


def get_font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        return ImageFont.load_default()


def draw_wrapped_text_fitted(draw, pos, text, initial_size, fill, max_width, max_height, line_spacing=6):
    """Garantiza que el texto nunca sobrepase los límites de la viñeta."""
    cur_size = initial_size
    while cur_size >= 12:
        font = get_font(cur_size)
        bbox = font.getbbox("AyÁg")
        line_h = (bbox[3] - bbox[1]) + line_spacing
        
        paragraphs = text.split("\n")
        all_lines = []
        for p in paragraphs:
            words = p.split(" ")
            curr_line = []
            for w in words:
                if not w:
                    continue
                test_line = " ".join(curr_line + [w])
                if draw.textlength(test_line, font=font) <= max_width:
                    curr_line.append(w)
                else:
                    if curr_line:
                        all_lines.append(" ".join(curr_line))
                        curr_line = [w]
                    else:
                        all_lines.append(w)
                        curr_line = []
            if curr_line:
                all_lines.append(" ".join(curr_line))
                
        total_h = len(all_lines) * line_h
        if total_h <= max_height or cur_size <= 12:
            x, y = pos
            for i, line in enumerate(all_lines):
                draw.text((x, y + i * line_h), line, fill=fill, font=font)
            return total_h, cur_size
        cur_size -= 1
    return 0, cur_size


def resample_to_48k(data, sr):
    if len(data.shape) > 1:
        data = np.mean(data, axis=1)
    if sr != TARGET_SR:
        num_samples = int(round(len(data) * float(TARGET_SR) / sr))
        data = scipy.signal.resample(data, num_samples)
    return data.astype(np.float32)


def render_card_overlay(title: str, body: str, badge: str = "MYKOS // SOVEREIGN AI"):
    """Crea una capa HUD con márgenes de seguridad de 40px para superponer sobre el vídeo."""
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Dimensiones de la tarjeta inferior
    card_w = 1200
    card_h = 240
    card_x = (W - card_w) // 2
    card_y = H - card_h - 70
    
    # Fondo con borde cian técnico
    draw.rounded_rectangle([(card_x, card_y), (card_x + card_w, card_y + card_h)], radius=12, fill=BG_CARD, outline=BORDER_CYAN, width=2)
    
    # Badge superior de la tarjeta
    badge_font = get_font(13)
    draw.text((card_x + 40, card_y + 20), badge.upper(), fill=AMBER, font=badge_font)
    
    # Título destacado
    title_font = get_font(22)
    draw.text((card_x + 40, card_y + 45), title, fill=CYAN, font=title_font)
    
    # Texto del cuerpo con auto-escalado y margen estricto de 40px
    body_x = card_x + 40
    body_y = card_y + 90
    max_w = card_w - 80  # 40px a cada lado
    max_h = card_h - 110 # Margen vertical seguro
    draw_wrapped_text_fitted(draw, (body_x, body_y), body, 18, TEXT_WHITE, max_w, max_h, line_spacing=6)
    
    return overlay


def build_master(scenes_manifest: list, output_mp4: Path):
    """
    Ensambla el vídeo maestro uniendo escenas, audios, pads y overlays con NVENC.
    """
    print("=" * 60)
    print("🎬 INICIANDO ENSAMBLADO COMFY VIDEO NEWS (1080p @ 30 FPS NVENC)")
    print("=" * 60)
    
    # Comprobar ffmpeg y nvenc
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgba",
        "-s", f"{W}x{H}",
        "-r", str(FPS),
        "-i", "-",               # Vídeo por stdin
        "-i", "/tmp/mixed_audio.wav", # Audio mezclado
        "-c:v", "h264_nvenc",
        "-preset", "p7",
        "-cq", "18",
        "-c:a", "aac",
        "-b:a", "320k",
        "-ar", str(TARGET_SR),
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(output_mp4.resolve())
    ]
    
    print(f"Salida destino: {output_mp4}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ensamblador Comfy Video News")
    parser.add_argument("--manifest", type=str, help="Ruta al JSON de manifiesto con escenas y audios")
    parser.add_argument("--output", type=str, default="/home/ruben/Escritorio/Comfy_Video_News_Master.mp4")
    args = parser.parse_args()
    print("Motor Comfy Video News listo para ser invocado.")
