# Native Windows backend

The Windows implementation controls the installed Minecraft for Windows client.
It uses Windows Graphics Capture (WGC) for window-scoped images and Win32 SendInput
for keyboard/mouse events. A persistent Python helper avoids starting a process
for every action. It does not inject DLLs, modify the game, or emulate Bedrock packets.

## Install

Install Bun and Python 3.10+ **x64** first. The capture dependency ships an x64
Windows wheel. Windows 10 2004+ or Windows 11 and an unlocked interactive desktop
are required. The desktop is shared with the user; screenshots work when the game
is covered, but minimized windows must be restored. A system capture border may
be shown by Windows.

From this repository in PowerShell:

```powershell
.\scripts\windows\setup.ps1
```

To select a specific Python installation:

```powershell
.\scripts\windows\setup.ps1 -Python 'C:\Python314\python.exe'
```

Equivalent manual commands:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r scripts/windows/requirements.txt
bun install --frozen-lockfile
bun run typecheck
```

The helper automatically uses `.venv\Scripts\python.exe` relative to the repository.
`MINECRAFT_WINDOWS_PYTHON` overrides that path. If neither exists, it uses `py -3`.
No environment activation is needed. Do not launch the MCP at a different elevation
from the game: Windows can block cross-elevation SendInput.

## Connect Codex

Add a stdio server in Codex's MCP settings, or configure `~/.codex/config.toml`.
Replace both paths with the actual installation paths:

```toml
[mcp_servers.minecraft]
command = 'C:\path\to\bun.exe'
args = ['run', 'C:\path\to\minecraft-mcp\src\index.ts']
startup_timeout_sec = 30
tool_timeout_sec = 120
```

The equivalent CLI registration is:

```powershell
codex mcp add minecraft -- 'C:\path\to\bun.exe' run 'C:\path\to\minecraft-mcp\src\index.ts'
```

Start a new connection after changing the server code. Setup does not edit your
Codex configuration or replace an existing MCP registration.

## Workflow

1. Call `preflight`, then `list`. `list` returns actual Minecraft PID/HWND values
   and installed package AUMIDs. Java Edition and launchers are excluded.
2. Call `attach({id:"test",pid:12345})` using the returned PID. Add `hwnd` when
   one process has more than one candidate window. Attach preserves size and focus.
   Alternatively, `launch` starts a registered Minecraft installation when no game
   window is already running. Use the exact `app_id` from `list` when needed.
   Custom installations can use an absolute `executable` path or the
   `MINECRAFT_WINDOWS_EXE` environment variable.
3. Call `screenshot({width:854})`, inspect it, then `focus` and the desired input.
   For known actions, put focus and input in one caller-controlled tool batch so
   another application does not regain focus between them.
4. Inspect a fresh screenshot after actions. A successful input response means
   Windows accepted events, not that a particular menu transition or world action
   succeeded. Avoid blind retries.
5. Call `stop()` to release inputs and detach. `stop({close_game:true})` posts a
   normal window-close request and detaches; it does not force kill Minecraft and
   does not claim the game finished closing.

One MCP connection controls one selected game at a time. An OS named mutex prevents
another connection from controlling that game concurrently. Client disconnect
releases held input and capture resources; it leaves Minecraft running. Pressed
keys/buttons release when the game loses focus or after 60 seconds, including when
the caller never sends a matching release. Abrupt OS termination can prevent cleanup.

## Tools and coordinates

- `launch`, `attach`, `stop`, `list`, `preflight`, `state`, `focus`, `resize`
- `screenshot`, `key`, `hold_key`, `type`, `chat`, `look`, `click`, `mouse_move_to`, `scroll`
- `open_uri`, `add_server`, `wait`, `log`

Screenshots crop out the window's title bar and borders and use physical pixels.
Click coordinates refer to the last image returned by the helper; the helper maps
both axes to the current client area. Resizing invalidates those coordinates.
Moving a window between displays does not authorize clicks into other apps;
pointer targets are checked against the selected game window.

`screenshot` accepts an optional absolute `save_path`. Set `include_image:false`
to save without forwarding the PNG to the model. Screenshot results include
`capture_ms`, `frame_age_ms`, and `new_frame`. WGC only produces frames when Windows
updates the window. After two seconds without a new frame, the most recent frame
is returned with its age and `new_frame:false`; this is not proof of fresh game progress.

`key` supports letters, digits, F1–F12, navigation keys, and shift/ctrl/alt modifiers.
`press`/`release` can span calls. `type` sends Unicode UTF-16 events, leaves the
clipboard untouched, and never presses Enter. Some game widgets/fonts may not
accept or display every Unicode character. `chat` opens chat with T and submits
with Enter; only call it after verifying that the client is in a world.

## Platform limits

- Input uses the foreground desktop and real pointer. It is not background or
  isolated input. Other applications regaining focus cause input to fail.
- The backend cannot hide the game, choose an isolated profile or Xbox login,
  enforce Linux resource limits, read game FPS, cap FPS, or suppress rendering.
  `set_fps` and `set_render_mode` explicitly fail. `state.fps` is `null`.
- `launch` returns when a game window exists. It does not assert menu readiness.
  Optional width/height resize the window; games in fullscreen may ignore this.
- `open_uri` targets the registered package corresponding to the attached executable.
  Unregistered custom executables cannot use targeted URI dispatch. Windows and
  Minecraft may reject individual URI operations; inspect the returned error/screen.
- `add_server` dispatches the add-server URI and returns `saved:"unverified"`.
  Automatic `join:true` is rejected. Inspect/complete the UI and then explicitly
  dispatch a connect URI if desired. No saved-server files are rewritten.
- The bundled Linux headless/JeV launch scripts still require their Linux runtime.
  Their game socket and `/proc` attachment are not the Windows helper transport.
  This backend does not require JeV or a separate model API key.

## Verify

```powershell
bun run typecheck
bun test
.\.venv\Scripts\python.exe -m unittest discover -s scripts/windows -p test_agent.py -v
.\.venv\Scripts\python.exe scripts/windows/input_smoke.py
bun scripts/smoke.ts
```

The Python input smoke creates disposable test windows, briefly focuses them, and
verifies WGC, scaled clicks, Unicode typing, scan-code input, focus-loss release,
stale-coordinate rejection, ownership and detach cleanup. It does not send input
to Minecraft. The game smoke is read-only: it attaches, captures, checks duplicate
attachment rejection and unsupported controls, and detaches without closing the game.
Set `MINECRAFT_SMOKE_PID` when more than one game window exists. Evidence stays in
git-ignored `.artifacts/windows-smoke`.

For manual testing, `bun scripts/windows/console.ts` accepts one
`{"name":"tool","arguments":{...}}` JSON request per line. It saves images locally.
Send `{"name":"exit"}` to close the MCP connection gracefully.

### Local validation, 2026-10-01

Tested against an existing OderSo 26.45 packaged native client on Windows, with
Python 3.14 and Bun 1.4.2. Live checks verified game-only capture while occluded,
downscaling, exclusive attachment and detach without closing the game. The initial
capture, including Python capture-library initialization, took 863 ms; the next
two MCP screenshot calls took 48 and 52 ms. These are three local samples, not a
benchmark guarantee. Menu Escape and a screenshot-coordinate Play click were
visually checked. Targeted `minecraft://` URI dispatch was accepted by Windows.
Unicode was validated in the disposable native fixture. Cold game launch, server
joining, in-world movement/combat, and native game closure were not exercised by
the read-only smoke and must be verified for the target game build.
