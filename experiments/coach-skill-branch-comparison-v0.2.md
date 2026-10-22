# Coach Skill Branch Comparison — Experiment v0.2

**Date:** 2026-10-21  
**Status:** Branches created; instruction-level simulations completed; implementation remains experimental.  
**Baseline:** `main` at v0.1 snapshot commit `66e9720`.

## Branches

| Branch | Change |
|---|---|
| `main` | Frozen v0.1 coach skill and prior experiment records. |
| `improve/progressive-hints` | S1-1: for novice “how do I start?” requests, ask one diagnostic question and provide one hint at a time unless full solution requested. |
| `improve/learner-first-checker` | S1-2: ask the learner to propose checker state and an update before supplying a recipe. |
| `improve/tool-execution-clarity` | S1-3: distinguish absence of an integrated runner from actual tool-backed runs requested and performed. |
| `improve/combined-mvp` | Combines S1-1, S1-2, and S1-3. |

Each improvement branch is based on the same baseline commit and contains its stated change only.

## Repeat simulation

**Scenario:** A novice asks how to start the package-shipping capacity problem, then asks for help implementing the fixed-capacity checker. This follows the prompt and problem in `binary-search-feedback-v0.1/sessions/session-1-baseline.md`.

| Version | First coaching turn | Checker turn | Result |
|---|---|---|---|
| `main` | May proceed to explain the monotone check, binary search, bounds, invariant, and updates together. | Gives `days_used`, `load_today`, both updates, and the return condition before the learner tries. | Baseline behavior reproduced from the original transcript. |
| `improve/progressive-hints` | “We want the smallest capacity that works. For a proposed capacity, what yes/no question could we ask about shipping the packages in order?” Then pauses for the learner. | Still gives the checker recipe. | S1-1 behavior observed in the instruction simulation. |
| `improve/learner-first-checker` | Follows baseline pattern. | “What state do you think we need to track, and what should happen when the next package would exceed capacity?” | S1-2 behavior observed in the instruction simulation. |
| `improve/tool-execution-clarity` | Follows baseline pattern. | Follows baseline pattern. The scenario never asks to run code. | S1-3 not exercised by this scenario. |
| `improve/combined-mvp` | Uses a single diagnostic question and waits before revealing the full search recipe. | Elicits state and an update rule before scaffolding. | S1-1 and S1-2 behavior observed in the instruction simulation. |

These are simulated coaching excerpts derived from the branch instructions, not verbatim outputs from separate live skill invocations. They check whether the wording encodes the intended behavior; they do not establish improved learning outcomes. S1-3 needs a separate run-code prompt with and without an available runtime.

## Independent evaluation

A separate evaluator ranked branches using MVP value, evidence fidelity, regression safety, and testability (1–5 each):

| Rank | Branch | MVP | Evidence fidelity | Regression safety | Testability | Rationale |
|---:|---|---:|---:|---:|---:|---|
| 1 | `improve/combined-mvp` | 5 | 5 | 3 | 5 | Broadest MVP gain: both medium-priority coaching changes plus clearer execution reporting. Combined interaction needs checking. |
| 2 | `improve/progressive-hints` | 4 | 5 | 4 | 5 | Addresses the novice’s early “how do I start?” turn; likely the highest-value single behavior change. |
| 3 | `improve/learner-first-checker` | 4 | 5 | 4 | 5 | Directly addresses the checker recipe supplied before the learner attempted implementation. |
| 4 | `improve/tool-execution-clarity` | 2 | 5 | 5 | 5 | Useful transparency clarification, but less central to the coaching MVP. |

The reviewer emphasized that findings come from one simulated learner and that proposed regression checks have not yet been run against revised skills. Therefore, the rank is a prioritization recommendation, not evidence of comparative learning efficacy.

## Recommendation

Use `improve/combined-mvp` as the leading review candidate because it includes the two coaching changes tied to the clearest baseline findings, along with the low-cost execution clarification. Keep `main` as the frozen baseline and retain the focused branches to isolate effects. Before treating the changes as validated, run the exact regression prompts on each actual skill version, including a separate execution prompt for S1-3; compare the learner’s own reasoning and implementation attempts, not only answer correctness.

## Provenance

- Baseline and student sessions: `binary-search-feedback-v0.1/`.
- Prior experimental findings: `experiments/phase-a-findings-2026-10-21.md` and `binary-search-feedback-v0.1/sessions/session-1-evaluation.md`.
- This comparison is a simulated instruction review. It is not a human study, formal experiment, or evidence of long-term retention.
