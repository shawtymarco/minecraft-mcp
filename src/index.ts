#!/usr/bin/env bun
// Windows drives the installed native client. Linux retains the launcher socket backend.
if (process.platform === "win32") {
  await import("./windows/server.ts");
} else {
  await import("./linux.ts");
}
export {};
