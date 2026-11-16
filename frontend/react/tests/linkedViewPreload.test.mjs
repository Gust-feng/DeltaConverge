import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";
import { fileURLToPath } from "node:url";

const bundle = await build({
  stdin: {
    contents: `
      export { LinkedView } from './src/rewrite/features/review/linkedView';
      export { useAppStore } from './src/rewrite/state/appStore';
    `,
    resolveDir: fileURLToPath(new URL("../", import.meta.url)),
  },
  bundle: true, platform: "node", format: "esm", write: false,
});
const { LinkedView, useAppStore } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`);

class Element {
  innerHTML = "";
  style = {};
  dataset = {};
  children = [];
  classList = { add() {}, remove() {}, toggle() {} };
  addEventListener() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  appendChild(child) { this.children.push(child); }
}

function setup() {
  useAppStore.setState({ projectRoot: "repo-A", sessionId: null, runId: null, diffMode: "auto", commitFrom: null, commitTo: "HEAD", reportViewMode: "report" });
  const elements = new Map(["#reportDiffFileList", "#reportDiffContent", "#reportContainer", "#diffViewContainer"].map((id) => [id, new Element()]));
  const root = new Element();
  root.querySelector = (id) => elements.get(id) ?? null;
  return { view: new LinkedView(root), list: elements.get("#reportDiffFileList") };
}
const response = (data) => new Response(JSON.stringify(data), { status: 200 });
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };

await test("report details preload, share requests and isolate contexts", async (t) => {
  const originals = { fetch: globalThis.fetch, window: globalThis.window, document: globalThis.document };
  globalThis.window = { setTimeout: () => 0 };
  globalThis.document = { createElement: () => new Element() };
  try {
    await t.test("opening a preloaded details tab makes no request or loading flash", async () => {
      const calls = [];
      globalThis.fetch = async (url) => { calls.push(url); return response({ files: [{ path: "ready.ts" }], detected_mode: "staged" }); };
      const { view, list } = setup();
      await view.loadReportDiffFiles();
      const file = list.children.at(-1);
      assert.equal(file.dataset.path, "ready.ts");
      list.innerHTML = "ready list";
      view.switchReportView("diff");
      await view.loadReportDiffFiles();
      assert.equal(calls.length, 1);
      assert.equal(list.innerHTML, "ready list");
      assert.match(calls[0], /mode=auto/);
      view.dispose();
    });

    await t.test("an open during preloading reuses the pending request", async () => {
      const pending = deferred();
      let calls = 0;
      globalThis.fetch = () => { calls++; return pending.promise; };
      const { view } = setup();
      const preload = view.loadReportDiffFiles();
      assert.equal(view.loadReportDiffFiles(), preload);
      view.switchReportView("diff");
      assert.equal(calls, 1);
      pending.resolve(response({ files: [] }));
      await preload;
      view.dispose();
    });

    await t.test("a slow previous project cannot overwrite the current project", async () => {
      const pending = deferred();
      globalThis.fetch = (url) => String(url).includes("repo-A") ? pending.promise : Promise.resolve(response({ files: [{ path: "B.ts" }] }));
      const { view, list } = setup();
      const previous = view.loadReportDiffFiles();
      useAppStore.setState({ projectRoot: "repo-B" });
      await view.loadReportDiffFiles();
      pending.resolve(response({ files: [{ path: "A.ts" }] }));
      await previous;
      assert.equal(list.children.at(-1).dataset.path, "B.ts");
      view.dispose();
    });

    await t.test("snapshot preloading skips messages, events and the live working tree", async () => {
      const calls = [];
      globalThis.fetch = async (url) => {
        calls.push(url);
        if (url === "/api/v2/sessions/saved") return response({ summary: { project_root: "snapshot-repo" }, latest_run: { id: "run-1" } });
        if (url.endsWith("/diff")) return response({ diff_files: [{ path: "snapshot.ts" }], diff_units: [] });
        if (url === "/api/v2/scans/run-1") return response({ linked: {} });
        throw new Error(`unexpected request: ${url}`);
      };
      const { view, list } = setup();
      useAppStore.setState({ sessionId: "saved", runId: "run-1" });
      await view.loadReportDiffFiles();
      view.switchReportView("diff");
      assert.equal(calls.length, 3);
      assert.equal(list.children.at(-1).dataset.path, "snapshot.ts");
      view.dispose();
    });

    await t.test("failed initial loads can retry, failed refreshes preserve loaded content", async () => {
      let calls = 0;
      globalThis.fetch = async () => { calls++; throw new Error("offline"); };
      const { view, list } = setup();
      await view.loadReportDiffFiles();
      assert.match(list.innerHTML, /加载失败/);
      assert.match(list.innerHTML, /重试/);
      globalThis.fetch = async () => { calls++; return response({ files: [] }); };
      await view.loadReportDiffFiles();
      assert.match(list.innerHTML, /无文件变更/);
      const loaded = list.innerHTML;
      globalThis.fetch = async () => { throw new Error("offline"); };
      await view.refresh();
      assert.equal(list.innerHTML, loaded);
      assert.equal(calls, 2);
      view.dispose();
    });

    await t.test("an empty run snapshot stays empty instead of showing unrelated working changes", async () => {
      const calls = [];
      globalThis.fetch = async (url) => {
        calls.push(url);
        if (url === "/api/v2/sessions/empty") return response({ summary: {}, latest_run: { id: "empty-run" } });
        return response({});
      };
      const { view, list } = setup();
      useAppStore.setState({ sessionId: "empty", runId: "empty-run" });
      await view.loadReportDiffFiles();
      assert.match(list.innerHTML, /无文件变更/);
      assert.equal(calls.length, 3);
      view.dispose();
    });

    await t.test("a hung backend times out and the next open can retry", async (t) => {
      t.mock.timers.enable({ apis: ["setTimeout"] });
      globalThis.fetch = (_url, { signal }) => new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
      });
      const { view, list } = setup();
      const load = view.loadReportDiffFiles();
      t.mock.timers.tick(15_000);
      await load;
      assert.match(list.innerHTML, /请求超时/);
      globalThis.fetch = async () => response({ files: [] });
      await view.loadReportDiffFiles();
      assert.match(list.innerHTML, /无文件变更/);
      view.dispose();
      t.mock.timers.reset();
    });

    await t.test("disposing the controller prevents late responses from changing the view", async () => {
      const pending = deferred();
      globalThis.fetch = () => pending.promise;
      const { view, list } = setup();
      const load = view.loadReportDiffFiles();
      view.dispose();
      list.innerHTML = "disposed";
      pending.resolve(response({ files: [{ path: "late.ts" }] }));
      await load;
      assert.equal(list.innerHTML, "disposed");
    });
  } finally {
    Object.assign(globalThis, originals);
  }
});
