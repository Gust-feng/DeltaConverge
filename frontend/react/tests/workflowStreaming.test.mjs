import assert from "node:assert/strict";
import { test } from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const bundle = await build({
  entryPoints: [fileURLToPath(new URL("../src/rewrite/features/review/workflowLive.ts", import.meta.url))],
  bundle: true, platform: "node", format: "cjs", write: false,
});

class TextNode {
  nodeType = 3;
  constructor(data) { this.data = data; }
  appendData(text) { this.data += text; }
  get textContent() { return this.data; }
}

// Model only the DOM operations used by streaming; count layout reads explicitly.
class Element {
  children = []; dataset = {}; style = {}; listeners = {}; className = "";
  isConnected = true; reads = 0; top = 0;
  classList = { contains: () => false, add() {} };
  appendChild(child) { this.children.push(child); return child; }
  get lastChild() { return this.children.at(-1); }
  get textContent() { return this.children.map((child) => child.textContent).join(""); }
  set textContent(text) { this.children = [new TextNode(text)]; }
  set innerHTML(html) { this.html = html; this.children = []; }
  get innerHTML() { return this.html || ""; }
  setAttribute() {}
  addEventListener(type, handler) { this.listeners[type] = handler; }
  removeEventListener() {}
  querySelector(selector) {
    for (const child of this.children) {
      if (child.className?.split(" ").includes(selector.slice(1))) return child;
      const found = child.querySelector?.(selector);
      if (found) return found;
    }
    return null;
  }
  querySelectorAll() { return []; }
  get scrollTop() { this.reads++; return this.top; }
  set scrollTop(value) { this.top = value; }
  get scrollHeight() { this.reads++; return 500; }
  get clientHeight() { this.reads++; return 100; }
}

function fixture() {
  const frames = new Map(), timers = new Map();
  let nextId = 0;
  const schedule = (tasks) => (callback) => { const id = nextId++; tasks.set(id, callback); return id; };
  const module = { exports: {} };
  vm.runInNewContext(bundle.outputFiles[0].text, {
    module, Node: { TEXT_NODE: 3 },
    document: { createElement: () => new Element(), createTextNode: (text) => new TextNode(text) },
    requestAnimationFrame: schedule(frames), cancelAnimationFrame: (id) => frames.delete(id),
    window: {
      setTimeout: schedule(timers), clearTimeout: (id) => timers.delete(id),
      setInterval: schedule(timers), clearInterval: (id) => timers.delete(id),
      marked: { parse: (text) => `<p>${text}</p>` },
    },
  });
  const entries = new Element(), area = new Element(), root = new Element();
  root.querySelector = (selector) => selector === "#workflowEntries" ? entries : area;
  const renderer = new module.exports.LiveWorkflowRenderer(root, {
    onReviewChunk() {}, consumePendingReviewChunk: () => "",
  });
  // Supply existing stage/thought/chunk nodes without parsing unrelated header HTML.
  renderer.ensureStage = () => entries;
  const text = new Element(), body = new Element(), thought = new Element();
  text.className = "thought-text"; body.className = "thought-body";
  thought.appendChild(text); thought.appendChild(body);
  renderer.currentThoughtEl = thought;
  const appendThought = (content) => renderer.append({ type: "thought", stage: "intent", content });
  const chunk = new Element();
  chunk.dataset.stage = "planner";
  renderer.currentChunkEl = chunk;
  const appendChunk = (content) => renderer.append({ type: "chunk", stage: chunk.dataset.stage, content });
  const drain = (tasks) => {
    const callbacks = [...tasks.values()];
    tasks.clear();
    callbacks.forEach((callback) => callback());
  };
  return { renderer, text, body, area, entries, chunk, frames, timers, appendThought, appendChunk,
    tick: () => drain(frames), runTimers: () => drain(timers) };
}

test("reasoning bursts preserve whitespace and update/scroll once per frame", () => {
  const f = fixture();
  const deltas = [" lead", " ", "\n", ...Array.from({ length: 100 }, (_, index) => ` ${index}\n`)];
  deltas.forEach(f.appendThought);
  assert.equal(f.frames.size, 1);
  assert.equal(f.text.textContent, "");
  assert.equal(f.area.reads + f.entries.reads + f.body.reads, 0);
  f.tick();
  assert.equal(f.text.textContent, deltas.join(""));
  for (const target of [f.area, f.entries, f.body]) assert.equal(target.reads, 3);
  const textNode = f.text.lastChild;
  f.appendThought(" tail\n");
  f.tick();
  assert.equal(f.text.lastChild, textNode);
  assert.equal(f.text.textContent, deltas.join("") + " tail\n");
  f.renderer.dispose();
});

test("finalize synchronously flushes every pending thought and completes chunk Markdown", () => {
  const f = fixture(), nextText = new Element(), nextThought = new Element();
  nextText.className = "thought-text";
  nextThought.appendChild(nextText);
  f.appendThought(" old\n");
  f.renderer.currentThoughtEl = nextThought;
  f.appendThought(" new ");
  f.chunk.dataset.stage = "intent";
  f.appendChunk("**complete**");
  f.renderer.finalize();
  assert.equal(f.text.textContent, " old\n");
  assert.equal(nextText.textContent, " new ");
  assert.equal(f.chunk.innerHTML, "<p>**complete**</p>");
  assert.equal(f.chunk._streamMdTimer, null);
  assert.equal(f.frames.size, 0);
  f.runTimers();
  assert.equal(f.frames.size, 0);
  f.renderer.dispose();
});

test("reset and dispose cancel pending frames and Markdown timers", () => {
  for (const method of ["reset", "dispose"]) {
    const f = fixture();
    f.appendThought("kept");
    f.appendChunk('{"plan":[');
    f.tick();
    assert.ok(f.timers.has(f.chunk._streamMdTimer));
    f.appendThought(" discarded");
    const chunkText = f.chunk.textContent;
    f.renderer[method]();
    assert.equal(f.frames.size, 0);
    assert.equal(f.timers.size, 0);
    f.tick();
    f.runTimers();
    assert.equal(f.text.textContent, "kept");
    assert.equal(f.chunk.textContent, chunkText);
  }
});

test("planner visualization survives new deltas, raw view and obsolete Markdown timers", () => {
  const f = fixture();
  f.appendChunk('{"plan":[{"unit_id":"one","reason":"a"');
  f.tick();
  const obsoleteTimer = f.chunk._streamMdTimer;
  assert.ok(f.timers.has(obsoleteTimer));
  f.appendChunk("}");
  assert.equal(f.timers.has(obsoleteTimer), false);
  f.tick();
  const visualizer = f.chunk.querySelector(".plan-visualizer");
  const pre = f.chunk.querySelector(".workflow-stream-text");
  const toggle = f.chunk.querySelector(".plan-raw-toggle");
  assert.ok(visualizer);
  assert.equal(visualizer.children.length, 1);
  assert.equal(pre.style.display, "none");
  toggle.listeners.click();
  f.appendChunk(',{"unit_id":"two","reason":"b"}]}');
  f.tick();
  assert.equal(f.chunk.querySelector(".plan-visualizer"), visualizer);
  assert.equal(f.chunk.querySelector(".plan-raw-toggle"), toggle);
  assert.equal(visualizer.children.length, 2);
  assert.equal(pre.textContent, f.chunk.dataset.fullText);
  assert.equal(pre.style.display, "block");
  f.renderer.finalize();
  f.runTimers();
  assert.equal(f.chunk.querySelector(".plan-visualizer"), visualizer);
  assert.equal(f.chunk._streamMdTimer, null);
  f.renderer.dispose();
});
