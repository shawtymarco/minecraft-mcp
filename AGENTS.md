# Minecraft MCP — agent guidelines

## Windows backend

- `src/index.ts` dispatches to `src/windows/server.ts` on Windows and `src/linux.ts` otherwise.
- Windows uses the persistent `scripts/windows/agent.py` helper over stdin/stdout.
  Its commands are separate from the Linux launcher socket protocol below.
- Keep screenshots scoped to the selected game window and coordinates scoped to
  the latest client-area screenshot. Reject stale dimensions and background input.
- Preserve exclusive per-process ownership and key/button release on focus loss,
  disconnect, and bounded hold timeout. Never force kill a user's game.
- Run `bun run typecheck`, `bun test`, and Python validation tests. On Windows,
  run `scripts/windows/input_smoke.py` for the disposable fixture and
  `bun scripts/smoke.ts` against an existing game. Report which native game actions
  were actually observed; a successful SendInput call is not semantic proof.
- Publish fork work to `shawtymarco/minecraft-mcp`; the upstream push note below
  describes the original Linux maintainer's deployment, not this fork's target.

## Linux backend

Bun + TypeScript MCP server over the `--agent-socket` of the bedrock-mc mcpelauncher fork
(github.com/bedrock-mc/mcpelauncher-manifest, local clone ~/Coding/other/mcpelauncher-manifest). The socket
protocol is documented in README.md; the server side is `mcpelauncher-client/src/agent_server.cpp` in the fork.

- New socket commands go in both places in the same change: `agent_server.cpp` and a tool in `src/index.ts`.
- `bun run scripts/smoke.ts` is the end-to-end check; it needs the fork's client installed
  and a signed-in game data dir. Check rendered menu readiness rather than using a fixed
  startup delay; a local 854×480, 20 FPS run showed a usable menu at about eight seconds.
- Never add clicking/typing into the game on the model's behalf beyond what the tools already do explicitly;
  every action stays a tool call the caller chose.
- Keep the launch capacity check and stale-client cleanup working when changing lifecycle
  behavior. Do not kill other tasks' clients outside the precise idle lease policy.
- If use reveals slowness or an edge case, make a focused verified improvement here. Agents
  with push permission may push directly to `RestartFU/minecraft-mcp` `main` after
  fast-forwarding and integrating concurrent changes. The installed skill must point to
  this checkout so the local copy updates at the same time.
