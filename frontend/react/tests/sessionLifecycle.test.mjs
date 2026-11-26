import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";
import { fileURLToPath } from "node:url";

const bundle = await build({
  stdin: {
    contents: `
      export { SessionController } from './src/rewrite/features/sessions/SessionController';
      export { ReviewController } from './src/rewrite/features/review/ReviewController';
      export { useAppStore } from './src/rewrite/state/appStore';
    `,
    resolveDir: fileURLToPath(new URL("../", import.meta.url)),
  },
  bundle: true, platform: "node", format: "esm", write: false,
});
const { SessionController, ReviewController, useAppStore } = await import(
  `data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`
);
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const tick = () => new Promise((resolve) => setImmediate(resolve));
const json = (value) => new Response(JSON.stringify(value));
const message = (content, runId) => ({ role: "assistant", content, run_id: runId, metadata: { kind: "final_report" } });

function element() {
  return {
    innerHTML: "", dataset: {}, style: {}, disabled: false,
    classList: { add() {}, remove() {}, contains: () => false },
    appendChild() {}, querySelector: () => null,
  };
}

await test("session and run lifecycle ignores obsolete asynchronous work", async (t) => {
  const originals = Object.fromEntries(
    ["window", "document", "localStorage", "fetch", "requestAnimationFrame", "cancelAnimationFrame"].map((key) => [key, globalThis[key]])
  );
  let elements;
  const setup = () => {
    elements = new Map(["reportContainer", "messageContainer", "startReviewBtn"].map((id) => [id, element()]));
    globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
    globalThis.window = Object.assign(new EventTarget(), {
      marked: { parse: (text) => text }, setTimeout: () => 0, clearTimeout() {},
    });
    globalThis.document = {
      getElementById: (id) => elements.get(id) ?? null,
      querySelector: () => null, querySelectorAll: () => [], createElement: element,
    };
    globalThis.requestAnimationFrame = () => 1;
    globalThis.cancelAnimationFrame = () => {};
    useAppStore.setState({ projectRoot: "repo", sessionId: null, runId: null, runningSessionId: null, viewingHistory: false });
  };
  const historyFetch = async (url) => {
    const id = String(url).split("/")[4];
    if (url.includes("/messages")) return json({ items: [message(`report-${id}`, `run-${id}`)] });
    if (url.includes("/events")) return json({ items: [] });
    return json({ summary: { project_root: `repo-${id}` }, latest_run: { id: `run-${id}`, status: "completed" } });
  };
  const review = () => {
    const root = {
      querySelector: (selector) => elements.get(selector.slice(1)) ?? null,
      querySelectorAll: () => [],
    };
    return Object.assign(Object.create(ReviewController.prototype), {
      root, activeSessionId: "session", runSeq: 1, disposed: false,
      reportRenderFrame: null, reportFinalized: false, running: true,
      workflow: { finalize() {}, clearWaiting() {}, reset() {}, showWaiting() {} },
      linked: { refresh: async () => {} }, scanner: null, scannerSection: null,
      appendUsageTotal() {},
    });
  };

  try {
    for (const stage of ["detail", "messages", "events"]) {
      await t.test(`switching A to B discards A delayed ${stage}`, async () => {
        setup();
        const pending = deferred();
        globalThis.fetch = (url) => {
          const delayed = stage === "detail" ? url === "/api/v2/sessions/A" : url.includes(`/A/${stage}`);
          return delayed ? pending.promise : historyFetch(url);
        };
        const controller = new SessionController(null);
        const first = controller.loadSession("A");
        await tick();
        await controller.loadSession("B");
        pending.resolve(await historyFetch(stage === "detail" ? "/api/v2/sessions/A" : `/api/v2/sessions/A/${stage}`));
        await first;
        assert.equal(useAppStore.getState().sessionId, "B");
        assert.equal(useAppStore.getState().runId, "run-B");
        assert.equal(useAppStore.getState().projectRoot, "repo-B");
        assert.equal(elements.get("reportContainer").dataset.rawMarkdown, "report-B");
      });
    }

    await t.test("a late failure from A leaves B and its messages intact", async () => {
      setup();
      const pending = deferred();
      globalThis.fetch = (url) => url === "/api/v2/sessions/A" ? pending.promise : historyFetch(url);
      const controller = new SessionController(null);
      const first = controller.loadSession("A");
      await controller.loadSession("B");
      let notifications = 0;
      elements.get("messageContainer").appendChild = () => notifications++;
      pending.reject(new Error("obsolete failure"));
      await first;
      assert.equal(notifications, 0);
      assert.equal(elements.get("reportContainer").dataset.rawMarkdown, "report-B");
    });

    for (const action of ["dispose", "returnToNewWorkspace"]) {
      await t.test(`${action} invalidates a pending history load`, async () => {
        setup();
        const pending = deferred();
        globalThis.fetch = () => pending.promise;
        const controller = new SessionController(null);
        const loading = controller.loadSession("A");
        controller[action]();
        const report = elements.get("reportContainer");
        report.innerHTML = "current view";
        pending.resolve(await historyFetch("/api/v2/sessions/A"));
        await loading;
        assert.equal(report.innerHTML, "current view");
        assert.equal(useAppStore.getState().runId, null);
      });
    }

    await t.test("starting a new run in the same session invalidates a pending history load", async () => {
      setup();
      const pending = deferred();
      globalThis.fetch = () => pending.promise;
      const controller = new SessionController(null);
      const loading = controller.loadSession("A");
      useAppStore.setState({ runId: "new-run", runningSessionId: "A" });
      pending.resolve(await historyFetch("/api/v2/sessions/A"));
      await loading;
      assert.equal(useAppStore.getState().runId, "new-run");
      assert.equal(useAppStore.getState().projectRoot, "repo");
      assert.equal(elements.get("reportContainer").innerHTML, "");
    });

    for (const outcome of ["complete", "reject"]) {
      await t.test(`a superseded run's ${outcome} cannot overwrite or finish a new run`, async () => {
        setup();
        const pending = deferred();
        globalThis.fetch = () => pending.promise;
        useAppStore.setState({ sessionId: "session", runId: "old-run", runningSessionId: "session" });
        const controller = review();
        const terminal = controller.handleTerminal({ type: "review.completed" });
        controller.runSeq++;
        controller.reportFinalized = false;
        useAppStore.setState({ runId: "new-run" });
        elements.get("reportContainer").innerHTML = "new report";
        elements.get("startReviewBtn").disabled = true;
        if (outcome === "complete") pending.resolve(json({ items: [message("old report", "old-run")] }));
        else pending.reject(new Error("old run unavailable"));
        await terminal;
        assert.equal(elements.get("reportContainer").innerHTML, "new report");
        assert.equal(elements.get("startReviewBtn").disabled, true);
        assert.equal(controller.running, true);
        assert.equal(useAppStore.getState().runningSessionId, "session");
      });
    }

    for (const reason of ["disposed", "other session", "canceled"]) {
      await t.test(`terminal report is ignored after ${reason}`, async () => {
        setup();
        useAppStore.setState({ sessionId: "session", runId: "run", runningSessionId: "session" });
        const pending = deferred();
        globalThis.fetch = () => pending.promise;
        const controller = review();
        const terminal = controller.handleTerminal({ type: "review.completed" });
        if (reason === "disposed") controller.disposed = true;
        if (reason === "other session") useAppStore.setState({ sessionId: "other-session" });
        if (reason === "canceled") { controller.runSeq++; controller.running = false; }
        pending.resolve(json({ items: [message("obsolete report", "run")] }));
        await terminal;
        assert.equal(elements.get("reportContainer").innerHTML, "");
      });
    }

    await t.test("terminal report lookup uses its run id and completes the current run", async () => {
      setup();
      useAppStore.setState({ sessionId: "session", runId: "current-run", runningSessionId: "session" });
      globalThis.fetch = async () => json({ items: [message("current report", "current-run"), message("unrelated report", "other-run")] });
      const controller = review();
      await controller.handleTerminal({ type: "review.completed" });
      assert.equal(elements.get("reportContainer").dataset.rawMarkdown, "current report");
      assert.equal(controller.running, false);
      assert.equal(useAppStore.getState().runningSessionId, null);
    });

    await t.test("stream closure waits for the terminal report before releasing the start button", async () => {
      setup();
      useAppStore.setState({ sessionId: "session", enableStaticScan: false });
      useAppStore.getState().setAvailableGroups([{ provider: "test", label: "Test", is_active: true, models: [{ name: "test:model", label: "Model", available: true }] }]);
      const pending = deferred();
      const requested = deferred();
      globalThis.fetch = async (url) => {
        if (url === "/api/v2/reviews") return json({ run: { id: "current-run" } });
        if (url.endsWith("/stream")) {
          return new Response(`data: ${JSON.stringify({ type: "review.completed" })}\n\n`);
        }
        if (url.includes("/messages")) { requested.resolve(); return pending.promise; }
        throw new Error(`Unexpected URL: ${url}`);
      };
      const controller = review();
      const started = controller.startReview();
      await requested.promise;
      await tick();
      assert.equal(controller.running, true);
      assert.equal(useAppStore.getState().runningSessionId, "session");
      assert.equal(elements.get("startReviewBtn").disabled, true);
      pending.resolve(json({ items: [message("final report", "current-run")] }));
      await started;
      assert.equal(elements.get("reportContainer").dataset.rawMarkdown, "final report");
      assert.equal(controller.running, false);
      assert.equal(elements.get("startReviewBtn").disabled, false);
    });
  } finally {
    Object.assign(globalThis, originals);
  }
});
