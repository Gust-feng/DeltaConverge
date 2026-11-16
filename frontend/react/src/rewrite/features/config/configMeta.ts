/**
 * 1:1 复刻 legacy/ui_v1/static/modules/config.js 的标签、描述与分组顺序。
 * 后端 JSON 的顶层键与字段顺序才是最终渲染顺序；这里只规定分组顺序与文案。
 */

export type ConfigRecord = Record<string, unknown>;

export type ConfigFieldKind = "boolean" | "number" | "string";

export type ConfigField = {
  key: string;
  label: string;
  kind: ConfigFieldKind;
  initialValue: boolean | string;
};

export type ConfigSection = {
  key: string;
  title: string;
  /** 旧版仅 LLM 分组用 .section-header 包住 h3，其余分组直接放 h3。 */
  withSectionHeader: boolean;
  fields: ConfigField[];
};

export const CONFIG_LABELS: Record<string, string> = {
  "llm.enable_structured_output": "结构化输出参数",
  "llm.call_timeout": "调用超时 (秒)",
  "llm.planner_timeout": "规划器超时 (秒)",
  "llm.planner_first_token_timeout": "规划器首 token 超时 (秒)",
  "llm.planner_first_token_timeout_thinking": "规划器首 token 超时-思考模型 (秒)",
  "llm.max_retries": "最大重试次数",
  "llm.retry_delay": "重试延迟 (秒)",
  "context.max_context_chars": "单字段最大长度 (字符)",
  "context.full_file_max_lines": "全文件读取限制 (行)",
  "context.callers_max_hits": "调用者最大命中数",
  "context.file_cache_ttl": "文件缓存时间 (秒)",
  "review.max_units_per_batch": "单次审查最大单元数",
  "review.enable_intent_cache": "启用意图缓存",
  "review.intent_cache_ttl_days": "意图缓存过期天数",
  "review.stream_chunk_sample_rate": "流式日志采样率",
  "review.review_index_max_chars": "审查索引最大字符数",
  "review.intent_max_chars": "意图字段最大字符数",
  "review.context_bundle_max_items": "上下文包最大条目数",
  "review.context_bundle_max_chars": "上下文包最大字符数",
  "review.context_field_max_chars": "单条上下文最大字符数",
  "review.caller_max_chars": "调用者信息最大字符数",
  "review.tags_max_count": "标签最大数量",
  "fusion_thresholds.high": "高置信度阈值",
  "fusion_thresholds.medium": "中置信度阈值",
  "fusion_thresholds.low": "低置信度阈值",
};

export const CONFIG_DESCRIPTIONS: Record<string, string> = {
  "llm.enable_structured_output": "关闭时通过提示词要求 JSON；开启时附带格式约束，不支持时自动退回兼容方式。",
  "llm.call_timeout": "单次 LLM API 调用的最大等待时间，超时将自动中断。",
  "llm.planner_timeout": "规划阶段（分析代码结构）的最大等待时间。",
  "llm.planner_first_token_timeout":
    "历史遗留/兼容项：规划阶段从发起请求到收到首个增量输出的超时保护（非思考模型）。一般不需要调整。",
  "llm.planner_first_token_timeout_thinking":
    "历史遗留/兼容项：规划阶段从发起请求到收到首个增量输出的超时保护（思考模型）。一般不需要调整。",
  "llm.max_retries": "API 调用失败时的最大重试次数。",
  "llm.retry_delay": "每次重试前的等待时间，避免频繁请求。",
  "context.max_context_chars": "单字段最大字符数；每个上下文字段分别截断。",
  "context.full_file_max_lines": "完整文件模式的最大行数，超过则按行截断或回退。",
  "context.callers_max_hits": "调用方搜索的最大命中数。",
  "context.file_cache_ttl": "文件内容在内存中的缓存时间，减少磁盘 IO。",
  "review.max_units_per_batch": "单次审查任务包含的最大代码单元数量。",
  "review.enable_intent_cache": "启用意图分析缓存。",
  "review.intent_cache_ttl_days": "意图缓存的过期天数。",
  "review.stream_chunk_sample_rate": "流式日志采样率。",
  "review.review_index_max_chars": "拼装审查索引时节选的源码与结构信息上限。",
  "review.intent_max_chars": "项目意图写入提示词时的最大字符数。",
  "review.context_bundle_max_items": "单个审查单元最多附带的上下文字段数量。",
  "review.context_bundle_max_chars": "单个审查单元上下文包的总字符上限。",
  "review.context_field_max_chars": "每个上下文字段单独截断的字符上限。",
  "review.caller_max_chars": "调用者信息（调用点与签名）的字符上限。",
  "review.tags_max_count": "每个审查单元保留的语义标签数量上限。",
  "fusion_thresholds.high": "规则侧置信度≥此值时，以规则建议为主。",
  "fusion_thresholds.medium": "介于低/高之间为中等置信区间。",
  "fusion_thresholds.low": "规则侧置信度≤此值时，优先采纳 LLM 的上下文建议。",
};

export const CONFIG_SECTIONS: ReadonlyArray<{ key: string; title: string; withSectionHeader: boolean }> = [
  { key: "llm", title: "LLM 配置", withSectionHeader: true },
  { key: "context", title: "上下文配置", withSectionHeader: false },
  { key: "review", title: "审查配置", withSectionHeader: false },
  { key: "fusion_thresholds", title: "融合阈值配置", withSectionHeader: false },
];

export function isScalarConfigValue(value: unknown): value is string | number | boolean | null {
  return !(typeof value === "object" && value !== null);
}

/**
 * 与 legacy renderConfigForm 一样：
 * - 只有顶层分组存在（truthy）才渲染该分组；
 * - 跳过值为对象（非 null）的字段；
 * - 字段顺序完全沿用 Object.entries（即后端 JSON 顺序）。
 */
export function buildConfigSections(config: ConfigRecord): ConfigSection[] {
  const sections: ConfigSection[] = [];

  for (const spec of CONFIG_SECTIONS) {
    const group = config[spec.key];
    if (!group) continue;
    if (typeof group !== "object" || Array.isArray(group)) continue;

    const fields: ConfigField[] = [];
    for (const [field, value] of Object.entries(group as Record<string, unknown>)) {
      if (typeof value === "object" && value !== null) continue;
      const key = `${spec.key}.${field}`;
      const isBoolean = typeof value === "boolean";
      const kind: ConfigFieldKind = isBoolean ? "boolean" : typeof value === "number" ? "number" : "string";
      fields.push({
        key,
        // 未知 key 直接显示后端字段名（旧版行为）。
        label: CONFIG_LABELS[key] || field,
        kind,
        initialValue: isBoolean ? value : String(value),
      });
    }

    sections.push({
      key: spec.key,
      title: spec.title,
      withSectionHeader: spec.withSectionHeader,
      fields,
    });
  }

  return sections;
}
