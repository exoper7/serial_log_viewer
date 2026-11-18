"""Serial Log Viewer - podglad i zbieranie logow z portu COM (ESP-IDF).

Uruchomienie:
    pip install -r requirements.txt
    python serial_log_viewer.py
"""

from __future__ import annotations

import colorsys
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import serial
import serial.tools.list_ports
from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, QRect, QSettings, QSize, Qt, QThread,
    QTimer, QUrl, Signal,
)
from PySide6.QtGui import (
    QAction, QColor, QDesktopServices, QFont, QFontDatabase, QIcon,
    QKeySequence, QPainter, QPalette, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QStyle, QStyledItemDelegate, QTableView, QToolButton, QVBoxLayout, QWidget,
)

from log_parser import LEVEL_NAMES, LEVELS, NO_TAG, LineAssembler, LogEntry, LogParser

APP_NAME = "Serial Log Viewer"
APP_DIR = Path(__file__).resolve().parent
LOG_DIR = APP_DIR / "logs"
MAX_ENTRIES = 300_000      # limit wpisow w pamieci (plik logu zbiera wszystko)
TRIM_CHUNK = 50_000        # ile najstarszych wpisow usunac po przekroczeniu limitu
BAUD_RATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600", "1500000", "2000000"]

# ---------------------------------------------------------------- motyw ----
C_BG = "#14161b"
C_PANEL = "#1b1e24"
C_PANEL2 = "#21252c"
C_BORDER = "#2b3039"
C_TEXT = "#d8dbe2"
C_MUTED = "#8b919d"
C_DIM = "#5b616d"
C_ACCENT = "#4f8cff"
C_SEL = "#2a3a5c"

LEVEL_COLORS = {
    "E": "#ff5f5f",
    "W": "#f2b43c",
    "I": "#4cc38a",
    "D": "#58a6ff",
    "V": "#a58bff",
    "-": "#8b919d",
}
LEVEL_SHORT = {"E": "ERR", "W": "WARN", "I": "INFO", "D": "DBG", "V": "VRB", "-": "—"}
NO_TAG_LABEL = "(bez tagu)"

QSS = f"""
* {{ font-family: "Segoe UI"; font-size: 9pt; color: {C_TEXT}; }}
QMainWindow, QWidget#central {{ background: {C_BG}; }}
QFrame#topbar, QFrame#filterbar {{ background: {C_PANEL}; border-bottom: 1px solid {C_BORDER}; }}
QFrame#sidebar {{ background: {C_PANEL}; border-right: 1px solid {C_BORDER}; }}
QLabel#sectionTitle {{ color: {C_MUTED}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }}
QLabel#appTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#statusDot {{ font-size: 12pt; }}

QComboBox, QLineEdit {{
    background: {C_PANEL2}; border: 1px solid {C_BORDER}; border-radius: 6px;
    padding: 5px 8px; selection-background-color: {C_ACCENT};
}}
QComboBox:hover, QLineEdit:hover {{ border-color: #3a404b; }}
QComboBox:focus, QLineEdit:focus {{ border-color: {C_ACCENT}; }}
QLineEdit[invalid="true"] {{ border-color: {LEVEL_COLORS['E']}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {C_PANEL2}; border: 1px solid {C_BORDER}; selection-background-color: {C_SEL}; outline: 0;
}}

QPushButton, QToolButton {{
    background: {C_PANEL2}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 5px 10px;
}}
QPushButton:hover, QToolButton:hover {{ background: #2a2f38; border-color: #3a404b; }}
QPushButton:pressed, QToolButton:pressed {{ background: #323843; }}
QPushButton:checked, QToolButton:checked {{ background: #24324d; border-color: {C_ACCENT}; color: #cfe0ff; }}
QPushButton:disabled, QToolButton:disabled {{ color: {C_DIM}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QPushButton#primary {{ background: {C_ACCENT}; border-color: {C_ACCENT}; color: white; font-weight: 600; padding: 5px 16px; }}
QPushButton#primary:hover {{ background: #6a9dff; }}
QPushButton#danger {{ background: #3a2026; border-color: #6b2b35; color: #ffb3b3; font-weight: 600; padding: 5px 16px; }}
QPushButton#danger:hover {{ background: #4a2830; }}
QPushButton#link {{ background: transparent; border: none; color: {C_MUTED}; padding: 2px 6px; }}
QPushButton#link:hover {{ color: {C_TEXT}; }}

QTableView {{
    background: {C_BG}; alternate-background-color: #171a1f; border: none;
    gridline-color: transparent; selection-background-color: {C_SEL}; selection-color: {C_TEXT};
    outline: 0;
}}
QHeaderView::section {{
    background: {C_PANEL}; color: {C_MUTED}; border: none; border-bottom: 1px solid {C_BORDER};
    border-right: 1px solid {C_BORDER}; padding: 4px 8px; font-size: 8pt; font-weight: 600;
}}
QListWidget {{ background: transparent; border: none; outline: 0; }}
QPlainTextEdit#detail {{
    background: {C_PANEL}; border: none; border-top: 1px solid {C_BORDER};
    selection-background-color: {C_ACCENT};
}}
QSplitter::handle {{ background: {C_BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QStatusBar {{ background: {C_PANEL}; border-top: 1px solid {C_BORDER}; color: {C_MUTED}; }}
QStatusBar QLabel {{ color: {C_MUTED}; padding: 0 8px; }}
QMenu {{ background: {C_PANEL2}; border: 1px solid {C_BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background: {C_SEL}; }}
QMenu::separator {{ height: 1px; background: {C_BORDER}; margin: 4px 8px; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #343a45; border-radius: 4px; min-height: 30px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: #454c59; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #343a45; border-radius: 4px; min-width: 30px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{ background: {C_PANEL2}; color: {C_TEXT}; border: 1px solid {C_BORDER}; padding: 4px; }}
"""


def tag_color(tag: str) -> QColor:
    """Stabilny, czytelny na ciemnym tle kolor dla nazwy watku."""
    if tag == NO_TAG:
        return QColor(C_MUTED)
    h = int(hashlib.md5(tag.encode("utf-8")).hexdigest()[:6], 16)
    hue = (h % 360) / 360.0
    sat = 0.45 + ((h >> 9) % 20) / 100.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.68, sat)
    return QColor(int(r * 255), int(g * 255), int(b * 255))


def tag_label(tag: str) -> str:
    return tag if tag != NO_TAG else NO_TAG_LABEL


def rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


_ICON_FONT = None


def icon(glyph: str, color: str = C_TEXT, size: int = 16) -> QIcon:
    """Ikona z fontu Segoe MDL2 Assets (Windows 10/11)."""
    global _ICON_FONT
    if _ICON_FONT is None:
        fams = QFontDatabase.families()
        _ICON_FONT = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in fams), "")
    if not _ICON_FONT:
        return QIcon()
    ic = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.TextAntialiasing)
        f = QFont(_ICON_FONT)
        f.setPixelSize(int(size * 0.8))
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, glyph)
        p.end()
        ic.addPixmap(pm)
    return ic


G_REFRESH, G_PLAY, G_STOP, G_DELETE, G_SAVE = "", "", "", "", ""
G_OPEN, G_FOLDER, G_SEARCH, G_DOWN, G_POWER, G_COPY = "", "", "", "", "", ""


def mono_family() -> str:
    fams = QFontDatabase.families()
    return next((f for f in ("Cascadia Mono", "Cascadia Code", "JetBrains Mono", "Consolas") if f in fams), "Courier New")


def mono_font(pt: float = 9.5) -> QFont:
    f = QFont(mono_family())
    f.setPointSizeF(pt)
    f.setStyleHint(QFont.Monospace)
    return f


def fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1000:.0f}k"
    return str(n)


# ------------------------------------------------------- watek portu COM ----
class SerialReader(QThread):
    entries = Signal(list)        # list[LogEntry]
    raw_lines = Signal(list)      # list[(datetime, str)] - do zapisu w pliku
    state = Signal(str, bool)     # komunikat, czy polaczony

    def __init__(self, port: str, baud: int, auto_reconnect: bool, parser: LogParser):
        super().__init__()
        self.port = port
        self.baud = baud
        self.auto_reconnect = auto_reconnect
        self.parser = parser
        self.rx_bytes = 0
        self._stop = False
        self._reset_req = False

    def stop(self):
        self._stop = True

    def request_reset(self):
        self._reset_req = True

    def _wait(self, seconds: float):
        end = time.monotonic() + seconds
        while not self._stop and time.monotonic() < end:
            self.msleep(50)

    def run(self):
        first = True
        while not self._stop:
            ser = None
            try:
                ser = serial.Serial()
                ser.port = self.port
                ser.baudrate = self.baud
                ser.timeout = 0.05
                # DTR/RTS nieaktywne, jak w idf.py monitor - nie trzymamy ESP w resecie/bootloaderze
                ser.dtr = False
                ser.rts = False
                ser.open()
                self.state.emit(f"Połączono: {self.port} @ {self.baud}", True)
                first = True
                self._loop(ser)
            except (serial.SerialException, OSError, ValueError) as e:
                if first or not self.auto_reconnect:
                    self.state.emit(f"{self.port}: {e}", False)
                first = False
            finally:
                if ser is not None and ser.is_open:
                    try:
                        ser.close()
                    except Exception:
                        pass
            if self._stop or not self.auto_reconnect:
                break
            self.state.emit(f"{self.port}: oczekiwanie na port (auto-połączenie)…", False)
            self._wait(1.0)
        self.state.emit("Rozłączono", False)

    def _loop(self, ser: serial.Serial):
        asm = LineAssembler()
        batch: list[LogEntry] = []
        raws: list[tuple[datetime, str]] = []
        last_emit = last_rx = time.monotonic()

        def take(line: str):
            ts = datetime.now()
            raws.append((ts, line))
            batch.extend(self.parser.parse(line, ts))

        while not self._stop:
            if self._reset_req:
                self._reset_req = False
                ser.dtr = False
                ser.rts = True       # EN = 0
                time.sleep(0.12)
                ser.rts = False      # EN = 1 -> start aplikacji
            data = ser.read(ser.in_waiting or 1)
            now = time.monotonic()
            if data:
                self.rx_bytes += len(data)
                last_rx = now
                for line in asm.feed(data):
                    take(line)
            elif asm.has_partial() and now - last_rx > 0.3:
                take(asm.flush())  # linia bez '\n' (np. prompt)
            if (batch or raws) and (now - last_emit > 0.05 or len(batch) > 1000):
                self._emit(batch, raws)
                batch, raws = [], []
                last_emit = now
        if asm.has_partial():
            take(asm.flush())
        self._emit(batch, raws)

    def _emit(self, batch, raws):
        if raws:
            self.raw_lines.emit(raws)
        if batch:
            self.entries.emit(batch)


# ------------------------------------------------------------- model logu ----
COL_TIME, COL_DEV, COL_LEVEL, COL_TAG, COL_MSG = range(5)


class LogModel(QAbstractTableModel):
    HEADERS = ["CZAS", "URZ. [ms]", "POZIOM", "WĄTEK", "WIADOMOŚĆ"]

    def __init__(self):
        super().__init__()
        self.all: list[LogEntry] = []
        self.rows: list[LogEntry] = []
        self.levels = set(LEVELS)
        self.hidden_tags: set[str] = set()
        self.text_re: re.Pattern | None = None
        self.tag_counts: dict[str, int] = {}
        self.level_counts: dict[str, int] = {l: 0 for l in LEVELS}
        self._tag_colors: dict[str, QColor] = {}
        self._level_q = {k: QColor(v) for k, v in LEVEL_COLORS.items()}
        self._bg_err = QColor(255, 80, 80, 26)
        self._bg_warn = QColor(242, 180, 60, 18)
        self._muted = QColor(C_MUTED)
        self._dim = QColor(C_DIM)

    # --- filtrowanie
    def accepts(self, e: LogEntry) -> bool:
        if e.level not in self.levels or e.tag in self.hidden_tags:
            return False
        return self.text_re is None or self.text_re.search(e.raw) is not None

    def refilter(self):
        self.beginResetModel()
        acc = self.accepts
        self.rows = [e for e in self.all if acc(e)]
        self.endResetModel()

    def color_for(self, tag: str) -> QColor:
        c = self._tag_colors.get(tag)
        if c is None:
            c = self._tag_colors[tag] = tag_color(tag)
        return c

    # --- dane
    def append(self, batch: list[LogEntry]) -> set[str]:
        """Dodaje wpisy, zwraca zbior nowo zobaczonych tagow."""
        new_tags = set()
        tc, lc = self.tag_counts, self.level_counts
        for e in batch:
            if e.tag not in tc:
                tc[e.tag] = 0
                new_tags.add(e.tag)
            tc[e.tag] += 1
            lc[e.level] += 1
        self.all.extend(batch)
        if len(self.all) > MAX_ENTRIES:
            self._trim()
        else:
            vis = [e for e in batch if self.accepts(e)]
            if vis:
                n = len(self.rows)
                self.beginInsertRows(QModelIndex(), n, n + len(vis) - 1)
                self.rows.extend(vis)
                self.endInsertRows()
        return new_tags

    def _trim(self):
        drop = self.all[:TRIM_CHUNK]
        for e in drop:
            self.tag_counts[e.tag] -= 1
            self.level_counts[e.level] -= 1
        del self.all[:TRIM_CHUNK]
        self.refilter()

    def clear(self):
        self.beginResetModel()
        self.all.clear()
        self.rows.clear()
        self.tag_counts.clear()
        self.level_counts = {l: 0 for l in LEVELS}
        self.endResetModel()

    # --- Qt
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 5

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        e = self.rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == COL_MSG:
                return e.msg
            if col == COL_TAG:
                return tag_label(e.tag)
            if col == COL_TIME:
                return e.host_ts.strftime("%H:%M:%S.") + f"{e.host_ts.microsecond // 1000:03d}"
            if col == COL_DEV:
                return "" if e.dev_ts is None else str(e.dev_ts)
            if col == COL_LEVEL:
                return e.level
        elif role == Qt.ForegroundRole:
            if col == COL_TAG:
                return self.color_for(e.tag)
            if col == COL_MSG:
                if e.level in ("E", "W"):
                    return self._level_q[e.level]
                if e.level in ("D", "V", "-"):
                    return self._muted if e.level != "-" else None
            if col in (COL_TIME, COL_DEV):
                return self._dim
        elif role == Qt.BackgroundRole:
            if e.level == "E":
                return self._bg_err
            if e.level == "W":
                return self._bg_warn
        elif role == Qt.ToolTipRole and col == COL_MSG and len(e.msg) > 120:
            return e.msg[:2000]
        return None

    def entry(self, row: int) -> LogEntry:
        return self.rows[row]


class LevelDelegate(QStyledItemDelegate):
    """Kolumna poziomu rysowana jako kolorowa 'pigulka'."""

    def paint(self, p: QPainter, opt, index):
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else QApplication.style()
        lvl = index.data(Qt.DisplayRole)
        opt.text = ""
        style.drawControl(QStyle.CE_ItemViewItem, opt, p, opt.widget)
        c = QColor(LEVEL_COLORS.get(lvl, C_MUTED))
        text = LEVEL_SHORT.get(lvl, lvl)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = opt.rect
        w = min(r.width() - 10, 46)
        pill = QRect(r.left() + 6, r.center().y() - 7, w, 15)
        bg = QColor(c)
        bg.setAlpha(38)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(pill, 7, 7)
        f = QFont(opt.font)
        f.setFamily("Segoe UI")
        f.setPointSizeF(7)
        f.setBold(True)
        p.setFont(f)
        p.setPen(c)
        p.drawText(pill, Qt.AlignCenter, text)
        p.restore()


# ------------------------------------------------------ lista watkow --------
ROLE_TAG = Qt.UserRole
ROLE_VISIBLE = Qt.UserRole + 1
ROLE_COUNT = Qt.UserRole + 2
ROLE_COLOR = Qt.UserRole + 3


class ThreadDelegate(QStyledItemDelegate):
    def sizeHint(self, opt, index):
        return QSize(0, 28)

    def paint(self, p: QPainter, opt, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = opt.rect
        visible = bool(index.data(ROLE_VISIBLE))
        color = QColor(index.data(ROLE_COLOR))
        count = index.data(ROLE_COUNT) or 0
        name = tag_label(index.data(ROLE_TAG))

        if opt.state & QStyle.State_MouseOver:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#262a32"))
            p.drawRoundedRect(r.adjusted(6, 1, -6, -1), 6, 6)

        dot = QRect(r.left() + 16, r.center().y() - 4, 9, 9)
        if visible:
            p.setPen(Qt.NoPen)
            p.setBrush(color)
        else:
            p.setPen(QPen(QColor(C_DIM), 1.4))
            p.setBrush(Qt.NoBrush)
        p.drawEllipse(dot)

        fm = opt.fontMetrics
        ctext = fmt_count(count)
        cw = fm.horizontalAdvance(ctext) + 14
        cr = QRect(r.right() - cw - 12, r.center().y() - 9, cw, 18)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C_PANEL2 if visible else C_PANEL))
        p.drawRoundedRect(cr, 9, 9)
        p.setPen(QColor(C_MUTED if visible else C_DIM))
        p.drawText(cr, Qt.AlignCenter, ctext)

        tr = QRect(dot.right() + 10, r.top(), cr.left() - dot.right() - 16, r.height())
        p.setPen(QColor(C_TEXT if visible else C_DIM))
        f = QFont(opt.font)
        f.setStrikeOut(not visible)
        if index.data(ROLE_TAG) == NO_TAG:
            f.setItalic(True)
        p.setFont(f)
        p.drawText(tr, Qt.AlignVCenter | Qt.AlignLeft, fm.elidedText(name, Qt.ElideRight, tr.width()))
        p.restore()


# ------------------------------------------------------------ okno glowne ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self._app_icon())
        self.settings = QSettings("APA", "SerialLogViewer")
        self.parser = LogParser()
        self.reader: SerialReader | None = None
        self.log_file = None
        self.log_path: Path | None = None
        self.tag_items: dict[str, QListWidgetItem] = {}
        self._programmatic_scroll = False
        self._last_rx = 0
        self._rx_rate = 0

        self.model = LogModel()
        self._build_ui()
        self._build_shortcuts()
        self._restore_settings()
        self.refresh_ports()

        self.ui_timer = QTimer(self, interval=400, timeout=self._periodic)
        self.ui_timer.start()

    # ----------------------------------------------------------- budowa UI
    def _app_icon(self) -> QIcon:
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(C_ACCENT))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        p.setPen(QPen(QColor("white"), 5, Qt.SolidLine, Qt.RoundCap))
        for i, w in enumerate((34, 22, 28)):
            y = 20 + i * 12
            p.drawLine(15, y, 15 + w, y)
        p.end()
        return QIcon(pm)

    def _build_ui(self):
        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- pasek polaczenia
        top = QFrame(objectName="topbar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(8)
        title = QLabel(APP_NAME, objectName="appTitle")
        tl.addWidget(title)
        tl.addSpacing(16)

        self.port_combo = QComboBox(minimumWidth=230)
        self.port_combo.setToolTip("Port szeregowy")
        tl.addWidget(self.port_combo)
        self.btn_refresh = QToolButton(icon=icon(G_REFRESH), toolTip="Odśwież listę portów")
        self.btn_refresh.clicked.connect(self.refresh_ports)
        tl.addWidget(self.btn_refresh)
        self.baud_combo = QComboBox(editable=True, minimumWidth=100)
        self.baud_combo.addItems(BAUD_RATES)
        self.baud_combo.setCurrentText("115200")
        self.baud_combo.setToolTip("Prędkość [bps]")
        tl.addWidget(self.baud_combo)

        self.btn_connect = QPushButton("Połącz", objectName="primary", icon=icon(G_PLAY, "white"))
        self.btn_connect.clicked.connect(self.toggle_connection)
        tl.addWidget(self.btn_connect)

        self.btn_autorecon = QPushButton("Auto-połączenie", checkable=True, checked=True)
        self.btn_autorecon.setToolTip("Po zniknięciu portu (reset/odłączenie USB) łącz ponownie automatycznie")
        tl.addWidget(self.btn_autorecon)

        self.btn_reset = QPushButton("Reset ESP", icon=icon(G_POWER), enabled=False)
        self.btn_reset.setToolTip("Reset układu przez linię RTS (EN), jak w idf.py monitor")
        self.btn_reset.clicked.connect(lambda: self.reader and self.reader.request_reset())
        tl.addWidget(self.btn_reset)

        tl.addStretch(1)
        self.state_dot = QLabel("●", objectName="statusDot")
        self.state_label = QLabel("Rozłączono")
        self._set_state_style(False)
        tl.addWidget(self.state_dot)
        tl.addWidget(self.state_label)
        root.addWidget(top)

        # --- pasek filtrow
        fb = QFrame(objectName="filterbar")
        fl = QHBoxLayout(fb)
        fl.setContentsMargins(14, 8, 14, 8)
        fl.setSpacing(6)
        self.level_buttons: dict[str, QPushButton] = {}
        for lvl in LEVELS:
            b = QPushButton(LEVEL_NAMES[lvl], checkable=True, checked=True)
            c = LEVEL_COLORS[lvl]
            b.setStyleSheet(
                f"QPushButton {{ border-radius: 12px; padding: 4px 12px; color: {C_DIM};"
                f" background: transparent; border: 1px solid {C_BORDER}; }}"
                f"QPushButton:hover {{ border-color: {rgba(c, 0.6)}; }}"
                f"QPushButton:checked {{ color: {c}; background: {rgba(c, 0.13)}; border-color: {rgba(c, 0.55)}; }}"
            )
            b.setToolTip("Kliknij: przełącz · Prawy klik: pokaż tylko ten poziom")
            b.toggled.connect(self._levels_changed)
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _p, l=lvl: self._solo_level(l))
            self.level_buttons[lvl] = b
            fl.addWidget(b)
        fl.addSpacing(12)

        self.search = QLineEdit(placeholderText="Szukaj w logu…  (Ctrl+F)", clearButtonEnabled=True)
        self.search.addAction(icon(G_SEARCH, C_MUTED), QLineEdit.LeadingPosition)
        self.search.setMinimumWidth(260)
        self.search_timer = QTimer(self, singleShot=True, interval=200, timeout=self._apply_text_filter)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        fl.addWidget(self.search, 1)
        self.btn_regex = QPushButton(".*", checkable=True, toolTip="Wyrażenie regularne")
        self.btn_regex.setFixedWidth(34)
        self.btn_regex.toggled.connect(self._apply_text_filter)
        fl.addWidget(self.btn_regex)
        self.btn_case = QPushButton("Aa", checkable=True, toolTip="Uwzględniaj wielkość liter")
        self.btn_case.setFixedWidth(34)
        self.btn_case.toggled.connect(self._apply_text_filter)
        fl.addWidget(self.btn_case)
        fl.addSpacing(12)

        self.btn_follow = QPushButton("Śledź", checkable=True, checked=True, icon=icon(G_DOWN))
        self.btn_follow.setToolTip("Automatyczne przewijanie do najnowszych wpisów")
        self.btn_follow.toggled.connect(lambda on: on and self._scroll_bottom())
        fl.addWidget(self.btn_follow)
        self.btn_clear = QPushButton("Wyczyść", icon=icon(G_DELETE), toolTip="Wyczyść widok (Ctrl+L)")
        self.btn_clear.clicked.connect(self.clear_log)
        fl.addWidget(self.btn_clear)

        self.btn_file = QToolButton(icon=icon(G_SAVE), text="Plik", toolTip="Zapis / odczyt logów")
        self.btn_file.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_file.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(self.btn_file)
        self.act_record = QAction("Zapisuj logi do pliku podczas połączenia", m, checkable=True, checked=True)
        m.addAction(self.act_record)
        m.addAction(icon(G_FOLDER), "Otwórz folder logów", self.open_log_dir)
        m.addSeparator()
        m.addAction(icon(G_SAVE), "Eksportuj wszystko…  (Ctrl+S)", lambda: self.export(False))
        m.addAction(icon(G_SAVE), "Eksportuj widoczne (po filtrach)…", lambda: self.export(True))
        m.addSeparator()
        m.addAction(icon(G_OPEN), "Wczytaj plik logu…  (Ctrl+O)", self.load_file)
        self.btn_file.setMenu(m)
        fl.addWidget(self.btn_file)
        root.addWidget(fb)

        # --- cialo: sidebar | tabela + szczegoly
        split = QSplitter(Qt.Horizontal, childrenCollapsible=False)
        root.addWidget(split, 1)

        side = QFrame(objectName="sidebar")
        side.setMinimumWidth(190)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 12, 0, 8)
        sl.setSpacing(6)
        hl = QHBoxLayout()
        hl.setContentsMargins(16, 0, 8, 0)
        hl.addWidget(QLabel("WĄTKI", objectName="sectionTitle"))
        self.tag_count_label = QLabel("0", objectName="sectionTitle")
        hl.addWidget(self.tag_count_label)
        hl.addStretch(1)
        b_all = QPushButton("wszystkie", objectName="link")
        b_all.clicked.connect(lambda: self._set_all_tags(True))
        b_none = QPushButton("żadne", objectName="link")
        b_none.clicked.connect(lambda: self._set_all_tags(False))
        hl.addWidget(b_all)
        hl.addWidget(b_none)
        sl.addLayout(hl)
        self.tag_search = QLineEdit(placeholderText="Filtruj wątki…", clearButtonEnabled=True)
        self.tag_search.textChanged.connect(self._filter_tag_list)
        wrap = QHBoxLayout()
        wrap.setContentsMargins(10, 0, 10, 4)
        wrap.addWidget(self.tag_search)
        sl.addLayout(wrap)
        self.tag_list = QListWidget()
        self.tag_list.setItemDelegate(ThreadDelegate(self.tag_list))
        self.tag_list.setMouseTracking(True)
        self.tag_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.tag_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tag_list.setToolTip("Klik: pokaż/ukryj · Dwuklik: tylko ten wątek · Prawy klik: menu")
        self.tag_list.itemClicked.connect(self._tag_clicked)
        self.tag_list.itemDoubleClicked.connect(lambda it: self._solo_tag(it.data(ROLE_TAG)))
        self.tag_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tag_list.customContextMenuRequested.connect(self._tag_menu)
        sl.addWidget(self.tag_list, 1)
        split.addWidget(side)

        vsplit = QSplitter(Qt.Vertical, childrenCollapsible=True)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setFont(mono_font())
        self.table.setItemDelegateForColumn(COL_LEVEL, LevelDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerItem)
        vh = self.table.verticalHeader()
        vh.setVisible(False)
        vh.setSectionResizeMode(QHeaderView.Fixed)
        vh.setDefaultSectionSize(21)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hh.setStretchLastSection(True)
        for col, w in ((COL_TIME, 100), (COL_DEV, 80), (COL_LEVEL, 62), (COL_TAG, 170)):
            hh.resizeSection(col, w)
        self.table.selectionModel().currentRowChanged.connect(self._show_detail)
        self.table.verticalScrollBar().valueChanged.connect(self._user_scrolled)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        vsplit.addWidget(self.table)

        self.detail = QPlainTextEdit(objectName="detail", readOnly=True)
        self.detail.setFont(mono_font(9.5))
        self.detail.setPlaceholderText("Wybierz wpis, aby zobaczyć szczegóły (JSON formatowany automatycznie)")
        vsplit.addWidget(self.detail)
        vsplit.setStretchFactor(0, 4)
        vsplit.setStretchFactor(1, 1)
        vsplit.setSizes([600, 140])
        split.addWidget(vsplit)
        split.setStretchFactor(1, 1)
        split.setSizes([230, 1000])
        self.hsplit, self.vsplit = split, vsplit

        # --- status
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.st_lines = QLabel()
        self.st_rx = QLabel()
        self.st_file = QLabel()
        sb.addWidget(self.st_lines)
        sb.addWidget(self.st_rx)
        sb.addPermanentWidget(self.st_file)
        self._update_status()

    def _build_shortcuts(self):
        for seq, fn in (
            ("Ctrl+F", lambda: (self.search.setFocus(), self.search.selectAll())),
            ("Ctrl+L", self.clear_log),
            ("Ctrl+C", self.copy_selected),
            ("End", lambda: self.btn_follow.setChecked(True)),
            ("Escape", lambda: self.search.clear()),
            ("Ctrl+S", lambda: self.export(False)),
            ("Ctrl+O", self.load_file),
        ):
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.setShortcutContext(Qt.WindowShortcut)
            a.triggered.connect(fn)
            self.addAction(a)

    # --------------------------------------------------------- polaczenie
    def refresh_ports(self):
        current = self.port_combo.currentData() or self.settings.value("port", "")
        self.port_combo.clear()
        ports = sorted(serial.tools.list_ports.comports(), key=lambda p: (len(p.device), p.device))
        for p in ports:
            desc = p.description if p.description and p.description != "n/a" else ""
            if desc.endswith(f"({p.device})"):
                desc = desc[: -len(p.device) - 2].strip()
            self.port_combo.addItem(f"{p.device}  ·  {desc}" if desc else p.device, p.device)
        if not ports:
            self.port_combo.addItem("Brak portów COM", None)
        i = self.port_combo.findData(current)
        if i >= 0:
            self.port_combo.setCurrentIndex(i)

    def toggle_connection(self):
        if self.reader:
            self.disconnect_port()
        else:
            self.connect_port()

    def connect_port(self):
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, APP_NAME, "Wybierz port COM.")
            return
        try:
            baud = int(self.baud_combo.currentText())
        except ValueError:
            QMessageBox.warning(self, APP_NAME, "Nieprawidłowa prędkość transmisji.")
            return
        self.settings.setValue("port", port)
        self.settings.setValue("baud", baud)
        if self.act_record.isChecked():
            self._open_record_file(port)
        self.reader = SerialReader(port, baud, self.btn_autorecon.isChecked(), self.parser)
        self.reader.entries.connect(self._on_entries)
        self.reader.raw_lines.connect(self._on_raw_lines)
        self.reader.state.connect(self._on_state)
        self.reader.finished.connect(self._on_reader_finished)
        self.reader.start()
        self._last_rx = 0
        self.btn_connect.setText("Rozłącz")
        self.btn_connect.setObjectName("danger")
        self.btn_connect.setIcon(icon(G_STOP, "#ffb3b3"))
        self._repolish(self.btn_connect)
        for w in (self.port_combo, self.baud_combo, self.btn_refresh, self.btn_autorecon):
            w.setEnabled(False)
        self.btn_reset.setEnabled(True)

    def disconnect_port(self):
        if self.reader:
            self.reader.stop()
            self.reader.wait(2000)

    def _on_reader_finished(self):
        self.reader = None
        self._close_record_file()
        self.btn_connect.setText("Połącz")
        self.btn_connect.setObjectName("primary")
        self.btn_connect.setIcon(icon(G_PLAY, "white"))
        self._repolish(self.btn_connect)
        for w in (self.port_combo, self.baud_combo, self.btn_refresh, self.btn_autorecon):
            w.setEnabled(True)
        self.btn_reset.setEnabled(False)
        self._on_state("Rozłączono", False)

    def _on_state(self, msg: str, connected: bool):
        self.state_label.setText(msg)
        self._set_state_style(connected, waiting=self.reader is not None and not connected)

    def _set_state_style(self, connected: bool, waiting: bool = False):
        c = LEVEL_COLORS["I"] if connected else (LEVEL_COLORS["W"] if waiting else C_DIM)
        self.state_dot.setStyleSheet(f"color: {c};")
        self.state_label.setStyleSheet(f"color: {C_TEXT if connected else C_MUTED};")

    @staticmethod
    def _repolish(w):
        w.style().unpolish(w)
        w.style().polish(w)

    # ------------------------------------------------------ zapis do pliku
    def _open_record_file(self, port: str):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{port}_{datetime.now():%Y-%m-%d_%H-%M-%S}.log"
        self.log_path = LOG_DIR / name
        try:
            self.log_file = open(self.log_path, "a", encoding="utf-8", buffering=1 << 16)
        except OSError as e:
            self.log_file = None
            QMessageBox.warning(self, APP_NAME, f"Nie można utworzyć pliku logu:\n{e}")

    def _close_record_file(self):
        if self.log_file:
            self.log_file.close()
            self.log_file = None

    def _on_raw_lines(self, raws):
        if self.log_file:
            self.log_file.writelines(f"{ts.isoformat(sep=' ', timespec='milliseconds')} {line}\n" for ts, line in raws)

    # ---------------------------------------------------------- nowe dane
    def _on_entries(self, batch):
        new_tags = self.model.append(batch)
        for tag in new_tags:
            self._add_tag_item(tag)
        if self.btn_follow.isChecked():
            self._scroll_bottom()

    def _scroll_bottom(self):
        self._programmatic_scroll = True
        self.table.scrollToBottom()
        self._programmatic_scroll = False

    def _user_scrolled(self, value):
        if self._programmatic_scroll:
            return
        sb = self.table.verticalScrollBar()
        at_bottom = value >= sb.maximum() - 1
        if at_bottom != self.btn_follow.isChecked():
            self.btn_follow.blockSignals(True)
            self.btn_follow.setChecked(at_bottom)
            self.btn_follow.blockSignals(False)

    def _periodic(self):
        # liczniki watkow i poziomow
        tc = self.model.tag_counts
        self.tag_list.setUpdatesEnabled(False)
        for tag, it in self.tag_items.items():
            n = tc.get(tag, 0)
            if it.data(ROLE_COUNT) != n:
                it.setData(ROLE_COUNT, n)
        self.tag_list.setUpdatesEnabled(True)
        for lvl, b in self.level_buttons.items():
            n = self.model.level_counts.get(lvl, 0)
            b.setText(f"{LEVEL_NAMES[lvl]}  {fmt_count(n)}" if n else LEVEL_NAMES[lvl])
        if self.reader:
            rx = self.reader.rx_bytes
            self._rx_rate = (rx - self._last_rx) / (self.ui_timer.interval() / 1000)
            self._last_rx = rx
        self._update_status()
        if self.log_file:
            self.log_file.flush()

    def _update_status(self):
        total, vis = len(self.model.all), len(self.model.rows)
        self.st_lines.setText(f"Wpisy: {vis:,} widoczne / {total:,}".replace(",", " "))
        if self.reader:
            self.st_rx.setText(f"RX: {self.reader.rx_bytes / 1024:,.1f} KiB  ·  {self._rx_rate / 1024:.1f} KiB/s".replace(",", " "))
        else:
            self.st_rx.setText("")
        self.st_file.setText(f"Zapis: {self.log_path.name}" if self.log_file and self.log_path else "Zapis do pliku: wył.")

    # ---------------------------------------------------------------- watki
    def _add_tag_item(self, tag: str):
        it = QListWidgetItem()
        it.setData(ROLE_TAG, tag)
        it.setData(ROLE_VISIBLE, tag not in self.model.hidden_tags)
        it.setData(ROLE_COUNT, self.model.tag_counts.get(tag, 0))
        it.setData(ROLE_COLOR, self.model.color_for(tag).name())
        # wstawianie alfabetyczne, "(bez tagu)" na gorze
        key = (tag != NO_TAG, tag.lower())
        row = 0
        while row < self.tag_list.count():
            t = self.tag_list.item(row).data(ROLE_TAG)
            if (t != NO_TAG, t.lower()) > key:
                break
            row += 1
        self.tag_list.insertItem(row, it)
        self.tag_items[tag] = it
        needle = self.tag_search.text().strip().lower()
        it.setHidden(bool(needle) and needle not in tag_label(tag).lower())
        self.tag_count_label.setText(str(len(self.tag_items)))

    def _tag_clicked(self, it: QListWidgetItem):
        tag = it.data(ROLE_TAG)
        self._set_tags_visible({tag}, tag in self.model.hidden_tags)

    def _set_tags_visible(self, tags, visible: bool):
        if visible:
            self.model.hidden_tags -= set(tags)
        else:
            self.model.hidden_tags |= set(tags)
        for t in tags:
            if t in self.tag_items:
                self.tag_items[t].setData(ROLE_VISIBLE, visible)
        self._refilter()

    def _solo_tag(self, tag: str):
        self.model.hidden_tags = set(self.tag_items) - {tag}
        for t, it in self.tag_items.items():
            it.setData(ROLE_VISIBLE, t == tag)
        self._refilter()

    def _set_all_tags(self, visible: bool):
        # dotyczy watkow widocznych na liscie (z uwzglednieniem filtra listy)
        tags = [t for t, it in self.tag_items.items() if not it.isHidden()]
        self._set_tags_visible(tags, visible)

    def _filter_tag_list(self, text: str):
        needle = text.strip().lower()
        for t, it in self.tag_items.items():
            it.setHidden(bool(needle) and needle not in tag_label(t).lower())

    def _tag_menu(self, pos):
        it = self.tag_list.itemAt(pos)
        m = QMenu(self)
        if it:
            tag = it.data(ROLE_TAG)
            m.addAction(f"Tylko „{tag_label(tag)}”", lambda: self._solo_tag(tag))
            m.addAction(f"Ukryj „{tag_label(tag)}”", lambda: self._set_tags_visible({tag}, False))
            m.addAction("Kopiuj nazwę", lambda: QApplication.clipboard().setText(tag))
            m.addSeparator()
        m.addAction("Pokaż wszystkie", lambda: self._set_all_tags(True))
        m.addAction("Ukryj wszystkie", lambda: self._set_all_tags(False))
        m.addAction("Odwróć zaznaczenie", self._invert_tags)
        m.exec(self.tag_list.mapToGlobal(pos))

    def _invert_tags(self):
        self.model.hidden_tags = set(self.tag_items) - self.model.hidden_tags
        for t, it in self.tag_items.items():
            it.setData(ROLE_VISIBLE, t not in self.model.hidden_tags)
        self._refilter()

    # ------------------------------------------------------------ filtry
    def _levels_changed(self):
        self.model.levels = {l for l, b in self.level_buttons.items() if b.isChecked()}
        self._refilter()

    def _solo_level(self, lvl: str):
        for l, b in self.level_buttons.items():
            b.blockSignals(True)
            b.setChecked(l == lvl)
            b.blockSignals(False)
        self._levels_changed()

    def _apply_text_filter(self):
        text = self.search.text()
        flags = 0 if self.btn_case.isChecked() else re.IGNORECASE
        rx, ok = None, True
        if text:
            try:
                rx = re.compile(text if self.btn_regex.isChecked() else re.escape(text), flags)
            except re.error:
                ok = False
        self.search.setProperty("invalid", not ok)
        self._repolish(self.search)
        if ok:
            self.model.text_re = rx
            self._refilter()

    def _refilter(self):
        cur = self.table.currentIndex()
        keep = self.model.entry(cur.row()).seq if cur.isValid() else None
        self.model.refilter()
        if self.btn_follow.isChecked() or keep is None:
            self._scroll_bottom()
        else:
            # przywroc zaznaczony wpis, jesli nadal widoczny (lub najblizszy kolejny)
            rows = self.model.rows
            lo, hi = 0, len(rows)
            while lo < hi:
                mid = (lo + hi) // 2
                if rows[mid].seq < keep:
                    lo = mid + 1
                else:
                    hi = mid
            if lo < len(rows):
                idx = self.model.index(lo, COL_MSG)
                self.table.setCurrentIndex(idx)
                self.table.scrollTo(idx, QAbstractItemView.PositionAtCenter)
        self._update_status()

    # ------------------------------------------------- szczegoly / kopiuj
    def _show_detail(self, cur, _prev):
        if not cur.isValid():
            self.detail.clear()
            return
        e = self.model.entry(cur.row())
        head = (
            f"{e.host_ts:%Y-%m-%d %H:%M:%S}.{e.host_ts.microsecond // 1000:03d}   "
            f"{LEVEL_NAMES[e.level]}   wątek: {tag_label(e.tag)}"
            + (f"   urządzenie: {e.dev_ts} ms" if e.dev_ts is not None else "")
        )
        body = e.msg
        pretty = _pretty_json(e.msg)
        if pretty:
            body += "\n\n" + pretty
        self.detail.setPlainText(f"{head}\n{'─' * 60}\n{body}")

    def _selected_entries(self) -> list[LogEntry]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self.model.entry(r) for r in rows]

    def copy_selected(self):
        if self.detail.hasFocus() and self.detail.textCursor().hasSelection():
            self.detail.copy()
            return
        if self.search.hasFocus() or self.tag_search.hasFocus():
            w = QApplication.focusWidget()
            w.copy()
            return
        ents = self._selected_entries()
        if ents:
            QApplication.clipboard().setText("\n".join(e.raw for e in ents))

    def _table_menu(self, pos):
        idx = self.table.indexAt(pos)
        m = QMenu(self)
        m.addAction(icon(G_COPY), "Kopiuj zaznaczone", self.copy_selected)
        if idx.isValid():
            e = self.model.entry(idx.row())
            m.addSeparator()
            m.addAction(f"Tylko wątek „{tag_label(e.tag)}”", lambda: self._solo_tag(e.tag))
            m.addAction(f"Ukryj wątek „{tag_label(e.tag)}”", lambda: self._set_tags_visible({e.tag}, False))
            m.addAction(f"Tylko poziom {LEVEL_NAMES[e.level]}", lambda: self._solo_level(e.level))
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ----------------------------------------------------- plik / czyszczenie
    def clear_log(self):
        self.model.clear()
        self.tag_list.clear()
        self.tag_items.clear()
        self.tag_count_label.setText("0")
        self.detail.clear()
        self._periodic()

    def open_log_dir(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR)))

    def export(self, visible_only: bool):
        ents = self.model.rows if visible_only else self.model.all
        if not ents:
            QMessageBox.information(self, APP_NAME, "Brak wpisów do zapisania.")
            return
        default = str(LOG_DIR / f"export_{datetime.now():%Y-%m-%d_%H-%M-%S}.log")
        path, _ = QFileDialog.getSaveFileName(self, "Eksportuj log", default, "Log (*.log *.txt);;Wszystkie (*.*)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            for e in ents:
                f.write(f"{e.host_ts.isoformat(sep=' ', timespec='milliseconds')} {e.raw}\n")
        self.statusBar().showMessage(f"Zapisano {len(ents):,} wpisów do {path}".replace(",", " "), 5000)

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Wczytaj plik logu", str(LOG_DIR), "Log (*.log *.txt);;Wszystkie (*.*)")
        if path:
            self.load_path(path)

    def load_path(self, path: str):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Nie można odczytać pliku:\n{e}")
            return
        batch = []
        for line in lines:
            batch.extend(self.parser.parse_file_line(line))
        self._on_entries(batch)
        self._periodic()
        self.statusBar().showMessage(f"Wczytano {len(batch):,} wpisów z {Path(path).name}".replace(",", " "), 5000)

    # ------------------------------------------------------- ustawienia
    def _restore_settings(self):
        g = self.settings.value("geometry")
        if g is not None:
            self.restoreGeometry(g)
        else:
            self.resize(1400, 820)
        for key, sp in (("hsplit", self.hsplit), ("vsplit", self.vsplit)):
            s = self.settings.value(key)
            if s is not None:
                sp.restoreState(s)
        self.baud_combo.setCurrentText(str(self.settings.value("baud", "115200")))
        self.btn_autorecon.setChecked(self.settings.value("autoReconnect", True, type=bool))
        self.act_record.setChecked(self.settings.value("record", True, type=bool))

    def closeEvent(self, ev):
        self.disconnect_port()
        self._close_record_file()
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("hsplit", self.hsplit.saveState())
        self.settings.setValue("vsplit", self.vsplit.saveState())
        self.settings.setValue("autoReconnect", self.btn_autorecon.isChecked())
        self.settings.setValue("record", self.act_record.isChecked())
        super().closeEvent(ev)


def _pretty_json(text: str) -> str | None:
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        return None
    s = text[min(starts):]
    try:
        obj = json.loads(s)
    except ValueError:
        return None
    if not isinstance(obj, (dict, list)) or not obj:
        return None
    return json.dumps(obj, indent=2, ensure_ascii=False)


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("apa.seriallogviewer")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    pal = QPalette()
    for role, col in (
        (QPalette.Window, C_BG), (QPalette.Base, C_BG), (QPalette.AlternateBase, "#171a1f"),
        (QPalette.Button, C_PANEL2), (QPalette.Text, C_TEXT), (QPalette.WindowText, C_TEXT),
        (QPalette.ButtonText, C_TEXT), (QPalette.Highlight, C_SEL), (QPalette.HighlightedText, C_TEXT),
        (QPalette.ToolTipBase, C_PANEL2), (QPalette.ToolTipText, C_TEXT), (QPalette.PlaceholderText, C_DIM),
    ):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    app.setStyleSheet(QSS + f'QTableView, QPlainTextEdit#detail {{ font-family: "{mono_family()}"; }}')
    w = MainWindow()
    w.show()
    for arg in sys.argv[1:]:
        if os.path.isfile(arg):
            w.load_path(arg)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
