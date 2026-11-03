#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Explorer detector: finds the selected file in the active Explorer window
using the Shell.Application COM object.
"""

import ctypes

import win32com.client
import pythoncom

# Per-window data lives in top-level folder now

USER32 = ctypes.WinDLL("user32", use_last_error=True)

VIDEO_SOURCE_EXTS = {"mp4", "avi", "mkv", "webm", "mov", "gif", "wmv", "flv", "m4v"}
IMAGE_SOURCE_EXTS = {"png", "jpg", "jpeg", "webp", "ico", "bmp", "tiff", "tif", "gif", "heic", "heif"}

VIDEO_TARGETS = ["MP4", "AVI", "WEBM", "MKV", "MOV", "GIF"]
IMAGE_TARGETS = ["PNG", "JPG", "WEBP", "ICO", "BMP", "TIFF", "GIF", "HEIC"]

GA_ROOT = 2


def _is_folder_window(hwnd: int) -> bool:
    """Return True if the window class is an Explorer folder window."""
    # Reuse a small buffer
    buf = ctypes.create_unicode_buffer(256)
    USER32.GetClassNameW(hwnd, buf, 256)
    cls = buf.value
    return cls in ("CabinetWClass", "ExploreWClass")


def _get_root_hwnd(hwnd: int) -> int:
    return int(USER32.GetAncestor(hwnd, GA_ROOT))


def get_selected_explorer_file():
    """
    Returns (file_path, formats) where formats is a list of offered
    target format labels, or (None, None) if no media file is selected.

    The 0.08 s delay lets Explorer finish processing the Alt+Click that
    triggered the hotkey, otherwise SelectedItems() may still reflect the
    previous selection.
    """
    import time
    try:
        fg = USER32.GetForegroundWindow()
        if not fg:
            return None, None
        root = _get_root_hwnd(fg)
        if not _is_folder_window(root):
            return None, None

        time.sleep(0.08)   # let Explorer finalize the click selection

        pythoncom.CoInitialize()
        try:
            shell = win32com.client.Dispatch("Shell.Application")
            windows = shell.Windows()
            target_hwnd = int(root)
            for window in windows:
                try:
                    if int(window.HWND) != target_hwnd:
                        continue
                    sel = window.Document.SelectedItems()
                    if sel.Count != 1:
                        return None, None
                    path = sel.Item(0).Path
                    return path, _detect_formats(path)
                except Exception:
                    continue
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        pass
    return None, None


def _detect_formats(path):
    """Return offered target formats for the given file path, or None."""
    if not path or "." not in path:
        return None
    ext = path.rsplit(".", 1)[-1].lower()

    if ext in VIDEO_SOURCE_EXTS:
        cur = ext.upper()
        return [t for t in VIDEO_TARGETS if t != cur]
    if ext in IMAGE_SOURCE_EXTS:
        cur = {"jpeg": "JPG", "tif": "TIFF", "heif": "HEIC"}.get(ext, ext.upper())
        return [t for t in IMAGE_TARGETS if t != cur]
    return None


if __name__ == "__main__":
    print(get_selected_explorer_file())
