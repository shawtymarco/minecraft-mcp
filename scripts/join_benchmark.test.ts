import { expect, test } from "bun:test";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expandAddServerTimings, parseOptions, withoutDisposableServer } from "./join_benchmark.ts";

test("combined mode names the verified Save, URI, and Continue route", () => {
  const args = ["--target", "127.0.0.1:19357", "--output", join(tmpdir(), "minecraft-join-test"), "--mode", "combined"];
  expect(parseOptions(args).mode).toBe("combined");
  expect(parseOptions(args).cpuQuotaPercent).toBe(250);
  expect(parseOptions(args).fpsCap).toBe(20);
  expect(parseOptions([...args, "--fps-cap", "30"]).fpsCap).toBe(30);
  expect(parseOptions([...args.slice(0, -1), "uri-only"]).mode).toBe("uri-only");
  expect(parseOptions([...args.slice(0, -1), "startup-uri"]).mode).toBe("startup-uri");
  expect(parseOptions([...args.slice(0, -1), "launch-join"]).mode).toBe("launch-join");
  expect(() => parseOptions([...args.slice(0, -1), "add-and-play"])).toThrow("--mode must be saved, combined, direct-uri, uri-only, startup-uri, or launch-join");
  expect(parseOptions([...args, "--expected-method", "deep_link"]).expectedMethod).toBe("deep_link");
});

test("add_server cumulative offsets become ordered wall-clock stages", () => {
  const rows = expandAddServerTimings({ add_uri_sent: 5, servers_tab_ready: 205,
    entry_verified: 505, continue_clicked: 1205, total_ms: 1206 }, 8000, Date.UTC(2026, 8, 26, 12));
  expect(rows.map((row) => [row.stage, row.elapsed_ms, row.delta_ms])).toEqual([
    ["add_uri_sent", 8005, 5], ["servers_tab_ready", 8205, 200],
    ["entry_verified", 8505, 300], ["continue_clicked", 9205, 700],
    ["add_server_complete", 9206, 1],
  ]);
  expect(rows[1].at_utc).toBe("2026-09-26T12:00:00.205Z");
  expect(() => expandAddServerTimings({ form_ready: 100, add_uri_sent: 50, total_ms: 110 }, 0, 0)).toThrow("out-of-order");
});

test("disposable server cleanup preserves unrelated entries and line endings", () => {
  const original = "1:Other:127.0.0.1:19153:1\r\n2:Bench123:127.0.0.1:19153:2\r\n3:Bench123:example.test:19153:3\r\n";
  expect(withoutDisposableServer(original, "Bench123", "127.0.0.1", 19153)).toEqual({
    content: "1:Other:127.0.0.1:19153:1\r\n3:Bench123:example.test:19153:3\r\n",
    removed: 1,
  });
});

test("disposable server cleanup refuses ambiguous matches", () => {
  const original = "1:Bench123:127.0.0.1:19153:1\n2:Bench123:127.0.0.1:19153:2\n";
  expect(() => withoutDisposableServer(original, "Bench123", "127.0.0.1", 19153)).toThrow("Refusing to remove 2");
});
