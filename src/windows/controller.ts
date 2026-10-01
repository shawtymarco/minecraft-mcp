import type { Driver } from "./bridge.ts";

export class WindowsController {
  instance?: string;
  constructor(readonly driver: Driver) {}

  requireInstance(instance?: string) {
    if (!this.instance) throw new Error("No Windows client attached; call list then attach, or launch first");
    if (instance && instance !== this.instance) throw new Error(`Instance ${instance} is not attached to this MCP connection`);
  }

  async attach(id: string, pid?: number, hwnd?: number) {
    if (this.instance) throw new Error("Detach the current client with stop before attaching another");
    const result = await this.driver.call("attach", { pid, hwnd });
    this.instance = id;
    return { ...result, instance: id };
  }

  async launch(id: string, args: Record<string, unknown>) {
    if (this.instance) throw new Error("This MCP connection already has an attached client");
    const result = await this.driver.call("launch", args);
    this.instance = id;
    return { ...result, instance: id };
  }

  async call(cmd: string, args: Record<string, unknown> = {}, instance?: string) {
    this.requireInstance(instance);
    return this.driver.call(cmd, args);
  }

  async stop(instance?: string, closeGame = false) {
    this.requireInstance(instance);
    const result = await this.driver.call("detach", { close_game: closeGame });
    this.instance = undefined;
    return result;
  }
}
