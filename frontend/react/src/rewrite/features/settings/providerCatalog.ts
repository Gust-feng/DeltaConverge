/** Presentation only: keep backend registration and automatic model selection unchanged. */
export const PROVIDER_CATALOG: Record<string, { label: string; logo: string; order: number }> = {
  openai: { label: "OpenAI", logo: "openai.svg", order: 0 },
  deepseek: { label: "DeepSeek", logo: "deepseek.svg", order: 1 },
  moonshot: { label: "月之暗面", logo: "moonshot.svg", order: 2 },
  bailian: { label: "通义千问", logo: "qwen.svg", order: 3 },
  minimax: { label: "MiniMax", logo: "minimax.svg", order: 4 },
  glm: { label: "智谱 AI", logo: "glm.svg", order: 5 },
  openrouter: { label: "OpenRouter", logo: "openrouter.svg", order: 6 },
  siliconflow: { label: "硅基流动", logo: "siliconflow.svg", order: 7 },
  modelscope: { label: "魔搭社区", logo: "modelscope.svg", order: 8 },
};

export function providerOrder(id: string): number {
  return PROVIDER_CATALOG[id]?.order ?? 100;
}

export function providerDescription(id: string): string {
  return ["openrouter", "siliconflow", "modelscope"].includes(id) ? "模型服务平台" : "官方 API";
}
