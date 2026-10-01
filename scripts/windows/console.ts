#!/usr/bin/env bun
// Developer console: one {name,arguments} MCP call per stdin line.
// Image content is saved locally instead of printed as base64.
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { createInterface } from "node:readline";
import { resolve } from "node:path";
import { mkdir, writeFile } from "node:fs/promises";

const client = new Client({ name: "windows-dev-console", version: "1" });
const output = resolve(".artifacts/windows-console");
await mkdir(output, { recursive: true });
let shot = 0;
try {
  await client.connect(new StdioClientTransport({ command: process.execPath, args: [resolve("src/index.ts")] }));
  console.log(JSON.stringify({ ready: true }));
  for await (const line of createInterface({ input: process.stdin })) {
    try {
      const request = JSON.parse(line);
      if (request.name === "exit") break;
      const result = await client.callTool(request);
      for (const part of result.content as { type: string; data?: string; text?: string }[]) {
        if (part.type === "image") {
          const path = resolve(output, `frame-${++shot}.png`);
          await writeFile(path, Buffer.from(part.data!, "base64"));
          console.log(JSON.stringify({ image: path }));
        } else if (part.type === "text") console.log(JSON.stringify({ isError: !!result.isError, text: part.text }));
      }
    } catch (error) { console.log(JSON.stringify({ error: String(error) })); }
  }
} finally { await client.close(); }
