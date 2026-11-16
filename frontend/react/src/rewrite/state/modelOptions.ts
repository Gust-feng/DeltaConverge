import { buildModelGroups, getProvidersRaw, type ProviderInfo } from "../lib/api";
import { useAppStore } from "./appStore";

let loadSequence = 0;

// 设置与选择器共用同一份响应；较早发起的请求不能覆盖保存后的刷新。
export async function refreshSavedModels(): Promise<ProviderInfo[] | null> {
  const sequence = ++loadSequence;
  const providers = await getProvidersRaw(true);
  if (sequence !== loadSequence) return null;
  useAppStore.getState().setAvailableGroups(buildModelGroups(providers));
  return providers;
}
