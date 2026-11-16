import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const bundle = await build({
  stdin: {
    contents: `
      export { buildModelGroups } from './src/rewrite/lib/api';
      export { availableModel, modelCapabilityLabel } from './src/rewrite/lib/modelSelection';
      export { useAppStore } from './src/rewrite/state/appStore';
      export { refreshSavedModels } from './src/rewrite/state/modelOptions';
    `,
    resolveDir: projectRoot,
  },
  bundle: true,
  platform: "node",
  format: "esm",
  write: false,
});
const { buildModelGroups, availableModel, modelCapabilityLabel, useAppStore, refreshSavedModels } =
  await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`);

function provider(models = ["saved"], overrides = {}) {
  return {
    id: "service", label: "Service", available: true, configured: true, added: true, models,
    model_details: [{ id: "saved", capabilities: { reasoning: true } }],
    ...overrides,
  };
}

function response(items) {
  return new Response(JSON.stringify({ items }), { status: 200 });
}

await test("saved model selection stays consistent across updates and failures", async (t) => {
  const originalFetch = globalThis.fetch;
  try {
    await t.test("only saved models from enabled services enter the selector, with metadata", () => {
      const groups = buildModelGroups([
        provider(), provider(["hidden"], { id: "disabled", disabled: true }),
        provider([], { id: "empty" }), provider(["needs-key"], { id: "unconfigured", configured: false }),
        provider(["preset"], { id: "catalog-only", added: false, configured: false, available: false }),
      ]);
      assert.deepEqual(groups.map((group) => group.provider), ["service", "unconfigured"]);
      assert.equal(availableModel(groups, "service:saved")?.name, "service:saved");
      assert.equal(availableModel(groups, "service:discovered-but-unsaved"), undefined);
      assert.equal(availableModel(groups, "unconfigured:needs-key"), undefined);
      assert.equal(modelCapabilityLabel(groups[0].models[0].capabilities), "思考");
      assert.equal(availableModel(groups, "mock"), undefined);
    });

    await t.test("deleting or disabling the selected model reconciles selection atomically", () => {
      const store = useAppStore.getState();
      store.setAvailableGroups(buildModelGroups([provider(["saved", "other"])]));
      store.setModel("service:other");
      store.setAvailableGroups(buildModelGroups([provider(["other"])]));
      assert.equal(useAppStore.getState().model, "service:other");
      store.setAvailableGroups(buildModelGroups([provider(["saved"])]));
      assert.equal(useAppStore.getState().model, "service:saved");
      store.setModel("service:deleted");
      assert.equal(useAppStore.getState().model, "");
      store.setAvailableGroups(buildModelGroups([provider(["saved"], { disabled: true })]));
      assert.equal(useAppStore.getState().model, "");
      assert.deepEqual(useAppStore.getState().availableGroups, []);
    });

    await t.test("empty saved services and unadded catalog presets leave the selector empty", async () => {
      globalThis.fetch = async () => response([
        provider([]),
        provider(["preset"], { added: false, configured: false, available: false }),
      ]);
      await refreshSavedModels();
      assert.equal(useAppStore.getState().model, "");
      assert.deepEqual(useAppStore.getState().availableGroups, []);
    });

    await t.test("model refresh does not depend on the tools endpoint", async () => {
      const calls = [];
      globalThis.fetch = async (url) => {
        calls.push(url);
        if (url === "/api/v2/tools") throw new Error("tools unavailable");
        return response([provider()]);
      };
      const items = await refreshSavedModels();
      assert.deepEqual(calls, ["/api/v2/models/providers?include_disabled=true"]);
      assert.equal(items[0].models[0], "saved");
      assert.equal(useAppStore.getState().model, "service:saved");
    });

    await t.test("a failed refresh preserves the last successfully loaded list", async () => {
      const before = useAppStore.getState().availableGroups;
      globalThis.fetch = async () => { throw new Error("connection failed"); };
      await assert.rejects(refreshSavedModels(), /connection failed/);
      assert.equal(useAppStore.getState().availableGroups, before);
      assert.equal(useAppStore.getState().model, "service:saved");
    });

    await t.test("a slow response cannot overwrite a newer saved-model refresh", async () => {
      const pending = [];
      globalThis.fetch = () => new Promise((resolve) => pending.push(resolve));
      const oldLoad = refreshSavedModels();
      const savedLoad = refreshSavedModels();
      pending[1](response([provider(["new"])]));
      await savedLoad;
      pending[0](response([provider(["old"])]));
      assert.equal(await oldLoad, null);
      assert.equal(useAppStore.getState().model, "service:new");
      assert.deepEqual(useAppStore.getState().availableGroups[0].models.map((model) => model.name), ["service:new"]);
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
