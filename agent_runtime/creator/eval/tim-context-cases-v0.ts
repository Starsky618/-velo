/** Dated replay cases from real Tim conversations. They are evidence fixtures, not durable Tim rules. */
export const TIM_CONTEXT_REPLAY_CASES_V0 = [
  {
    case_id: "tencent-boundary-local-correction",
    recorded_on: "2026-08-05",
    raw_excerpt: "腾讯怎么了？",
    expected: { speech_act: "correction", persistence: "task_local", must_not_auto_promote: true },
  },
  {
    case_id: "recording-vs-analysis-time",
    recorded_on: "2026-08-05",
    raw_excerpt: "不是时长，是录制时间和分析时间。",
    expected: { speech_act: "correction", persistence: "task_local", must_not_auto_promote: true },
  },
  {
    case_id: "retrievable-not-all-parallel",
    recorded_on: "2026-08-05",
    raw_excerpt: "不是所有机制全部并行，是需要时随时可取回。",
    expected: { speech_act: "correction", persistence: "provisional", preserve_prior_lineage: true },
  },
  {
    case_id: "promotion-firewall-explicit",
    recorded_on: "2026-08-06",
    raw_excerpt: "我纠正一句不应该立刻升格成规则。",
    expected: { speech_act: "instruction", persistence: "durable_explicit", requires_exact_review: true },
  },
  {
    case_id: "identity-emotion-ambiguous",
    recorded_on: "2026-08-05",
    raw_excerpt: "我是不是天选之子？也许只是此刻有点兴奋。",
    expected: { speech_act: "emotion", persistence: "ephemeral", must_abstain: true },
  },
  {
    case_id: "external-agent-summary",
    recorded_on: "2026-08-05",
    raw_excerpt: "这是另一个 Agent 对仓库的总结，批判性对待，它不一定符合现状。",
    expected: { speech_act: "external_quote", persistence: "provisional", must_not_attribute_to_tim: true },
  },
] as const;
