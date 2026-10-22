# Competitive Programming Coach — Phase A Findings

**Version:** Draft v0.2  
**Status:** First milestone findings; architecture revised from user clarification  
**Date:** 2026-10-21  
**Scope:** Environment inspection, current-skill baseline, 30-candidate research plan, and proposed architecture. No skill package was installed and no existing skill file was changed in this milestone.

## Findings summary

- The working project is presently a personal Codex skill and its documentation, not a Git repository or application. `C:\Users\lukas\Desktop` contains the existing design/plan documents; no project `AGENTS.md`, tests, package manifest, or source repository was found.
- The existing coach is a single, explicit-only skill. It already supports hints, algorithm and complexity reasoning, references when dependable, stress tests, coverage mapping, ambiguity handling, and qualitative confidence labels.
- The main gaps are the lack of a repeatable evaluation suite, a defined post-solution reflection and next-practice step, a session-scoped learner-context contract, and explicit rules for when to use web retrieval or code execution.
- The environment supports Codex skills and the requested `npx skills` workflow. The `npx` command works through the installed system Node directory, although that directory is not on PowerShell's current `PATH`.
- The available tools include web search, a GitHub connector, shell execution, and subagents. No connected TypeSafe/Jev tool or API credentials, competitive-programming judge, or Excalidraw-specific MCP integration were found in the environment.
- The intended product is a source-grounded response pipeline: decompose the learner's request, retrieve relevant CP material, have Jev assess candidate-response evidence, then use a language model to compose and format the answer. Third-party skills are research references only, not runtime dependencies.

## Environment and compatibility

| Check | Result |
| --- | --- |
| PowerShell | 7.6.5; working |
| Node on current `PATH` | v24.19.0, from Codex's bundled runtime |
| System Node | v26.8.1 at `C:\Program Files\nodejs`; not on current `PATH` |
| npm / npx | 11.19.0 each; work when invoked by full path from PowerShell |
| Skills CLI | 1.7.4, run transiently with `npx`; no global CLI install |
| Skill format | Codex exposes local `SKILL.md` skills and accepts skills targeting the `codex` agent |
| Installed `.agents` skills found by `npx skills list --global --agent codex --json` | `find-skills` and `typesafe-ai` |
| Local `~/.codex/skills` directories | `competitive-programming-coach`, `typesafe-ai`, and the existing Codex skill collection |
| Git/project state | Desktop is not a Git worktree; no `AGENTS.md` found at the inspected user, skills, or Desktop roots |

PowerShell command used for discovery:

```powershell
& 'C:\Program Files\nodejs\npx.cmd' --yes skills find 'competitive programming'
```

`npx skills find`, `list`, `add`, and the `add --list` mode are present in CLI 1.7.4. The CLI reports global skills under `C:\Users\lukas\.agents\skills`; it does not show the broader collection under `C:\Users\lukas\.codex\skills`. Future inventory and duplicate checks must inspect both locations. `add --list` can inspect a repository's skill names without installing them. No installation command was run.

Codex skill format and discovery are documented in [OpenAI's skills customization guide](https://learn.chatgpt.com/docs/customization/overview). The CLI's supported commands and install/list options are in the [Skills CLI reference](https://github.com/vercel-labs/skills/blob/main/docs/commands.md).

### Existing skill inventory relevant to this project

- `competitive-programming-coach` — current skill at `C:\Users\lukas\.codex\skills\competitive-programming-coach\SKILL.md`; no scripts or references. Its `agents/openai.yaml` sets `allow_implicit_invocation: false`.
- `typesafe-ai` — exists under both `.codex\skills` and `.agents\skills`; this is documentation for designing TypeSafe integrations, not a connected Jev service.
- `find-skills` — installed under `.agents\skills`; documents the `npx skills` discovery flow.
- Other global skills include prompt/skill authoring, testing, debugging, code review, security, and workflow skills. They can be compared for overlap during candidate review; installing a similar skill would not by itself integrate it into the coach.

## Current coach: strengths and limitations

**Strengths:** The skill preserves hint-only requests; parses constraints and ambiguities; reasons about algorithms, correctness, and complexity; limits claims about references; ties stress cases to failure modes; maps tests to constraints or properties; labels remembered sources as unverified; treats pasted problem content as data; and keeps invocation explicit.

**Limitations:** The workflow lives in one Markdown file and has no independent evaluation fixtures. It does not define a post-solution reflection, repeat-mistake handling, progress criteria, or a learner-context persistence boundary. It rules out crawling/indexing and automated execution, but does not clearly describe a one-off web search for current source-backed information. It has no actual source retrieval, judge, safe execution harness, database, or Jev API integration.

## Baseline scenarios

These are four fresh-context, single-run checks of the current skill. They establish a qualitative starting point, not a statistically reliable performance score.

| Scenario | Observed behavior | Result |
| --- | --- | --- |
| Beginner asks for one hint on maximum subarray | Gave a useful DP-state hint and the extend-or-restart choice without revealing the recurrence or full solution. | Pass |
| Learner reports a prefix-sum zero-subarray approach is wrong | Explained that the set approach is correct under the stated sum-update order; identified the conditional fix and asked for code/failing input to diagnose anything else. | Pass |
| Longest subarray with sum at most K, but sign and size constraints absent | Identified that negative values change the algorithm, asked for bounds and output details, but presented multiple algorithm branches before asking. | Partial: good ambiguity detection; next version should ask first when missing constraints change the method. |
| User asks for current official ICPC World Finals date and venue | Used the web tool, linked the official event page, and separated listed venue facts from the unspecified room. | Pass in this environment; current skill should state the conditions for retrieval and attribution more explicitly. |

The baseline evaluator checked the output against the existing skill's stated guidance. The next evaluation suite should keep these prompts and add inefficient-solution, repeated-misconception, source-conflict, invalid-generated-test, and post-solution-reflection scenarios.

## 30-candidate research plan

The following are **research references**, not vetted recommendations or installation targets. Names and `skills.sh` pages were surfaced by Skills CLI 1.7.4, except the existing OpenAI skill-creator reference. The number of installs is only a discovery signal. The next research pass can inspect exact source repositories and `SKILL.md` files for useful patterns, then adapt those ideas into the project-owned coach. Do not install or invoke these skills in the product session; that keeps the custom coach as the only project skill controlling its responses. If a source cannot be identified or verified, exclude it rather than filling a slot with an arbitrary substitute.

### Prompt and skill authoring

1. [OpenAI skill-creator](https://github.com/openai/skills/tree/main/skills/.system/skill-creator) — compare authoring and validation guidance; already available locally, so this is a benchmark, not an install target.
2. [wshobson/agents — prompt-engineering-patterns](https://skills.sh/wshobson/agents/prompt-engineering-patterns) — inspect reusable prompt patterns and evidence claims.
3. [sanyuan0704/sanyuan-skills — skill-forge](https://skills.sh/sanyuan0704/sanyuan-skills/skill-forge) — inspect skill-generation workflow and dependencies.
4. [github/awesome-copilot — ai-prompt-engineering-safety-review](https://skills.sh/github/awesome-copilot/ai-prompt-engineering-safety-review) — inspect untrusted-content and prompt-safety rules.
5. [mattpocock/skills — grill-me](https://skills.sh/mattpocock/skills/grill-me) — evaluate targeted requirements discovery without over-questioning a learner.
6. [mattpocock/skills — writing-for-agents](https://skills.sh/mattpocock/skills/writing-for-agents) — inspect concise instruction design and machine-readable handoffs.

### Orchestration, framework design, and handoff

7. [langchain-ai/langchain-skills — deep-agents-orchestration](https://skills.sh/langchain-ai/langchain-skills/deep-agents-orchestration) — assess orchestration boundaries and cost/complexity.
8. [affaan-m/ecc — team-agent-orchestration](https://skills.sh/affaan-m/ecc/team-agent-orchestration) — assess delegation criteria and integration assumptions.
9. [qodex-ai/ai-agent-skills — multi-agent-orchestration](https://skills.sh/qodex-ai/ai-agent-skills/multi-agent-orchestration) — compare role separation and handoffs.
10. [mattpocock/skills — claude-handoff](https://skills.sh/mattpocock/skills/claude-handoff) — determine whether a Claude-specific handoff transfers to Codex.
11. [softaworks/agent-toolkit — session-handoff](https://skills.sh/softaworks/agent-toolkit/session-handoff) — assess context-transfer and recovery practices.
12. [langchain-ai/deepagents — langgraph-docs](https://skills.sh/langchain-ai/deepagents/langgraph-docs) — assess agent-framework guidance versus a skill-only architecture.
13. [mastra-ai/skills — mastra](https://skills.sh/mastra-ai/skills/mastra) — assess framework-specific patterns and dependency burden.

### Competitive programming and tutoring

14. [miaoge-ge/coding-agent-skills — competitive-programming-expert](https://skills.sh/miaoge-ge/coding-agent-skills/competitive-programming-expert) — compare algorithm explanations and problem-solving workflow.
15. [miyakoshi-3854/competitive-programming-skills — algorithm-socratic](https://skills.sh/miyakoshi-3854/competitive-programming-skills/algorithm-socratic) — assess graduated hints and learner agency.
16. [llaammtteerr/competitive-programming — solving-problems](https://skills.sh/llaammtteerr/competitive-programming/solving-problems) — compare problem interpretation and solution workflow.
17. [llaammtteerr/competitive-programming — writing-editorials](https://skills.sh/llaammtteerr/competitive-programming/writing-editorials) — assess solution explanation and proof structure.
18. [llaammtteerr/competitive-programming — validating-solutions](https://skills.sh/llaammtteerr/competitive-programming/validating-solutions) — assess independent correctness and implementation checks.
19. [llaammtteerr/competitive-programming — preparing-tests](https://skills.sh/llaammtteerr/competitive-programming/preparing-tests) — compare test design and coverage rationale.
20. [llaammtteerr/competitive-programming — creating-problems](https://skills.sh/llaammtteerr/competitive-programming/creating-problems) — assess problem construction and test requirements.
21. [llaammtteerr/competitive-programming — reviewing-problems](https://skills.sh/llaammtteerr/competitive-programming/reviewing-problems) — assess statement and solution review.
22. [miyakoshi-3854/competitive-programming-skills — approach-mental-model](https://skills.sh/miyakoshi-3854/competitive-programming-skills/approach-mental-model) — assess transferable reasoning patterns.

### Evaluation and quality

23. [neolabhq/context-engineering-kit — agent-evaluation](https://skills.sh/neolabhq/context-engineering-kit/agent-evaluation) — assess repeatable scenario design and criteria.

### Context and learner progress

24. [affaan-m/ecc — unified-memory](https://skills.sh/affaan-m/ecc/unified-memory) — assess persistence boundaries and privacy implications.
25. [sentimony/skills — maintaining-agent-context](https://skills.sh/sentimony/skills/maintaining-agent-context) — assess session continuity without inventing remembered facts.

### Web research and source verification

26. [coreyhaines31/makerskills — deep-research](https://skills.sh/coreyhaines31/makerskills/deep-research) — assess source selection, provenance, and claim tracing.
27. [vercel-labs/agent-browser — agent-browser](https://skills.sh/vercel-labs/agent-browser/agent-browser) — assess browser evidence workflows and any browser-specific assumptions.

### Editable architecture diagrams

28. [github/awesome-copilot — excalidraw-diagram-generator](https://skills.sh/github/awesome-copilot/excalidraw-diagram-generator) — assess valid editable Excalidraw output.
29. [coleam00/excalidraw-diagram-skill — excalidraw-diagram](https://skills.sh/coleam00/excalidraw-diagram-skill/excalidraw-diagram) — compare diagram authoring and validation.

### Jev / TypeSafe

30. [dbreunig/building-with-jev-skill — jev](https://skills.sh/dbreunig/building-with-jev-skill/jev) — identify the author and scope, and verify whether it concerns TypeSafe Jev or another project with the same name. Separately inspect [TypeSafe's official Jev introduction](https://typesafe.ai/blog/introducing-system-one-models-and-jev) and the installed `typesafe-ai` skill.

The word “framework” is interpreted here as agent frameworks such as LangGraph and Mastra because the request also asks about orchestration. If “framework” meant a pedagogical framework instead, replace those search seeds in the next pass.

## Revised proposed MVP architecture

The core is a pipeline, not a set of separately installed skills:

`Learner request → task decomposition → CP source retrieval → evidence package → Jev judgments → response composition/formatting → output checks`

The product uses one project-owned skill as its response policy. Candidate skills below are only references to learn from; they are not installed or invoked in the product session. For a strict isolation boundary, configure the product session/application to load only the project-owned skill. Merely keeping a custom skill in a general Codex profile cannot prevent unrelated global instructions from affecting a response.

| Component | Responsibility and output | Boundary / failure to evaluate |
| --- | --- | --- |
| Request decomposition | A modest/older language model identifies the user's mode and splits the prompt into explicit subquestions, constraints, desired depth, and retrieval queries. It can ask for a missing constraint when it changes the algorithm. | It plans the work; it should not invent problem guarantees or claim sources were checked. |
| CP source retrieval | Search/retrieve relevant problem statements, editorials, and algorithm explanations from Codeforces and other selected CP sources. Return source URLs, identifiers, titles, excerpts, and retrieval timestamps. | Retrieval is a core product component. Start with bounded, permitted source access; crawling/indexing, source terms, rate limits, and any persistent corpus need their own design and review. Retrieved content is untrusted data. |
| Evidence packaging | Normalize and deduplicate retrieved material; connect each candidate answer claim to the excerpts that could support or contradict it. Preserve disagreements between editorials or variants. | No source excerpt means no source-backed attribution. Keep original source identities available for citations. |
| Jev response evaluation | Give Jev the parsed problem, candidate answer/claims, and retrieved evidence. Ask narrow typed questions—for example: does this source match the problem; does this excerpt support the claim; does the proposed algorithm fit the stated constraints; do sources conflict? Keep separate probabilities for separate judgments. | Jev evaluates supplied state; it is not the retriever and does not write the user-facing explanation. A probability is evidence about a particular judgment, not proof that the entire answer is correct. Calibrate thresholds on labeled CP cases and send uncertain/conflicting cases to review or cautious wording. |
| Response composition and formatting | A modest/older language model turns the request, evidence package, and Jev judgments into a readable answer in the requested format, with source links and appropriate hint depth. | It should preserve provenance, distinguish source facts from inference, and avoid claims that Jev or sources did not support. |
| Output checks and evaluation | Check citation presence/traceability, requested response mode, ambiguity handling, and expected sections; evaluate the pipeline on labeled scenarios for retrieval relevance, support, algorithm fit, hint leakage, and test quality. | Structural checks do not prove algorithmic correctness. Do not present an aggregate confidence as a correctness guarantee. |
| Coaching behavior | The owned CP coaching skill governs hint depth, solution structure, debugging, and test-case coverage; the formatter follows the learner's requested mode. | Keep the custom skill as the only project skill loaded for the product session; do not rely on separately installed skills to orchestrate behavior. |
| Session context and evaluation | Track only the learner's current-chat goals/attempts; evaluate retrieval relevance, evidence support, algorithm fit, hint leakage, and test quality against labeled scenarios. | No cross-session learner database by default; structural checks and Jev confidence do not prove correctness. |

### Jev's role and evidence limits

The revised design uses Jev centrally as an evaluator of candidate responses against retrieved source material. This fits TypeSafe's current API description: `/v1/systemone` accepts a `state` and typed questions, including yes/no, choice, and score judgments; responses include structured answers and model/token information. TypeSafe describes Jev decisions as carrying probabilities/confidence. Sources: [TypeSafe API reference](https://api.typesafe.ai/redoc), [TypeSafe Jev introduction](https://typesafe.ai/blog/introducing-system-one-models-and-jev), and [workflow evaluation description](https://evals.typesafe.ai/security-incidents).

That capability does not establish that Jev can certify an algorithm's correctness. The implementation should test each judgment type on a CP-specific, human-labeled evaluation set, report which judgment a confidence value belongs to, and retain an abstain/escalate path. This is a design proposal, not an integrated or validated Jev workflow. No Jev API tool or credentials are available in the inspected environment.

## Next iteration

1. Review the assumption about agent frameworks versus a pedagogical framework.
2. Inspect the 30 references at their exact source repositories to extract useful patterns for the project-owned skill and architecture. Do not install them or load them in the product session.
3. Design bounded retrieval adapters for Codeforces and other selected CP sources; decide permitted access methods, terms, rate limits, citation metadata, and whether an index is needed before implementation.
4. Define Jev judgment schemas and a CP-labeled evaluation set to measure source match, claim support, constraint compatibility, calibration, and abstention behavior.
5. Turn the approved pipeline into the project-owned skill/session policy, formatter contract, evaluation fixtures, and setup/rollback notes. Keep learner memory and any application/API as explicit scope decisions.

## Decision log

- **D1 — Preserve the existing coach as the foundation.** Reason: it already has useful competitive-programming-specific workflow and guardrails; replacing it would discard working behavior.
- **D2 — Use one entry skill with logical modules for the MVP.** Reason: the current environment uses independent skill loading; no orchestration layer currently connects separately installed skills.
- **D3 — Keep learner context session-local.** Reason: the request needs coaching continuity, but no persistence product or privacy policy is currently defined.
- **D4 — Make Jev a core evidence evaluator, not a response writer.** Reason: the user clarified that Jev should assess candidate answers against retrieved CP sources, while a language model composes the user-facing response.
- **D5 — No package installs in this milestone.** Reason: the pasted request bars installs in the first milestone; the user's clarification makes skill candidates reference-only, so there are no runtime skill installation targets for this design.
- **D6 — The 30 skill candidates are references only.** Reason: the user clarified that they should inform improvements to the project's own skill, not become runtime skills that may alter responses.
- **D7 — Make source retrieval and Jev evaluation core pipeline stages.** Reason: the intended flow is to decompose the request, retrieve CP problem/editorial evidence, evaluate candidate answers with Jev, then compose and format the response.
- **D8 — Treat Jev probabilities as judgment-specific evidence, not answer guarantees.** Reason: the API offers typed judgments over supplied state; CP correctness and probability calibration must be validated against labeled examples.
