---
name: minecraft-windows
description: Control native Minecraft Bedrock on Windows through the registered minecraft MCP, using batched actions and local OCR for known menus. Use for game-client automation and visual game checks, not unrelated Minecraft server development.
---

# Native Minecraft on Windows

Codex is the main planner: choose the objective, interpret unfamiliar screens and
world geometry, and decide the next short action segment. The local MCP executes
that segment. Jev is an optional text-only fallback for ambiguous menu OCR, not
the main planner or a visual gameplay model.

Use the registered `minecraft` MCP tools directly. If they are not exposed in the
current chat, report that the MCP connection needs to be restarted/reloaded. Do
not silently substitute a terminal console or SDK harness for normal play.
Connection probes are appropriate during setup, but label them as probes.

## Keep the normal loop short

- Reuse the attached instance and the last confirmed image dimensions. On first
  use, `list` identifies actual game windows; `attach` selects the exact PID/HWND.
  Use `launch` only when the user needs a new game process.
- Take one screenshot to understand the current situation. Prefer the MCP's inline
  image instead of save → terminal polling → `view_image`. Use `save_path` when
  an artifact is actually needed.
- For a known short segment, call `execute` with the actions and one final capture.
  It focuses once, runs actions sequentially, releases held keys/buttons and returns
  one image. A failure ends the segment. Do not make a model turn per key, wait or
  intermediate screenshot. Only include actions justified by the observed screen.
- For repeated menu transitions, use `run_route` with verified crop boxes, literal
  labels and fixed click/navigation-key actions. Local Windows OCR checks the start
  and every resulting screen, while Codex receives only the final or failed image.
  Default to `mode:local`; no API key is needed. Use `hybrid` only when the user has
  enabled Jev and configured `TYPESAFE_API_KEY`; unmatched OCR text then goes to
  TypeSafe. Missing keys, uncertain answers or API errors stop at fallback.
- Unfamiliar dialogs, parkour, combat and visual correctness still require Codex's
  visual judgment. OCR/menu timings do not establish real-time gameplay latency.
- Match the user's completion condition and stop when it passes. If the user stops
  capture or gameplay, detach/release inputs and do not resume it for setup tests.

Example known movement segment (only after observing a playable world):

```json
{"actions":[{"cmd":"key","key":"w","action":"press"},{"cmd":"wait","ms":400},{"cmd":"key","key":"w","action":"release"}],"capture":true,"width":854}
```

If a pause menu is visible, decide how to resume from that image before movement;
do not prepend Escape blindly. Batch focus/resume/movement when that sequence is
already justified. Windows shares the user's desktop: input fails on focus loss.
Do not repeatedly refocus against active user input.

## Route plans

`run_route.plan` contains the inspected screenshot `width`, `height`, an OCR
`language` (default `en-US`), `start`, and 1–12 `steps`.

Each screen check has `description`, `regions` (`[left,top,right,bottom]` pixel
boxes), and `all` (every literal clause must match). A `|` within a clause lists
observed OCR spelling alternatives. Each step has an explicit `action`, an `after`
screen check, and `settle_ms` appropriate to that known transition. Routes support
left-clicks and navigation-key taps; use `execute` for other known actions.

Derive crop boxes and coordinates from the actual game frame. Recalibrate after
layout/dimension changes. A fallback is evidence for diagnosis, not permission to
blindly repeat the route. Keep the same MCP instance and let the tool preserve
capture/worker state. Do not run competing input controllers.

## Windows specifics

Screenshots contain only the client area. Mouse coordinates use the most recent
image pixels and expire on resize. `type` sends literal Unicode without submitting;
`chat` sends a message, so use it only when that submission is authorized.

`stop` detaches and leaves Minecraft running. `close_game:true` explicitly requests
normal game closure. Hidden windows, isolated profiles, FPS caps, and render gating
are unavailable on this backend. Do not apply Linux headless instructions to it.
`add_server`/`open_uri` only confirm dispatch; verify the resulting screen.

Distinguish capture latency, local route duration and complete Codex task time.
Never promise zero latency or infer a gameplay speedup from a menu/OCR microbenchmark.
