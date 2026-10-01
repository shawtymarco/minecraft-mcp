import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";

export interface NativeResponse { ok: boolean; error?: string; [key: string]: unknown }
export interface Driver { call(cmd: string, args?: Record<string, unknown>): Promise<NativeResponse> }

// One persistent helper, with serialized requests. Its stdout is exclusively JSON.
export class WindowsBridge implements Driver {
  private proc: ChildProcessWithoutNullStreams;
  private nextId = 1;
  private pending = new Map<number, { resolve: (r: NativeResponse) => void; reject: (e: Error) => void; timer: ReturnType<typeof setTimeout> }>();
  private queue: Promise<unknown> = Promise.resolve();
  private stderr = "";
  private ended = false;

  constructor() {
    const helper = fileURLToPath(new URL("../../scripts/windows/agent.py", import.meta.url));
    const venv = fileURLToPath(new URL("../../.venv/Scripts/python.exe", import.meta.url));
    const configured = process.env.MINECRAFT_WINDOWS_PYTHON;
    const python = configured || (existsSync(venv) ? venv : "py");
    this.proc = spawn(python, [...(!configured && python === "py" ? ["-3"] : []), "-u", helper], {
      windowsHide: true, stdio: "pipe", env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    });
    this.proc.stderr.on("data", (chunk: Buffer) => { this.stderr = (this.stderr + chunk.toString()).slice(-4000); });
    createInterface({ input: this.proc.stdout }).on("line", (line) => {
      try {
        const response = JSON.parse(line) as NativeResponse & { id: number };
        const waiter = this.pending.get(response.id);
        if (!waiter) return;
        this.pending.delete(response.id);
        clearTimeout(waiter.timer);
        if (response.ok) waiter.resolve(response);
        else waiter.reject(new Error(response.error || "Windows helper failed"));
      } catch (error) { this.fail(new Error(`Invalid Windows helper response: ${error}`)); }
    });
    this.proc.on("error", (error) => this.fail(new Error(`Cannot start Windows helper: ${error.message}. Run scripts/windows/setup.ps1 or set MINECRAFT_WINDOWS_PYTHON.`)));
    this.proc.on("exit", (code) => this.fail(new Error(`Windows helper exited (${code}): ${this.stderr.trim()}`)));
    this.proc.stdin.on("error", (error) => this.fail(error));
  }

  call(cmd: string, args: Record<string, unknown> = {}): Promise<NativeResponse> {
    const run = this.queue.then(() => this.send(cmd, args));
    this.queue = run.catch(() => {});
    return run;
  }

  private send(cmd: string, args: Record<string, unknown>): Promise<NativeResponse> {
    if (this.ended) return Promise.reject(new Error("Windows helper is closed"));
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        // Do not continue issuing commands after an unknown input outcome.
        this.fail(new Error(`Windows ${cmd} timed out; reconnect before sending more input`));
        this.proc.stdin.end();
        const terminate = setTimeout(() => this.proc.kill(), 5_000);
        this.proc.once("exit", () => clearTimeout(terminate));
      }, 95_000);
      this.pending.set(id, { resolve, reject, timer });
      this.proc.stdin.write(JSON.stringify({ ...args, id, cmd }) + "\n");
    });
  }

  private fail(error: Error) {
    if (this.ended) return;
    this.ended = true;
    for (const waiter of this.pending.values()) { clearTimeout(waiter.timer); waiter.reject(error); }
    this.pending.clear();
    this.proc.stdin.end();
  }

  async close() {
    if (!this.ended) {
      try { await this.call("shutdown"); } finally { this.proc.stdin.end(); }
    }
  }
}
