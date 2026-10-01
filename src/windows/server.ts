import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, isAbsolute } from "node:path";
import { WindowsBridge } from "./bridge.ts";
import { WindowsController } from "./controller.ts";
import { externalServerUri } from "../add_server.ts";

const bridge = new WindowsBridge();
const controller = new WindowsController(bridge);
const server = new McpServer({ name: "minecraft-windows", version: "0.2.0" }, {
  instructions: "Controls native Minecraft for Windows. Start with list, then attach to an exact PID or launch. Screenshots contain only the game client area. Call focus before input; input fails if another app has focus. Screenshot pixel coordinates are mapped internally and expire on window resize. stop detaches by default; close_game:true requests normal game closure. Windows does not support hidden clients, isolated profiles, render/FPS control, or automatic server confirmation. Verify screenshots after actions; URI dispatch is not proof of a saved server or joined world.",
});
const instance = { instance: z.string().optional().describe("Attached instance ID; defaults to this connection's client") };
const id = z.string().regex(/^[a-zA-Z0-9_-]+$/).max(64).default("main");
const text = (value: unknown) => ({ content: [{ type: "text" as const, text: JSON.stringify(value) }] });
const unsupported = (name: string): never => { throw new Error(`${name} is unavailable on the native Windows backend; no game setting was changed`); };

server.tool("preflight", "Check Windows capture dependencies, available memory, and native Minecraft windows", {}, async () => text(await bridge.call("preflight")));
server.tool("list", "List registered Minecraft installations and running game windows with PID/HWND for attach", {}, async () => text({ ...(await bridge.call("list")), instance: controller.instance }));
server.tool("attach", "Attach exclusively to an existing Minecraft window without resizing, focusing, or closing it", {
  id, pid: z.number().int().positive().optional(), hwnd: z.number().int().positive().optional(),
}, async ({ id, pid, hwnd }) => text(await controller.attach(id, pid, hwnd)));
server.tool("launch", "Start installed Minecraft for Windows and attach. Refuses if a client is already running; use attach instead. Returns window readiness, not menu readiness", {
  id,
  app_id: z.string().min(1).optional().describe("Exact registered AUMID from list; omit only when one stable installation exists"),
  executable: z.string().min(1).optional().describe("Absolute Minecraft.Windows.exe path for a custom installation"),
  width: z.number().int().min(320).max(7680).optional(), height: z.number().int().min(180).max(4320).optional(),
}, async ({ id, ...args }) => text(await controller.launch(id, args)));
server.tool("stop", "Release inputs and detach. close_game:true additionally requests normal window closure; never force kills Minecraft", {
  ...instance, close_game: z.boolean().default(false),
}, async ({ instance, close_game }) => text(await controller.stop(instance, close_game)));
server.tool("state", "Window dimensions, focus, PID, capture capabilities, and held inputs; game FPS is unavailable", instance,
  async ({ instance }) => text(await controller.call("state", {}, instance)));
server.tool("focus", "Restore and bring the attached game to the foreground for subsequent input", instance,
  async ({ instance }) => text(await controller.call("focus", {}, instance)));
server.tool("resize", "Resize the game client area; take a new screenshot before coordinate input", {
  ...instance, width: z.number().int().min(320).max(7680), height: z.number().int().min(180).max(4320),
}, async ({ instance, ...args }) => text(await controller.call("resize", args, instance)));
server.tool("screenshot", "Capture the attached game client area with Windows Graphics Capture, including when occluded (not minimized)", {
  ...instance, width: z.number().int().min(64).max(7680).optional(),
  save_path: z.string().min(1).optional(), include_image: z.boolean().default(true),
}, async ({ instance, width, save_path, include_image }) => {
  if (save_path && !isAbsolute(save_path)) throw new Error("save_path must be an absolute path on the Windows MCP host");
  if (!include_image && !save_path) throw new Error("include_image:false requires save_path");
  const result = await controller.call("screenshot", { width }, instance);
  const { png_base64, ...metadata } = result;
  if (save_path) { await mkdir(dirname(save_path), { recursive: true }); await writeFile(save_path, Buffer.from(png_base64 as string, "base64")); }
  return { content: [
    ...(include_image ? [{ type: "image" as const, data: png_base64 as string, mimeType: "image/png" }] : []),
    { type: "text" as const, text: JSON.stringify({ ...metadata, save_path, coordinates: "pixels in this image; recapture after resizing" }) },
  ] };
});
const key = z.string().min(1).max(32);
const action = z.enum(["tap", "press", "release"]).default("tap");
const hold_ms = z.number().int().min(1).max(60_000).default(60);
server.tool("key", "Send a game key. Requires foreground focus; held inputs release on focus loss, detach, or after 60s", {
  ...instance, key, action, hold_ms, mods: z.array(z.enum(["shift", "ctrl", "alt"])).max(3).optional(),
}, async ({ instance, ...args }) => text(await controller.call("key", args, instance)));
server.tool("hold_key", "Hold a game key for a bounded duration while the game stays focused", {
  ...instance, key, ms: z.number().int().min(1).max(60_000),
}, async ({ instance, key, ms }) => text(await controller.call("key", { key, action: "tap", hold_ms: ms }, instance)));
server.tool("type", "Type literal Unicode text into the focused game field, without submitting or changing the clipboard", {
  ...instance, text: z.string().max(4096),
}, async ({ instance, text: value }) => text(await controller.call("text", { text: value }, instance)));
server.tool("chat", "Open game chat, type a message and press Enter; use only in a verified world", {
  ...instance, message: z.string().min(1).max(4096),
}, async ({ instance, message }) => text(await controller.call("chat", { text: message }, instance)));
server.tool("look", "Turn the camera with relative mouse movement while the game is focused", {
  ...instance, dx: z.number().int().min(-32767).max(32767), dy: z.number().int().min(-32767).max(32767),
}, async ({ instance, ...args }) => text(await controller.call("mouse_move", args, instance)));
server.tool("click", "Click in the last screenshot's pixels; omit coordinates for attack/use at the current game pointer", {
  ...instance, button: z.enum(["left", "right", "middle"]).default("left"), x: z.number().optional(), y: z.number().optional(), action, hold_ms,
}, async ({ instance, ...args }) => text(await controller.call("click", args, instance)));
server.tool("mouse_move_to", "Move to coordinates in the last screenshot; requires game focus", {
  ...instance, x: z.number(), y: z.number(),
}, async ({ instance, ...args }) => text(await controller.call("mouse_pos", args, instance)));
server.tool("scroll", "Scroll the game wheel in notches; positive is up", {
  ...instance, dy: z.number().min(-100).max(100),
}, async ({ instance, dy }) => text(await controller.call("scroll", { dy }, instance)));
server.tool("add_server", "Dispatch Minecraft's add-server URI. Inspect the resulting game screen to verify saving; no automatic join or confirmation", {
  ...instance, name: z.string(), address: z.string(), join: z.boolean().default(false),
}, async ({ instance, name, address, join }) => {
  controller.requireInstance(instance);
  if (join) throw new Error("Windows add_server cannot automatically confirm joining; verify saving, then call open_uri with a minecraft://connect URI");
  return text(await controller.call("uri", { uri: externalServerUri(name, address) }, instance));
});
server.tool("open_uri", "Dispatch a minecraft: URI through the attached installation's registered handler; verify its effect on a screenshot", {
  ...instance, uri: z.string().startsWith("minecraft:").max(2048),
}, async ({ instance, uri }) => text(await controller.call("uri", { uri }, instance)));
server.tool("set_fps", "Unavailable on native Windows; frame pacing requires the modified Linux launcher", {
  ...instance, cap: z.number().int().min(0),
}, async () => unsupported("set_fps"));
server.tool("set_render_mode", "Unavailable on native Windows; this backend cannot skip game draw calls", {
  ...instance, on_demand: z.boolean(),
}, async () => unsupported("set_render_mode"));
server.tool("wait", "Wait for a bounded game transition", { ms: z.number().int().min(1).max(60_000) }, async ({ ms }) => {
  await new Promise((resolve) => setTimeout(resolve, ms)); return text({ ok: true });
});
server.tool("log", "Return recent backend lifecycle diagnostics (not private game logs)", instance,
  async ({ instance }) => text(await controller.call("log", {}, instance)));

let closing: Promise<void> | undefined;
const close = () => closing ??= bridge.close().catch((error) => { console.error(String(error)); });
process.on("SIGINT", () => { void close().then(() => process.exit(0)); });
process.on("SIGTERM", () => { void close().then(() => process.exit(0)); });
const transport = new StdioServerTransport();
await server.connect(transport);
const previousClose = transport.onclose;
transport.onclose = () => { previousClose?.(); void close(); };
