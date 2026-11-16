import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";
import { fileURLToPath } from "node:url";

const bundle = await build({
  stdin: {
    contents: `
      export { HistoryCache, fetchHistory } from './src/rewrite/features/sessions/historyCache';
      export { SessionController } from './src/rewrite/features/sessions/SessionController';
      export { useAppStore } from './src/rewrite/state/appStore';
    `,
    resolveDir: fileURLToPath(new URL("../", import.meta.url)),
  },
  bundle: true, platform: "node", format: "esm", write: false,
});
const { HistoryCache, fetchHistory, SessionController, useAppStore } = await import(
  `data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`
);
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const session = (name = "历史", id = "sess_test") => ({ session_id: id, name });
const tick = () => new Promise((resolve) => setImmediate(resolve));

await test("history cache concurrency and recovery", async (t) => {
  await t.test("preload/open/remount share a request and fresh result, including empty results", async () => {
    const request = deferred();
    let calls = 0;
    const cache = new HistoryCache(() => { calls++; return request.promise; });
    const preload = cache.load("A");
    assert.equal(cache.load("A"), preload);
    await tick();
    assert.equal(calls, 1);
    request.resolve([]);
    await preload;
    await cache.load("A");
    assert.equal(calls, 1);
    assert.deepEqual(cache.snapshot("A").sessions, []);
  });

  await t.test("stale refresh keeps data; failure is recoverable without erasing it", async () => {
    let now = 100;
    let response = Promise.resolve([session()]);
    const cache = new HistoryCache(() => response, () => now, 10);
    await cache.load("A");
    now += 11;
    const refresh = deferred();
    response = refresh.promise;
    const pending = cache.load("A");
    assert.equal(cache.snapshot("A").sessions[0].name, "历史");
    assert.ok(cache.snapshot("A").pending);
    refresh.reject(new Error("连接暂时中断"));
    await pending;
    assert.equal(cache.snapshot("A").error, "连接暂时中断");
    assert.equal(cache.snapshot("A").sessions[0].name, "历史");
    response = Promise.resolve([session("更新")]);
    await cache.load("A", true);
    assert.equal(cache.snapshot("A").error, null);
    assert.equal(cache.snapshot("A").sessions[0].name, "更新");
  });

  await t.test("initial failure releases the pending request so retry can succeed", async () => {
    let calls = 0;
    const cache = new HistoryCache(async () => {
      if (++calls === 1) throw new Error("HTTP 503");
      return [session()];
    });
    await cache.load(null);
    assert.equal(cache.snapshot(null).sessions, null);
    assert.equal(cache.snapshot(null).pending, null);
    await cache.load(null, true);
    assert.equal(calls, 2);
    assert.equal(cache.snapshot(null).sessions.length, 1);
  });

  await t.test("mutation during a list request discards its result and shares one follow-up", async () => {
    const requests = [deferred(), deferred()];
    let calls = 0;
    const cache = new HistoryCache(() => requests[calls++].promise);
    const pending = cache.load("A");
    await tick();
    cache.invalidate();
    assert.equal(cache.load("A"), pending);
    requests[0].resolve([session("删除前")]);
    await tick();
    assert.equal(cache.snapshot("A").sessions, null);
    assert.equal(calls, 2);
    requests[1].resolve([]);
    await pending;
    assert.deepEqual(cache.snapshot("A").sessions, []);
  });

  await t.test("rename/delete patch all project caches immediately and late responses cannot undo them", async () => {
    const old = deferred();
    let calls = 0;
    const cache = new HistoryCache(async () => {
      calls++;
      if (calls === 3) return old.promise;
      return [session(calls >= 4 ? "新名称" : "旧名称")];
    });
    await cache.load("A");
    await cache.load(null);
    const pending = cache.load("A", true);
    await tick();
    cache.invalidate((items) => items.map((item) => ({ ...item, name: "新名称" })));
    assert.equal(cache.snapshot("A").sessions[0].name, "新名称");
    assert.equal(cache.snapshot(null).sessions[0].name, "新名称");
    old.resolve([session("旧名称")]);
    await pending;
    assert.equal(cache.snapshot("A").sessions[0].name, "新名称");
    cache.invalidate((items) => items.filter((item) => item.session_id !== "sess_test"));
    assert.deepEqual(cache.snapshot("A").sessions, []);
    assert.deepEqual(cache.snapshot(null).sessions, []);
  });

  await t.test("project responses remain isolated even when they finish in reverse order", async () => {
    const a = deferred(), b = deferred();
    const cache = new HistoryCache((root) => root === "A" ? a.promise : b.promise);
    const first = cache.load("A"), second = cache.load("B");
    b.resolve([session("B")]);
    await second;
    a.resolve([session("A")]);
    await first;
    assert.equal(cache.snapshot("A").sessions[0].name, "A");
    assert.equal(cache.snapshot("B").sessions[0].name, "B");
  });
});

await test("history controller DOM lifecycle", async (t) => {
  const originals = { window: globalThis.window, document: globalThis.document, fetch: globalThis.fetch };
  const events = new EventTarget();
  globalThis.window = Object.assign(events, { setInterval, clearInterval });
  globalThis.document = { getElementById: () => null };
  const list = () => Object.assign(new EventTarget(), {
    innerHTML: "", attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
  });
  try {
    await t.test("hung backend GET is aborted and releases the request for retry", async () => {
      let signal;
      globalThis.fetch = (_url, init) => new Promise((_resolve, reject) => {
        signal = init.signal;
        signal.addEventListener("abort", () => reject(new Error("aborted")));
      });
      await assert.rejects(fetchHistory("timeout-project", 5), /加载超时/);
      assert.equal(signal.aborted, true);
      globalThis.fetch = async () => ({ ok: true, json: async () => ({ items: [] }) });
      assert.deepEqual(await fetchHistory("timeout-project", 100), []);
    });

    await t.test("project switch never renders an obsolete result or error", async () => {
      const a = deferred(), b = deferred();
      globalThis.fetch = (url) => url.includes("project-a") ? a.promise : b.promise;
      useAppStore.setState({ projectRoot: "project-a" });
      const element = list();
      const controller = new SessionController(element);
      controller.init();
      await tick();
      useAppStore.setState({ projectRoot: "project-b" });
      await tick();
      b.resolve({ ok: true, json: async () => ({ items: [{ id: "b", name: "项目 B" }] }) });
      await tick();
      assert.match(element.innerHTML, /项目 B/);
      a.reject(new Error("旧项目错误"));
      await tick();
      assert.match(element.innerHTML, /项目 B/);
      assert.doesNotMatch(element.innerHTML, /旧项目错误/);
      controller.dispose();
    });

    await t.test("dispose removes delegated clicks and prevents late request errors from mutating DOM", async () => {
      const response = deferred();
      globalThis.fetch = () => response.promise;
      useAppStore.setState({ projectRoot: "dispose-project" });
      const element = list();
      const controller = new SessionController(element);
      controller.init();
      await tick();
      controller.dispose();
      element.innerHTML = "新组件内容";
      response.reject(new Error("disposed error"));
      await tick();
      assert.equal(element.innerHTML, "新组件内容");
      let clicked = false;
      controller.loadSessions = () => { clicked = true; };
      const click = new Event("click");
      Object.defineProperty(click, "target", { value: { closest: () => true } });
      element.dispatchEvent(click);
      assert.equal(clicked, false);
    });

    await t.test("initial failure exposes a functional retry action and escapes diagnostics", async () => {
      let calls = 0;
      globalThis.fetch = async () => {
        if (++calls === 1) throw new Error('<img src=x onerror="bad()">');
        return { ok: true, json: async () => ({ items: [{ id: "retry", name: "恢复成功" }] }) };
      };
      useAppStore.setState({ projectRoot: "retry-project" });
      const element = list();
      const controller = new SessionController(element);
      controller.init();
      await tick();
      assert.match(element.innerHTML, /data-action="retry-sessions"/);
      assert.doesNotMatch(element.innerHTML, /<img/);
      const click = new Event("click");
      Object.defineProperty(click, "target", { value: { closest: (selector) => selector.includes("retry-sessions") } });
      element.dispatchEvent(click);
      await tick();
      assert.equal(calls, 2);
      assert.match(element.innerHTML, /恢复成功/);
      controller.dispose();
    });
  } finally {
    Object.assign(globalThis, originals);
  }
});
