import { readFileSync } from "node:fs";

import { contentHash } from "../../shared/canonical.ts";
import type { RiderConversationContext } from "../context/compiler.ts";
import type { RiderTaskContextPacket } from "../context/rider-task-context.ts";
import type { AgentV0RuntimeTrace, CandidatePlan } from "../planning/types.ts";
import type { SessionCommitResult, SessionRuntimePort } from "../session/committer.ts";

interface RegistryTool {
  tool_name: string;
  tool_version: string;
  capability_id: string;
  purpose_code: string;
  input_kind: string;
  observation_kind: string;
}

interface ToolRegistry {
  registry_id: string;
  registry_version: string;
  default_decision: "DENY";
  tools: RegistryTool[];
}

interface RuntimeOptions {
  session_id: string;
  session_revision: number;
  request_ref: string;
  world_revision: string;
  rider_context?: RiderConversationContext;
  rider_task_context?: RiderTaskContextPacket;
  max_model_turns?: number;
  max_tool_calls?: number;
  max_plan_generations?: number;
  now_ms?: () => number;
}

function bareHash(value: unknown): string {
  return contentHash(value).slice("sha256:".length);
}

/**
 * Deterministic adapter from the executable shadow into the existing Agent v0
 * contracts. It resolves every tool from the checked-in registry and records
 * one ContextManifest + one AgentAction for each logical model turn.
 */
export class AgentV0RuntimeController {
  readonly trace: AgentV0RuntimeTrace;
  readonly runId: string;
  readonly #registry: ToolRegistry;
  readonly #options: Required<Pick<RuntimeOptions, "max_model_turns" | "max_tool_calls" | "max_plan_generations">> & RuntimeOptions;
  readonly #startedAt: string;
  readonly #deadlineAt: string;
  readonly #deadlineEpochMs: number;
  readonly #clock: () => number;
  #modelTurns = 0;
  #toolCalls = 0;
  #planGenerations = 0;

  constructor(options: RuntimeOptions) {
    if (!Number.isInteger(options.session_revision) || options.session_revision < 1) throw new Error("Agent v0 requires a committed session revision");
    this.#clock = options.now_ms ?? Date.now;
    const startedAtEpochMs = this.#clock();
    this.#startedAt = new Date(startedAtEpochMs).toISOString();
    this.#deadlineEpochMs = startedAtEpochMs + 30_000;
    this.#deadlineAt = new Date(this.#deadlineEpochMs).toISOString();
    this.#options = { max_model_turns: 6, max_tool_calls: 4, max_plan_generations: 2, ...options };
    const registryUrl = new URL("../../../contracts/agent_v0/tool_registry.v0.json", import.meta.url);
    this.#registry = JSON.parse(readFileSync(registryUrl, "utf8")) as ToolRegistry;
    if (this.#registry.default_decision !== "DENY") throw new Error("tool registry must default deny");
    this.runId = `run:${bareHash({ session: options.session_id, revision: options.session_revision, request: options.request_ref, at: this.#startedAt }).slice(0, 24)}`;
    this.trace = {
      registry_id: this.#registry.registry_id,
      registry_version: this.#registry.registry_version,
      context_manifests: [], actions: [], tool_calls: [], tool_results: [], agent_run: {},
    };
  }

  get modelTurns(): number { return this.#modelTurns; }
  get toolCallCount(): number { return this.#toolCalls; }

  checkDeadline(): void { this.#assertBeforeDeadline(); }

  async invokeModel<T>(decide: (signal: AbortSignal) => T | Promise<T>): Promise<T> {
    return this.#executeWithinDeadline("model", decide);
  }

  updateWorldRevision(worldRevision: string): void {
    if (!worldRevision) throw new Error("world revision must not be empty");
    this.#options.world_revision = worldRevision;
  }

  beginTurn(taskMode: "discover" | "understand" | "compare" | "revise" | "execute", plans: CandidatePlan[] = []): number {
    this.#assertBeforeDeadline();
    if (this.#modelTurns >= this.#options.max_model_turns) throw new Error("Agent v0 model-turn budget exceeded");
    this.#modelTurns += 1;
    const turn = this.#modelTurns;
    const context = this.#options.rider_context;
    const riderTaskContext = this.#options.rider_task_context;
    const manifestId = `${this.runId}:context:${turn}`;
    const sourcePacketRefs = [
      {
        packet_type: "world_fact_packet", packet_id: `world-packet:${this.#options.world_revision}`,
        schema_version: "0.1.0", source_revision: this.#options.world_revision,
        content_hash: bareHash({ world_revision: this.#options.world_revision }),
      },
      ...(riderTaskContext ? [{
        packet_type: "rider_context_packet", packet_id: riderTaskContext.packet_id,
        schema_version: riderTaskContext.schema_version, source_revision: riderTaskContext.source_revision,
        content_hash: bareHash(riderTaskContext),
      }] : []),
    ];
    this.trace.context_manifests.push({
      schema_version: "0.1.0", manifest_id: manifestId, packet_environment: "shadow",
      session_id: this.#options.session_id, run_id: this.runId, model_call_id: `${this.runId}:model:${turn}`,
      compiled_at: this.#nowIso(), task_mode: taskMode,
      prompt_policy_version: "agent-v0-shadow-r1", playbook_version: "ride-planning-shadow-r1",
      tool_registry_version: this.#registry.registry_version, predicate_registry_version: "0.1.0",
      session_revision: this.#options.session_revision, source_packet_refs: sourcePacketRefs,
      memory_item_refs: context?.included_decision_refs ?? [],
      plan_revision_refs: plans.map((plan) => ({
        object_ref: { object_id: plan.plan_id, object_type: "ride_plan" }, revision: plan.plan_revision,
        content_hash: bareHash(plan),
      })),
      included_sections: [
        "current_request", "published_world",
        ...(context ? ["confirmed_rider_decisions"] : []),
        ...(riderTaskContext ? ["authorized_rider_route_history"] : []),
        ...(plans.length ? ["tool.observation.candidate_plan_set", "plan.candidate_summaries", "plan.validation_summaries"] : []),
      ],
      omitted_sections: [], privacy_redactions: [], token_budget: { budget: 4096, used: 0, reserved_for_response: 512 },
      token_counts: [], context_content_hash: bareHash({
        sourcePacketRefs,
        plans: plans.map((plan) => plan.plan_revision),
        conversation_context_hash: context?.context_hash,
        rider_task_context_hash: riderTaskContext === undefined ? undefined : bareHash(riderTaskContext),
      }),
      source_of_truth: false, metadata: { "x-runtime": "typescript-shadow" },
    });
    return turn;
  }

  recordQuestion(turn: number, question: {
    question: string;
    question_kind: "intent" | "location" | "time_budget" | "route_preference" | "candidate_choice";
    answer_mode: "single_choice" | "multi_choice" | "free_text" | "map_pin" | "yes_no";
    blocking_unknown_refs: string[];
  }): void {
    this.#assertBeforeDeadline();
    this.trace.actions.push(this.#action(turn, "ask_clarifying_question", {
      question_ref: `${this.runId}:question:${turn}`, question_kind: question.question_kind,
      user_safe_question: question.question, answer_mode: question.answer_mode,
      blocking_unknown_refs: question.blocking_unknown_refs,
    }, []));
  }

  recordModelFailure(turn: number, message: string): void {
    if (turn < 1) return;
    if (this.trace.actions.some((action) => action.model_turn_index === turn)) return;
    this.trace.actions.push(this.#action(turn, "no_result", {
      reason_code: "data_unavailable",
      user_safe_message: message,
      blocking_unknown_refs: [],
      suggested_next_step: "try_later",
    }, []));
  }

  async invokeTool<T>(turn: number, toolName: string, inputRef: string, execute: (signal: AbortSignal) => T | Promise<T>): Promise<T> {
    this.#assertBeforeDeadline();
    const tool = this.#registry.tools.find((item) => item.tool_name === toolName);
    if (!tool) throw new Error(`tool denied by Agent v0 registry: ${toolName}`);
    if (this.#toolCalls >= this.#options.max_tool_calls) throw new Error("Agent v0 tool-call budget exceeded");
    if (toolName === "planning.generate_candidate_plans" && this.#planGenerations >= this.#options.max_plan_generations) {
      throw new Error("Agent v0 plan-generation budget exceeded");
    }
    this.#toolCalls += 1;
    if (toolName === "planning.generate_candidate_plans") this.#planGenerations += 1;
    const toolCallId = `${this.runId}:tool:${this.#toolCalls}`;
    const action = this.#action(turn, "propose_tool_call", { tool_call_ref: toolCallId }, []);
    this.trace.actions.push(action);
    this.trace.tool_calls.push({
      schema_version: "0.1.0", environment: "shadow", fixture_only: false, tool_call_id: toolCallId,
      run_id: this.runId, session_id: this.#options.session_id, base_session_revision: this.#options.session_revision,
      model_turn_index: turn, requested_by_agent_action_ref: action.action_id,
      tool_registry_id: this.#registry.registry_id, tool_registry_version: this.#registry.registry_version,
      tool_name: tool.tool_name, tool_version: tool.tool_version, capability_id: tool.capability_id,
      purpose_code: tool.purpose_code,
      input: { input_kind: tool.input_kind, input_ref: inputRef, input_revision: this.#options.session_revision, input_schema_version: "0.1.0", target_revision_refs: [] },
      expected_observation_kind: tool.observation_kind, proposed_at: this.#nowIso(), proposal_only: true,
      metadata: { "x-runtime": "typescript-shadow" },
    });
    let result: T;
    try {
      result = await this.#executeWithinDeadline(`tool ${toolName}`, execute);
    } catch (error) {
      const deadlineExceeded = error instanceof AgentDeadlineExceededError;
      this.trace.tool_results.push({
        schema_version: "0.1.0", environment: "shadow", fixture_only: false,
        observation_id: `${this.runId}:observation:${this.#toolCalls}`,
        tool_call_id: toolCallId, run_id: this.runId, session_id: this.#options.session_id,
        base_session_revision: this.#options.session_revision, tool_registry_id: this.#registry.registry_id,
        tool_registry_version: this.#registry.registry_version, tool_name: tool.tool_name, tool_version: tool.tool_version,
        capability_id: tool.capability_id, observation_kind: tool.observation_kind,
        result_status: deadlineExceeded ? "timed_out" : "failed",
        result_code: deadlineExceeded ? "TOOL_TIMEOUT" : "TOOL_HARD_FAIL",
        domain_reason_code: deadlineExceeded ? "RUN_DEADLINE_EXCEEDED" : "DOMAIN_SERVICE_FAILURE",
        attempt_index: 1, result_finality: "TERMINAL", observed_at: this.#nowIso(), observation_only: true,
        raw_provider_payload_exposed: false, exact_coordinates_exposed: false, canonical_fact_claimed: false,
        result_refs: [], warning_refs: [], unknown_refs: [],
        retry_disposition: deadlineExceeded ? "DEFER" : "DO_NOT_RETRY",
        user_safe_summary: deadlineExceeded ? `${tool.purpose_code} 因运行时限终止` : `${tool.purpose_code} 执行失败`,
        metadata: { "x-runtime": "typescript-shadow" },
      });
      throw error;
    }
    const observationId = `${this.runId}:observation:${this.#toolCalls}`;
    const resultRef = tool.observation_kind === "world_fact_packet"
      ? { packet_type: "world_fact_packet", packet_id: `world-packet:${this.#options.world_revision}`, schema_version: "0.1.0", source_revision: this.#options.world_revision, content_hash: bareHash({ world_revision: this.#options.world_revision }) }
      : { contract_kind: tool.observation_kind, contract_id: `${this.runId}:${tool.observation_kind}:${this.#toolCalls}`, contract_revision: `artifact:${bareHash(result).slice(0, 24)}`, schema_version: "0.1.0" };
    this.trace.tool_results.push({
      schema_version: "0.1.0", environment: "shadow", fixture_only: false, observation_id: observationId,
      tool_call_id: toolCallId, run_id: this.runId, session_id: this.#options.session_id,
      base_session_revision: this.#options.session_revision, tool_registry_id: this.#registry.registry_id,
      tool_registry_version: this.#registry.registry_version, tool_name: tool.tool_name, tool_version: tool.tool_version,
      capability_id: tool.capability_id, observation_kind: tool.observation_kind,
      result_status: "succeeded", result_code: "TOOL_SUCCEEDED", attempt_index: 1, result_finality: "TERMINAL",
      observed_at: this.#nowIso(), observation_only: true, raw_provider_payload_exposed: false,
      exact_coordinates_exposed: false, canonical_fact_claimed: false, result_refs: [resultRef],
      warning_refs: [], unknown_refs: [], retry_disposition: "NOT_APPLICABLE", user_safe_summary: `${tool.purpose_code} 已完成`,
      metadata: { "x-runtime": "typescript-shadow" },
    });
    return result;
  }

  async commitSession(content: string, sessionPort: SessionRuntimePort): Promise<SessionCommitResult> {
    this.#assertBeforeDeadline();
    const controller = new AbortController();
    const remainingMs = this.#deadlineEpochMs - this.#clock();
    const timer = setTimeout(() => {
      controller.abort(new AgentDeadlineExceededError("session commit exceeded the Agent v0 wall-clock deadline"));
    }, remainingMs);
    let result: SessionCommitResult;
    try {
      // Once the port crosses its guard and mutates state, we must await and
      // preserve its exact receipt even if the run deadline passes meanwhile.
      result = await sessionPort.commitAgentTurn(content, this.#options.session_revision, {
        signal: controller.signal,
        assertCanCommit: () => this.#assertBeforeDeadline(),
      });
    } finally {
      clearTimeout(timer);
    }
    if (result.expected_base_revision !== this.#options.session_revision) {
      throw new Error("session committer returned a mismatched base revision");
    }
    if (result.commit_status === "committed" && result.committed_revision !== this.#options.session_revision + 1) {
      throw new Error("session committer returned a non-sequential committed revision");
    }
    return result;
  }

  recordTerminal(turn: number, candidates: CandidatePlan[], message: string): void {
    this.#assertBeforeDeadline();
    if (candidates.length > 0) {
      const refs = candidates.slice(0, 3).map((candidate) => ({
        candidate_ref: candidate.plan_id,
        plan_revision_ref: {
          object_ref: { object_id: candidate.plan_id, object_type: "ride_plan" },
          revision: candidate.plan_revision,
          content_hash: bareHash(candidate),
        },
        validation_result_ref: `validation:${candidate.plan_id}:${candidate.request_hash.slice(-12)}`,
      }));
      const actionId = `${this.runId}:action:${turn}`;
      const mapAction = {
        schema_version: "0.1.0", environment: "shadow", fixture_only: false,
        map_action_id: `${this.runId}:map:${turn}`, session_id: this.#options.session_id,
        base_session_revision: this.#options.session_revision, source_agent_action_ref: actionId, sequence: 1,
        issued_at: this.#nowIso(), reducer_required: true, action_type: "show_candidate_set",
        payload: { candidates: refs.map((ref, index) => ({ ...ref, display_order: index + 1 })) },
        metadata: { "x-runtime": "typescript-shadow" },
      };
      this.trace.actions.push(this.#action(turn, "present_valid_candidates", {
        candidates: refs, user_safe_summary: message, comparison_summary_ref: `${this.runId}:comparison:1`,
      }, [mapAction]));
    } else {
      this.trace.actions.push(this.#action(turn, "no_result", {
        reason_code: "no_viable_plan", user_safe_message: message, blocking_unknown_refs: [], suggested_next_step: "relax_constraint",
      }, []));
    }
  }

  finish(
    requestedStopReason: "completed" | "no_result" | "waiting_for_user" | "deterministic_error",
    sessionCommit: SessionCommitResult | undefined,
  ): void {
    const deadlineExceeded = this.#clock() >= this.#deadlineEpochMs;
    const stopReason = sessionCommit?.commit_status === "reconciliation_required"
      ? "deterministic_error"
      : deadlineExceeded ? "budget_exceeded" : requestedStopReason;
    if (stopReason === "completed" && sessionCommit?.commit_status !== "committed") {
      throw new Error("completed Agent v0 run requires a committed session revision");
    }
    const paused = stopReason === "waiting_for_user";
    const endedAt = this.#nowIso();
    this.trace.agent_run = {
      schema_version: "0.1.0", environment: "shadow", fixture_only: false, run_id: this.runId,
      session_id: this.#options.session_id, state_owner: "deterministic_run_controller",
      run_lineage_ref: `lineage:${this.#options.session_id}`, base_session_revision: this.#options.session_revision,
      trigger: { trigger_type: "user_turn", trigger_ref: this.#options.request_ref },
      run_status: paused ? "paused" : "stopped", stop_reason: stopReason,
      current_step: "respond_or_stop",
      ...(paused ? { pending_gate: { gate_kind: "user_input", gate_ref: `${this.runId}:question-gate`, created_at: endedAt } } : {}),
      budget: {
        limits: { max_model_turns: this.#options.max_model_turns, max_tool_calls: this.#options.max_tool_calls, max_plan_generations: this.#options.max_plan_generations, max_same_tool_retries: 0, wall_clock_deadline: this.#deadlineAt, token_limit: 4096 },
        consumed: { model_turns: this.#modelTurns, tool_calls: this.#toolCalls, plan_generations: this.#planGenerations, tokens: 0 },
        tool_retry_counters: [...new Set(this.trace.tool_calls.map((call) => call.tool_name as string))].map((tool_name) => ({ tool_name, retries: 0 })),
      },
      context_manifest_refs: this.trace.context_manifests.map((item) => item.manifest_id),
      action_proposal_refs: this.trace.actions.map((item) => item.action_id),
      tool_call_refs: this.trace.tool_calls.map((item) => item.tool_call_id),
      observation_refs: this.trace.tool_results.map((item) => item.observation_id),
      session_commit: sessionCommit ?? { commit_status: "not_attempted", expected_base_revision: this.#options.session_revision },
      started_at: this.#startedAt, last_checkpoint_at: endedAt, ...(paused ? {} : { ended_at: endedAt }),
      metadata: { "x-runtime": "typescript-shadow" },
    };
  }

  #assertBeforeDeadline(): void {
    if (this.#clock() >= this.#deadlineEpochMs) throw new AgentDeadlineExceededError();
  }

  async #executeWithinDeadline<T>(label: string, execute: (signal: AbortSignal) => T | Promise<T>): Promise<T> {
    this.#assertBeforeDeadline();
    const remainingMs = this.#deadlineEpochMs - this.#clock();
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => {
        controller.abort(new AgentDeadlineExceededError(`${label} exceeded the Agent v0 wall-clock deadline`));
        reject(controller.signal.reason);
      }, remainingMs);
    });
    try {
      const result = await Promise.race([Promise.resolve().then(() => execute(controller.signal)), timeout]);
      this.#assertBeforeDeadline();
      return result;
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }

  #nowIso(): string {
    return new Date(this.#clock()).toISOString();
  }

  #action(turn: number, actionType: string, payload: Record<string, unknown>, mapActions: Record<string, unknown>[]): Record<string, unknown> {
    return {
      schema_version: "0.1.0", environment: "shadow", fixture_only: false,
      action_id: `${this.runId}:action:${turn}`, run_id: this.runId, session_id: this.#options.session_id,
      base_session_revision: this.#options.session_revision, model_turn_index: turn, proposed_at: this.#nowIso(),
      proposal_only: true, action_type: actionType, payload, map_actions: mapActions,
      metadata: { "x-runtime": "typescript-shadow" },
    };
  }
}

export class AgentDeadlineExceededError extends Error {
  constructor(message = "Agent v0 wall-clock deadline exceeded") {
    super(message);
    this.name = "AgentDeadlineExceededError";
  }
}
