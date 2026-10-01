# Minecraft MCP

An MCP server for controlling a real Minecraft Bedrock client. This fork adds a
**native Windows backend** for Minecraft for Windows, including registered custom
installations such as OderSo. Linux uses the existing
[mcpelauncher agent socket](https://github.com/bedrock-mc/mcpelauncher-manifest).
`src/index.ts` selects the backend for the host OS.

## Windows quick start

Requires Windows 10 2004+ or Windows 11 (x64), Bun, Python 3.10+ x64, and an installed
Minecraft for Windows. No WSL or modified Linux launcher is needed. Minecraft runs
in the interactive desktop session; input requires it to be in the foreground.

```powershell
git clone https://github.com/shawtymarco/minecraft-mcp.git
cd minecraft-mcp
.\scripts\windows\setup.ps1
bun run src/index.ts
```

The setup script creates a project-local `.venv`, installs the pinned Windows
capture library and Bun dependencies, and checks TypeScript. It does not install
Python, Bun, or Minecraft. See [Windows setup and limitations](docs/windows.md)
for Codex configuration, custom Python paths, tools, and verification.

Start with `list`, then `attach` to the returned PID for an already-running game.
Call `focus` before input and `screenshot` before coordinate clicks. `stop` releases
the connection without closing the game; explicitly set `close_game: true` to
request normal window closure. `launch` refuses to start a second running client.

| Feature | Native Windows | Linux launcher |
|---|---|---|
| MCP screenshot, key, mouse, camera, wheel | Yes | Yes |
| Text input | Unicode via SendInput | Printable ASCII via XTest |
| Attach to a running native game | Yes, exact PID/HWND | MCP-owned instances |
| URI dispatch | Targeted registered Windows package | Launcher socket |
| Automatic server-save/join confirmation | Inspect and confirm through tools | Integrated 854×480 flow |
| Hidden clients, render gating, FPS control | Unavailable | Supported |
| CPU/RAM enforcement, isolated profiles | Unavailable | Existing Linux controls |

## Linux requirements

- Linux with a user systemd manager, `xvfb-run`, `xauth`, Python 3, and the agent-enabled
  mcpelauncher client. The bundled `bin/mcpelauncher-headless-fedora` documents this host's
  Flatpak launcher command; set `MCPELAUNCHER_CLIENT` to the installed wrapper.
- Bun, a locally installed Bedrock version, and a signed-in launcher data directory.
- On this host, `MCPELAUNCHER_ABI=x86_64`,
  `MCPELAUNCHER_DATA=/home/danick/.var/app/io.mrarm.mcpelauncher/data/mcpelauncher`, and
  `MCPELAUNCHER_SOCKET_DIR=/home/danick/.var/app/io.mrarm.mcpelauncher/data/s`.

```sh
bun install --frozen-lockfile
bun run typecheck
bun run src/index.ts
```

## Linux session controls

`preflight` and `launch` count actual clients across MCP connections, check host load, and
require available RAM equal to the requested session memory limit plus 2 GiB. At most four
clients run at once. Each Linux client starts through a systemd user unit. Flatpak moves
the game into its own app scope, so `launch` applies and verifies the default 250% CPU
quota (2.5 cores) and 4096 MiB memory limit on that game scope before returning. The
wrapper unit is limited too. Routine sessions render at 20 FPS.
`launch` accepts bounded `cpu_quota_percent`, `memory_limit_mib`, and `fps_cap` overrides.
`preflight` uses the requested quota and memory limit to require enough host capacity;
`launch` repeats that check. The game scope appears a few seconds after process start,
so the game cap takes effect when the scope is discovered, before `launch` returns.
Keep 20 FPS throughout routine sessions. For passive waiting,
`set_render_mode({on_demand:true})` skips common OpenGL draws between screenshots;
each screenshot turns drawing on for a complete following frame. Restore continuous
drawing before active gameplay. Use 5 FPS only when a task explicitly prioritizes
lower CPU over screenshot response time. See the
[measurements](skills/minecraft-headless/references/benchmarks.md#on-demand-draw-probe).

The cleanup timer checks every ten minutes and stops only agent-owned clients whose MCP
lease has been idle for two hours. Install it with:

```sh
mkdir -p ~/.config/systemd/user
cp deploy/minecraft-mcp-cleanup.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now minecraft-mcp-cleanup.timer
```

## Linux tools

`preflight` · `launch` · `stop` · `list` · `state` · `screenshot` · `key` · `hold_key` · `type` ·
`chat` · `look` · `click` · `mouse_move_to` · `scroll` · `add_server` · `open_uri` · `set_fps` ·
`set_render_mode` · `wait` · `log`

Most tools take an optional `instance`. Use a unique instance ID per task. `list` covers the
current MCP process; `skills/minecraft-headless/scripts/client_inventory.py` counts every
live agent client on the host.

For evidence or a vision subagent, `screenshot` accepts an absolute `save_path` on
the MCP host. Add `include_image: false` to return dimensions and the path without
sending the image to the caller. The default still returns the inline PNG; saving
creates missing parent directories and replaces the requested file.

```json
{"instance":"task-id","width":854,"save_path":"/tmp/task-evidence/frame.png","include_image":false}
```

When parent and subagent share the host filesystem, give the saved path to the
vision worker and keep the parent as the only input controller. Minecraft instances
belong to their MCP connection; a separate subagent connection cannot capture or
control the parent's instance. Use local OCR (optical character recognition) for
checked labels on known menus, and pixel vision for unfamiliar screens. See the
[screenshot benchmark](skills/minecraft-headless/references/benchmarks.md#screenshot-interpretation-and-subagent-handoff)
for measurements and limits.

`type` and `chat` use the bundled native XTest input helper on that instance's private Xvfb
display. The helper accepts printable ASCII. Screenshots and mouse input use the launcher
agent socket. See [the skill](skills/minecraft-headless/SKILL.md) for working navigation
patterns and [the Jev skill](skills/minecraft-jev/SKILL.md) for reviewed repeated routes.

`launch` returns as soon as the client socket is ready by default. Set
`wait_for_menu: true` when the next action needs the main menu; it checks the rendered
buttons rather than sleeping for a fixed startup period.

For a **new server on a new client**, pass `server_to_join: { name: "Example", address:
"example.org:19132" }` to `launch` at 854×480. The launcher delivers the add-server URI
while Minecraft starts; the MCP checks the exact saved entry and a ready screen, then
opens and confirms the external-server prompt. `launch` returns after Continue is
dismissed, while the world may still be loading. Verify the joined world or server
response. When the host and port are already saved, the same launch option sends the
connect URI during startup and keeps the existing saved name. For an already running
client, call `add_server` with `name`, `address`, and `join: true`; it avoids duplicate
saved entries. The regular `startup_uri` launch option passes a Minecraft URI without
assuming it succeeded; inspect its effect before acting.

## Verification

`bun test` runs platform-independent tests. `bun run scripts/smoke.ts` selects the
host's smoke test. On Windows it attaches to an existing game, captures it,
verifies exclusive control, and detaches without game input or closing it. The
Python validation and disposable-window input tests are documented in
[docs/windows.md](docs/windows.md).

`scripts/benchmark.ts` runs a single bounded client, records launch, screenshot, and stop
timings, and always stops the client on exit. It requires the same launcher environment
variables as the MCP. Use its output to compare changes to launch behavior; do not run
multiple benchmark clients when host resources are constrained.

`scripts/join_benchmark.ts` measures menu readiness, new-server save, external-server
confirmation, and a visible joined world against an owned test server. It saves frames,
stage times, and actual game-process cgroup limits under `/tmp`, then stops its client
and removes only its exact disposable server entry. See the [join benchmark notes](skills/minecraft-headless/references/benchmarks.md)
before interpreting a run; real server latency and world loading vary.
