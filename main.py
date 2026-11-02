#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Decoder — Quick Convert: Alt + Left click on a media file in Windows
Explorer opens a radial format menu and converts the file via ffmpeg.

Runs as a background tray application.  Usage:
    python main.py          (or pythonw main.py to hide the console)
"""

import sys
import time
import ctypes
import logging
import os

logging.basicConfig(
    filename=os.path.join(os.environ.get("TEMP", "."), "decoder.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

from PySide6.QtCore import Qt, QObject, Slot, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtGui import QIcon, QAction, QColor, QPainter, QPixmap, QFont
from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu,
)

from explorer_detector import get_selected_explorer_file
from converter import convert_file, _send_toast
from ui_radial_menu import RadialMenu

APP_NAME = "Decoder"
FG_COLOR = QColor(96, 88, 255)

# ---------------------------------------------------------------------------
# Icon (drawn in-code so no external asset is required)
# ---------------------------------------------------------------------------
def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(28, 28, 40))
    p.setPen(FG_COLOR)
    p.drawEllipse(4, 4, 56, 56)
    p.setBrush(FG_COLOR)
    p.setPen(Qt.NoPen)
    p.drawPie(8, 8, 48, 48, 30 * 16, 100 * 16)
    p.setFont(QFont("Segoe UI", 20, QFont.Bold))
    p.setPen(Qt.white)
    p.drawText(pm.rect(), Qt.AlignCenter, "▶")
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------
# Application core
# ---------------------------------------------------------------------------
class DecoderApp(QObject):
    """Owns the tray icon, the pynput listener and the radial menu."""

    # Signal: pynput thread -> GUI thread (carries cursor position)
    altClick = Signal(object)

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.paused = False
        self._menu = None
        self._last_path = None
        self._last_spawn_ts = 0.0   # debounce for double Alt+Click

        # tray
        self.tray = QSystemTrayIcon(make_icon(), None)
        self.tray.setToolTip(f"{APP_NAME} — Alt+Click по файлу в Проводнике")
        self._build_menu()
        self.tray.show()

        # connect signal BEFORE starting the listener
        self.altClick.connect(self._show_menu, Qt.QueuedConnection)

        # global hook
        self.listener = AltClickListener(self.on_hotspot)
        self.listener.start()

    # -- tray -----------------------------------------------------------
    def _build_menu(self):
        menu = QMenu()
        info = menu.addAction("Decoder — работает")
        info.setEnabled(False)

        self._act_pause = QAction("Пауза", self, checkable=True)
        self._act_pause.toggled.connect(self._set_paused)

        act_reload = QAction("Перезапуск", self)
        act_reload.triggered.connect(self._restart)

        act_exit = QAction("Выход", self)
        act_exit.triggered.connect(self._quit)

        menu.addAction(self._act_pause)
        menu.addSeparator()
        menu.addAction(act_reload)
        menu.addAction(act_exit)
        self.tray.setContextMenu(menu)

    def _set_paused(self, on: bool):
        self.paused = on
        self._act_pause.setText("Возобновить" if on else "Пауза")
        self.tray.setToolTip(
            f"{APP_NAME} — " + ("пауза" if on else "Alt+Click по файлу"))

    def _restart(self):
        self.listener.stop()
        self.listener = AltClickListener(self.on_hotspot)
        self.listener.start()
        self.tray.showMessage(APP_NAME, "Перезапущен",
                              QSystemTrayIcon.Information, 1500)

    def _quit(self):
        self.listener.stop()
        self.app.quit()

    # -- hot thread callback -------------------------------------------
    def on_hotspot(self, xy):
        """Runs in the pynput thread; hops to the GUI thread."""
        self.altClick.emit(xy)

    @Slot(object)
    def _show_menu(self, xy):
        try:
            logging.info("Alt+Click at %s", xy)
            if self.paused:
                logging.info("paused -> ignore")
                return
            if self._menu is not None and self._menu.isVisible():
                logging.info("menu already open -> ignore")
                return

            # Debounce: never spawn two menus from one physical click
            now = time.time()
            if now - self._last_spawn_ts < 0.35:
                logging.info("debounce -> ignore")
                return
            self._last_spawn_ts = now

            # Wait for the physical left-button release (max 0.4 s) so the
            # popup doesn't swallow the release and Explorer keeps the click.
            deadline = time.time() + 0.4
            try:
                user32 = ctypes.windll.user32
                while time.time() < deadline:
                    if not (user32.GetAsyncKeyState(0x01) & 0x8000):
                        break
                    time.sleep(0.02)
            except Exception:
                pass
            time.sleep(0.08)   # let Explorer finalize the selection

            path, formats = get_selected_explorer_file()
            logging.info("selected: %s formats=%s", path, formats)
            if not path or not formats:
                return  # not a media file (or nothing selected) -> do nothing
            # Build a fresh menu each time (the previous one is scheduled for deletion)
            menu = RadialMenu()
            menu.formatSelected.connect(self._start_conversion)
            # QCursor.pos() returns the true (DPI-aware) cursor position;
            # hook coordinates may be physical pixels on scaled displays.
            cursor = QCursor.pos()
            menu.popup(formats, cursor, title=path.rsplit(".", 1)[-1].upper())
            self._menu = menu
            self._last_path = path
        except Exception:
            logging.exception("show_menu failed")

    @Slot(str)
    def _start_conversion(self, target: str):
        path = getattr(self, "_last_path", None)
        if not path:
            return
        self._last_path = None
        logging.info("convert %s -> %s", path, target)
        name = path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        _send_toast(APP_NAME, f"{name} → {target.upper()}")
        convert_file(path, target)


# ---------------------------------------------------------------------------
# pynput global hook
# ---------------------------------------------------------------------------
class AltClickListener:
    """
    Global keyboard + mouse hooks.
    On Alt + Left click calls AltClick -> DecoderApp.on_hotspot((x, y)).
    """

    def __init__(self, callback):
        from pynput import keyboard, mouse   # defer import: on non-Windows this still loads
        self._kb = keyboard
        self._ms = mouse
        self._callback = callback
        self._alt_down = False
        self._kb_listener = None
        self._ms_listener = None

    def start(self):
        kb, ms = self._kb, self._ms

        def kb_press(key):
            if key in (kb.Key.alt, kb.Key.alt_l, kb.Key.alt_r):
                self._alt_down = True

        def kb_release(key):
            if key in (kb.Key.alt, kb.Key.alt_l, kb.Key.alt_r):
                self._alt_down = False

        def ms_click(x, y, button, pressed):
            try:
                if button == ms.Button.left and pressed and self._alt_down:
                    logging.info("pynput click detected alt=%s", self._alt_down)
                    self._callback((x, y))
            except Exception:
                logging.exception("ms_click failed")

        self._kb_listener = kb.Listener(on_press=kb_press, on_release=kb_release)
        self._ms_listener = ms.Listener(on_click=ms_click)
        self._kb_listener.start()
        self._ms_listener.start()

    def stop(self):
        for l in (self._kb_listener, self._ms_listener):
            if l:
                try:
                    l.stop()
                except Exception:
                    pass
        self._kb_listener = self._ms_listener = None


# ---------------------------------------------------------------------------
def ensure_single_instance() -> bool:
    """Named mutex: False (and exit) if another copy is already running."""
    import ctypes as _c
    mutex = _c.windll.kernel32.CreateMutexW(None, False, "Global\\Decoder_QuickConvert")
    Exists = _c.GetLastError() == 183   # ERROR_ALREADY_EXISTS
    if Exists:
        return False
    # keep the handle referenced so it is not GC'd
    globals()["_MUTEX"] = mutex
    return True


def main():
    # PySide6 apps on Windows sometimes need COM re-init for win32com callbacks
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass

    if not ensure_single_instance():
        logging.info("second instance blocked by mutex")
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)   # tray app keeps running

    global _APP_KEEPALIVE
    _APP_KEEPALIVE = DecoderApp(app)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
