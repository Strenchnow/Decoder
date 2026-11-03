#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Converter: runs ffmpeg in a hidden background process and sends
native Windows toast notifications for start / success / error.
"""

import sys
import base64
import subprocess
import threading
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000


# ---------------------------------------------------------------------------
# Toast notifications
# ---------------------------------------------------------------------------
def _xml_escape(text: str) -> str:
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


def _send_toast(title: str, message: str, is_error: bool = False) -> None:
    """Native Windows toast via PowerShell; falls back to a message box."""
    import ctypes
    err_icon = 0x10 if is_error else 0x40
    try:
        ps_script = f'''
$ErrorActionPreference = "Stop"
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$template = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{_xml_escape(title)}</text>
      <text>{_xml_escape(message)}</text>
    </binding>
  </visual>
</toast>
"@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("PowerShell").Show($toast)
'''
        encoded = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle",
             "Hidden", "-EncodedCommand", encoded],
            creationflags=CREATE_NO_WINDOW,
            capture_output=True,
            timeout=20,
        )
    except Exception:
        try:
            ctypes.windll.user32.MessageBoxW(0, message, title, err_icon)
        except Exception:
            pass


def notify_start(file_name: str, target: str) -> None:
    _send_toast("Decoder — конвертация", f"{file_name} → {target}")


def _codec_args_for(target: str) -> list:
    """ffmpeg codec / filter options for the target format."""
    if target == "gif":
        # palette-based high-quality GIF
        return [
            "-vf",
            "fps=15,scale=480:-1:flags=lanczos,"
            "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
            "-loop", "0",
        ]
    if target == "webm":
        return ["-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0",
                "-c:a", "libopus"]
    if target == "mp4":
        return ["-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-pix_fmt", "yuv420p"]
    if target in ("mkv", "mov"):
        return ["-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-pix_fmt", "yuv420p"]
    if target == "avi":
        return ["-c:v", "mpeg4", "-q:v", "3",
                "-c:a", "mp3", "-b:a", "128k"]
    if target == "tiff" or target == "tif":
        return ["-pix_fmt", "rgba"]
    if target == "ico":
        return ["-vf",
                "scale=256:256:force_original_aspect_ratio=decrease,"
                "pad=256:256:(ow-iw)/2:(oh-ih)/2"]
    if target in ("heic", "heif"):
        return ["-c:v", "libx265", "-q:v", "2", "-update", "1"]
    if target in ("jpg", "jpeg"):
        return ["-q:v", "2", "-update", "1"]
    if target == "webp":
        return ["-quality", "85", "-update", "1"]
    if target == "png":
        return ["-compression_level", "6", "-update", "1"]
    if target == "bmp":
        return ["-update", "1"]
    return []


# ---------------------------------------------------------------------------
# Public conversion API
# ---------------------------------------------------------------------------
def convert_file(input_path: str, target_format: str) -> "tuple[bool, str]":
    """
    Convert input_path to target_format (e.g. 'MP4').
    Output is written next to the source file.
    Runs ffmpeg asynchronously in a background thread.  Returns immediately.
    """
    def worker():
        success, message = _convert_blocking(input_path, target_format)
        if success:
            _send_toast("Decoder — готово ✔", message)
        else:
            _send_toast("Decoder — ошибка", message, is_error=True)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return None


_VIDEO_EXTS = {"mp4", "avi", "mkv", "webm", "mov", "gif"}
_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "ico", "bmp", "tiff", "tif", "gif", "heic", "heif"}


def _convert_blocking(input_path, target_format) -> "tuple[bool, str]":
    try:
        src = Path(input_path).resolve()
        if not src.exists():
            return False, f"Файл не найден: {src}"

        target = target_format.lower().lstrip(".")
        src_ext = src.suffix.lower().lstrip(".")

        # Output path next to the original
        if src_ext == target:
            out = src.with_name(f"{src.stem}_converted.{target}")
        else:
            out = src.with_name(f"{src.stem}.{target}")

        if src == out:
            return False, "Нельзя перезаписать исходный файл."

        is_image_src = src_ext in _IMAGE_EXTS
        is_video_src = src_ext in _VIDEO_EXTS
        is_video_out = target in _VIDEO_EXTS
        is_image_out = target in _IMAGE_EXTS

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-i", str(src)]

        if is_image_src and is_video_out:
            cmd += ["-loop", "1", "-t", "5"]
        elif is_video_src and is_image_out:
            cmd += ["-frames:v", "1"]

        cmd += _codec_args_for(target)
        cmd += [str(out)]

        result = subprocess.run(
            cmd,
            creationflags=CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )

        if result.returncode == 0 and out.exists():
            return True, f"{src.name} → {out.name}"

        err = (result.stderr or "").strip() or "Неизвестная ошибка"
        # Log the full stderr to the console (visible in debug runs)
        print(f"[ffmpeg] rc={result.returncode} :: {src.name} -> {target}",
              file=sys.stderr)
        print(err, file=sys.stderr)
        return False, f"{src.name} → {target.upper()} не удалось:\n{err[-400:]}"

    except subprocess.TimeoutExpired:
        return False, "Превышен таймаут конвертации (5 мин)."
    except FileNotFoundError:
        return False, "ffmpeg не установлен. Установите: winget install Gyan.FFmpeg"
    except Exception as e:
        return False, f"Ошибка: {e}"
