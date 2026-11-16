import type { ModelGroup, ModelItem } from "../types";

export function availableModel(groups: ModelGroup[], name: string): ModelItem | undefined {
  return groups.flatMap((group) => group.models).find((model) => model.name === name && model.available);
}

export function reconcileModel(groups: ModelGroup[], current: string): string {
  return availableModel(groups, current)?.name
    ?? groups.flatMap((group) => group.models).find((model) => model.available)?.name
    ?? "";
}

export function modelCapabilityLabel(capabilities: Record<string, unknown> | undefined): string | null {
  if (capabilities?.reasoning === true || capabilities?.thinking === true) return "思考";
  if (capabilities?.vision === true || capabilities?.image_input === true) return "视觉";
  return null;
}
