#!/usr/bin/env bun
// No game attachment, capture, input, or remote-model calls. Verifies MCP wiring.
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { resolve } from "node:path";

const client = new Client({ name: "minecraft-connection-probe", version: "1" });
try {
  await client.connect(new StdioClientTransport({ command: process.execPath, args: [resolve(process.argv[2] ?? "src/index.ts")] }));
  const tools = (await client.listTools()).tools.map((tool) => tool.name);
  for (const name of ["attach", "execute", "run_route", "screenshot", "stop"])
    if (!tools.includes(name)) throw new Error(`Missing Windows MCP tool: ${name}`);
  const result = await client.callTool({ name: "preflight", arguments: {} });
  if (result.isError) throw new Error("MCP preflight returned an error");
  const preflight = JSON.parse((result.content as { type: string; text: string }[]).find((c) => c.type === "text")!.text);
  if (!preflight.ready) throw new Error("Windows capture dependency is missing");
  console.log(JSON.stringify({ initialized: true, tool_count: tools.length, tools, ready: true, game_attached: false, captures: 0 }));
} finally { await client.close(); }
