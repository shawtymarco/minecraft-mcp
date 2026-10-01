if (process.platform === "win32") {
  await import("./windows/smoke.ts");
} else {
  await import("./linux_smoke.ts");
}
export {};
