import { expect, test } from "bun:test";
import { WindowsController } from "./controller.ts";
import type { Driver } from "./bridge.ts";

function fixture() {
  const calls: { cmd: string; args: unknown }[] = [];
  const driver: Driver = { async call(cmd, args) { calls.push({ cmd, args }); return { ok: true }; } };
  return { calls, driver, controller: new WindowsController(driver) };
}
test("input cannot accidentally target another MCP instance", async () => {
  const { controller, calls } = fixture();
  await expect(controller.call("key", { key: "w" })).rejects.toThrow("No Windows client");
  await controller.attach("first", 123);
  await expect(controller.call("key", { key: "w" }, "second")).rejects.toThrow("not attached");
  expect(calls.map((c) => c.cmd)).toEqual(["attach"]);
});
test("failed attach does not create an instance", async () => {
  const controller = new WindowsController({ async call() { throw new Error("ambiguous window"); } });
  await expect(controller.attach("test")).rejects.toThrow("ambiguous");
  expect(controller.instance).toBeUndefined();
});
test("a connection must detach before selecting a different game", async () => {
  const { controller, calls } = fixture();
  await controller.attach("first", 123);
  await expect(controller.attach("second", 456)).rejects.toThrow("Detach");
  await expect(controller.launch("second", {})).rejects.toThrow("already");
  expect(calls).toHaveLength(1);
});
test("stop detaches by default; normal game close requires explicit opt in", async () => {
  const { controller, calls } = fixture();
  await controller.attach("test", 123);
  await controller.stop();
  expect(calls.at(-1)).toEqual({ cmd: "detach", args: { close_game: false } });
  expect(controller.instance).toBeUndefined();
  await controller.attach("test", 123);
  await controller.stop("test", true);
  expect(calls.at(-1)).toEqual({ cmd: "detach", args: { close_game: true } });
});
test("failed detach preserves the instance for recovery", async () => {
  const { controller, driver } = fixture();
  await controller.attach("test", 123);
  driver.call = async () => { throw new Error("close failed"); };
  await expect(controller.stop()).rejects.toThrow("close failed");
  expect(controller.instance).toBe("test");
});
