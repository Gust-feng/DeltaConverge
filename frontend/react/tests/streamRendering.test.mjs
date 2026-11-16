import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const bundle = await build({
  stdin: {
    contents: `
      export { ReviewController } from './src/rewrite/features/review/ReviewController';
      export { setProgressStep } from './src/rewrite/features/review/progress';
      export { useAppStore } from './src/rewrite/state/appStore';
    `,
    resolveDir: projectRoot,
  },
  bundle: true,
  platform: "node",
  format: "esm",
  write: false,
});
const { ReviewController, setProgressStep, useAppStore } = await import(
  `data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`
);

await test("report rendering batches bursts and rejects obsolete callbacks", async (t) => {
  const originalWindow = globalThis.window;
  const originalRequest = globalThis.requestAnimationFrame;
  const originalCancel = globalThis.cancelAnimationFrame;
  let frames;
  let nextId = 0;
  let parses;
  globalThis.requestAnimationFrame = (callback) => {
    frames.set(++nextId, callback);
    return nextId;
  };
  globalThis.cancelAnimationFrame = (id) => frames.delete(id);
  globalThis.window = {
    marked: { parse(text) { parses.push(text); return `<p>${text}</p>`; } },
    setTimeout() {},
  };

  const setup = () => {
    frames = new Map();
    parses = [];
    const container = {
      dataset: { reportPlaceholder: "hero" },
      innerHTML: "",
      scrollTop: 0,
      scrollHeight: 100,
      scrollTo({ top }) { this.scrollTop = top; },
    };
    const controller = Object.assign(Object.create(ReviewController.prototype), {
      root: { querySelector: () => container },
      finalReportContent: "",
      pendingChunkContent: "",
      reportRenderFrame: null,
      reportFinalized: false,
      disposed: false,
      activeSessionId: null,
      runSeq: 1,
    });
    return { controller, container };
  };
  const frame = () => {
    const callbacks = [...frames.values()];
    frames.clear();
    for (const callback of callbacks) callback();
  };

  try {
    await t.test("200 chunks in a frame produce one parse with every character", () => {
      const { controller, container } = setup();
      for (let i = 0; i < 200; i++) {
        controller.pendingChunkContent += `片段${i} `;
        controller.scheduleReportRender();
      }
      assert.equal(frames.size, 1);
      assert.deepEqual(parses, []);
      frame();
      assert.deepEqual(parses, [controller.pendingChunkContent]);
      assert.equal(container.dataset.rawMarkdown, controller.pendingChunkContent);
      assert.equal(container.dataset.reportPlaceholder, undefined);
      controller.pendingChunkContent += "下一帧";
      controller.scheduleReportRender();
      frame();
      assert.equal(parses.length, 2);
      assert.equal(container.dataset.rawMarkdown, controller.pendingChunkContent);
    });

    await t.test("final report cancels streaming work and stays at the top", () => {
      const { controller, container } = setup();
      controller.pendingChunkContent = "草稿";
      controller.scheduleReportRender();
      controller.reportFinalized = true;
      controller.renderFinalReport("最终报告");
      frame();
      assert.deepEqual(parses, ["最终报告"]);
      assert.equal(container.dataset.rawMarkdown, "最终报告");
      assert.equal(container.scrollTop, 0);
      controller.scheduleReportRender();
      assert.equal(frames.size, 0);
    });

    for (const reason of ["disposed", "new run", "other session"]) {
      await t.test(`pending render is ignored after ${reason}`, () => {
        const { controller, container } = setup();
        controller.pendingChunkContent = "旧报告";
        controller.scheduleReportRender();
        if (reason === "disposed") controller.disposed = true;
        if (reason === "new run") controller.runSeq++;
        if (reason === "other session") {
          controller.activeSessionId = "old-session";
          useAppStore.getState().setSessionId("new-session");
        }
        frame();
        assert.deepEqual(parses, []);
        assert.equal(container.innerHTML, "");
      });
    }

    await t.test("canceling a pending render allows the next run to schedule", () => {
      const { controller, container } = setup();
      controller.pendingChunkContent = "旧";
      controller.scheduleReportRender();
      controller.cancelReportRender();
      assert.equal(frames.size, 0);
      controller.runSeq++;
      controller.pendingChunkContent = "新";
      controller.scheduleReportRender();
      frame();
      assert.equal(container.dataset.rawMarkdown, "新");
    });
  } finally {
    globalThis.window = originalWindow;
    globalThis.requestAnimationFrame = originalRequest;
    globalThis.cancelAnimationFrame = originalCancel;
  }
});

test("repeated progress events preserve the active class without restarting it", () => {
  const classes = new Set(["step-item", "active"]);
  let mutations = 0;
  const element = {
    classList: {
      contains: (name) => classes.has(name),
      remove(...names) { mutations++; names.forEach((name) => classes.delete(name)); },
      add(name) { mutations++; classes.add(name); },
    },
  };
  const root = { querySelector: () => element };
  for (let i = 0; i < 200; i++) setProgressStep(root, "reviewing", "active");
  assert.equal(mutations, 0);
  setProgressStep(root, "reviewing", "completed");
  assert.equal(classes.has("completed"), true);
  assert.equal(classes.has("active"), false);
});
