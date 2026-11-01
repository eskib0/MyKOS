#!/usr/bin/env python3
"""Analizador MyKOS — Panel de análisis de disco con estética MyKOS."""
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict

from PySide6.QtCore import QRectF, QSize, QThread, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

APP_ID = "es.mykos.analizador"
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analizador-mykos-icon.png")

# Sistemas de archivos virtuales / pseudo-FS de Linux que distorsionan el espacio real
VIRTUAL_PATHS = {"/proc", "/sys", "/dev", "/run"}


def human(n: int) -> str:
    val = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if val < 1024 or unit == "TiB":
            return f"{int(val)} {unit}" if unit == "B" else f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} TiB"


CATEGORIES = {
    "Vídeo": {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".mpg", ".mpeg", ".3gp", ".ts"},
    "Imágenes": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".tif", ".ico", ".heic", ".avif", ".raw"},
    "Audio": {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus", ".aiff", ".mid"},
    "Documentos": {".pdf", ".doc", ".docx", ".txt", ".md", ".odt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".epub"},
    "Comprimidos": {".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".zst", ".iso", ".deb", ".rpm", ".snap"},
    "Modelos IA": {".gguf", ".safetensors", ".bin", ".pt", ".pth", ".onnx", ".tflite"},
    "Código": {".py", ".js", ".ts", ".html", ".css", ".c", ".cpp", ".h", ".rs", ".go", ".java", ".json", ".xml", ".yaml", ".yml", ".sh", ".sql"},
}


def get_category(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return cat
    return "Otros"


class NumericTreeItem(QTreeWidgetItem):
    """Permite ordenar columnas numéricas usando UserRole."""
    def __lt__(self, other: QTreeWidgetItem) -> bool:
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        v1 = self.data(col, Qt.UserRole)
        v2 = other.data(col, Qt.UserRole)
        if v1 is not None and v2 is not None:
            return v1 < v2
        return super().__lt__(other)


def real_file_size(st: os.stat_result) -> int:
    """Devuelve el espacio real ocupado en disco (evita archivos huecos / kcore)."""
    if hasattr(st, "st_blocks") and st.st_blocks > 0:
        return min(st.st_size, st.st_blocks * 512)
    return st.st_size


def scan(path: str, cancelled) -> dict:
    """Escanea recursivamente ignorando /proc, /sys, /dev, /run."""
    node = {
        "name": os.path.basename(path) or path,
        "path": path,
        "size": 0,
        "mtime": 0.0,
        "is_dir": True,
        "children": [],
    }
    try:
        with os.scandir(path) as it:
            for e in it:
                if cancelled():
                    break
                try:
                    if e.is_symlink():
                        continue
                    full_path = e.path
                    if full_path in VIRTUAL_PATHS:
                        continue
                    if e.is_dir(follow_symlinks=False):
                        child = scan(full_path, cancelled)
                    else:
                        st = e.stat(follow_symlinks=False)
                        child = {
                            "name": e.name,
                            "path": full_path,
                            "size": real_file_size(st),
                            "mtime": st.st_mtime,
                            "is_dir": False,
                            "children": [],
                        }
                    node["children"].append(child)
                    node["size"] += child["size"]
                except OSError:
                    continue
    except OSError:
        pass
    return node


def collect_files(node: dict, out: list | None = None) -> list[dict]:
    if out is None:
        out = []
    if not node["is_dir"]:
        out.append(node)
    else:
        for c in node["children"]:
            collect_files(c, out)
    return out


class ScanThread(QThread):
    done = Signal(dict)

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        self.done.emit(scan(self.path, lambda: self._cancel))


def file_hash(path: str, quick: bool = False) -> str | None:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            if quick:
                h.update(f.read(65536))
            else:
                while chunk := f.read(1024 * 1024):
                    h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


class DuplicatesThread(QThread):
    done = Signal(list)
    progress = Signal(str)

    def __init__(self, files: list[dict], min_size: int = 1):
        super().__init__()
        self.files = files
        self.min_size = max(1, min_size)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        by_size: dict[int, list[dict]] = defaultdict(list)
        for f in self.files:
            if f["size"] >= self.min_size:
                by_size[f["size"]].append(f)

        candidates = [group for group in by_size.values() if len(group) > 1]
        results = []

        total_groups = len(candidates)
        for idx, group in enumerate(candidates):
            if self._cancel:
                break
            if idx % 20 == 0:
                self.progress.emit(f"Analizando grupo {idx + 1} de {total_groups}…")

            by_qhash: dict[str, list[dict]] = defaultdict(list)
            for f in group:
                if self._cancel:
                    break
                qh = file_hash(f["path"], quick=True)
                if qh:
                    by_qhash[qh].append(f)

            for qgroup in by_qhash.values():
                if len(qgroup) < 2:
                    continue
                by_fhash: dict[str, list[dict]] = defaultdict(list)
                for f in qgroup:
                    if self._cancel:
                        break
                    fh = file_hash(f["path"], quick=False)
                    if fh:
                        by_fhash[fh].append(f)
                for fh, dup_files in by_fhash.items():
                    if len(dup_files) > 1:
                        results.append((dup_files[0]["size"], fh, dup_files))

        results.sort(key=lambda x: -(x[0] * (len(x[2]) - 1)))
        self.done.emit(results)


PALETTE = [
    QColor("#2563eb"), QColor("#059669"), QColor("#d97706"), QColor("#e11d48"),
    QColor("#7c3aed"), QColor("#0891b2"), QColor("#4f46e5"), QColor("#ea580c"),
    QColor("#0d9488"), QColor("#9333ea"), QColor("#0284c7"), QColor("#65a30d"),
]


class TreemapWidget(QWidget):
    """Gráfico Treemap interactivo con estética MyKOS."""
    nodeActivated = Signal(dict)
    contextMenuRequested = Signal(dict, object)

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.root_node: dict | None = None
        self.current_node: dict | None = None
        self.history: list[dict] = []
        self.rects: list[tuple[QRectF, dict, QColor]] = []
        self.hovered: dict | None = None

    def set_root(self, node: dict | None):
        self.root_node = node
        self.current_node = node
        self.history.clear()
        self.update()

    def navigate_to(self, node: dict):
        if self.current_node and node != self.current_node:
            self.history.append(self.current_node)
        self.current_node = node
        self.nodeActivated.emit(node)
        self.update()

    def go_up(self):
        if self.history:
            self.current_node = self.history.pop()
            self.nodeActivated.emit(self.current_node)
            self.update()

    def _layout_slice_and_dice(self, items: list[dict], rect: QRectF, depth: int = 0, out: list | None = None):
        if out is None:
            out = []
        total = sum(i["size"] for i in items)
        if total <= 0 or rect.width() < 4 or rect.height() < 4:
            return out

        horizontal = rect.width() >= rect.height()
        pos = rect.x() if horizontal else rect.y()
        full_span = rect.width() if horizontal else rect.height()

        for idx, item in enumerate(items):
            if item["size"] <= 0:
                continue
            ratio = item["size"] / total
            span = full_span * ratio
            if horizontal:
                r = QRectF(pos, rect.y(), span, rect.height())
            else:
                r = QRectF(rect.x(), pos, rect.width(), span)
            pos += span

            color = PALETTE[idx % len(PALETTE)]
            if depth > 0:
                color = color.darker(115 + depth * 12)
            out.append((r, item, color))

            if item["is_dir"] and depth < 1 and r.width() > 48 and r.height() > 48:
                inner = r.adjusted(4, 22, -4, -4)
                children = sorted(item["children"], key=lambda c: -c["size"])[:18]
                self._layout_slice_and_dice(children, inner, depth + 1, out)
        return out

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self.rects.clear()

        painter.fillRect(self.rect(), QColor("#06101e"))

        if not self.current_node or self.current_node["size"] <= 0:
            painter.setPen(QColor("#8ca6c5"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Selecciona una carpeta para generar el mapa visual")
            return

        children = sorted(self.current_node["children"], key=lambda c: -c["size"])[:40]
        area = QRectF(self.rect()).adjusted(6, 6, -6, -6)
        self.rects = self._layout_slice_and_dice(children, area)

        font = QFont(self.font())
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)

        for r, item, color in self.rects:
            is_hover = item is self.hovered
            fill = color.lighter(122) if is_hover else color
            grad = QLinearGradient(r.topLeft(), r.bottomRight())
            grad.setColorAt(0, fill.lighter(108))
            grad.setColorAt(1, fill.darker(115))
            painter.setBrush(grad)
            painter.setPen(QPen(QColor("#6db9ff" if is_hover else "#040a12"), 1.8 if is_hover else 1.0))
            painter.drawRoundedRect(r, 5, 5)

            if r.width() > 58 and r.height() > 22:
                painter.setPen(QColor("#f4f8ff"))
                label = f"{item['name']} · {human(item['size'])}"
                text_rect = r.adjusted(6, 3, -6, -3)
                elided = painter.fontMetrics().elidedText(label, Qt.ElideRight, int(text_rect.width()))
                painter.drawText(text_rect, Qt.AlignTop | Qt.AlignLeft, elided)

    def _item_at(self, pos) -> dict | None:
        for r, item, _ in reversed(self.rects):
            if r.contains(pos):
                return item
        return None

    def mouseMoveEvent(self, event):
        item = self._item_at(event.position())
        if item is not self.hovered:
            self.hovered = item
            if item and self.current_node and self.current_node["size"] > 0:
                pct = item["size"] / self.current_node["size"] * 100
                self.setToolTip(f"{item['name']}\nRuta: {item['path']}\nTamaño: {human(item['size'])} ({pct:.1f}%)")
            else:
                self.setToolTip("")
            self.update()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self._item_at(event.position())
            if item and item["is_dir"]:
                self.navigate_to(item)

    def contextMenuEvent(self, event):
        item = self._item_at(event.pos())
        if item:
            self.contextMenuRequested.emit(item, event.globalPos())


class SidebarButton(QPushButton):
    """Botón de panel de mandos con el diseño de MyKOS Monitor."""
    def __init__(self, icon_txt: str, title_txt: str, sub_txt: str):
        super().__init__()
        self.setCheckable(True)
        self.setObjectName("selectorBtn")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(54)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.lbl_icon = QLabel(icon_txt)
        self.lbl_icon.setObjectName("selectorIcon")
        self.lbl_icon.setFixedWidth(22)

        mid = QVBoxLayout()
        mid.setSpacing(1)
        self.lbl_name = QLabel(title_txt)
        self.lbl_name.setObjectName("selectorName")
        self.lbl_status = QLabel(sub_txt)
        self.lbl_status.setObjectName("selectorStatus")
        mid.addWidget(self.lbl_name)
        mid.addWidget(self.lbl_status)

        self.lbl_value = QLabel("—")
        self.lbl_value.setObjectName("selectorValue")
        self.lbl_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        top.addWidget(self.lbl_icon)
        top.addLayout(mid, 1)
        top.addWidget(self.lbl_value)

        self.bar = QProgressBar()
        self.bar.setObjectName("selectorBar")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)

        lay.addLayout(top)
        lay.addWidget(self.bar)

    def set_metrics(self, value_text: str, status_text: str, pct: int):
        self.lbl_value.setText(value_text)
        self.lbl_status.setText(status_text)
        self.bar.setValue(max(0, min(100, pct)))


MYKOS_QSS = """
* {
    font-family: "Inter", "Cantarell", "Sans";
    color: #f4f8ff;
}
QMainWindow, QWidget#rootWidget {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0b2e59, stop:0.25 #050f1e, stop:1 #02060c);
}
QFrame#headerBar {
    background: rgba(4, 10, 18, 225);
    border-bottom: 1px solid #284c78;
}
QLabel#markLabel {
    font-size: 24px;
    color: #4fa8ff;
}
QLabel#appTitle {
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 1.4px;
    color: #f4f8ff;
}
QLabel#appSubtitle {
    font-size: 12px;
    color: #8da6c2;
}
QLabel#stateBadge {
    font-size: 11px;
    font-weight: 800;
    color: #36d399;
    letter-spacing: 0.8px;
}
QFrame#sidePanel {
    background: rgba(6, 16, 30, 230);
    border: 1px solid #365b87;
    border-radius: 14px;
}
QLabel#sectionTitle {
    font-size: 10px;
    font-weight: 800;
    color: #71b8ff;
    letter-spacing: 1.1px;
    padding: 4px 4px 2px 4px;
}
QPushButton#selectorBtn {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    text-align: left;
}
QPushButton#selectorBtn:hover {
    background: rgba(79, 168, 255, 35);
    border: 1px solid #4fa8ff;
}
QPushButton#selectorBtn:checked {
    background: rgba(79, 168, 255, 62);
    border: 1px solid #6db9ff;
}
QLabel#selectorIcon {
    font-size: 17px;
    color: #71b8ff;
    background: transparent;
}
QLabel#selectorName {
    font-size: 11px;
    font-weight: 800;
    color: #e5f1ff;
    background: transparent;
}
QLabel#selectorStatus {
    font-size: 10px;
    color: #8ca6c5;
    background: transparent;
}
QLabel#selectorValue {
    font-size: 13px;
    font-weight: 800;
    color: #f4f8ff;
    background: transparent;
}
QProgressBar#selectorBar {
    background: #102139;
    border: none;
    border-radius: 2px;
}
QProgressBar#selectorBar::chunk {
    background: #36d399;
    border-radius: 2px;
}
QLabel#summaryBanner {
    padding: 11px 16px;
    background: rgba(5, 19, 37, 220);
    border: 1px solid #547aa5;
    border-radius: 12px;
    color: #aac0da;
    font-size: 12px;
    font-weight: 700;
}
QLabel#selectedTitle {
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 1.2px;
    color: #d9ebff;
}
QFrame#eventSheet {
    background: rgba(6, 16, 30, 225);
    border: 1px solid #365b87;
    border-radius: 14px;
}
QFrame#previewCard {
    background: rgba(10, 24, 44, 210);
    border: 1px solid #2b4c73;
    border-radius: 10px;
}
QPushButton#actionBtn {
    background: rgba(16, 35, 60, 210);
    border: 1px solid #3b6998;
    border-radius: 8px;
    padding: 7px 14px;
    font-size: 12px;
    font-weight: 700;
    color: #e5f1ff;
}
QPushButton#actionBtn:hover {
    background: rgba(79, 168, 255, 60);
    border-color: #6db9ff;
}
QPushButton#actionBtn:disabled {
    color: #546e8a;
    border-color: #1f3652;
}
QPushButton#primaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1d4ed8, stop:1 #2563eb);
    border: 1px solid #60a5fa;
    border-radius: 8px;
    padding: 7px 16px;
    font-size: 12px;
    font-weight: 800;
    color: #ffffff;
}
QPushButton#primaryBtn:hover {
    background: #3b82f6;
}
QTreeWidget, QListWidget {
    background: rgba(4, 11, 22, 190);
    alternate-background-color: rgba(10, 24, 44, 160);
    border: 1px solid #2b4c73;
    border-radius: 10px;
    font-size: 12px;
    outline: none;
}
QTreeWidget::item {
    padding: 6px 8px;
    border-bottom: 1px solid rgba(29, 52, 83, 140);
}
QTreeWidget::item:hover, QListWidget::item:hover {
    background: rgba(79, 168, 255, 28);
}
QTreeWidget::item:selected, QListWidget::item:selected {
    background: rgba(79, 168, 255, 65);
    color: #ffffff;
}
QHeaderView::section {
    background: rgba(12, 28, 50, 240);
    color: #71b8ff;
    font-size: 11px;
    font-weight: 800;
    padding: 7px 8px;
    border: none;
    border-bottom: 1px solid #2b4c73;
}
QLineEdit, QComboBox, QSpinBox {
    background: rgba(10, 23, 42, 220);
    border: 1px solid #365b87;
    border-radius: 7px;
    padding: 5px 10px;
    color: #f4f8ff;
    font-size: 12px;
}
QProgressBar#scanProgress {
    background: #0a182c;
    border: 1px solid #2b4c73;
    border-radius: 5px;
    height: 8px;
}
QProgressBar#scanProgress::chunk {
    background: #4fa8ff;
    border-radius: 4px;
}
QMenu {
    background: #081526;
    border: 1px solid #365b87;
    padding: 6px;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 5px;
}
QMenu::item:selected {
    background: rgba(79, 168, 255, 65);
}
"""


class MediaLibraryPage(QWidget):
    """Página especializada para Imágenes, Vídeos o Música de todo el sistema escaneado."""
    contextMenuRequested = Signal(str, object)
    openRequested = Signal(str)

    def __init__(self, category: str, has_gallery: bool = False):
        super().__init__()
        self.category = category
        self.has_gallery = has_gallery
        self.files: list[dict] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(10)
        self.lbl_stats = QLabel(f"0 archivos · 0 B")
        self.lbl_stats.setObjectName("selectorName")
        ctrl.addWidget(self.lbl_stats)

        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText(f"Buscar en {category.lower()} por nombre o carpeta…")
        self.edit_search.textChanged.connect(self.refresh_view)
        ctrl.addWidget(self.edit_search, 1)

        ctrl.addWidget(QLabel("Carpeta:"))
        self.combo_folder = QComboBox()
        self.combo_folder.setMinimumWidth(190)
        self.combo_folder.currentTextChanged.connect(self.refresh_view)
        ctrl.addWidget(self.combo_folder)

        if self.has_gallery:
            self.btn_toggle_mode = QPushButton("🖼 Vista Cuadrícula")
            self.btn_toggle_mode.setObjectName("actionBtn")
            self.btn_toggle_mode.setCheckable(True)
            self.btn_toggle_mode.toggled.connect(self._on_mode_toggled)
            ctrl.addWidget(self.btn_toggle_mode)

        v.addLayout(ctrl)

        splitter = QSplitter(Qt.Horizontal)

        self.view_stack = QStackedWidget()

        # Vista de tabla detallada
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["ARCHIVO", "TAMAÑO", "EXT", "MODIFICADO", "CARPETA CONTENEDORA"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(4, QHeaderView.Stretch)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(1, Qt.DescendingOrder)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context)
        self.tree.itemDoubleClicked.connect(lambda item, _: self._emit_open(item.data(0, Qt.UserRole)))
        self.tree.currentItemChanged.connect(self._on_tree_selected)
        self.view_stack.addWidget(self.tree)

        # Vista de galería de miniaturas (para imágenes)
        if self.has_gallery:
            self.gallery = QListWidget()
            self.gallery.setViewMode(QListWidget.IconMode)
            self.gallery.setIconSize(QSize(110, 110))
            self.gallery.setGridSize(QSize(145, 148))
            self.gallery.setResizeMode(QListWidget.Adjust)
            self.gallery.setSpacing(8)
            self.gallery.setWordWrap(True)
            self.gallery.setContextMenuPolicy(Qt.CustomContextMenu)
            self.gallery.customContextMenuRequested.connect(self._on_gallery_context)
            self.gallery.itemDoubleClicked.connect(lambda item: self._emit_open(item.data(Qt.UserRole)))
            self.gallery.currentItemChanged.connect(self._on_gallery_selected)
            self.view_stack.addWidget(self.gallery)

        splitter.addWidget(self.view_stack)

        # Panel lateral de vista previa / ficha del archivo
        self.preview_card = QFrame()
        self.preview_card.setObjectName("previewCard")
        self.preview_card.setFixedWidth(250)
        p_lay = QVBoxLayout(self.preview_card)
        p_lay.setContentsMargins(12, 12, 12, 12)
        p_lay.setSpacing(8)

        lbl_p_hdr = QLabel("VISTA PREVIA / DETALLE")
        lbl_p_hdr.setObjectName("sectionTitle")
        p_lay.addWidget(lbl_p_hdr)

        self.lbl_thumb = QLabel("Selecciona un archivo")
        self.lbl_thumb.setAlignment(Qt.AlignCenter)
        self.lbl_thumb.setFixedHeight(175)
        self.lbl_thumb.setStyleSheet("background: rgba(4, 11, 22, 180); border: 1px solid #233f63; border-radius: 8px; color: #8ca6c5;")
        p_lay.addWidget(self.lbl_thumb)

        self.lbl_info_name = QLabel("—")
        self.lbl_info_name.setWordWrap(True)
        self.lbl_info_name.setObjectName("selectorName")
        p_lay.addWidget(self.lbl_info_name)

        self.lbl_info_meta = QLabel("")
        self.lbl_info_meta.setWordWrap(True)
        self.lbl_info_meta.setObjectName("appSubtitle")
        p_lay.addWidget(self.lbl_info_meta)

        self.btn_play_open = QPushButton("▶ Abrir / Reproducir")
        self.btn_play_open.setObjectName("primaryBtn")
        self.btn_play_open.setEnabled(False)
        self.btn_play_open.clicked.connect(self._open_current)
        p_lay.addWidget(self.btn_play_open)

        self.btn_open_dir = QPushButton("📂 Ver en carpeta")
        self.btn_open_dir.setObjectName("actionBtn")
        self.btn_open_dir.setEnabled(False)
        self.btn_open_dir.clicked.connect(self._open_current_dir)
        p_lay.addWidget(self.btn_open_dir)

        p_lay.addStretch(1)
        splitter.addWidget(self.preview_card)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        v.addWidget(splitter, 1)
        self._current_selected_path: str | None = None

    def set_files(self, all_files: list[dict]):
        self.files = [f for f in all_files if get_category(f["name"]) == self.category]
        total_sz = sum(f["size"] for f in self.files)
        self.lbl_stats.setText(f"{len(self.files):,} archivos · {human(total_sz)}")

        # Poblar carpetas más frecuentes
        folder_sizes: dict[str, int] = defaultdict(int)
        for f in self.files:
            folder_sizes[os.path.dirname(f["path"])] += f["size"]
        top_folders = sorted(folder_sizes.items(), key=lambda x: -x[1])[:40]

        self.combo_folder.blockSignals(True)
        self.combo_folder.clear()
        self.combo_folder.addItem("Todas las carpetas", "")
        for folder, sz in top_folders:
            short = folder if len(folder) < 38 else "…" + folder[-36:]
            self.combo_folder.addItem(f"{short} ({human(sz)})", folder)
        self.combo_folder.blockSignals(False)

        self.refresh_view()

    def _filtered_list(self) -> list[dict]:
        q = self.edit_search.text().strip().lower()
        target_dir = self.combo_folder.currentData() or ""
        out = []
        for f in self.files:
            if target_dir and os.path.dirname(f["path"]) != target_dir:
                continue
            if q and q not in f["name"].lower() and q not in f["path"].lower():
                continue
            out.append(f)
        return out

    def refresh_view(self):
        filtered = self._filtered_list()
        self.tree.setSortingEnabled(False)
        self.tree.clear()

        for f in filtered[:3000]:
            ext = os.path.splitext(f["name"])[1].lower() or "-"
            mtime = f.get("mtime", 0)
            date_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)) if mtime else "-"
            folder = os.path.dirname(f["path"])
            item = NumericTreeItem(
                self.tree,
                [f["name"], human(f["size"]), ext, date_str, folder],
            )
            item.setData(0, Qt.UserRole, f["path"])
            item.setData(1, Qt.UserRole, f["size"])
            item.setData(3, Qt.UserRole, mtime)
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)

        self.tree.setSortingEnabled(True)

        if self.has_gallery and self.view_stack.currentIndex() == 1:
            self._populate_gallery(filtered)

    def _populate_gallery(self, filtered: list[dict]):
        self.gallery.clear()
        for f in filtered[:250]:
            item = QListWidgetItem(f"{f['name']}\n({human(f['size'])})")
            item.setData(Qt.UserRole, f["path"])
            item.setToolTip(f"{f['name']}\n{human(f['size'])}\n{f['path']}")
            pix = QPixmap(f["path"])
            if not pix.isNull():
                item.setIcon(QIcon(pix.scaled(110, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            self.gallery.addItem(item)

    def _on_mode_toggled(self, checked: bool):
        if checked:
            self.btn_toggle_mode.setText("📋 Vista Tabla")
            self.view_stack.setCurrentIndex(1)
            self._populate_gallery(self._filtered_list())
        else:
            self.btn_toggle_mode.setText("🖼 Vista Cuadrícula")
            self.view_stack.setCurrentIndex(0)

    def _on_tree_selected(self, current: QTreeWidgetItem | None, _prev):
        if current:
            self._update_preview(current.data(0, Qt.UserRole))

    def _on_gallery_selected(self, current: QListWidgetItem | None, _prev):
        if current:
            self._update_preview(current.data(Qt.UserRole))

    def _update_preview(self, path: str | None):
        self._current_selected_path = path
        if not path or not os.path.exists(path):
            self.lbl_thumb.setPixmap(QPixmap())
            self.lbl_thumb.setText("Selecciona un archivo")
            self.lbl_info_name.setText("—")
            self.lbl_info_meta.setText("")
            self.btn_play_open.setEnabled(False)
            self.btn_open_dir.setEnabled(False)
            return

        self.btn_play_open.setEnabled(True)
        self.btn_open_dir.setEnabled(True)
        name = os.path.basename(path)
        try:
            st = os.stat(path)
            sz = human(real_file_size(st))
            dt = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
        except OSError:
            sz, dt = "—", "—"

        self.lbl_info_name.setText(name)
        extra = ""
        if self.category == "Imágenes":
            pix = QPixmap(path)
            if not pix.isNull():
                extra = f"\nResolución: {pix.width()} × {pix.height()} px"
                self.lbl_thumb.setPixmap(pix.scaled(220, 165, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.lbl_thumb.setPixmap(QPixmap())
                self.lbl_thumb.setText("🖼 Sin vista previa")
        elif self.category == "Vídeo":
            self.lbl_thumb.setPixmap(QPixmap())
            self.lbl_thumb.setText("🎬\nArchivo de Vídeo\nDoble clic para reproducir")
        elif self.category == "Audio":
            self.lbl_thumb.setPixmap(QPixmap())
            self.lbl_thumb.setText("🎵\nPista de Audio\nDoble clic para escuchar")

        self.lbl_info_meta.setText(f"Tamaño: {sz}\nFecha: {dt}{extra}\n\nCarpeta:\n{os.path.dirname(path)}")

    def _emit_open(self, path: str | None):
        if path and os.path.exists(path):
            self.openRequested.emit(path)

    def _open_current(self):
        self._emit_open(self._current_selected_path)

    def _open_current_dir(self):
        if self._current_selected_path:
            folder = os.path.dirname(self._current_selected_path)
            self.openRequested.emit(folder)

    def _on_tree_context(self, pos):
        item = self.tree.itemAt(pos)
        if item:
            path = item.data(0, Qt.UserRole)
            if path:
                self.contextMenuRequested.emit(path, self.tree.viewport().mapToGlobal(pos))

    def _on_gallery_context(self, pos):
        item = self.gallery.itemAt(pos)
        if item:
            path = item.data(Qt.UserRole)
            if path:
                self.contextMenuRequested.emit(path, self.gallery.viewport().mapToGlobal(pos))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Analizador MyKOS")
        self.resize(1240, 780)
        self.setMinimumSize(1020, 660)
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))

        self.thread_: ScanThread | None = None
        self.dup_thread: DuplicatesThread | None = None
        self.root_data: dict | None = None
        self.all_files: list[dict] = []
        self.dup_groups: list[tuple[int, str, list[dict]]] = []

        root = QWidget()
        root.setObjectName("rootWidget")
        self.setCentralWidget(root)
        root_lay = QVBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        # Cabecera estilo MyKOS Monitor
        header = QFrame()
        header.setObjectName("headerBar")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(24, 14, 24, 14)
        h_lay.setSpacing(12)

        mark = QLabel("◉")
        mark.setObjectName("markLabel")
        h_lay.addWidget(mark)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        lbl_title = QLabel("ANALIZADOR MyKOS")
        lbl_title.setObjectName("appTitle")
        lbl_sub = QLabel("Inspección de almacenamiento, mediateca del sistema y limpieza de disco")
        lbl_sub.setObjectName("appSubtitle")
        titles.addWidget(lbl_title)
        titles.addWidget(lbl_sub)
        h_lay.addLayout(titles)
        h_lay.addStretch(1)

        self.btn_sys = QPushButton("🖥 Todo el Sistema (/)")
        self.btn_sys.setObjectName("actionBtn")
        self.btn_sys.clicked.connect(lambda: self.start("/"))

        self.btn_home = QPushButton("🏠 Carpeta Personal")
        self.btn_home.setObjectName("actionBtn")
        self.btn_home.clicked.connect(lambda: self.start(os.path.expanduser("~")))

        self.btn_open = QPushButton("📂 Elegir carpeta…")
        self.btn_open.setObjectName("primaryBtn")
        self.btn_open.clicked.connect(self.choose)

        self.btn_cancel = QPushButton("⏹ Cancelar")
        self.btn_cancel.setObjectName("actionBtn")
        self.btn_cancel.clicked.connect(self.cancel_scan)
        self.btn_cancel.hide()

        self.btn_export = QPushButton("⬇ Exportar CSV")
        self.btn_export.setObjectName("actionBtn")
        self.btn_export.clicked.connect(self.export_csv)
        self.btn_export.setEnabled(False)

        self.lbl_state = QLabel("● LISTO")
        self.lbl_state.setObjectName("stateBadge")

        h_lay.addWidget(self.btn_sys)
        h_lay.addWidget(self.btn_home)
        h_lay.addWidget(self.btn_open)
        h_lay.addWidget(self.btn_cancel)
        h_lay.addWidget(self.btn_export)
        h_lay.addSpacing(8)
        h_lay.addWidget(self.lbl_state)
        root_lay.addWidget(header)

        # Cuerpo principal: Panel de mandos a la izquierda + Hoja central a la derecha
        body = QHBoxLayout()
        body.setContentsMargins(20, 16, 20, 16)
        body.setSpacing(18)
        root_lay.addLayout(body, 1)

        sidebar = QFrame()
        sidebar.setObjectName("sidePanel")
        sidebar.setFixedWidth(252)
        side_lay = QVBoxLayout(sidebar)
        side_lay.setContentsMargins(10, 10, 10, 10)
        side_lay.setSpacing(5)

        side_title = QLabel("PANEL DE ANÁLISIS")
        side_title.setObjectName("sectionTitle")
        side_lay.addWidget(side_title)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, SidebarButton] = {}

        analysis_defs = [
            ("tree", "▰", "ÁRBOL DISCO", "Jerarquía de carpetas", 0),
            ("treemap", "▦", "TREEMAP", "Mapa visual de bloques", 1),
            ("largest", "▲", "MÁS GRANDES", "Top archivos pesados", 2),
            ("types", "◈", "POR TIPO", "Filtro y categorías", 3),
            ("dups", "⧉", "DUPLICADOS", "Detector SHA-256", 4),
        ]

        for key, icon_txt, title_txt, sub_txt, idx in analysis_defs:
            btn = SidebarButton(icon_txt, title_txt, sub_txt)
            self.nav_group.addButton(btn, idx)
            self.nav_buttons[key] = btn
            side_lay.addWidget(btn)

        side_lay.addSpacing(6)
        media_title = QLabel("MEDIATECA DEL SISTEMA")
        media_title.setObjectName("sectionTitle")
        side_lay.addWidget(media_title)

        media_defs = [
            ("images", "🖼", "IMÁGENES", "Todas las fotos y gráficos", 5),
            ("videos", "🎬", "VÍDEOS", "Películas y clips", 6),
            ("audio", "🎵", "MÚSICA Y AUDIO", "Canciones y grabaciones", 7),
        ]

        for key, icon_txt, title_txt, sub_txt, idx in media_defs:
            btn = SidebarButton(icon_txt, title_txt, sub_txt)
            self.nav_group.addButton(btn, idx)
            self.nav_buttons[key] = btn
            side_lay.addWidget(btn)

        side_lay.addStretch(1)
        body.addWidget(sidebar)

        # Panel derecho
        main_col = QVBoxLayout()
        main_col.setSpacing(10)

        self.summary_banner = QLabel("PULSA 'CARPETA PERSONAL' O 'TODO EL SISTEMA (/)' PARA ESCANEAR ARCHIVOS Y MEDIATECA")
        self.summary_banner.setObjectName("summaryBanner")
        main_col.addWidget(self.summary_banner)

        self.progress = QProgressBar()
        self.progress.setObjectName("scanProgress")
        self.progress.setRange(0, 0)
        self.progress.hide()
        main_col.addWidget(self.progress)

        self.selection_title = QLabel("VISTA DE ALMACENAMIENTO · ÁRBOL DE CARPETAS")
        self.selection_title.setObjectName("selectedTitle")
        main_col.addWidget(self.selection_title)

        self.sheet = QFrame()
        self.sheet.setObjectName("eventSheet")
        sheet_lay = QVBoxLayout(self.sheet)
        sheet_lay.setContentsMargins(14, 14, 14, 14)

        self.stack = QStackedWidget()
        sheet_lay.addWidget(self.stack)
        main_col.addWidget(self.sheet, 1)
        body.addLayout(main_col, 1)

        self._build_tree_page()
        self._build_treemap_page()
        self._build_largest_page()
        self._build_types_page()
        self._build_duplicates_page()
        self._build_media_pages()

        self.nav_group.idClicked.connect(self._on_nav_changed)
        self.nav_buttons["tree"].setChecked(True)
        self.update_disk_summary()

    def update_disk_summary(self, scanned_path: str | None = None):
        target = scanned_path or os.path.expanduser("~")
        try:
            usage = shutil.disk_usage(target)
            pct = usage.used / usage.total * 100 if usage.total else 0
            disk_info = f"DISCO TOTAL  {human(usage.total)}     ·     USADO  {human(usage.used)} ({pct:.0f}%)     ·     LIBRE  {human(usage.free)}"
        except OSError:
            disk_info = "ESTADO DE ALMACENAMIENTO LOCAL"

        if self.root_data:
            self.summary_banner.setText(
                f"CARPETA  {self.root_data['path']} ({human(self.root_data['size'])} · {len(self.all_files):,} archivos)     ·     {disk_info}"
            )
        else:
            self.summary_banner.setText(disk_info)

    def _on_nav_changed(self, idx: int):
        titles = [
            "VISTA DE ALMACENAMIENTO · ÁRBOL DE CARPETAS",
            "MAPA PROPORCIONAL · GRÁFICO TREEMAP",
            "INSPECCIÓN DE ARCHIVOS · MÁS GRANDES",
            "CLASIFICACIÓN · FILTRO POR TIPO Y EXTENSIÓN",
            "AUDITORÍA DE ESPACIO · ARCHIVOS DUPLICADOS (SHA-256)",
            "MEDIATECA DEL SISTEMA · TODAS LAS IMÁGENES",
            "MEDIATECA DEL SISTEMA · TODOS LOS VÍDEOS",
            "MEDIATECA DEL SISTEMA · TODA LA MÚSICA Y AUDIO",
        ]
        self.selection_title.setText(titles[idx])
        self.stack.setCurrentIndex(idx)

    # --- Páginas del Stack ---

    def _build_tree_page(self):
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["CARPETA / ARCHIVO", "TAMAÑO REAL", "% DEL PADRE"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(1, Qt.DescendingOrder)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(lambda pos: self._show_tree_context_menu(self.tree, pos))
        self.stack.addWidget(self.tree)

    def _build_treemap_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        nav = QHBoxLayout()
        self.btn_tm_up = QPushButton("⬆ Subir nivel")
        self.btn_tm_up.setObjectName("actionBtn")
        self.btn_tm_up.clicked.connect(self._treemap_up)
        self.btn_tm_root = QPushButton("🏠 Raíz")
        self.btn_tm_root.setObjectName("actionBtn")
        self.btn_tm_root.clicked.connect(self._treemap_reset)
        self.lbl_tm_path = QLabel("Doble clic en cualquier bloque para explorar su interior · Clic derecho para acciones")
        self.lbl_tm_path.setObjectName("appSubtitle")
        nav.addWidget(self.btn_tm_up)
        nav.addWidget(self.btn_tm_root)
        nav.addWidget(self.lbl_tm_path, 1)

        self.treemap = TreemapWidget()
        self.treemap.nodeActivated.connect(self._on_treemap_nav)
        self.treemap.contextMenuRequested.connect(self._on_treemap_context)

        v.addLayout(nav)
        v.addWidget(self.treemap, 1)
        self.stack.addWidget(page)

    def _build_largest_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Mostrar top archivos:"))
        self.spin_top = QSpinBox()
        self.spin_top.setRange(10, 5000)
        self.spin_top.setSingleStep(50)
        self.spin_top.setValue(100)
        self.spin_top.valueChanged.connect(self.populate_largest)
        ctrl.addWidget(self.spin_top)
        ctrl.addStretch()

        self.tree_largest = QTreeWidget()
        self.tree_largest.setColumnCount(4)
        self.tree_largest.setHeaderLabels(["ARCHIVO", "TAMAÑO", "% DEL TOTAL", "RUTA COMPLETA"])
        self.tree_largest.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree_largest.header().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tree_largest.setSortingEnabled(True)
        self.tree_largest.sortByColumn(1, Qt.DescendingOrder)
        self.tree_largest.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_largest.customContextMenuRequested.connect(
            lambda pos: self._show_tree_context_menu(self.tree_largest, pos)
        )

        v.addLayout(ctrl)
        v.addWidget(self.tree_largest, 1)
        self.stack.addWidget(page)

    def _build_types_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Categoría:"))
        self.combo_cat = QComboBox()
        self.combo_cat.addItems(["Todas"] + list(CATEGORIES.keys()) + ["Otros"])
        self.combo_cat.currentTextChanged.connect(self.populate_filtered_files)
        ctrl.addWidget(self.combo_cat)

        ctrl.addWidget(QLabel("Filtrar por nombre o extensión:"))
        self.edit_ext = QLineEdit()
        self.edit_ext.setPlaceholderText("Ej: .gguf, .mp4, .snap, .iso…")
        self.edit_ext.textChanged.connect(self.populate_filtered_files)
        ctrl.addWidget(self.edit_ext, 1)

        splitter = QSplitter(Qt.Horizontal)

        self.tree_cats = QTreeWidget()
        self.tree_cats.setColumnCount(4)
        self.tree_cats.setHeaderLabels(["CATEGORÍA", "ARCHIVOS", "TAMAÑO", "%"])
        self.tree_cats.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree_cats.setSortingEnabled(True)
        self.tree_cats.sortByColumn(2, Qt.DescendingOrder)
        self.tree_cats.itemClicked.connect(self._on_cat_clicked)

        self.tree_filtered = QTreeWidget()
        self.tree_filtered.setColumnCount(3)
        self.tree_filtered.setHeaderLabels(["ARCHIVO", "TAMAÑO", "RUTA"])
        self.tree_filtered.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree_filtered.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tree_filtered.setSortingEnabled(True)
        self.tree_filtered.sortByColumn(1, Qt.DescendingOrder)
        self.tree_filtered.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_filtered.customContextMenuRequested.connect(
            lambda pos: self._show_tree_context_menu(self.tree_filtered, pos)
        )

        splitter.addWidget(self.tree_cats)
        splitter.addWidget(self.tree_filtered)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        v.addLayout(ctrl)
        v.addWidget(splitter, 1)
        self.stack.addWidget(page)

    def _build_duplicates_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Tamaño mínimo (KiB):"))
        self.spin_dup_min = QSpinBox()
        self.spin_dup_min.setRange(1, 1024 * 1024)
        self.spin_dup_min.setValue(64)
        ctrl.addWidget(self.spin_dup_min)

        self.btn_find_dups = QPushButton("🔍 Buscar duplicados (SHA-256)")
        self.btn_find_dups.setObjectName("primaryBtn")
        self.btn_find_dups.clicked.connect(self.start_duplicates_scan)
        self.btn_find_dups.setEnabled(False)
        ctrl.addWidget(self.btn_find_dups)

        self.lbl_dup_status = QLabel("Analiza una carpeta primero para activar el detector.")
        self.lbl_dup_status.setObjectName("appSubtitle")
        ctrl.addWidget(self.lbl_dup_status, 1)

        self.tree_dups = QTreeWidget()
        self.tree_dups.setColumnCount(3)
        self.tree_dups.setHeaderLabels(["GRUPO / ARCHIVO", "TAMAÑO / RECUPERABLE", "RUTA / HASH SHA-256"])
        self.tree_dups.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree_dups.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tree_dups.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_dups.customContextMenuRequested.connect(
            lambda pos: self._show_tree_context_menu(self.tree_dups, pos)
        )

        v.addLayout(ctrl)
        v.addWidget(self.tree_dups, 1)
        self.stack.addWidget(page)

    def _build_media_pages(self):
        self.page_images = MediaLibraryPage("Imágenes", has_gallery=True)
        self.page_videos = MediaLibraryPage("Vídeo", has_gallery=False)
        self.page_audio = MediaLibraryPage("Audio", has_gallery=False)

        for page in (self.page_images, self.page_videos, self.page_audio):
            page.contextMenuRequested.connect(self._open_context_menu_for_path)
            page.openRequested.connect(self.open_path)
            self.stack.addWidget(page)

    # --- Escaneo ---

    def choose(self):
        path = QFileDialog.getExistingDirectory(self, "Elegir carpeta para analizar", os.path.expanduser("~"))
        if path:
            self.start(path)

    def start(self, path: str):
        self.tree.clear()
        self.tree_largest.clear()
        self.tree_cats.clear()
        self.tree_filtered.clear()
        self.tree_dups.clear()
        self.treemap.set_root(None)
        self.dup_groups.clear()

        self.lbl_state.setText("● ANALIZANDO…")
        self.summary_banner.setText(f"ESCANEO EN CURSO · {path} (ignorando sistemas virtuales /proc, /sys, /dev, /run)…")
        self.progress.show()
        self.btn_open.setEnabled(False)
        self.btn_home.setEnabled(False)
        self.btn_sys.setEnabled(False)
        self.btn_cancel.show()
        self.btn_export.setEnabled(False)
        self.btn_find_dups.setEnabled(False)

        self.thread_ = ScanThread(path)
        self.thread_.done.connect(self.finished)
        self.thread_.start()

    def cancel_scan(self):
        if self.thread_ and self.thread_.isRunning():
            self.thread_.cancel()
        if self.dup_thread and self.dup_thread.isRunning():
            self.dup_thread.cancel()

    def finished(self, data: dict):
        self.progress.hide()
        self.btn_cancel.hide()
        self.btn_open.setEnabled(True)
        self.btn_home.setEnabled(True)
        self.btn_sys.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.btn_find_dups.setEnabled(True)
        self.lbl_state.setText("● ANÁLISIS ACTIVO")

        self.root_data = data
        self.all_files = collect_files(data)
        self.all_files.sort(key=lambda f: -f["size"])

        self.refresh_all_views()

    def refresh_all_views(self):
        if not self.root_data:
            return
        self.update_disk_summary(self.root_data["path"])

        self.tree.setSortingEnabled(False)
        self.tree.clear()
        self.add_node(self.tree.invisibleRootItem(), self.root_data, self.root_data["size"])
        if self.tree.topLevelItemCount() > 0:
            self.tree.topLevelItem(0).setExpanded(True)
        self.tree.setSortingEnabled(True)

        self.treemap.set_root(self.root_data)
        self.lbl_tm_path.setText(f"{self.root_data['path']} — {human(self.root_data['size'])}")

        self.populate_largest()
        self.populate_categories()
        self.populate_filtered_files()
        self.lbl_dup_status.setText("Pulsa 'Buscar duplicados' para auditar archivos idénticos.")

        # Poblar páginas de Mediateca
        self.page_images.set_files(self.all_files)
        self.page_videos.set_files(self.all_files)
        self.page_audio.set_files(self.all_files)

        # Actualizar indicadores del Panel de Mandos lateral
        total_sz = self.root_data["size"]
        try:
            usage = shutil.disk_usage(self.root_data["path"])
            disk_pct = int(min(100, total_sz / usage.total * 100)) if usage.total else 100
        except OSError:
            disk_pct = 100

        self.nav_buttons["tree"].set_metrics(
            human(total_sz), f"{len(self.root_data['children'])} subcarpetas", disk_pct
        )
        self.nav_buttons["treemap"].set_metrics(
            f"{len(self.root_data['children'])}", "Bloques raíz", min(100, len(self.root_data["children"]) * 4)
        )
        if self.all_files:
            top_f = self.all_files[0]
            top_pct = int(top_f["size"] / total_sz * 100) if total_sz else 0
            self.nav_buttons["largest"].set_metrics(human(top_f["size"]), top_f["name"], top_pct)
        else:
            self.nav_buttons["largest"].set_metrics("0 B", "Sin archivos", 0)

        self.nav_buttons["types"].set_metrics(
            f"{len(self.all_files):,}", "Archivos totales", 75
        )
        self.nav_buttons["dups"].set_metrics("Listo", "Pendiente escaneo", 0)

        for key, page in (("images", self.page_images), ("videos", self.page_videos), ("audio", self.page_audio)):
            cat_sz = sum(f["size"] for f in page.files)
            cat_pct = int(min(100, cat_sz / total_sz * 100)) if total_sz else 0
            self.nav_buttons[key].set_metrics(
                human(cat_sz), f"{len(page.files):,} archivos", cat_pct
            )

    def add_node(self, parent, node: dict, parent_size: int):
        pct = (node["size"] / parent_size * 100) if parent_size else 0.0
        item = NumericTreeItem(parent, [node["name"], human(node["size"]), f"{pct:.1f}%"])
        item.setData(0, Qt.UserRole, node["path"])
        item.setData(1, Qt.UserRole, node["size"])
        item.setData(2, Qt.UserRole, pct)
        item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
        for c in sorted(node["children"], key=lambda c: -c["size"]):
            self.add_node(item, c, node["size"])

    # --- Treemap ---

    def _on_treemap_nav(self, node: dict):
        self.lbl_tm_path.setText(f"{node['path']} — {human(node['size'])}")

    def _treemap_up(self):
        self.treemap.go_up()

    def _treemap_reset(self):
        if self.root_data:
            self.treemap.set_root(self.root_data)
            self.lbl_tm_path.setText(f"{self.root_data['path']} — {human(self.root_data['size'])}")

    def _on_treemap_context(self, node: dict, global_pos):
        self._open_context_menu_for_path(node["path"], global_pos)

    # --- Archivos más grandes ---

    def populate_largest(self):
        self.tree_largest.setSortingEnabled(False)
        self.tree_largest.clear()
        if not self.root_data:
            return
        total = self.root_data["size"]
        limit = self.spin_top.value()
        for f in self.all_files[:limit]:
            pct = (f["size"] / total * 100) if total else 0.0
            item = NumericTreeItem(
                self.tree_largest,
                [f["name"], human(f["size"]), f"{pct:.1f}%", f["path"]],
            )
            item.setData(0, Qt.UserRole, f["path"])
            item.setData(1, Qt.UserRole, f["size"])
            item.setData(2, Qt.UserRole, pct)
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
        self.tree_largest.setSortingEnabled(True)

    # --- Filtro por tipo ---

    def populate_categories(self):
        self.tree_cats.setSortingEnabled(False)
        self.tree_cats.clear()
        if not self.root_data:
            return
        total = self.root_data["size"]
        stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for f in self.all_files:
            cat = get_category(f["name"])
            stats[cat][0] += 1
            stats[cat][1] += f["size"]

        for cat, (count, sz) in stats.items():
            pct = (sz / total * 100) if total else 0.0
            item = NumericTreeItem(
                self.tree_cats,
                [cat, f"{count:,}", human(sz), f"{pct:.1f}%"],
            )
            item.setData(0, Qt.UserRole, cat)
            item.setData(1, Qt.UserRole, count)
            item.setData(2, Qt.UserRole, sz)
            item.setData(3, Qt.UserRole, pct)
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
            item.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)
        self.tree_cats.setSortingEnabled(True)

    def _on_cat_clicked(self, item: QTreeWidgetItem):
        cat = item.data(0, Qt.UserRole)
        if cat:
            self.combo_cat.setCurrentText(cat)

    def populate_filtered_files(self):
        self.tree_filtered.setSortingEnabled(False)
        self.tree_filtered.clear()
        if not self.root_data:
            return
        cat_filter = self.combo_cat.currentText()
        query = self.edit_ext.text().strip().lower()

        shown = 0
        for f in self.all_files:
            if cat_filter != "Todas" and get_category(f["name"]) != cat_filter:
                continue
            if query and query not in f["name"].lower():
                continue
            item = NumericTreeItem(
                self.tree_filtered,
                [f["name"], human(f["size"]), f["path"]],
            )
            item.setData(0, Qt.UserRole, f["path"])
            item.setData(1, Qt.UserRole, f["size"])
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            shown += 1
            if shown >= 2000:
                break
        self.tree_filtered.setSortingEnabled(True)

    # --- Duplicados ---

    def start_duplicates_scan(self):
        if not self.all_files:
            return
        min_bytes = self.spin_dup_min.value() * 1024
        self.tree_dups.clear()
        self.btn_find_dups.setEnabled(False)
        self.btn_cancel.show()
        self.progress.show()
        self.lbl_dup_status.setText("Calculando hashes SHA-256…")

        self.dup_thread = DuplicatesThread(self.all_files, min_bytes)
        self.dup_thread.progress.connect(self.lbl_dup_status.setText)
        self.dup_thread.done.connect(self.duplicates_finished)
        self.dup_thread.start()

    def duplicates_finished(self, groups: list):
        self.progress.hide()
        self.btn_cancel.hide()
        self.btn_find_dups.setEnabled(True)
        self.dup_groups = groups
        self.tree_dups.clear()

        total_wasted = sum(sz * (len(files) - 1) for sz, _, files in groups)
        self.lbl_dup_status.setText(
            f"Encontrados {len(groups)} grupos de duplicados · Espacio recuperable: {human(total_wasted)}"
        )
        pct = int(min(100, total_wasted / self.root_data["size"] * 100)) if (self.root_data and self.root_data["size"]) else 0
        self.nav_buttons["dups"].set_metrics(human(total_wasted), f"{len(groups)} grupos", pct)

        for sz, fhash, files in groups:
            wasted = sz * (len(files) - 1)
            group_item = NumericTreeItem(
                self.tree_dups,
                [
                    f"{len(files)} copias ({files[0]['name']})",
                    f"{human(wasted)} recuperables ({human(sz)} c/u)",
                    f"SHA-256: {fhash[:16]}…",
                ],
            )
            group_item.setData(1, Qt.UserRole, wasted)
            for f in files:
                child = NumericTreeItem(
                    group_item,
                    [f["name"], human(f["size"]), f["path"]],
                )
                child.setData(0, Qt.UserRole, f["path"])
                child.setData(1, Qt.UserRole, f["size"])
            group_item.setExpanded(True)

    # --- Menú contextual ---

    def _show_tree_context_menu(self, tree_widget: QTreeWidget, pos):
        item = tree_widget.itemAt(pos)
        if not item:
            return
        path = item.data(0, Qt.UserRole)
        if not path or not os.path.exists(path):
            return
        self._open_context_menu_for_path(path, tree_widget.viewport().mapToGlobal(pos))

    def _open_context_menu_for_path(self, path: str, global_pos):
        menu = QMenu(self)
        act_open = QAction("📄 Abrir archivo / carpeta", self)
        act_reveal = QAction("📂 Abrir carpeta contenedora", self)
        act_copy = QAction("📋 Copiar ruta", self)
        act_delete = QAction("🗑️ Eliminar del disco…", self)

        act_open.triggered.connect(lambda: self.open_path(path))
        act_reveal.triggered.connect(lambda: self.open_path_folder(path))
        act_copy.triggered.connect(lambda: QApplication.clipboard().setText(path))
        act_delete.triggered.connect(lambda: self.delete_path(path))

        menu.addAction(act_open)
        menu.addAction(act_reveal)
        menu.addAction(act_copy)
        menu.addSeparator()
        menu.addAction(act_delete)
        menu.exec(global_pos)

    def open_path(self, path: str):
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as e:
            QMessageBox.warning(self, "Error al abrir", str(e))

    def open_path_folder(self, path: str):
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        self.open_path(folder)

    def delete_path(self, path: str):
        is_dir = os.path.isdir(path)
        kind = "la carpeta y todo su contenido" if is_dir else "el archivo"
        reply = QMessageBox.question(
            self,
            "Confirmar eliminación",
            f"¿Seguro que quieres eliminar permanentemente {kind}?\n\n{path}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            if is_dir:
                shutil.rmtree(path)
            else:
                os.remove(path)
        except OSError as e:
            QMessageBox.critical(self, "Error al eliminar", str(e))
            return

        if self.root_data:
            if path == self.root_data["path"]:
                self.root_data = None
                self.tree.clear()
            else:
                self._remove_from_model(self.root_data, path)
                self.all_files = collect_files(self.root_data)
                self.all_files.sort(key=lambda f: -f["size"])
                self.refresh_all_views()

    def _remove_from_model(self, node: dict, target_path: str) -> int:
        for i, c in enumerate(node["children"]):
            if c["path"] == target_path:
                removed = c["size"]
                node["children"].pop(i)
                node["size"] -= removed
                return removed
            if c["is_dir"] and target_path.startswith(c["path"] + os.sep):
                removed = self._remove_from_model(c, target_path)
                if removed:
                    node["size"] -= removed
                    return removed
        return 0

    # --- Exportar CSV ---

    def export_csv(self):
        if not self.root_data:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar a CSV",
            os.path.expanduser("~/analizador_mykos.csv"),
            "Archivos CSV (*.csv)",
        )
        if not dest:
            return

        idx = self.stack.currentIndex()
        try:
            with open(dest, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if idx == 2:
                    writer.writerow(["Nombre", "Tamaño (Bytes)", "Tamaño", "Categoría", "Ruta"])
                    for item in self.all_files[: self.spin_top.value()]:
                        writer.writerow([item["name"], item["size"], human(item["size"]), get_category(item["name"]), item["path"]])
                elif idx == 4 and self.dup_groups:
                    writer.writerow(["Hash SHA-256", "Tamaño (Bytes)", "Tamaño", "Nombre", "Ruta"])
                    for sz, fhash, files in self.dup_groups:
                        for item in files:
                            writer.writerow([fhash, sz, human(sz), item["name"], item["path"]])
                elif idx in (5, 6, 7):
                    page = (self.page_images, self.page_videos, self.page_audio)[idx - 5]
                    writer.writerow(["Nombre", "Tamaño (Bytes)", "Tamaño", "Carpeta", "Ruta"])
                    for item in page._filtered_list():
                        writer.writerow([item["name"], item["size"], human(item["size"]), os.path.dirname(item["path"]), item["path"]])
                else:
                    writer.writerow(["Nombre", "Tipo", "Categoría", "Tamaño (Bytes)", "Tamaño", "Ruta"])
                    self._write_node_csv(writer, self.root_data)
            QMessageBox.information(self, "Exportación completada", f"Datos guardados en:\n{dest}")
        except OSError as e:
            QMessageBox.critical(self, "Error al exportar", str(e))

    def _write_node_csv(self, writer, node: dict):
        tipo = "Carpeta" if node["is_dir"] else "Archivo"
        cat = "-" if node["is_dir"] else get_category(node["name"])
        writer.writerow([node["name"], tipo, cat, node["size"], human(node["size"]), node["path"]])
        for c in sorted(node["children"], key=lambda x: -x["size"]):
            self._write_node_csv(writer, c)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setDesktopFileName(APP_ID)
    app.setStyleSheet(MYKOS_QSS)
    win = MainWindow()
    win.show()
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        win.start(sys.argv[1])
    sys.exit(app.exec())
