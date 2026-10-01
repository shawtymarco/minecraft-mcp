#!/usr/bin/env bun
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { DEFAULT_DATA_DIR, Instance, installedVersions } from "./instance.ts";
import { DEFAULT_CPU_QUOTA_PERCENT, DEFAULT_MEMORY_LIMIT_MIB, preflight } from "./preflight.ts";
import { nativeInput } from "./native_input.ts";
import { addServer, externalServerUri, savedServerName, serverConnectUri, waitForStartupServer } from "./add_server.ts";
import { screenshot } from "./screenshot.ts";

const instances = new Map<string, Instance>();
let current: string | undefined;

function pick(id?: string): Instance {
  const key = id ?? current;
  const inst = key ? instances.get(key) : undefined;
  if (!inst || !inst.alive) throw new Error(key ? `instance ${key} is not running` : "no running instance; call launch first");
  inst.touch();
  return inst;
}

const text = (s: unknown) => ({ content: [{ type: "text" as const, text: typeof s === "string" ? s : JSON.stringify(s) }] });
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const instanceArg = { instance: z.string().optional().describe("Instance id; defaults to the most recently launched") };

const server = new McpServer({ name: "mcpelauncher-agent", version: "0.1.0" });

server.tool("preflight", "Check host CPU, RAM, and global Minecraft client capacity before launch", {
  cpu_quota_percent: z.number().int().min(50).max(400).default(DEFAULT_CPU_QUOTA_PERCENT),
  memory_limit_mib: z.number().int().min(1024).max(8192).default(DEFAULT_MEMORY_LIMIT_MIB),
}, async ({ cpu_quota_percent, memory_limit_mib }) => text(await preflight(memory_limit_mib, cpu_quota_percent)));

server.tool(
  "launch",
  "Start a real Minecraft Bedrock client, optionally adding and joining a server during startup",
  {
    id: z.string().default("main").describe("Instance id, unique per running client"),
    version: z.string().optional().describe("Installed game version; defaults to the newest"),
    data_dir: z.string().optional().describe("Separate data dir (own Xbox login, worlds, settings) for running several bots"),
    startup_uri: z.string().startsWith("minecraft://").max(2048).optional().describe("Minecraft URI dispatched during startup; verify its effect after launch"),
    server_to_join: z.object({ name: z.string(), address: z.string() }).optional().describe("Save a new server or connect to an existing one during startup, then confirm the prompt (854×480)"),
    width: z.number().int().min(320).default(854),
    height: z.number().int().min(180).default(480),
    fps_cap: z.number().int().min(0).default(20).describe("Render cap; 20 FPS limits CPU for routine work"),
    hidden: z.boolean().default(true).describe("Keep the window hidden (still renders for screenshots)"),
    cpu_quota_percent: z.number().int().min(50).max(400).default(DEFAULT_CPU_QUOTA_PERCENT).describe("Per-client CPU quota on Linux; 100 = one CPU core"),
    memory_limit_mib: z.number().int().min(1024).max(8192).default(DEFAULT_MEMORY_LIMIT_MIB).describe("Per-client memory limit on Linux, in MiB"),
    wait_for_menu: z.boolean().default(false).describe("Default false returns when the window exists. True waits for two visible main menu frames"),
  },
  async ({ id, version, data_dir, startup_uri, server_to_join, width, height, fps_cap, hidden, cpu_quota_percent, memory_limit_mib, wait_for_menu }) => {
    if (instances.get(id)?.alive) throw new Error(`instance ${id} already running`);
    if (server_to_join && startup_uri) throw new Error("use either server_to_join or startup_uri, not both");
    if (server_to_join && wait_for_menu) throw new Error("server_to_join handles its own screen readiness; leave wait_for_menu false");
    if (server_to_join && (width !== 854 || height !== 480)) throw new Error("server_to_join requires an 854×480 client");
    const savedBeforeLaunch = server_to_join ? await savedServerName(data_dir ?? DEFAULT_DATA_DIR, server_to_join.address) : undefined;
    const initialUri = server_to_join
      ? (savedBeforeLaunch === undefined
        ? externalServerUri(server_to_join.name, server_to_join.address)
        : serverConnectUri(server_to_join.address))
      : startup_uri;
    const check = await preflight(memory_limit_mib, cpu_quota_percent);
    if (!check.ok) throw new Error(`not enough capacity to launch: ${check.issues.join("; ")}`);
    const inst = await Instance.launch(id, { version, dataDir: data_dir, startupUri: initialUri, width, height, fpsCap: fps_cap, hidden,
      cpuQuotaPercent: cpu_quota_percent, memoryLimitMiB: memory_limit_mib });
    instances.set(id, inst);
    current = id;
    let serverJoin: Awaited<ReturnType<typeof addServer>> | undefined;
    try {
      if (server_to_join) {
        if (savedBeforeLaunch === undefined) await waitForStartupServer(inst, server_to_join.name, server_to_join.address);
        serverJoin = await addServer(inst, server_to_join.name, server_to_join.address, true, savedBeforeLaunch !== undefined);
      } else if (wait_for_menu) {
        await inst.waitForMenu();
      }
      const state = await inst.socket.call("state");
      return text({ instance: id, version: inst.version, pid: inst.gamePid, cpu_quota_percent, memory_limit_mib, ...state,
        ...(serverJoin ? { server_join: serverJoin } : {}) });
    } catch (error) {
      await inst.stop(5_000);
      instances.delete(id);
      current = [...instances.keys()].pop();
      throw error;
    }
  },
);

server.tool("stop", "Quit a running client (in-game quit, force-killed after 35s)", instanceArg, async ({ instance }) => {
  const inst = pick(instance);
  await inst.stop();
  instances.delete(inst.id);
  if (current === inst.id) current = [...instances.keys()].pop();
  return text({ stopped: inst.id });
});

server.tool("list", "List installed game versions and running instances", {}, async () =>
  text({
    versions: installedVersions(),
    instances: [...instances.values()].filter((i) => i.alive).map((i) => ({ id: i.id, version: i.version, pid: i.gamePid, data_dir: i.dataDir })),
    current,
  }),
);

server.tool("state", "Window size, focus, measured fps and cursor lock", instanceArg, async ({ instance }) => text(await pick(instance).socket.call("state")));

server.tool(
  "screenshot",
  "Capture the current frame as PNG, optionally saving it on the MCP host for evidence or subagent handoff",
  {
    ...instanceArg,
    width: z.number().int().min(64).optional().describe("Downscale to this width (aspect kept); default = window size"),
    save_path: z.string().min(1).optional().describe("Absolute PNG path on the MCP host; creates parent directories and replaces an existing file"),
    include_image: z.boolean().default(true).describe("False returns only dimensions and the saved path; requires save_path"),
  },
  async ({ instance, ...options }) => screenshot(pick(instance), options),
);

const keySchema = z.string().describe("Key name: a-z, 0-9, f1-f12, space, enter, escape, tab, shift, ctrl, alt, up/down/left/right, ...");

server.tool(
  "key",
  "Press a key (tap by default; use action press/release to hold across calls)",
  { ...instanceArg, key: keySchema, action: z.enum(["tap", "press", "release"]).default("tap"), hold_ms: z.number().int().min(1).default(60), mods: z.array(z.enum(["shift", "ctrl", "alt", "super"])).optional() },
  async ({ instance, ...args }) => text(await pick(instance).socket.call("key", args)),
);

server.tool(
  "hold_key",
  "Hold a key for a duration (walking: w/a/s/d, jump: space, sneak: shift, sprint: ctrl)",
  { ...instanceArg, key: keySchema, ms: z.number().int().min(1).max(60_000) },
  async ({ instance, key, ms }) => {
    const inst = pick(instance);
    await inst.socket.call("key", { key, action: "press" });
    await sleep(ms);
    await inst.socket.call("key", { key, action: "release" });
    return text({ ok: true, key, ms });
  },
);

server.tool("type", "Type text into the focused field with the client's private Xvfb keyboard", { ...instanceArg, text: z.string() }, async ({ instance, text: t }) => {
  const inst = pick(instance);
  return text(await nativeInput(inst.id, t));
});

server.tool("chat", "Open chat, type a message and send it", { ...instanceArg, message: z.string() }, async ({ instance, message }) => {
  const inst = pick(instance);
  await inst.socket.call("key", { key: "t" });
  await sleep(400);
  return text(await nativeInput(inst.id, message, ["Return"]));
});

server.tool("look", "Turn the camera by a relative mouse delta (pixels)", { ...instanceArg, dx: z.number(), dy: z.number() }, async ({ instance, dx, dy }) => text(await pick(instance).socket.call("mouse_move", { dx, dy })));

server.tool(
  "click",
  "Click at coordinates in the last screenshot's pixels (or at the last position). left = attack/break, right = use/place",
  { ...instanceArg, button: z.enum(["left", "right", "middle"]).default("left"), x: z.number().optional(), y: z.number().optional(), action: z.enum(["tap", "press", "release"]).default("tap"), hold_ms: z.number().int().min(1).default(60) },
  async ({ instance, x, y, ...args }) => {
    const inst = pick(instance);
    const scaled = x !== undefined && y !== undefined ? { x: x * inst.shotScale, y: y * inst.shotScale } : {};
    return text(await inst.socket.call("click", { ...args, ...scaled }));
  },
);

server.tool("mouse_move_to", "Move the cursor to coordinates in the last screenshot's pixels (menus; in-world use look)", { ...instanceArg, x: z.number(), y: z.number() }, async ({ instance, x, y }) => {
  const inst = pick(instance);
  return text(await inst.socket.call("mouse_pos", { x: x * inst.shotScale, y: y * inst.shotScale }));
});

server.tool("scroll", "Scroll the mouse wheel (hotbar / lists)", { ...instanceArg, dy: z.number() }, async ({ instance, dy }) => text(await pick(instance).socket.call("scroll", { dy })));

server.tool(
  "add_server",
  "Add an external server using Minecraft's URI or form fallback and verify it was saved (854×480 clients)",
  { ...instanceArg, name: z.string(), address: z.string().describe("host or host:port (default port 19132)"),
    join: z.boolean().default(false).describe("After saving, connect and confirm the external-server prompt; does not wait for the world") },
  async ({ instance, name, address, join }) => text(await addServer(pick(instance), name, address, join)),
);

server.tool(
  "open_uri",
  "Send a raw minecraft: URI to the game (deep links: servers, worlds, marketplace)",
  { ...instanceArg, uri: z.string().describe("Must start with minecraft:") },
  async ({ instance, uri }) => text(await pick(instance).socket.call("uri", { uri })),
);

server.tool("set_fps", "Change the render cap at runtime (0 = uncapped while focused)", { ...instanceArg, cap: z.number().int().min(0) }, async ({ instance, cap }) => text(await pick(instance).socket.call("fps", { cap })));

server.tool(
  "set_render_mode",
  "Skip OpenGL draws between screenshots while keeping the game loop running; each screenshot renders a fresh full frame",
  { ...instanceArg, on_demand: z.boolean().describe("True skips passive drawing; false renders every frame") },
  async ({ instance, on_demand }) => text(await pick(instance).socket.call("render", { on_demand })),
);

server.tool("wait", "Wait for the game to catch up", { ms: z.number().int().min(1).max(60_000) }, async ({ ms }) => {
  await sleep(ms);
  return text({ ok: true });
});

server.tool("log", "Recent client log lines", { ...instanceArg, lines: z.number().int().min(1).max(500).default(50) }, async ({ instance, lines }) => text(pick(instance).log.slice(-lines).join("\n")));

async function stopAll() {
  await Promise.all([...instances.values()].map((i) => i.stop(5_000)));
  process.exit(0);
}
process.on("SIGINT", stopAll);
process.on("SIGTERM", stopAll);

await server.connect(new StdioServerTransport());
