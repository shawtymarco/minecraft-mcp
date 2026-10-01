#!/usr/bin/env bun
// Read-only game smoke: attach, capture, check exclusive ownership, detach.
// Never changes focus, sends game input, launches a game, or closes Minecraft.
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { PNG } from "pngjs";

if (process.platform !== "win32") throw new Error("Windows smoke requires a Windows host");
const output = resolve(process.argv[2] ?? ".artifacts/windows-smoke");
await mkdir(output, { recursive: true });
const client = new Client({ name: "windows-smoke", version: "1" });
const transport = new StdioClientTransport({ command: process.execPath, args: [resolve("src/index.ts")] });
const observations: unknown[] = [];
async function call(name: string, args: Record<string, unknown> = {}) {
  const started = performance.now();
  const result = await client.callTool({ name, arguments: args });
  if (result.isError) throw new Error(JSON.stringify(result.content));
  const value = JSON.parse((result.content as { type: string; text: string }[]).find((c) => c.type === "text")!.text);
  observations.push({ tool: name, elapsed_ms: Math.round(performance.now() - started), ...value });
  return value;
}
try {
  await client.connect(transport);
  const tools = await client.listTools();
  if (!tools.tools.some((t) => t.name === "attach")) throw new Error("Windows tools not selected");
  const preflight = await call("preflight");
  if (!preflight.ready) throw new Error(JSON.stringify(preflight));
  const listed = await call("list");
  const pid = Number(process.env.MINECRAFT_SMOKE_PID ?? listed.windows[0]?.pid);
  if (!pid) throw new Error("Start Minecraft first, then rerun the read-only smoke");
  await call("attach", { pid, id: "smoke" });
  await call("state");
  for (const width of [854, 426, 854]) {
    const path = resolve(output, `capture-${width}-${observations.length}.png`);
    const shot = await call("screenshot", { width, save_path: path, include_image: false });
    const png = PNG.sync.read(Buffer.from(await Bun.file(path).arrayBuffer()));
    if (png.width !== shot.width || png.height !== shot.height || png.data.every((v, i) => i % 4 === 3 || v === 0)) throw new Error("Invalid or black game capture");
  }
  const second = new Client({ name: "windows-lock-probe", version: "1" });
  try {
    await second.connect(new StdioClientTransport({ command: process.execPath, args: [resolve("src/index.ts")] }));
    const result = await second.callTool({ name: "attach", arguments: { pid } });
    if (!result.isError || !JSON.stringify(result.content).includes("already attached")) throw new Error("Exclusive control lock did not reject second connection");
    observations.push({ exclusive_control_lock: "passed" });
  } finally { await second.close(); }
  const unsupported = await client.callTool({ name: "set_fps", arguments: { cap: 20 } });
  if (!unsupported.isError) throw new Error("Unsupported FPS control reported success");
  await call("stop");
  const after = await call("list");
  if (!after.windows.some((w: { pid: number }) => w.pid === pid)) throw new Error("Detach unexpectedly closed the game");
  await writeFile(resolve(output, "report.json"), JSON.stringify(observations, null, 2));
  console.log(JSON.stringify({ status: "passed", output, observations }));
} finally { await client.close(); }
