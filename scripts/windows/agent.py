"""Persistent, window-scoped Windows backend. Protocol stdout contains JSON only."""
from __future__ import annotations

import base64
import ctypes as C
from ctypes import wintypes as W
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

GAME_NAMES = {"minecraft.windows.exe", "minecraft.windowsbeta.exe"}
CREATE_NO_WINDOW = 0x08000000


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}")
    return int(value)


def coordinate(x, y, shot, current):
    if shot is None:
        raise ValueError("Take a screenshot before coordinate input")
    source_w, source_h, image_w, image_h = shot
    if (source_w, source_h) != current:
        raise ValueError("Game window resized; take another screenshot before input")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (x, y)):
        raise ValueError("Coordinates must be finite numbers")
    if not 0 <= x < image_w or not 0 <= y < image_h:
        raise ValueError("Coordinates are outside the last screenshot")
    return min(source_w - 1, round(x * source_w / image_w)), min(source_h - 1, round(y * source_h / image_h))


def literal_text(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Text must contain at most 4096 printable characters; use key for control keys")
    # Validate surrogate encoding before emitting any input.
    value.encode("utf-16-le")
    return value


KEYS = {"space": 0x20, "enter": 0x0D, "return": 0x0D, "escape": 0x1B, "esc": 0x1B,
        "tab": 9, "backspace": 8, "delete": 0x2E, "insert": 0x2D,
        "shift": 0xA0, "lshift": 0xA0, "rshift": 0xA1, "ctrl": 0xA2, "lctrl": 0xA2,
        "rctrl": 0xA3, "alt": 0xA4, "lalt": 0xA4, "ralt": 0xA5,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "home": 0x24, "end": 0x23,
        "pageup": 0x21, "pagedown": 0x22, "comma": 0xBC, "period": 0xBE, "slash": 0xBF,
        "semicolon": 0xBA, "apostrophe": 0xDE, "minus": 0xBD, "equal": 0xBB,
        "grave": 0xC0, "lbracket": 0xDB, "rbracket": 0xDD, "backslash": 0xDC}
KEYS.update({chr(n): n for n in range(48, 58)})
KEYS.update({chr(n).lower(): n for n in range(65, 91)})
KEYS.update({f"f{n}": 0x6F + n for n in range(1, 13)})


def key_code(name):
    if not isinstance(name, str) or name.lower() not in KEYS:
        raise ValueError(f"Unsupported game key: {name!r}")
    return KEYS[name.lower()]


def bind(dll, name, result, *args):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = result, args
    return fn


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class INPUTUNION(C.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", INPUTUNION)]


class MEMORYSTATUSEX(C.Structure):
    _fields_ = [("dwLength", W.DWORD), ("dwMemoryLoad", W.DWORD)] + [(name, C.c_ulonglong) for name in
        ("ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile", "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")]


class Win32:
    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("The native Minecraft helper requires Windows")
        u = C.WinDLL("user32", use_last_error=True)
        k = C.WinDLL("kernel32", use_last_error=True)
        self.enum_proc = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        self.enum_windows = bind(u, "EnumWindows", W.BOOL, self.enum_proc, W.LPARAM)
        self.enum_children = bind(u, "EnumChildWindows", W.BOOL, W.HWND, self.enum_proc, W.LPARAM)
        self.window_pid = bind(u, "GetWindowThreadProcessId", W.DWORD, W.HWND, C.POINTER(W.DWORD))
        self.is_window = bind(u, "IsWindow", W.BOOL, W.HWND)
        self.is_visible = bind(u, "IsWindowVisible", W.BOOL, W.HWND)
        self.is_iconic = bind(u, "IsIconic", W.BOOL, W.HWND)
        self.window_text = bind(u, "GetWindowTextW", C.c_int, W.HWND, W.LPWSTR, C.c_int)
        self.get_client_rect = bind(u, "GetClientRect", W.BOOL, W.HWND, C.POINTER(W.RECT))
        self.get_window_rect = bind(u, "GetWindowRect", W.BOOL, W.HWND, C.POINTER(W.RECT))
        self.client_to_screen = bind(u, "ClientToScreen", W.BOOL, W.HWND, C.POINTER(W.POINT))
        self.foreground = bind(u, "GetForegroundWindow", W.HWND)
        self.root = bind(u, "GetAncestor", W.HWND, W.HWND, W.UINT)
        self.window_from_point = bind(u, "WindowFromPoint", W.HWND, W.POINT)
        self.set_foreground = bind(u, "SetForegroundWindow", W.BOOL, W.HWND)
        self.show_window = bind(u, "ShowWindow", W.BOOL, W.HWND, C.c_int)
        self.bring_top = bind(u, "BringWindowToTop", W.BOOL, W.HWND)
        self.attach_thread = bind(u, "AttachThreadInput", W.BOOL, W.DWORD, W.DWORD, W.BOOL)
        self.thread_id = bind(k, "GetCurrentThreadId", W.DWORD)
        self.set_cursor = bind(u, "SetCursorPos", W.BOOL, C.c_int, C.c_int)
        self.system_metric = bind(u, "GetSystemMetrics", C.c_int, C.c_int)
        self.get_cursor = bind(u, "GetCursorPos", W.BOOL, C.POINTER(W.POINT))
        self.send_input = bind(u, "SendInput", W.UINT, W.UINT, C.POINTER(INPUT), C.c_int)
        self.map_key = bind(u, "MapVirtualKeyW", W.UINT, W.UINT, W.UINT)
        self.key_state = bind(u, "GetAsyncKeyState", C.c_short, C.c_int)
        self.move_window = bind(u, "MoveWindow", W.BOOL, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.BOOL)
        self.post_message = bind(u, "PostMessageW", W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
        self.open_process = bind(k, "OpenProcess", W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
        self.close_handle = bind(k, "CloseHandle", W.BOOL, W.HANDLE)
        self.query_image = bind(k, "QueryFullProcessImageNameW", W.BOOL, W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD))
        self.process_times = bind(k, "GetProcessTimes", W.BOOL, W.HANDLE, *([C.POINTER(W.FILETIME)] * 4))
        self.create_mutex = bind(k, "CreateMutexW", W.HANDLE, C.c_void_p, W.BOOL, W.LPCWSTR)
        self.release_mutex = bind(k, "ReleaseMutex", W.BOOL, W.HANDLE)
        self.memory_status = bind(k, "GlobalMemoryStatusEx", W.BOOL, C.POINTER(MEMORYSTATUSEX))
        self.dwm_attribute = bind(C.WinDLL("dwmapi"), "DwmGetWindowAttribute", C.c_long, W.HWND, W.DWORD, C.c_void_p, W.DWORD)
        # Coordinate APIs and capture pixels must agree on physical pixels at any DPI.
        bind(u, "SetProcessDpiAwarenessContext", W.BOOL, W.HANDLE)(C.c_void_p(-4))

    def pid(self, hwnd):
        pid = W.DWORD()
        self.window_pid(hwnd, C.byref(pid))
        return pid.value

    def process(self, pid):
        handle = self.open_process(0x1000, False, pid)
        if not handle:
            return None
        try:
            buffer, size = C.create_unicode_buffer(32768), W.DWORD(32768)
            times = [W.FILETIME() for _ in range(4)]
            if not self.query_image(handle, 0, buffer, C.byref(size)) or not self.process_times(handle, *(C.byref(t) for t in times)):
                return None
            return {"executable": buffer.value, "created": str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)}
        finally:
            self.close_handle(handle)

    def rects(self, hwnd):
        client, window, frame, point = W.RECT(), W.RECT(), W.RECT(), W.POINT()
        if not self.get_client_rect(hwnd, C.byref(client)) or not self.get_window_rect(hwnd, C.byref(window)) or not self.client_to_screen(hwnd, C.byref(point)):
            raise RuntimeError("Cannot read game window geometry")
        if self.dwm_attribute(hwnd, 9, C.byref(frame), C.sizeof(frame)) != 0:
            frame = window
        return (client.right, client.bottom), (point.x, point.y), window, frame

    def inventory(self):
        found, cache = [], {}

        def info(pid):
            if pid not in cache:
                cache[pid] = self.process(pid)
            return cache[pid]

        @self.enum_proc
        def visit(hwnd, _):
            if not self.is_visible(hwnd):
                return True
            handles = [hwnd]

            @self.enum_proc
            def child(ch, _):
                handles.append(ch)
                return True

            self.enum_children(hwnd, child, 0)
            games = [(self.pid(h), info(self.pid(h))) for h in handles]
            games = [(pid, p) for pid, p in games if p and Path(p["executable"]).name.lower() in GAME_NAMES]
            if games:
                title = C.create_unicode_buffer(1024)
                self.window_text(hwnd, title, 1024)
                pid, proc = games[0]
                found.append({"hwnd": int(hwnd), "pid": pid, "title": title.value, **proc})
            return True

        self.enum_windows(visit, 0)
        return found

    def emit(self, event):
        if self.send_input(1, C.byref(event), C.sizeof(INPUT)) != 1:
            raise RuntimeError("SendInput failed; the game may run at a different elevation or the desktop may be locked")


class Capture:
    def __init__(self, native, hwnd):
        try:
            from windows_capture import WindowsCapture
        except ImportError as error:
            raise RuntimeError("Install scripts/windows/requirements.txt with this helper's Python") from error
        self.native, self.hwnd = native, hwnd
        self.condition = threading.Condition()
        self.latest = None
        self.stamp = 0.0
        self.closed = False
        self.capture = WindowsCapture(window_hwnd=hwnd, cursor_capture=False, draw_border=None)

        @self.capture.event
        def on_frame_arrived(frame, capture_control):
            with self.condition:
                if time.monotonic() - self.stamp < 0.045:
                    return
                self.latest = frame.frame_buffer.copy()
                self.stamp = time.monotonic()
                self.condition.notify_all()

        @self.capture.event
        def on_closed():
            with self.condition:
                self.closed = True
                self.condition.notify_all()

        self.control = self.capture.start_free_threaded()

    def screenshot(self, width=None):
        import cv2
        if self.native.is_iconic(self.hwnd):
            raise RuntimeError("Game is minimized; call focus to restore it before capture")
        started = time.monotonic()
        with self.condition:
            self.condition.wait_for(lambda: self.closed or (self.latest is not None and self.stamp >= started), timeout=2)
            if self.closed or self.latest is None:
                raise RuntimeError("Windows Graphics Capture produced no game frame")
            pixels, stamp = self.latest.copy(), self.stamp
        size, origin, window, frame = self.native.rects(self.hwnd)
        actual_h, actual_w = pixels.shape[:2]
        if (actual_w, actual_h) != size:
            bounds = next((r for r in (frame, window) if (r.right - r.left, r.bottom - r.top) == (actual_w, actual_h)), None)
            if bounds is None:
                raise RuntimeError("Capture size changed during screenshot; capture again before input")
            x, y = origin[0] - bounds.left, origin[1] - bounds.top
            if x < 0 or y < 0 or x + size[0] > actual_w or y + size[1] > actual_h:
                raise RuntimeError("Game client area does not fit capture bounds")
            pixels = pixels[y:y + size[1], x:x + size[0]]
        if size[0] <= 0 or size[1] <= 0:
            raise RuntimeError("Game client area is empty")
        out_w = min(size[0], integer(width, "width", 64, 7680)) if width is not None else size[0]
        out_h = max(1, round(size[1] * out_w / size[0]))
        if (out_w, out_h) != size:
            pixels = cv2.resize(pixels, (out_w, out_h), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".png", pixels[:, :, :3], [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if not ok:
            raise RuntimeError("Could not encode game screenshot")
        return {"width": out_w, "height": out_h, "source_width": size[0], "source_height": size[1],
                "png_base64": base64.b64encode(encoded).decode("ascii"),
                "frame_age_ms": round((time.monotonic() - stamp) * 1000),
                "new_frame": stamp >= started, "capture_ms": round((time.monotonic() - started) * 1000)}

    def close(self):
        if not self.control.is_finished():
            self.control.stop()


class Target:
    def __init__(self, native, record):
        self.n, self.record = native, record
        self.hwnd, self.pid = record["hwnd"], record["pid"]
        self.lock = self.n.create_mutex(None, True, f"Local\\MinecraftMCP-{self.pid}-{record['created']}")
        if not self.lock:
            raise RuntimeError("Cannot acquire game control lock")
        if C.get_last_error() == 183:
            self.n.close_handle(self.lock)
            self.lock = None
            raise RuntimeError("This Minecraft process is already attached to another MCP connection")
        self.capture = None
        self.shot = None
        self.held = {}
        self.guard = threading.RLock()
        self.done = threading.Event()
        self.watcher = threading.Thread(target=self.watch, daemon=True)
        self.watcher.start()

    def valid(self):
        proc = self.n.process(self.pid)
        if not self.n.is_window(self.hwnd) or not proc or proc != {k: self.record[k] for k in ("executable", "created")}:
            raise RuntimeError("Attached Minecraft process/window closed; list and attach again")
        # Older UWP clients use an ApplicationFrameHost parent with a game child.
        if self.n.pid(self.hwnd) != self.pid:
            children = []

            @self.n.enum_proc
            def child(hwnd, _):
                children.append(self.n.pid(hwnd))
                return True

            self.n.enum_children(self.hwnd, child, 0)
            if self.pid not in children:
                raise RuntimeError("The attached window no longer belongs to Minecraft")

    def focused(self):
        return self.n.root(self.n.foreground(), 2) == self.n.root(self.hwnd, 2)

    def require_focus(self):
        self.valid()
        if not self.focused() or self.n.is_iconic(self.hwnd):
            self.release_all()
            raise RuntimeError("Minecraft is not foreground; call focus before sending input")

    def state(self):
        self.valid()
        size, origin, _, _ = self.n.rects(self.hwnd)
        return {**self.record, "width": size[0], "height": size[1], "screen_x": origin[0], "screen_y": origin[1],
                "focused": self.focused(), "minimized": bool(self.n.is_iconic(self.hwnd)), "fps": None,
                "backend": "windows-native", "held_inputs": list(self.held),
                "capabilities": {"capture": "windows-graphics-capture", "unicode_text": True, "hidden": False,
                                 "fps_control": False, "render_on_demand": False, "isolated_profiles": False}}

    def focus(self):
        self.valid()
        if self.n.is_iconic(self.hwnd):
            self.n.show_window(self.hwnd, 9)
        self.n.set_foreground(self.hwnd)
        if not self.focused():
            current = self.n.thread_id()
            other = self.n.window_pid(self.n.foreground(), None)
            attached = bool(other and other != current and self.n.attach_thread(current, other, True))
            try:
                self.n.bring_top(self.hwnd)
                self.n.set_foreground(self.hwnd)
            finally:
                if attached:
                    self.n.attach_thread(current, other, False)
        time.sleep(0.1)
        self.require_focus()
        return self.state()

    def resize(self, width, height):
        self.valid()
        width, height = integer(width, "width", 320, 7680), integer(height, "height", 180, 4320)
        self.release_all()
        self.shot = None
        if self.n.is_iconic(self.hwnd):
            raise RuntimeError("Restore the game with focus before resizing")
        size, _, rect, _ = self.n.rects(self.hwnd)
        if not self.n.move_window(self.hwnd, rect.left, rect.top, width + rect.right - rect.left - size[0],
                                  height + rect.bottom - rect.top - size[1], True):
            raise RuntimeError("Windows refused to resize the game")
        time.sleep(0.15)
        return self.state()

    def screenshot(self, width):
        self.valid()
        if self.capture is None:
            self.capture = Capture(self.n, self.hwnd)
        result = self.capture.screenshot(width)
        self.shot = tuple(result[k] for k in ("source_width", "source_height", "width", "height"))
        return result

    def emit_key(self, vk, down):
        scan = self.n.map_key(vk, 4)
        flags = 0x0008 | (0x0001 if scan & 0xFF00 else 0) | (0 if down else 0x0002)
        event = INPUT(type=1, ki=KEYBDINPUT(0, scan & 0xFF, flags, 0, 0))
        self.n.emit(event)

    def emit_mouse(self, flag, data=0, dx=0, dy=0):
        self.n.emit(INPUT(type=0, mi=MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flag, 0, 0)))

    def down(self, token, emitter):
        with self.guard:
            self.require_focus()
            if token in self.held:
                return
            emitter(True)
            self.held[token] = (time.monotonic() + 60, emitter)

    def up(self, token):
        with self.guard:
            entry = self.held.pop(token, None)
            if entry:
                entry[1](False)

    def release_all(self):
        with self.guard:
            for token in list(self.held):
                try:
                    self.up(token)
                except OSError:
                    pass

    def watch(self):
        while not self.done.wait(0.05):
            with self.guard:
                try:
                    if self.held and (not self.focused() or not self.n.is_window(self.hwnd)):
                        self.release_all()
                    else:
                        for token, (expires, _) in list(self.held.items()):
                            if time.monotonic() >= expires:
                                self.up(token)
                except Exception:
                    # Keep the watchdog alive, without writing to protocol stdout.
                    self.held.clear()

    def wait_focused(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.require_focus()
            time.sleep(min(0.03, max(0, deadline - time.monotonic())))

    def key(self, name, action="tap", hold_ms=60, mods=None):
        code = key_code(name)
        delay = integer(hold_ms, "hold_ms", 1, 60000) / 1000
        if action not in ("tap", "press", "release"):
            raise ValueError("Unknown key action")
        mods = mods or []
        if not isinstance(mods, list) or len(mods) > 3 or any(m not in ("shift", "ctrl", "alt") for m in mods):
            raise ValueError("Modifiers must be shift, ctrl, or alt")
        codes = list(dict.fromkeys([key_code(m) for m in mods] + [code]))
        if action == "release":
            for vk in reversed(codes):
                self.up(f"key:{vk}")
        else:
            pressed = []
            try:
                for vk in codes:
                    if f"key:{vk}" not in self.held:
                        if self.n.key_state(vk) & 0x8000:
                            raise RuntimeError("Requested key is already held by the user; release it before MCP input")
                        self.down(f"key:{vk}", lambda down, vk=vk: self.emit_key(vk, down))
                        pressed.append(vk)
                if action == "tap":
                    self.wait_focused(delay)
            except Exception:
                for vk in reversed(pressed):
                    self.up(f"key:{vk}")
                raise
            finally:
                if action == "tap":
                    for vk in reversed(pressed):
                        self.up(f"key:{vk}")
        return {"key": name, "action": action}

    def text(self, value):
        value = literal_text(value)
        self.require_focus()
        if self.held or any(self.n.key_state(vk) & 0x8000 for vk in (0x10, 0x11, 0x12)):
            raise RuntimeError("Release held keys and modifiers before typing text")
        raw = value.encode("utf-16-le")
        for offset in range(0, len(raw), 2):
            self.require_focus()
            unit = int.from_bytes(raw[offset:offset + 2], "little")
            try:
                self.n.emit(INPUT(type=1, ki=KEYBDINPUT(0, unit, 0x0004, 0, 0)))
            finally:
                self.n.emit(INPUT(type=1, ki=KEYBDINPUT(0, unit, 0x0004 | 0x0002, 0, 0)))
            time.sleep(0.01)
        return {"characters": len(value), "submitted": False}

    def move_to(self, x, y):
        self.require_focus()
        size, origin, _, _ = self.n.rects(self.hwnd)
        x, y = coordinate(x, y, self.shot, size)
        point = W.POINT(origin[0] + x, origin[1] + y)
        if self.n.root(self.n.window_from_point(point), 2) != self.n.root(self.hwnd, 2):
            raise RuntimeError("Click target is covered by another window; focus Minecraft and capture again")
        left, top = self.n.system_metric(76), self.n.system_metric(77)
        desktop_w, desktop_h = self.n.system_metric(78), self.n.system_metric(79)
        if not (left <= point.x < left + desktop_w and top <= point.y < top + desktop_h):
            raise RuntimeError("Game coordinate is outside the visible desktop")
        # SendInput generates the input path used by DirectInput/Raw Input games;
        # SetCursorPos alone can move the OS pointer without moving the game cursor.
        self.emit_mouse(0x8000 | 0x4000 | 0x0001,
                        dx=round((point.x - left) * 65535 / max(1, desktop_w - 1)),
                        dy=round((point.y - top) * 65535 / max(1, desktop_h - 1)))
        return {"x": x, "y": y}

    def click(self, button="left", x=None, y=None, action="tap", hold_ms=60):
        buttons = {"left": (2, 4), "right": (8, 16), "middle": (32, 64)}
        if button not in buttons or action not in ("tap", "press", "release"):
            raise ValueError("Invalid mouse button/action")
        delay = integer(hold_ms, "hold_ms", 1, 60000) / 1000
        if (x is None) != (y is None):
            raise ValueError("Supply both x and y, or neither")
        token = f"mouse:{button}"
        if action == "release":
            self.up(token)
            return {"button": button, "action": action}
        self.require_focus()
        if x is not None:
            self.move_to(x, y)
            self.wait_focused(0.1)
        point = W.POINT()
        self.n.get_cursor(C.byref(point))
        if self.n.root(self.n.window_from_point(point), 2) != self.n.root(self.hwnd, 2):
            raise RuntimeError("Pointer is outside Minecraft; move it to an observed game coordinate first")
        down, up = buttons[button]
        try:
            self.down(token, lambda pressed: self.emit_mouse(down if pressed else up))
            if action == "tap":
                self.wait_focused(delay)
        finally:
            if action == "tap":
                self.up(token)
        return {"button": button, "action": action}

    def close(self):
        self.done.set()
        self.watcher.join(timeout=1)
        self.release_all()
        try:
            if self.capture:
                self.capture.close()
        finally:
            if self.lock:
                self.n.release_mutex(self.lock)
                self.n.close_handle(self.lock)
                self.lock = None


def installations():
    script = """$ErrorActionPreference='Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$items = @(Get-AppxPackage '*Minecraft*' | ForEach-Object {
  $pkg = $_
  [xml]$manifest = Get-Content -LiteralPath (Join-Path $pkg.InstallLocation 'AppxManifest.xml')
  foreach ($app in $manifest.Package.Applications.Application) {
    if ($app.Executable -match '(^|[\\/])Minecraft\\.Windows(Beta)?\\.exe$') {
      [pscustomobject]@{app_id=($pkg.PackageFamilyName+'!'+$app.Id); name=$pkg.Name; version=$pkg.Version.ToString(); executable=(Join-Path $pkg.InstallLocation $app.Executable)}
    }
  }
})
ConvertTo-Json -InputObject $items -Compress
"""
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, encoding="utf-8", errors="replace", timeout=20, creationflags=CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("Could not enumerate registered Minecraft packages: " + result.stderr[-800:])
    return json.loads(result.stdout.lstrip("\ufeff").strip() or "[]")


def activate_app(app_id, uri=None):
    """Activate the exact registered package, not whichever app owns minecraft: globally."""
    if uri is None:
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + app_id], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        return
    # WinRT also supports packaged desktop/GDK apps. Run activation outside the
    # persistent helper so an unresponsive protocol handler cannot hang input cleanup.
    script = """$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.System.Launcher,Windows.System,ContentType=WindowsRuntime]
$options = [Windows.System.LauncherOptions,Windows.System,ContentType=WindowsRuntime]::new()
$options.TargetApplicationPackageFamilyName = $env:MINECRAFT_ACTIVATION_FAMILY
$operation = [Windows.System.Launcher]::LaunchUriAsync([Uri]$env:MINECRAFT_ACTIVATION_URI, $options)
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$task = $asTask.MakeGenericMethod([bool]).Invoke($null, @($operation))
if (-not $task.Wait(15000)) { throw 'Minecraft protocol activation timed out; inspect the game before retrying' }
if (-not $task.Result) { throw 'Windows did not dispatch the URI to the attached Minecraft package' }
"""
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            env={**os.environ, "MINECRAFT_ACTIVATION_FAMILY": app_id.split("!")[0], "MINECRAFT_ACTIVATION_URI": uri},
                            capture_output=True, encoding="utf-8", errors="replace", timeout=20, creationflags=CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("Minecraft URI activation failed: " + result.stderr[-1200:])


class Agent:
    def __init__(self):
        self.n = Win32()
        self.target = None
        self.logs = []

    def attach(self, pid=None, hwnd=None):
        if self.target:
            raise RuntimeError("Detach the current game before attaching another")
        if pid is not None:
            pid = integer(pid, "pid", 1, 0xFFFFFFFF)
        if hwnd is not None:
            hwnd = integer(hwnd, "hwnd", 1, 2 ** 53 - 1)
        matches = [r for r in self.n.inventory() if (pid is None or r["pid"] == pid) and (hwnd is None or r["hwnd"] == hwnd)]
        if len(matches) != 1:
            raise RuntimeError(f"Expected exactly one Minecraft window; found {len(matches)}. Use list then attach with its PID/HWND")
        candidate = Target(self.n, matches[0])
        try:
            state = candidate.state()
        except Exception:
            candidate.close()
            raise
        self.target = candidate
        self.logs.append(f"Attached Minecraft PID {candidate.pid}")
        return state

    def launch(self, req):
        if self.target or self.n.inventory():
            raise RuntimeError("Minecraft is already running; use list and attach instead of launching another client")
        if (req.get("width") is None) != (req.get("height") is None):
            raise ValueError("Supply width and height together")
        if req.get("width") is not None:
            integer(req["width"], "width", 320, 7680)
            integer(req["height"], "height", 180, 4320)
        executable = req.get("executable") or os.environ.get("MINECRAFT_WINDOWS_EXE")
        app_id = req.get("app_id")
        if executable and app_id:
            raise ValueError("Use either executable or app_id")
        if executable:
            path = Path(executable)
            if not path.is_absolute() or not path.is_file() or path.name.lower() not in GAME_NAMES:
                raise ValueError("executable must be an absolute path to Minecraft.Windows.exe or Minecraft.WindowsBeta.exe")
            expected_executable = str(path)
            subprocess.Popen([str(path)], cwd=str(path.parent), stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            packages = installations()
            candidates = [p for p in packages if p["app_id"] == app_id] if app_id else [p for p in packages if "beta" not in p["name"].lower()]
            if len(candidates) != 1:
                raise ValueError("Select exactly one registered app_id from list, or supply an executable path")
            expected_executable = candidates[0]["executable"]
            activate_app(candidates[0]["app_id"])
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            windows = [w for w in self.n.inventory() if os.path.normcase(w["executable"]) == os.path.normcase(expected_executable)]
            if windows:
                if len(windows) != 1:
                    raise RuntimeError("Multiple new game windows appeared; use list and attach to choose one")
                result = self.attach(windows[0]["pid"], windows[0]["hwnd"])
                try:
                    if req.get("width") is not None:
                        result = self.target.resize(req["width"], req["height"])
                except Exception:
                    self.target.close()
                    self.target = None
                    raise
                return {**result, "started": True, "menu_ready": "unverified"}
            time.sleep(0.25)
        raise RuntimeError("Minecraft exposed no window within 60s; inspect its launcher/login before retrying")

    def dispatch(self, req):
        cmd = req.get("cmd")
        if cmd == "list":
            return {"windows": self.n.inventory(), "installations": installations()}
        if cmd == "preflight":
            mem = MEMORYSTATUSEX(dwLength=C.sizeof(MEMORYSTATUSEX))
            if not self.n.memory_status(C.byref(mem)):
                raise RuntimeError("Cannot read Windows memory status")
            capture = importlib.util.find_spec("windows_capture") is not None
            return {"ready": capture, "available_mib": mem.ullAvailPhys // 1048576, "windows": self.n.inventory(),
                    "python": sys.version.split()[0], "capture_dependency": capture,
                    "issues": [] if capture else ["Install scripts/windows/requirements.txt"]}
        if cmd == "attach":
            return self.attach(req.get("pid"), req.get("hwnd"))
        if cmd == "launch":
            return self.launch(req)
        if cmd == "shutdown":
            self.close()
            return {"detached": True}
        if not self.target:
            raise RuntimeError("No Minecraft window attached")
        t = self.target
        if cmd == "detach":
            if req.get("close_game", False):
                t.valid()
                if not self.n.post_message(t.hwnd, 0x0010, 0, 0):
                    raise RuntimeError("Could not request normal Minecraft window closure")
            t.close()
            self.target = None
            return {"detached": True, "close_requested": bool(req.get("close_game", False))}
        if cmd == "state": return t.state()
        if cmd == "focus": return t.focus()
        if cmd == "resize": return t.resize(req.get("width"), req.get("height"))
        if cmd == "screenshot": return t.screenshot(req.get("width"))
        if cmd == "key": return t.key(req.get("key"), req.get("action", "tap"), req.get("hold_ms", 60), req.get("mods"))
        if cmd == "text": return t.text(req.get("text"))
        if cmd == "chat":
            value = literal_text(req.get("text"))
            t.key("t")
            t.wait_focused(0.4)
            t.text(value)
            t.key("enter")
            return {"characters": len(value), "submitted": True}
        if cmd == "mouse_pos": return t.move_to(req.get("x"), req.get("y"))
        if cmd == "click": return t.click(req.get("button", "left"), req.get("x"), req.get("y"), req.get("action", "tap"), req.get("hold_ms", 60))
        if cmd == "mouse_move":
            dx, dy = integer(req.get("dx"), "dx", -32767, 32767), integer(req.get("dy"), "dy", -32767, 32767)
            t.require_focus()
            t.emit_mouse(1, dx=dx, dy=dy)
            return {"dx": dx, "dy": dy}
        if cmd == "scroll":
            dy = req.get("dy")
            if isinstance(dy, bool) or not isinstance(dy, (int, float)) or not math.isfinite(dy) or not -100 <= dy <= 100:
                raise ValueError("dy must be finite, between -100 and 100")
            t.require_focus()
            point = W.POINT()
            self.n.get_cursor(C.byref(point))
            if self.n.root(self.n.window_from_point(point), 2) != self.n.root(t.hwnd, 2):
                raise RuntimeError("Move the pointer over Minecraft before scrolling")
            t.emit_mouse(0x0800, round(dy * 120))
            return {"dy": dy}
        if cmd == "uri":
            uri = req.get("uri")
            if not isinstance(uri, str) or not uri.startswith("minecraft:") or len(uri) > 2048 or any(ord(c) < 32 for c in uri):
                raise ValueError("Expected a bounded minecraft: URI")
            t.valid()
            packages = installations()
            package = next((p for p in packages if os.path.normcase(p["executable"]) == os.path.normcase(t.record["executable"])), None)
            if not package:
                raise RuntimeError("Attached executable is not registered as a Minecraft app; URI routing cannot be verified")
            activate_app(package["app_id"], uri)
            return {"dispatched": True, "package": package["app_id"], "saved": "unverified", "joined": "unverified"}
        if cmd == "log": return {"lines": self.logs[-50:]}
        raise ValueError(f"Unknown Windows command: {cmd}")

    def close(self):
        if self.target:
            self.target.close()
            self.target = None


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    agent = Agent()
    try:
        for line in sys.stdin:
            req = {}
            try:
                if len(line) > 32768:
                    raise ValueError("Request is too large")
                req = json.loads(line)
                if not isinstance(req, dict):
                    raise ValueError("Request must be an object")
                result = {"id": req.get("id"), "ok": True, **agent.dispatch(req)}
            except Exception as error:
                result = {"id": req.get("id") if isinstance(req, dict) else None, "ok": False, "error": str(error)}
            print(json.dumps(result, ensure_ascii=True), flush=True)
            if isinstance(req, dict) and req.get("cmd") == "shutdown":
                break
    finally:
        agent.close()


if __name__ == "__main__":
    main()
