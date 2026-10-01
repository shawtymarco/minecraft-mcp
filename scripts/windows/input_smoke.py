"""Exercise real WGC/SendInput on a disposable Tk window, never on a user's game.

Run on an unlocked Windows desktop. The fixture briefly takes foreground focus.
"""
import ctypes as C
import json
import os
import threading
import time
import traceback
from pathlib import Path

from agent import Win32, Target

n = Win32()  # Set physical-pixel DPI awareness before creating the fixture.
import tkinter as tk

root = tk.Tk()
root.title("Minecraft MCP input test fixture")
root.geometry("640x360+50+50")
tk.Label(root, text="Minecraft MCP: disposable input/capture test", font=("Arial", 14)).pack(pady=25)
value = tk.StringVar()
entry = tk.Entry(root, textvariable=value, font=("Arial", 16))
entry.pack(fill="x", padx=25, pady=15)
tk.Label(root, text="This test does not send input to Minecraft.").pack()
other = tk.Toplevel(root)
other.title("Minecraft MCP focus-loss fixture")
other.geometry("350x100+750+80")
other_value = tk.StringVar()
tk.Entry(other, textvariable=other_value).pack()
report = []
failure = []


def record(check):
    report.append(check)


def wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for fixture observation")


def test(hwnd, other_hwnd, entry_center):
    target = None
    try:
        proc = n.process(os.getpid())
        target = Target(n, {"hwnd": hwnd, "pid": os.getpid(), "title": root.title(), **proc})
        target.focus()
        shot = target.screenshot(320)
        assert shot["source_width"] == 640 and shot["width"] == 320, shot
        record("WGC capture and client-area cropping")
        x, y = entry_center
        target.click(x=x * shot["width"] / shot["source_width"], y=y * shot["height"] / shot["source_height"])
        target.text("MCP 한글 Ω 123")
        wait_until(lambda: value.get() == "MCP 한글 Ω 123")
        record("scaled screenshot click and Unicode SendInput")
        target.key("backspace")
        wait_until(lambda: value.get() == "MCP 한글 Ω 12")
        record("scan-code key tap")
        target.key("w", action="press")
        assert n.key_state(87) & 0x8000
        n.set_foreground(other_hwnd)
        wait_until(lambda: not target.held)
        assert not n.key_state(87) & 0x8000
        before = other_value.get()
        try:
            target.text("must not type")
            raise AssertionError("Background input was accepted")
        except RuntimeError as error:
            assert "foreground" in str(error)
        assert other_value.get() == before
        record("focus-loss releases held key and rejects background typing")
        target.focus()
        target.resize(700, 400)
        try:
            target.click(x=10, y=10)
            raise AssertionError("Input accepted stale screenshot coordinates")
        except ValueError as error:
            assert "screenshot" in str(error)
        target.screenshot(350)
        record("resize invalidates screenshot coordinate mapping")
        try:
            duplicate = Target(n, target.record)
            duplicate.close()
            raise AssertionError("Duplicate control lock was accepted")
        except RuntimeError as error:
            assert "already attached" in str(error)
        record("exclusive process lock")
        target.key("a", action="press")
        target.close()
        target = None
        assert not n.key_state(65) & 0x8000
        record("detach releases held inputs")
        print(json.dumps({"status": "passed", "checks": report}), flush=True)
    except Exception:
        failure.append(traceback.format_exc())
        print(failure[-1], flush=True)
    finally:
        if target:
            target.close()
        root.after(0, root.destroy)


def start():
    hwnd = n.root(root.winfo_id(), 2)
    other_hwnd = n.root(other.winfo_id(), 2)
    origin = n.rects(hwnd)[1]
    center = (entry.winfo_rootx() + entry.winfo_width() // 2 - origin[0],
              entry.winfo_rooty() + entry.winfo_height() // 2 - origin[1])
    threading.Thread(target=test, args=(hwnd, other_hwnd, center), daemon=True).start()


root.after(400, start)
root.after(30000, lambda: (failure.append("Native input smoke watchdog elapsed"), root.destroy()))
root.mainloop()
if failure:
    raise SystemExit(1)
