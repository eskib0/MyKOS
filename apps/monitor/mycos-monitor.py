#!/usr/bin/env python3
"""MyCOS Monitor: dashboard local con medidores circulares."""
import math
import os
import signal
import subprocess
import time
import cairo
import collections
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, Pango
import psutil

APP_ID = "es.mykos.monitor"
RING = ((0.00, "#36d399"), (0.55, "#f7d154"), (0.75, "#fb923c"), (0.90, "#fb5b6e"))

# Histórico circular por métrica: max 120 puntos (4 min a 2s)
HISTORY_LEN = 120
history = {"cpu": collections.deque(maxlen=HISTORY_LEN),
           "gpu": collections.deque(maxlen=HISTORY_LEN),
           "memory": collections.deque(maxlen=HISTORY_LEN),
           "disk": collections.deque(maxlen=HISTORY_LEN),
           "network": collections.deque(maxlen=HISTORY_LEN),
           "temperature": collections.deque(maxlen=HISTORY_LEN),
           "swap": collections.deque(maxlen=HISTORY_LEN),
           "fan": collections.deque(maxlen=HISTORY_LEN),
           "iface_speed": collections.deque(maxlen=HISTORY_LEN)}

def size(value):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB": return f"{value:.1f} {unit}"
        value /= 1024

def colour(value):
    return next(code for threshold, code in reversed(RING) if value >= threshold)

class Gauge(Gtk.DrawingArea):
    def __init__(self, title, icon, compact=False):
        super().__init__()
        self.title, self.icon, self.compact = title, icon, compact
        self.value, self.main, self.detail = 0, "—", "Cargando…"
        self.secondary_value = None
        self.left_title = self.right_title = None
        self.left_unit = self.right_unit = None
        self.right_main = None
        if compact:
            self.set_content_width(132); self.set_content_height(94)
        else:
            self.set_content_width(480); self.set_content_height(455); self.set_hexpand(True); self.set_vexpand(True)
        self.set_draw_func(self.draw)
    def update(self, value, main, detail, secondary_value=None, left_title=None, right_title=None, left_unit=None, right_unit=None, right_main=None):
        self.value = max(0, min(1, value)); self.main, self.detail = main, detail
        self.secondary_value = None if secondary_value is None else max(0, min(1, secondary_value))
        self.left_title, self.right_title = left_title, right_title
        self.left_unit, self.right_unit = left_unit, right_unit
        self.right_main = right_main
        self.queue_draw()
    @staticmethod
    def paint(ctx, code):
        code = code.lstrip("#"); ctx.set_source_rgb(*(int(code[i:i+2], 16)/255 for i in (0, 2, 4)))
    def draw_smc(self, ctx, width, height):
        """Esfera principal con la composición del medidor central de SMC."""
        cx, cy, radius = width * .43, height * .50, min(width, height) * .39
        start, end = math.radians(135), math.radians(405)
        # Sombra elíptica inferior y aro exterior azul con volumen.
        ctx.save(); ctx.translate(cx, cy + radius * .92); ctx.scale(1, .18)
        shade = cairo.RadialGradient(0, 0, 0, 0, 0, radius * .86)
        shade.add_color_stop_rgba(0, 0, 0, 0, .58); shade.add_color_stop_rgba(1, 0, 0, 0, 0)
        ctx.set_source(shade); ctx.arc(0, 0, radius * .86, 0, math.tau); ctx.fill(); ctx.restore()
        outer = cairo.RadialGradient(cx-radius*.28, cy-radius*.36, radius*.05, cx, cy, radius*1.16)
        outer.add_color_stop_rgb(0, .28, .47, .70); outer.add_color_stop_rgb(.38, .06, .14, .25); outer.add_color_stop_rgb(.76, .01, .03, .07); outer.add_color_stop_rgb(1, .24, .39, .60)
        ctx.set_source(outer); ctx.arc(cx, cy, radius + 18, 0, math.tau); ctx.fill()
        self.paint(ctx, "#07101b"); ctx.arc(cx, cy, radius + 10, 0, math.tau); ctx.fill()
        self.paint(ctx, "#1c3654"); ctx.arc(cx, cy, radius + 10, 0, math.tau); ctx.set_line_width(3); ctx.stroke()
        self.paint(ctx, "#101d2d"); ctx.arc(cx, cy, radius + 3, 0, math.tau); ctx.fill()
        # Dos arcos de actividad, verde a la izquierda y azul eléctrico a la derecha.
        for low, high, code in ((0, .50, "#55d319"), (.50, 1, "#4e8cff")):
            self.paint(ctx, "#263747"); ctx.set_line_width(13); ctx.arc(cx, cy, radius, start+(end-start)*low, start+(end-start)*high); ctx.stroke()
            self.paint(ctx, code); ctx.set_line_width(8)
            if self.secondary_value is not None:
                progress = self.value if low == 0 else self.secondary_value
            else:
                progress = min(1, self.value / .50) if low == 0 else max(0, min(1, (self.value-.50)/.50))
            if progress > .01:
                ctx.arc(cx, cy, radius, start+(end-start)*low+.018, start+(end-start)*(low+(high-low)*progress)-.018); ctx.stroke()
        for tick in range(21):
            angle = start + (end-start)*tick/20; outer_r = radius-9; inner_r = outer_r-(12 if tick%4 == 0 else 6)
            self.paint(ctx, "#eef6ff" if tick%4 == 0 else "#7990aa"); ctx.set_line_width(2 if tick%4 == 0 else 1)
            ctx.move_to(cx+math.cos(angle)*outer_r, cy+math.sin(angle)*outer_r); ctx.line_to(cx+math.cos(angle)*inner_r, cy+math.sin(angle)*inner_r); ctx.stroke()
            if tick % 4 == 0:
                label=str(tick*5); ctx.select_font_face("Sans", 0, 0); ctx.set_font_size(12); self.paint(ctx, "#dce8f7")
                ext=ctx.text_extents(label); label_r=radius-30; ctx.move_to(cx+math.cos(angle)*label_r-ext.width/2, cy+math.sin(angle)*label_r+ext.height/2); ctx.show_text(label)
        self.paint(ctx, "#172b43"); ctx.arc(cx, cy, radius*.57, 0, math.tau); ctx.fill()
        self.paint(ctx, "#4e6d91"); ctx.arc(cx, cy, radius*.57, 0, math.tau); ctx.set_line_width(2); ctx.stroke()
        self.paint(ctx, "#6f8eb1"); ctx.set_line_width(1); ctx.move_to(cx, cy-radius*.43); ctx.line_to(cx, cy+radius*.43); ctx.stroke()
        # Dos campos centrales al estilo del reloj de referencia; el derecho da contexto del sistema.
        ctx.select_font_face("Sans", 0, 0); ctx.set_font_size(14); self.paint(ctx, "#cbd9e8")
        l_title = self.left_title or self.title
        r_title = self.right_title or "NIVEL"
        for text, x in ((l_title, cx-radius*.29), (r_title, cx+radius*.29)):
            ext=ctx.text_extents(text); ctx.move_to(x-ext.width/2, cy-radius*.17); ctx.show_text(text)
        ctx.select_font_face("Sans", 0, 1); self.paint(ctx, "#f6f9ff")
        left_font = 26 if len(self.main) > 4 else 36
        ctx.set_font_size(left_font)
        ext=ctx.text_extents(self.main); ctx.move_to(cx-radius*.29-ext.width/2, cy+radius*.11); ctx.show_text(self.main)
        level = self.right_main if self.right_main is not None else f"{self.value*100:.0f}"
        right_font = 26 if len(level) > 4 else 36
        ctx.set_font_size(right_font)
        ext=ctx.text_extents(level); ctx.move_to(cx+radius*.29-ext.width/2, cy+radius*.11); ctx.show_text(level)
        ctx.select_font_face("Sans", 0, 0); ctx.set_font_size(11); self.paint(ctx, "#9cb7d5")
        l_unit = self.left_unit or "USO"
        r_unit = self.right_unit or "%"
        for text, x in ((l_unit, cx-radius*.29), (r_unit, cx+radius*.29)):
            ext=ctx.text_extents(text); ctx.move_to(x-ext.width/2, cy+radius*.25); ctx.show_text(text)
        ctx.select_font_face("Sans", 0, 0); self.paint(ctx, "#a9c1dc")
        lines = self.detail.split("\n")
        base_y = cy + radius * (.68 if len(lines) > 1 else .74)
        for idx, line in enumerate(lines):
            ctx.set_font_size(11 if len(lines) > 1 else 13)
            ext=ctx.text_extents(line)
            if ext.width > radius * 1.15:
                ctx.set_font_size(10); ext=ctx.text_extents(line)
            ctx.move_to(cx-ext.width/2, base_y + idx*15); ctx.show_text(line)
    def draw(self, _, ctx, width, height):
        if not self.compact:
            self.draw_smc(ctx, width, height); return
        # Cuadro de instrumentos: esfera 270°, aro, zona roja y aguja central.
        cx, cy, radius = width / 2, height * .50, min(width, height) * (.33 if self.compact else .40)
        start, end = math.radians(135), math.radians(405)
        ctx.set_line_cap(1)
        # Bisel azul profundo inspirado en el cuadro de System Monitoring Center.
        self.paint(ctx, "#02060d"); ctx.arc(cx, cy, radius + 17, 0, math.tau); ctx.fill()
        self.paint(ctx, "#4d719a"); ctx.arc(cx, cy, radius + 15, 0, math.tau); ctx.set_line_width(2); ctx.stroke()
        self.paint(ctx, "#112b4b"); ctx.arc(cx, cy, radius + 12, 0, math.tau); ctx.set_line_width(5); ctx.stroke()
        self.paint(ctx, "#071221"); ctx.arc(cx, cy, radius + 7, 0, math.tau); ctx.fill()
        self.paint(ctx, "#263f60"); ctx.arc(cx, cy, radius + 7, 0, math.tau); ctx.set_line_width(2); ctx.stroke()
        self.paint(ctx, "#101d2d"); ctx.arc(cx, cy, radius - 3, 0, math.tau); ctx.fill()
        for low, high, code in ((0, .55, "#36d399"), (.55, .75, "#f7d154"), (.75, .90, "#fb923c"), (.90, 1, "#ff334f")):
            self.paint(ctx, code); ctx.set_line_width(7)
            ctx.arc(cx, cy, radius, start + (end-start)*low + .012, start + (end-start)*high - .012); ctx.stroke()
        for tick in range(21):
            angle = start + (end-start) * tick / 20
            outer = radius - 5; inner = outer - ((7 if self.compact else 12) if tick % 5 == 0 else (3 if self.compact else 6))
            self.paint(ctx, "#f3f6fb" if tick % 5 == 0 else "#728197"); ctx.set_line_width(2 if tick % 5 == 0 else 1)
            ctx.move_to(cx + math.cos(angle)*outer, cy + math.sin(angle)*outer)
            ctx.line_to(cx + math.cos(angle)*inner, cy + math.sin(angle)*inner); ctx.stroke()
            if not self.compact and tick % 4 == 0:
                label = str(tick * 5)
                ctx.select_font_face("Sans", 0, 0); ctx.set_font_size(10); self.paint(ctx, "#dce8f7")
                ext = ctx.text_extents(label); label_r = radius - 26
                ctx.move_to(cx + math.cos(angle)*label_r-ext.width/2, cy + math.sin(angle)*label_r+ext.height/2); ctx.show_text(label)
        # Valor central sin aguja: como el medidor luminoso de SMC.
        self.paint(ctx, "#172b43"); ctx.arc(cx, cy, radius * .56, 0, math.tau); ctx.fill()
        self.paint(ctx, "#4d719a"); ctx.arc(cx, cy, radius * .56, 0, math.tau); ctx.set_line_width(1.5); ctx.stroke()
        ctx.select_font_face("Sans", 0, 1); ctx.set_font_size(8 if self.compact else 14); self.paint(ctx, "#c5d8ef")
        text = self.title; ext = ctx.text_extents(text); ctx.move_to(cx-ext.width/2, cy-(8 if self.compact else 21)); ctx.show_text(text)
        ctx.select_font_face("Sans", 0, 1); ctx.set_font_size(14 if self.compact else 42); self.paint(ctx, "#f4f8ff")
        ext = ctx.text_extents(self.main); ctx.move_to(cx-ext.width/2, cy+(6 if self.compact else 16)); ctx.show_text(self.main)
        if not self.compact:
            ctx.select_font_face("Sans", 0, 0); ctx.set_font_size(11); self.paint(ctx, "#9cb7d5")
            unit = "USO"; ext = ctx.text_extents(unit); ctx.move_to(cx-ext.width/2, cy+36); ctx.show_text(unit)
            ctx.set_font_size(12); self.paint(ctx, "#8da6c2")
            ext = ctx.text_extents(self.detail); ctx.move_to(cx-ext.width/2, height-24); ctx.show_text(self.detail)

class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.last_net = self.last_net_time = None
        self.last_disk = self.last_disk_time = None
        self.disk_gauge_extra = {}
        self.last_services_time = 0
        self.services_summary = (0, 0, 0)
        self.last_system_time = 0
        self.system_summary = (0.0, "—", "Cargando…")
        self.selected = "cpu"; self.metrics = {}; self.selector_status = {}; self.selector_buttons = {}
        # Gestión interactiva de procesos
        self.proc_search_query = ""
        self.proc_sort_col = "cpu"
        self.proc_sort_desc = True
        self.selected_proc_pid = None
        self.selected_proc_name = None
        self.proc_col_buttons = {}
    def do_activate(self):
        if self.props.active_window: self.props.active_window.present(); return
        self.window = Gtk.ApplicationWindow(application=self, title="MyCOS Monitor")
        self.window.set_default_size(1160, 720); self.window.set_size_request(980, 600)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); root.add_css_class("root"); self.window.set_child(root)
        header = Gtk.Box(spacing=13); header.add_css_class("header")
        mark = Gtk.Label(label="◉"); mark.add_css_class("mark"); header.append(mark)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title = Gtk.Label(label="MyCOS MONITOR", xalign=0); title.add_css_class("title"); labels.append(title)
        subtitle = Gtk.Label(label="Estado del sistema en tiempo real", xalign=0); subtitle.add_css_class("muted"); labels.append(subtitle)
        header.append(labels); header.append(Gtk.Box(hexpand=True))
        state = Gtk.Label(label="● SISTEMA ACTIVO"); state.add_css_class("state"); header.append(state); root.append(header)
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        body.set_margin_top(20); body.set_margin_bottom(20); body.set_margin_start(24); body.set_margin_end(24); root.append(body)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); sidebar.add_css_class("side-panel"); sidebar.set_size_request(230, -1)
        side_title = Gtk.Label(label="PANEL DE MANDOS", xalign=0); side_title.add_css_class("section"); sidebar.append(side_title)
        metric_defs = (
            ("cpu", "CPU", "◌"),
            ("gpu", "GPU", "◉"),
            ("memory", "MEMORIA", "▦"),
            ("disk", "DISCO", "▰"),
            ("network", "RED", "↟"),
            ("processes", "PROCESOS", "◼"),
            ("services", "SERVICIOS", "⚙"),
            ("system", "SISTEMA", "❖"),
        )
        for key, title, icon in metric_defs:
            button = Gtk.Button(); button.add_css_class("selector")
            selector = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            selector_top = Gtk.Box(spacing=8)
            symbol = Gtk.Label(label=icon); symbol.add_css_class("selector-icon"); selector_top.append(symbol)
            selector_labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1); selector_labels.set_size_request(126, -1)
            name = Gtk.Label(label=title, xalign=0); name.add_css_class("selector-name"); name.set_width_chars(15); name.set_max_width_chars(15); name.set_ellipsize(Pango.EllipsizeMode.END); selector_labels.append(name)
            status = Gtk.Label(label="Cargando…", xalign=0); status.add_css_class("selector-status"); status.set_width_chars(15); status.set_max_width_chars(15); status.set_ellipsize(Pango.EllipsizeMode.END); selector_labels.append(status)
            selector_top.append(selector_labels)
            value = Gtk.Label(label="—", xalign=1); value.add_css_class("selector-value"); value.set_width_chars(5); value.set_max_width_chars(5); value.set_size_request(54, -1); selector_top.append(value)
            bar = Gtk.ProgressBar(); bar.add_css_class("selector-bar"); bar.set_show_text(False)
            selector.append(selector_top); selector.append(bar); button.set_child(selector)
            button.connect("clicked", self.select_metric, key)
            sidebar.append(button); self.selector_status[key] = (value, status, bar); self.selector_buttons[key] = button
        body.append(sidebar)
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True, vexpand=True); main.add_css_class("main-panel")
        self.summary = Gtk.Label(xalign=0); self.summary.add_css_class("summary"); main.append(self.summary)
        self.selection_title = Gtk.Label(xalign=0); self.selection_title.add_css_class("selected-title"); main.append(self.selection_title)
        self.view_stack = Gtk.Stack(hexpand=True, vexpand=True)
        self.view_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.view_stack.set_transition_duration(150)
        self.main_gauge = Gauge("CPU", "◌"); self.main_gauge.add_css_class("main-gauge"); self.main_gauge.set_halign(Gtk.Align.CENTER)
        self.view_stack.add_named(self.main_gauge, "gauge")
        # Hoja de eventos / detalle de Procesos
        proc_sheet = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, hexpand=True, vexpand=True)
        proc_sheet.add_css_class("event-sheet")

        # Barra superior: estadísticas y buscador interactivo
        proc_top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.proc_header_stats = Gtk.Label(label="Cargando procesos…", xalign=0, hexpand=True)
        self.proc_header_stats.add_css_class("sheet-stats")
        proc_top_bar.append(self.proc_header_stats)

        self.proc_search = Gtk.SearchEntry()
        self.proc_search.set_placeholder_text("Buscar por nombre o PID…")
        self.proc_search.set_size_request(240, -1)
        self.proc_search.add_css_class("proc-search")
        self.proc_search.connect("search-changed", self.on_proc_search_changed)
        proc_top_bar.append(self.proc_search)
        proc_sheet.append(proc_top_bar)

        # Barra de acción e interactividad para el proceso seleccionado
        self.proc_action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.proc_action_bar.add_css_class("proc-action-bar")
        self.proc_action_icon = Gtk.Label(label="⚙")
        self.proc_action_icon.add_css_class("proc-action-icon")
        self.proc_action_bar.append(self.proc_action_icon)

        self.proc_action_label = Gtk.Label(label="Haz clic en un proceso para seleccionarlo y gestionarlo", xalign=0, hexpand=True)
        self.proc_action_label.add_css_class("proc-action-label")
        self.proc_action_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.proc_action_bar.append(self.proc_action_label)

        self.proc_feedback_label = Gtk.Label(label="", xalign=1)
        self.proc_feedback_label.add_css_class("proc-feedback-label")
        self.proc_action_bar.append(self.proc_feedback_label)

        self.btn_proc_term = Gtk.Button(label="Terminar (SIGTERM)")
        self.btn_proc_term.add_css_class("proc-btn-warn")
        self.btn_proc_term.set_sensitive(False)
        self.btn_proc_term.connect("clicked", lambda _: self.prompt_kill_selected(force=False))
        self.proc_action_bar.append(self.btn_proc_term)

        self.btn_proc_kill = Gtk.Button(label="Forzar (SIGKILL)")
        self.btn_proc_kill.add_css_class("proc-btn-danger")
        self.btn_proc_kill.set_sensitive(False)
        self.btn_proc_kill.connect("clicked", lambda _: self.prompt_kill_selected(force=True))
        self.proc_action_bar.append(self.btn_proc_kill)

        self.btn_proc_deselect = Gtk.Button(label="✕")
        self.btn_proc_deselect.add_css_class("proc-btn-close")
        self.btn_proc_deselect.set_sensitive(False)
        self.btn_proc_deselect.set_tooltip_text("Deseleccionar")
        self.btn_proc_deselect.connect("clicked", lambda _: self.deselect_process())
        self.proc_action_bar.append(self.btn_proc_deselect)

        proc_sheet.append(self.proc_action_bar)

        # Cabeceras de columna ordenables
        col_hdr = Gtk.Box(spacing=10); col_hdr.add_css_class("sheet-table-header")
        self.proc_col_buttons = {}
        cols = (
            ("pid", "PID", 7, 0, False),
            ("name", "PROCESO", 24, 0, True),
            ("status", "ESTADO", 11, 0, False),
            ("cpu", "CPU %", 8, 1, False),
            ("mem", "RAM %", 8, 1, False),
        )
        for col_id, title, chars, xal, hexp in cols:
            btn = Gtk.Button()
            btn.add_css_class("sheet-col-btn")
            if hexp:
                btn.set_hexpand(True)
            lbl = Gtk.Label(label=title, xalign=xal)
            lbl.set_width_chars(chars)
            lbl.add_css_class("sheet-col-title")
            btn.set_child(lbl)
            btn.connect("clicked", self.on_proc_sort_clicked, col_id)
            col_hdr.append(btn)
            self.proc_col_buttons[col_id] = (btn, lbl, title, chars, xal)

        act_hdr = Gtk.Label(label="ACCIÓN", xalign=0.5)
        act_hdr.set_width_chars(10)
        act_hdr.add_css_class("sheet-col-title")
        col_hdr.append(act_hdr)

        proc_sheet.append(col_hdr)
        self.update_sort_header_labels()

        proc_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        proc_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.processes_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        proc_scroll.set_child(self.processes_list)
        proc_sheet.append(proc_scroll)
        self.view_stack.add_named(proc_sheet, "processes")
        # Hoja de eventos / detalle de Servicios
        svc_sheet = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, hexpand=True, vexpand=True)
        svc_sheet.add_css_class("event-sheet")
        self.svc_header_stats = Gtk.Label(label="Cargando servicios…", xalign=0)
        self.svc_header_stats.add_css_class("sheet-stats")
        svc_sheet.append(self.svc_header_stats)
        svc_col_hdr = Gtk.Box(spacing=10); svc_col_hdr.add_css_class("sheet-table-header")
        for text, chars, xal, hexp in (("ÁMBITO", 8, 0, False), ("SERVICIO", 24, 0, False), ("ESTADO", 11, 0, False), ("DESCRIPCIÓN / EVENTO", 28, 0, True)):
            lbl = Gtk.Label(label=text, xalign=xal, hexpand=hexp); lbl.set_width_chars(chars); lbl.add_css_class("sheet-col-title")
            svc_col_hdr.append(lbl)
        svc_sheet.append(svc_col_hdr)
        svc_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        svc_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.services_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        svc_scroll.set_child(self.services_list)
        svc_sheet.append(svc_scroll)
        self.view_stack.add_named(svc_sheet, "services")
        # Hoja de especificaciones de Sistema (estilo System Monitoring Center)
        sys_sheet = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True, vexpand=True)
        sys_sheet.add_css_class("event-sheet")
        sys_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sys_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.system_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, hexpand=True)
        sys_scroll.set_child(self.system_content)
        sys_sheet.append(sys_scroll)
        self.view_stack.add_named(sys_sheet, "system")
        main.append(self.view_stack)
        body.append(main)
        self.load_css(); self.window.present(); psutil.cpu_percent(percpu=True); self.refresh(); GLib.timeout_add_seconds(2, self.refresh)
    def select_metric(self, _button, key):
        self.selected = key; self.show_selected()
    def show_selected(self):
        for key, button in self.selector_buttons.items():
            if key == self.selected: button.add_css_class("selected")
            else: button.remove_css_class("selected")
        title, value, main, detail = self.metrics.get(self.selected, (self.selected.upper(), 0, "—", "Cargando…"))
        if self.selected in ("processes", "services", "system"):
            self.selection_title.set_label(f"HOJA DE EVENTOS · {title}" if self.selected != "system" else f"FICHA DEL SISTEMA · {title}")
            self.view_stack.set_visible_child_name(self.selected)
        else:
            self.selection_title.set_label(f"MEDIDOR PRINCIPAL · {title}")
            self.view_stack.set_visible_child_name("gauge")
            self.main_gauge.title = title
            if self.selected == "disk" and self.disk_gauge_extra:
                self.main_gauge.update(**self.disk_gauge_extra)
            else:
                self.main_gauge.update(value, main, detail)
    def load_css(self):
        css = b'''* { font-family: "Inter", Cantarell, sans-serif; } window { background:transparent; } .root { background:linear-gradient(to bottom, rgba(23, 105, 255, 0.50), rgba(5, 15, 30, 0.82) 22%, rgba(2, 6, 12, 0.94) 100%); color:#f4f8ff; }
        .header { padding:18px 28px; background:rgba(4, 10, 18, 0.88); border-bottom:1px solid #284c78; } .mark { font-size:26px; color:#4fa8ff; }
        .title { font-size:18px; font-weight:800; letter-spacing:1.4px; } .muted { font-size:12px; color:#8da6c2; } .state { font-size:11px; font-weight:800; color:#36d399; letter-spacing:.8px; }
        .summary { padding:13px 16px; background:rgba(5, 19, 37, 0.86); border:1px solid #547aa5; border-radius:12px; color:#aac0da; font-size:12px; font-weight:700; }
        .side-panel { padding:14px 10px; background:linear-gradient(to right, rgba(2, 7, 14, 0.92), rgba(12, 30, 53, 0.78)); border:1px solid #365b87; border-radius:14px; } .main-panel { min-width:520px; }
        button.selector { padding:10px 9px; background:transparent; border:1px solid transparent; border-radius:10px; } button.selector:hover { background:rgba(79, 168, 255, 0.13); border-color:#4fa8ff; } button.selector.selected { background:rgba(79, 168, 255, 0.24); border-color:#6db9ff; box-shadow:inset 0 0 10px rgba(79, 168, 255, 0.32); }
        .selector-icon { min-width:19px; font-size:19px; color:#71b8ff; } .selector-name { font-size:12px; font-weight:800; letter-spacing:.8px; color:#e5f1ff; } .selector-status { font-size:10px; color:#8ca6c5; } .selector-value { font-size:17px; font-weight:800; color:#f4f8ff; } .selector-bar trough { min-height:5px; border-radius:4px; background:#102139; } .selector-bar progress { min-height:5px; border-radius:4px; background:#36d399; } button.status-yellow .selector-bar progress { background:#f7d154; } button.status-orange .selector-bar progress { background:#fb923c; } button.status-red .selector-bar progress { background:#fb5b6e; }
        .main-gauge { background:transparent; border:0; } .selected-title { font-size:13px; font-weight:800; letter-spacing:1.2px; color:#d9ebff; } .section { font-size:11px; font-weight:800; color:#9bb1ca; letter-spacing:1px; }
        .event-sheet { padding:16px 20px; background:rgba(6, 16, 30, 0.88); border:1px solid #365b87; border-radius:14px; }
        .sheet-stats { padding:8px 12px; background:rgba(16, 35, 60, 0.75); border:1px solid #2b4c73; border-radius:8px; font-size:12px; font-weight:700; color:#bde0ff; }
        .sheet-table-header { padding:6px 10px; border-bottom:1px solid #2b4c73; }
        .sheet-col-title { font-size:11px; font-weight:800; letter-spacing:.8px; color:#71b8ff; }
        .sheet-col-btn { background:transparent; border:0; padding:2px 4px; border-radius:4px; }
        .sheet-col-btn:hover { background:rgba(79, 168, 255, 0.15); }
        .col-active-sort .sheet-col-title { color:#4fa8ff; font-weight:900; }
        .proc-search { background:rgba(10, 24, 45, 0.85); color:#f4f8ff; border:1px solid #365b87; border-radius:8px; font-size:12px; padding:2px 8px; }
        .proc-search text { color:#f4f8ff; }
        .proc-search:focus-within { border-color:#4fa8ff; box-shadow:inset 0 0 4px rgba(79, 168, 255, 0.35); }
        .proc-action-bar { padding:8px 12px; background:rgba(12, 28, 50, 0.85); border:1px solid #284c78; border-radius:8px; }
        .proc-action-icon { font-size:15px; color:#71b8ff; }
        .proc-action-label { font-size:12px; font-weight:700; color:#cbd9e8; }
        .proc-feedback-label { font-size:12px; font-weight:700; margin-right:8px; }
        .feedback-ok { color:#36d399; }
        .feedback-error { color:#fb5b6e; }
        .proc-btn-warn { background:rgba(247, 209, 84, 0.15); border:1px solid #f7d154; border-radius:6px; color:#f7d154; font-size:11px; font-weight:700; padding:4px 10px; }
        .proc-btn-warn:hover { background:rgba(247, 209, 84, 0.30); color:#ffffff; }
        .proc-btn-danger { background:rgba(251, 91, 110, 0.15); border:1px solid #fb5b6e; border-radius:6px; color:#fb5b6e; font-size:11px; font-weight:700; padding:4px 10px; }
        .proc-btn-danger:hover { background:rgba(251, 91, 110, 0.30); color:#ffffff; }
        .proc-btn-close { background:transparent; border:1px solid #365b87; border-radius:6px; color:#8ca6c5; font-size:11px; padding:4px 8px; }
        .proc-btn-close:hover { background:rgba(79, 168, 255, 0.2); color:#ffffff; border-color:#4fa8ff; }
        .process { padding:7px 10px; border-bottom:1px solid rgba(29, 52, 83, 0.65); border-radius:6px; }
        .process:hover { background:rgba(79, 168, 255, 0.10); }
        .process-selected { background:rgba(79, 168, 255, 0.22); border:1px solid #4fa8ff; border-radius:6px; }
        .process-row-term-btn { background:rgba(251, 91, 110, 0.12); border:1px solid rgba(251, 91, 110, 0.4); border-radius:5px; color:#fb923c; font-size:10px; font-weight:700; padding:2px 8px; }
        .process-row-term-btn:hover { background:rgba(251, 91, 110, 0.35); border-color:#fb5b6e; color:#ffffff; }
        .process-pid { font-family: monospace; font-size:12px; color:#8ca6c5; }
        .process-name { font-size:13px; font-weight:700; color:#f4f8ff; }
        .process-state { font-size:11px; font-weight:700; color:#36d399; }
        .process-state-warn { font-size:11px; font-weight:800; color:#f7d154; }
        .process-state-fail { font-size:11px; font-weight:800; color:#fb5b6e; }
        .process-state-sleep { font-size:11px; color:#8ca6c5; }
        .process-meta { font-family: monospace; font-size:12px; font-weight:700; color:#d9ebff; }
        .service-desc { font-size:12px; color:#9cb7d5; }
        .sys-banner { padding:10px 14px; background:rgba(16, 35, 60, 0.65); border:1px solid #2b4c73; border-radius:10px; }
        .sys-hero-title { font-size:24px; font-weight:800; color:#f4f8ff; }
        .sys-hero-os { font-size:14px; font-weight:800; color:#71b8ff; }
        .sys-hero-vendor { font-size:12px; color:#aac0da; }
        .sys-card { padding:12px 14px; background:rgba(10, 23, 42, 0.72); border:1px solid #233f63; border-radius:10px; }
        .sys-section-title { font-size:13px; font-weight:800; color:#71b8ff; margin-bottom:4px; }
        .sys-key { font-size:12px; color:#9cb7d5; }
        .sys-val { font-size:12px; font-weight:800; color:#f4f8ff; }'''
        provider = Gtk.CssProvider(); provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(self.window.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    @staticmethod
    def gpu_reading():
        try:
            command = ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]
            util, temp, used, total = (float(v.strip()) for v in subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL, timeout=2).strip().split(","))
            return util/100, f"{util:.0f}%", f"{temp:.0f} °C · {used:.0f}/{total:.0f} MiB"
        except (FileNotFoundError, subprocess.SubprocessError, ValueError): return 0, "—", "No disponible"
    def on_proc_search_changed(self, entry):
        self.proc_search_query = entry.get_text()
        self.update_processes()

    def on_proc_sort_clicked(self, _button, col_id):
        if self.proc_sort_col == col_id:
            self.proc_sort_desc = not self.proc_sort_desc
        else:
            self.proc_sort_col = col_id
            self.proc_sort_desc = True if col_id in ("cpu", "mem") else False
        self.update_sort_header_labels()
        self.update_processes()

    def update_sort_header_labels(self):
        for col_id, (btn, lbl, title, _chars, _xal) in self.proc_col_buttons.items():
            if col_id == self.proc_sort_col:
                arrow = " ▼" if self.proc_sort_desc else " ▲"
                lbl.set_label(f"{title}{arrow}")
                btn.add_css_class("col-active-sort")
            else:
                lbl.set_label(title)
                btn.remove_css_class("col-active-sort")

    def select_process(self, pid, name):
        self.selected_proc_pid = pid
        self.selected_proc_name = name
        self.proc_action_label.set_label(f"Proceso: {name} (PID: {pid})")
        self.btn_proc_term.set_sensitive(True)
        self.btn_proc_kill.set_sensitive(True)
        self.btn_proc_deselect.set_sensitive(True)
        for child in self._get_box_children(self.processes_list):
            if getattr(child, "_proc_pid", None) == pid:
                child.add_css_class("process-selected")
            else:
                child.remove_css_class("process-selected")

    def deselect_process(self):
        self.selected_proc_pid = None
        self.selected_proc_name = None
        self.proc_action_label.set_label("Haz clic en un proceso para seleccionarlo y gestionarlo")
        self.btn_proc_term.set_sensitive(False)
        self.btn_proc_kill.set_sensitive(False)
        self.btn_proc_deselect.set_sensitive(False)
        for child in self._get_box_children(self.processes_list):
            child.remove_css_class("process-selected")

    @staticmethod
    def _get_box_children(box):
        children = []
        child = box.get_first_child()
        while child:
            children.append(child)
            child = child.get_next_sibling()
        return children

    def show_proc_feedback(self, msg, is_error=False):
        self.proc_feedback_label.set_label(msg)
        if is_error:
            self.proc_feedback_label.add_css_class("feedback-error")
            self.proc_feedback_label.remove_css_class("feedback-ok")
        else:
            self.proc_feedback_label.add_css_class("feedback-ok")
            self.proc_feedback_label.remove_css_class("feedback-error")

        def clear_msg():
            self.proc_feedback_label.set_label("")
            return False

        GLib.timeout_add_seconds(4, clear_msg)

    def prompt_kill_selected(self, force=False):
        if self.selected_proc_pid:
            self.prompt_kill_pid(self.selected_proc_pid, self.selected_proc_name or "proceso", force=force)

    def prompt_kill_pid(self, pid, name, force=False):
        self.select_process(pid, name)
        sig_type = "Forzar cierre (SIGKILL)" if force else "Terminar proceso (SIGTERM)"
        alert = Gtk.AlertDialog(
            message=f"¿{sig_type} de '{name}'?",
            detail=f"PID: {pid}\n¿Confirmas que deseas enviar la señal al proceso?",
            buttons=["Cancelar", "Forzar detención" if force else "Terminar proceso"]
        )
        alert.set_cancel_button(0)
        alert.set_default_button(1)

        def on_response(source, result):
            try:
                if source.choose_finish(result) == 1:
                    self.execute_kill(pid, name, force=force)
            except Exception:
                pass

        alert.choose(self.window, None, on_response)

    def execute_kill(self, pid, name, force=False):
        sig_name = "SIGKILL" if force else "SIGTERM"
        try:
            p = psutil.Process(pid)
            if force:
                p.kill()
            else:
                p.terminate()
            self.show_proc_feedback(f"✔ Señal {sig_name} enviada a '{name}' (PID {pid})", is_error=False)
            if self.selected_proc_pid == pid:
                self.deselect_process()
            self.update_processes()
        except psutil.NoSuchProcess:
            self.show_proc_feedback(f"ℹ El proceso '{name}' ({pid}) ya no existe", is_error=False)
            if self.selected_proc_pid == pid:
                self.deselect_process()
            self.update_processes()
        except psutil.AccessDenied:
            self.show_proc_feedback(f"✖ Permiso denegado para {pid}. Requiere privilegios root.", is_error=True)
        except Exception as e:
            self.show_proc_feedback(f"✖ Error: {e}", is_error=True)

    def _proc_sort_key(self, item):
        col = self.proc_sort_col
        if col == "cpu":
            return item.get("cpu_percent") or 0.0
        elif col == "mem":
            return item.get("memory_percent") or 0.0
        elif col == "pid":
            return item.get("pid") or 0
        elif col == "name":
            return (item.get("name") or "").lower()
        elif col == "status":
            return (item.get("status") or "").lower()
        return item.get("cpu_percent") or 0.0

    def update_processes(self):
        data = []
        running = sleeping = 0
        for proc in psutil.process_iter(("pid", "name", "cpu_percent", "memory_percent", "status")):
            try:
                info = proc.info
                data.append(info)
                st = info.get("status")
                if st == psutil.STATUS_RUNNING: running += 1
                else: sleeping += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        total = len(data)
        top_by_cpu = sorted(data, key=lambda item: item.get("cpu_percent") or 0.0, reverse=True)
        top_proc = top_by_cpu[0]["name"] if top_by_cpu else "—"
        top_cpu = (top_by_cpu[0].get("cpu_percent") or 0.0) if top_by_cpu else 0.0

        query = self.proc_search_query.strip().lower()
        if query:
            filtered = [
                item for item in data
                if query in (item.get("name") or "").lower() or query in str(item.get("pid") or "")
            ]
        else:
            filtered = data

        filtered.sort(key=self._proc_sort_key, reverse=self.proc_sort_desc)

        if query:
            self.proc_header_stats.set_label(
                f"FILTRO: {len(filtered)} de {total} procesos     ·     ACTIVOS: {running}     ·     TOP CPU: {top_proc} ({top_cpu:.1f}%)"
            )
        else:
            self.proc_header_stats.set_label(
                f"TOTAL: {total} procesos     ·     EJECUTANDO: {running}     ·     EN ESPERA: {sleeping}     ·     TOP CPU: {top_proc} ({top_cpu:.1f}%)"
            )

        while child := self.processes_list.get_first_child():
            self.processes_list.remove(child)

        state_map = {
            "running": "ACTIVO",
            "sleeping": "REPO",
            "disk-sleep": "I/O WAIT",
            "idle": "IDLE",
            "stopped": "PARADO",
            "zombie": "ZOMBIE",
        }

        limit = 60 if query else 30
        selected_still_present = False

        for item in filtered[:limit]:
            pid = item["pid"]
            name = item.get("name") or "desconocido"
            if pid == self.selected_proc_pid:
                selected_still_present = True

            row = Gtk.Box(spacing=10); row.add_css_class("process")
            row._proc_pid = pid
            if pid == self.selected_proc_pid:
                row.add_css_class("process-selected")

            pid_lbl = Gtk.Label(label=str(pid), xalign=0); pid_lbl.set_width_chars(7); pid_lbl.add_css_class("process-pid")
            name_lbl = Gtk.Label(label=name, xalign=0, hexpand=True); name_lbl.add_css_class("process-name"); name_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            raw_st = item.get("status") or "sleeping"
            st_lbl = Gtk.Label(label=state_map.get(raw_st, raw_st.upper()), xalign=0); st_lbl.set_width_chars(11)
            st_lbl.add_css_class("process-state" if raw_st == "running" else "process-state-sleep")
            cpu_val = item.get("cpu_percent") or 0.0
            ram_val = item.get("memory_percent") or 0.0
            cpu_lbl = Gtk.Label(label=f"{cpu_val:.1f}%", xalign=1); cpu_lbl.set_width_chars(8); cpu_lbl.add_css_class("process-meta")
            ram_lbl = Gtk.Label(label=f"{ram_val:.1f}%", xalign=1); ram_lbl.set_width_chars(8); ram_lbl.add_css_class("process-meta")

            term_btn = Gtk.Button(label="Terminar")
            term_btn.set_size_request(80, -1)
            term_btn.add_css_class("process-row-term-btn")
            term_btn.connect("clicked", lambda _b, p_pid=pid, p_name=name: self.prompt_kill_pid(p_pid, p_name, force=False))

            row.append(pid_lbl); row.append(name_lbl); row.append(st_lbl); row.append(cpu_lbl); row.append(ram_lbl); row.append(term_btn)

            click_ctrl = Gtk.GestureClick()
            click_ctrl.connect("released", lambda _g, _n, _x, _y, p_pid=pid, p_name=name: self.select_process(p_pid, p_name))
            row.add_controller(click_ctrl)

            self.processes_list.append(row)

        if self.selected_proc_pid and not selected_still_present and not any(p["pid"] == self.selected_proc_pid for p in data):
            self.deselect_process()

        return total, running, top_proc
    def update_services(self, now):
        if now - self.last_services_time < 4 and self.services_summary[0] > 0:
            return self.services_summary
        self.last_services_time = now
        items = []
        sys_running = user_running = failed_count = 0
        for scope, extra_args in (("SISTEMA", []), ("USUARIO", ["--user"])):
            try:
                cmd = ["systemctl", *extra_args, "list-units", "--type=service", "--state=running,failed", "--no-pager", "--no-legend"]
                out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=2)
                for line in out.splitlines():
                    line = line.lstrip("●* ").strip()
                    if not line: continue
                    parts = line.split(None, 4)
                    if len(parts) < 4: continue
                    unit, _load, _active, sub = parts[:4]
                    desc = parts[4] if len(parts) > 4 else ""
                    name = unit[:-8] if unit.endswith(".service") else unit
                    is_failed = (sub == "failed" or _active == "failed")
                    if is_failed:
                        failed_count += 1
                    elif scope == "SISTEMA":
                        sys_running += 1
                    else:
                        user_running += 1
                    items.append((0 if is_failed else (1 if scope == "SISTEMA" else 2), scope, name, "FALLIDO" if is_failed else "ACTIVO", desc, is_failed))
            except (FileNotFoundError, subprocess.SubprocessError):
                pass
        items.sort(key=lambda x: (x[0], x[2].lower()))
        total_running = sys_running + user_running
        self.svc_header_stats.set_label(
            f"ACTIVOS: {total_running} servicios     ·     SISTEMA: {sys_running}     ·     USUARIO: {user_running}     ·     FALLIDOS: {failed_count}"
        )
        while child := self.services_list.get_first_child():
            self.services_list.remove(child)
        for _, scope, name, state_txt, desc, is_failed in items[:60]:
            row = Gtk.Box(spacing=10); row.add_css_class("process")
            sc_lbl = Gtk.Label(label=scope, xalign=0); sc_lbl.set_width_chars(8); sc_lbl.add_css_class("process-pid")
            nm_lbl = Gtk.Label(label=name, xalign=0); nm_lbl.set_width_chars(24); nm_lbl.set_max_width_chars(24); nm_lbl.set_ellipsize(Pango.EllipsizeMode.END); nm_lbl.add_css_class("process-name")
            st_lbl = Gtk.Label(label=state_txt, xalign=0); st_lbl.set_width_chars(11)
            st_lbl.add_css_class("process-state-fail" if is_failed else "process-state")
            ds_lbl = Gtk.Label(label=desc, xalign=0, hexpand=True); ds_lbl.set_ellipsize(Pango.EllipsizeMode.END); ds_lbl.add_css_class("service-desc")
            row.append(sc_lbl); row.append(nm_lbl); row.append(st_lbl); row.append(ds_lbl)
            self.services_list.append(row)
        self.services_summary = (total_running, sys_running, failed_count)
        return self.services_summary
    @staticmethod
    def _read_dmi(field):
        try:
            with open(f"/sys/class/dmi/id/{field}", "r") as f:
                return f.read().strip() or "—"
        except OSError:
            return "—"
    def build_system_info(self):
        import platform, sys
        try:
            import tkinter
            tk_ver = str(tkinter.TkVersion)
        except ImportError:
            tk_ver = "8.6"
        os_rel = {}
        try:
            with open("/etc/os-release", "r") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        os_rel[k] = v.strip('"')
        except OSError:
            pass
        os_name = os_rel.get("NAME", "Linux")
        os_ver = os_rel.get("VERSION_ID", "")
        os_codename = os_rel.get("VERSION_CODENAME", "")
        os_ver_code = f"{os_ver}" + (f" ({os_codename})" if os_codename and os_codename not in os_ver else "")
        os_like = " ".join(w.capitalize() for w in os_rel.get("ID_LIKE", "debian").split())
        vendor = self._read_dmi("sys_vendor")
        product = self._read_dmi("product_name")
        chassis_map = {"3": "Desktop", "4": "Low Profile Desktop", "6": "Mini Tower", "7": "Tower", "8": "Portable", "9": "Laptop", "10": "Notebook"}
        chassis = chassis_map.get(self._read_dmi("chassis_type"), "Desktop")
        cpu_model = platform.processor() or "—"
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.startswith("model name"):
                        cpu_model = line.split(":", 1)[1].strip(); break
        except OSError:
            pass
        mem = psutil.virtual_memory(); swap = psutil.swap_memory()
        swap_txt = f"{size(swap.total)}" if swap.total > 0 else "0 B"
        mem_str = f"{size(mem.total)} (RAM)  -  {swap_txt} (Memoria Swap)"
        gpus = []
        try:
            out = subprocess.check_output(["lspci"], text=True, stderr=subprocess.DEVNULL, timeout=2)
            for line in out.splitlines():
                if "VGA compatible controller:" in line or "3D controller:" in line:
                    gpus.append(line.split(": ", 1)[1].strip())
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
        gpu1 = gpus[0] if len(gpus) > 0 else "—"
        gpu2 = gpus[1] if len(gpus) > 1 else "—"
        res_str = "—"
        monitors = 0
        try:
            xout = subprocess.check_output(["xrandr", "--current"], text=True, stderr=subprocess.DEVNULL, timeout=2)
            for line in xout.splitlines():
                if line.startswith("Screen 0:") and "current" in line:
                    res_str = line.split("current")[1].split(",")[0].strip().replace(" ", "")
                if " connected" in line:
                    monitors += 1
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
        if monitors == 0:
            monitors = 1
        apt_count = flatpak_count = 0
        try:
            dout = subprocess.check_output(["dpkg-query", "-f", ".\n", "-W"], text=True, stderr=subprocess.DEVNULL, timeout=3)
            apt_count = len(dout.splitlines())
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
        try:
            fout = subprocess.check_output(["flatpak", "list"], text=True, stderr=subprocess.DEVNULL, timeout=3)
            flatpak_count = len([l for l in fout.splitlines() if l.strip()])
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
        de = os.environ.get("XDG_CURRENT_DESKTOP", "GNOME")
        try:
            gout = subprocess.check_output(["gnome-shell", "--version"], text=True, stderr=subprocess.DEVNULL, timeout=2).strip()
            gver = gout.replace("GNOME Shell ", "").strip()
            if gver: de = f"{de} ({gver})"
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
        win_sys = os.environ.get("XDG_SESSION_TYPE", "x11").upper()
        dm = "—"
        try:
            with open("/etc/X11/default-display-manager", "r") as f:
                dm = os.path.basename(f.read().strip())
        except OSError:
            pass
        uname = os.uname()
        return {
            "os_banner": f"{os_name} - {os_ver}",
            "vendor_banner": f"{vendor} - {product}",
            "top": (
                ("CPU:", cpu_model),
                ("Memoria:", mem_str),
                ("GPU:", gpu1),
                ("GPU (2):", gpu2),
                ("Resolución:", res_str),
            ),
            "computer": (
                ("Marca:", vendor),
                ("Modelo:", product),
                ("Tipo de computadora:", chassis),
                ("Nombre:", uname.nodename),
                ("Arquitectura:", uname.machine),
                ("Número de monitores (pantallas):", str(monitors)),
            ),
            "os": (
                ("Nombre:", os_name),
                ("Versión - Nombre en clave:", os_ver_code),
                ("Familia de SO:", uname.sysname),
                ("Basado en:", os_like),
                ("Publicación del kernel:", uname.release),
                ("Versión del kernel:", uname.version),
            ),
            "packages": (
                ("Sistema:", f"{apt_count} (APT)"),
                ("Flatpak:", str(flatpak_count)),
                ("Versión de Tkinter:", tk_ver),
                ("Versión de Python:", sys.version.split()[0]),
                ("Versión de GTK:", f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"),
            ),
            "gui": (
                ("Entorno de escritorio:", de),
                ("Sistema de ventanas:", win_sys),
                ("Gestor de ventanas:", "-"),
                ("Gestor de pantalla:", dm),
            ),
            "short_os": os_name,
            "short_detail": f"{vendor} · {uname.release.split('-')[0]}",
        }
    def update_system(self, now):
        if self.system_content.get_first_child() is None or (now - self.last_system_time >= 30):
            self.last_system_time = now
            info = self.build_system_info()
            while child := self.system_content.get_first_child():
                self.system_content.remove(child)
            # Cabecera principal estilo SMC ("Sistema   Zorin OS - 18.1 / LENOVO - 91DF003VES")
            banner = Gtk.Box(spacing=18); banner.add_css_class("sys-banner")
            hero = Gtk.Label(label="Sistema", xalign=0); hero.add_css_class("sys-hero-title"); banner.append(hero)
            sub_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            os_lbl = Gtk.Label(label=info["os_banner"], xalign=0); os_lbl.add_css_class("sys-hero-os"); sub_box.append(os_lbl)
            ven_lbl = Gtk.Label(label=info["vendor_banner"], xalign=0); ven_lbl.add_css_class("sys-hero-vendor"); sub_box.append(ven_lbl)
            banner.append(sub_box)
            self.system_content.append(banner)
            # Bloque superior (CPU, Memoria, GPU, GPU 2, Resolución)
            top_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6); top_card.add_css_class("sys-card")
            top_grid = Gtk.Grid(column_spacing=24, row_spacing=5)
            for row_idx, (k, v) in enumerate(info["top"]):
                kl = Gtk.Label(label=k, xalign=0); kl.add_css_class("sys-key"); kl.set_width_chars(14)
                vl = Gtk.Label(label=v, xalign=0, hexpand=True); vl.add_css_class("sys-val"); vl.set_ellipsize(Pango.EllipsizeMode.END)
                top_grid.attach(kl, 0, row_idx, 1, 1); top_grid.attach(vl, 1, row_idx, 1, 1)
            top_card.append(top_grid)
            self.system_content.append(top_card)
            # Dos filas de 2 columnas: (Computador | Sistema operativo) y (Paquetes | Interfaz gráfica)
            for left_title, left_rows, right_title, right_rows in (
                ("Computador", info["computer"], "Sistema operativo (SO)", info["os"]),
                ("Paquetes", info["packages"], "Interfaz gráfica de usuario (GUI)", info["gui"]),
            ):
                row_box = Gtk.Box(spacing=14, homogeneous=True)
                for sec_title, sec_rows in ((left_title, left_rows), (right_title, right_rows)):
                    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True); card.add_css_class("sys-card")
                    st = Gtk.Label(label=sec_title, xalign=0); st.add_css_class("sys-section-title"); card.append(st)
                    grid = Gtk.Grid(column_spacing=16, row_spacing=5)
                    for r_idx, (k, v) in enumerate(sec_rows):
                        kl = Gtk.Label(label=k, xalign=0); kl.add_css_class("sys-key")
                        vl = Gtk.Label(label=v, xalign=0, hexpand=True); vl.add_css_class("sys-val"); vl.set_ellipsize(Pango.EllipsizeMode.END)
                        grid.attach(kl, 0, r_idx, 1, 1); grid.attach(vl, 1, r_idx, 1, 1)
                    card.append(grid)
                    row_box.append(card)
                self.system_content.append(row_box)
            self.system_summary = (0.35, "Zorin", info["short_detail"])
        return self.system_summary
    def refresh(self):
        cpu, memory, disk = psutil.cpu_percent(), psutil.virtual_memory(), psutil.disk_usage("/")
        now = time.monotonic()
        counters = psutil.net_io_counters(); rx = tx = 0
        if self.last_net:
            elapsed = max(now - self.last_net_time, .1); rx = (counters.bytes_recv - self.last_net.bytes_recv) / elapsed; tx = (counters.bytes_sent - self.last_net.bytes_sent) / elapsed
        self.last_net, self.last_net_time = counters, now
        disk_io = psutil.disk_io_counters(); dr = dw = 0
        if self.last_disk and disk_io:
            elapsed_d = max(now - self.last_disk_time, .1)
            dr = max(0, (disk_io.read_bytes - self.last_disk.read_bytes) / elapsed_d)
            dw = max(0, (disk_io.write_bytes - self.last_disk.write_bytes) / elapsed_d)
        self.last_disk, self.last_disk_time = disk_io, now
        disk_rate = dr + dw
        disk_demand = min(disk_rate / (250 * 1024 * 1024), 1.0)
        if disk_rate >= 1024 * 1024:
            demand_val, demand_unit = f"{disk_rate / (1024 * 1024):.1f}", "MiB/s"
        elif disk_rate >= 1024:
            demand_val, demand_unit = f"{disk_rate / 1024:.0f}", "KiB/s"
        else:
            demand_val, demand_unit = f"{disk_rate:.0f}", "B/s"
        self.disk_gauge_extra = {
            "value": disk_demand,
            "secondary_value": disk.percent / 100,
            "main": demand_val,
            "right_main": f"{disk.percent:.0f}%",
            "left_title": "DEMANDA",
            "right_title": "LLENO",
            "left_unit": demand_unit,
            "right_unit": f"{size(disk.free)} libres",
            "detail": f"{size(disk.used)} / {size(disk.total)} ({size(disk.free)} libres)\n↓ {size(dr)}/s  ·  ↑ {size(dw)}/s",
        }
        gpu_value, gpu_main, gpu_detail = self.gpu_reading()
        network=min((rx+tx)/(100*1024*1024),1)
        proc_total, proc_running, proc_top = self.update_processes()
        proc_ratio = min(proc_total / 500, 1.0)
        svc_total, svc_sys, svc_failed = self.update_services(now)
        svc_ratio = 0.95 if svc_failed > 0 else min(svc_total / 150, 0.50)
        svc_detail = f"{svc_failed} con fallo" if svc_failed > 0 else f"{svc_sys} sis · {svc_total - svc_sys} usr"
        sys_ratio, sys_main, sys_detail = self.update_system(now)
        self.metrics = {
            "cpu": ("CPU", cpu/100, f"{cpu:.0f}%", f"{psutil.cpu_count()} hilos activos"),
            "gpu": ("GPU", gpu_value, gpu_main, gpu_detail),
            "memory": ("MEMORIA", memory.percent/100, f"{memory.percent:.0f}%", f"{size(memory.used)} de {size(memory.total)}"),
            "disk": ("DISCO", disk.percent/100, f"{disk.percent:.0f}%", f"{size(disk.free)} · ⇅ {size(disk_rate)}/s"),
            "network": ("RED", network, f"{network*100:.0f}%", f"↓ {size(rx)}/s · ↑ {size(tx)}/s"),
            "processes": ("PROCESOS", proc_ratio, str(proc_total), f"{proc_running} act · {proc_top}"),
            "services": ("SERVICIOS", svc_ratio, str(svc_total), svc_detail),
            "system": ("SISTEMA", sys_ratio, sys_main, sys_detail),
        }
        for key, (title, value, main, detail) in self.metrics.items():
            value_label, status_label, bar = self.selector_status[key]
            value_label.set_label(main); status_label.set_label(detail); bar.set_fraction(value)
            button = self.selector_buttons[key]
            for level in ("status-green", "status-yellow", "status-orange", "status-red"): button.remove_css_class(level)
            button.add_css_class("status-green" if value < .55 else "status-yellow" if value < .75 else "status-orange" if value < .90 else "status-red")
        uptime=int(time.time()-psutil.boot_time()); days, rest=divmod(uptime,86400); load=os.getloadavg()
        self.summary.set_label(f"ACTIVO  {days}d {rest//3600}h {(rest%3600)//60}m     ·     CARGA  {load[0]:.2f} · {load[1]:.2f} · {load[2]:.2f}     ·     KERNEL  {os.uname().release}")
        self.show_selected(); return True

if __name__ == "__main__": App().run()
