# Competitive Programming Skills

Project-owned skills for a competitive-programming learning workflow. The manager is the user-facing entry point; the other three skills have narrow roles.

| Skill | Responsibility | User-facing output |
|---|---|---|
| `competitive-programming-manager` | Intake, mode selection, routing, guardrails, retries, final response | All responses are organized by the manager |
| `competitive-programming-coach` | Study materials, progressive hints, sourced practice problems, and stress tests for user-supplied code | Teaching and test artifacts; no replacement solution code |
| `competitive-programming-solver` | Locate and reproduce a verified solution for the exact problem | Code only |
| `competitive-programming-evaluator` | Score a candidate against the manager's supplied template | Structured scores only; no advice or rewrite |
| `competitive-programming-originality` | Point out published Codeforces problems similar or identical to a Problem Setter statement | Short neutral notice; never an accusation |

## Use in VS Code Chat

In a Copilot Chat session with Agent Skills enabled, type `/competitive` and add your request after it. For example: `/competitive Quero aprender busca binária com dicas graduais.` This workspace skill is the user-invocable entry point and follows the role instructions in `skills/`.

The slash command loads the workflow instructions; it does not itself provide private role sessions or guarantee inter-skill calls. Use `python -m cp_framework.app` when you need the Python framework's runtime orchestration.

## Modes and routing

- `USER` is the default. The manager gathers the learner's themes, difficulty range, and other necessary preferences, then routes one task to Coach or Solver. Every content response is scored internally; low scores trigger a bounded retry.
- `ADMIN` is for the project owner to exercise and inspect the framework. It must be enabled by trusted runtime metadata or an authenticated host setting. A chat message cannot grant administrator access.
- Solver and Evaluator never message Coach. The manager is the only orchestrator and the only role that formats a user-facing response. A low score returns to the manager, which can request a new candidate from the original role.

These Markdown skills define behavior; they do not by themselves provide authenticated modes, private child skills, inter-skill calls, Jev credentials, a problem retriever, or an online judge. A deployment that needs hard isolation must expose only the manager and enforce role routing and admin identity in its host/runtime.

The Evaluator is model-agnostic: it can run on any configured free model profile, on Jev (which accepts typed judgments and ratings) when a TypeSafe key is configured, or be disabled. Scores must not be described as proof of correctness.

## Existing experiments

The prior coaching baseline, experiments, and transcripts are preserved in the repository's `main` history and `experiments/`. The Coach path now contains the teaching-only role; the manager, solver, and evaluator specifications sit alongside it. This branch also adds the proposed four-role framework.

## Branches

- `main`: captured Draft v0.1 baseline.
- `improve/progressive-hints`: S1-1 only.
- `improve/learner-first-checker`: S1-2 only.
- `improve/tool-execution-clarity`: S1-3 only.
- `improve/combined-mvp`: all three proposed changes.

## Python services (MVP)

The runtime separates the source collector, response-template renderer, and guardrails. Each one can be invoked as its own short-lived JSON process; `cp_framework.app` is the session manager that coordinates them. They do not currently expose network servers or require a queue.

| Service | Responsibility | Process entry point |
|---|---|---|
| Sources | Call the Codeforces and GitHub APIs; write local JSON snapshots only | `python -m cp_framework.services.sources` |
| Templates | Use Manager/Coach skills, rank source candidates with Jev when configured, and ask a configurable chat-completions model to render a response template | `python -m cp_framework.services.templates` |
| Guardrails | Enforce USER/ADMIN configuration, learning/problem-setter gates, response checks, and score-only evaluation with Jev when configured | `python -m cp_framework.services.guardrails` |
| Session app | Maintain one in-memory conversation and launch each service in a separate child process | `python -m cp_framework.app` |

Sources stores snapshots under `data/sources/` (or `CP_DATA_DIR`): Codeforces problem metadata, the tag → rating catalog (`codeforces_catalog.json`), the cp-algorithms article index, and requested Markdown articles. The application syncs the catalogs on first use if local snapshots are missing; Codeforces calls are throttled to one request every 2 seconds. Article content is fetched on demand. The data directory is git-ignored.

The manager selects practice problems locally from the catalog (`cp_framework/catalog.py`): topics in Portuguese or English map to Codeforces tags, and combinations require every tag. Bands are easy 800–999, medium 1000–1499, hard 1500–2099, and veteran 2100+ (Problem Setter references only). By default the two most-solved unseen problems per band are shown, never more than three per band and topic; "mais problemas" continues until the catalog runs out. If a band is short, the rating range widens (±100, ±200) and then accepts partial tag matches; the template tells the user what was adjusted.

### Run a session

Use Python 3.10 or later. The default profile is the local Ollama model `llama3.2`, accessed through the official [`ollama-python`](https://github.com/ollama/ollama-python) SDK. The `ollama-llama3.2-1b` profile remains available for `llama3.2:1b`. Other models can be selected from `models.json`.

1. If `make` is not installed on Windows, install GNU Make once:

   ```powershell
   winget install --id GnuWin32.Make --exact --accept-source-agreements --accept-package-agreements
   ```

   Reopen the terminal so `make` is added to `PATH`.

2. Install the project dependencies and native tools:

   ```powershell
   make dependencies
   ```

   This syncs the Ollama and GitHub Copilot Python SDKs and installs Glow and Ollama via Winget when they are not already on `PATH`. Reopen the terminal after installation. Download the default model once with `ollama pull llama3.2`.

3. Check the connection (the check sends one chat and one JSON request to Ollama), then start the terminal chat:

   ```powershell
   uv run python -m cp_framework.app --check
   uv run python -m cp_framework.app
   ```

   If Glow is unavailable, the app warns and displays the Markdown source as plain text. The timestamp is printed after the user presses Enter, and each Manager response is timestamped when it finishes. Inside the chat, `/model` lists profiles, `/model <profile>` switches the model for the next turns, and `/sair` (`/exit` or `/quit`) returns to the terminal.

Manage profiles with `uv run python -m cp_framework.models`: `list`, `search [text] [--json] [--include-paid]` (OpenRouter catalog, free models by default), and `add <name> --model <id> [--provider groq|gemini|ollama|custom ...] [--free-tier] [--default]`. For OpenRouter, `add` checks that the model exists and fills its price and JSON support from the public model list. Other providers (Groq, Gemini, Mistral, DeepSeek, Ollama, any custom base URL) use presets for the endpoint and key variable.

Every model call is appended to `data/runs/usage.jsonl` (profile, model, purpose such as `template:learning_start`, `solver`, or `evaluator`, latency, tokens, list and billed cost, session). Every chat session is also saved in full for later manual analysis under `data/sessions/<session-id>/`: `meta.json`, `turns.jsonl` (each command and turn with the final answer, preflight, template, rejected candidates, failed guardrail checks, Solver status), `calls.jsonl` (each model call with user prompt, response, and usage), and `prompts/` (system prompts stored once by hash). Set `CP_USAGE_LOG=0` or `CP_TRANSCRIPTS=0` to disable them.

`CP_PROMPT_VARIANT=compact` drops the long Manager/Coach/Solver/Evaluator skill texts from the prompts (keeping the rules, situations, and template guides), shortens article excerpts, and keeps less history.

### GitHub Copilot models

Copilot models are used through the official GitHub Copilot SDK, as profiles with `"provider": "copilot"`. They consume the plan's AI credits (1 credit = US$ 0.01, priced per token), so they require `CP_ALLOW_PAID=1`. Sessions run in the SDK's isolated `empty` mode with their own home (`data/copilot-home/`), no tools, and our system prompt replacing the agent's, so nothing touches `~/.copilot` and only the task is measured.

```powershell
winget install GitHub.cli; gh auth login --web       # once: your GitHub user with Copilot (gho_ token in the keyring)
uv run python -m cp_framework.models copilot                       # models + prices on your account
uv run python -m cp_framework.models add copilot-gpt-6-luna --provider copilot --model gpt-6-luna
```

The token is resolved from `COPILOT_GITHUB_TOKEN`, then `GH_TOKEN`, then `gh auth token`; classic `ghp_` tokens are rejected. `models add` reads the model's per-token prices from the API. The billed cost comes from the usage the SDK reports (`nano_aiu × 10⁻¹¹` USD, cache discounts included).

To start an interactive terminal session using Luna 6, explicitly allow paid usage for this run:

```powershell
uv run python -m cp_framework.app --model copilot-gpt-6-luna --allow-paid
```

The app prompts with `Você>`; type `/help` to see the learning commands and `/sair` (`/exit` or `/quit`) to end the session. To check Copilot authentication, SDK availability, and model connectivity before chatting, add `--check` to the same command (keeping both `--model copilot-gpt-6-luna` and `--allow-paid`).

### Benchmark

`python -m cp_framework.benchmark` runs 18 use-case scenarios (from [docs/template-use-cases.md](docs/template-use-cases.md)) through the real pipeline for each model profile and prompt variant, with objective checks on the final answer, a spending cap, resume by run id, and full transcripts:

```powershell
uv run python -m cp_framework.benchmark scenarios
uv run python -m cp_framework.benchmark estimate --profiles copilot-gpt-6-luna,copilot-claude-sonnet-5.5 --variants full,compact
uv run python -m cp_framework.benchmark run --profiles copilot-gpt-6-luna --variants full,compact --allow-paid --budget-usd 2
uv run python -m cp_framework.benchmark rescore <run-id>                 # re-evaluate checks from transcripts, no model calls
uv run python -m cp_framework.benchmark report <name> --merge run-a,run-b  # one report for runs executed in parallel
```

Each run writes `data/benchmarks/<run-id>/` with `results.jsonl`, `usage.jsonl`, `sessions/`, `summary.md`, and `report.html`, which has dependency-free SVG charts: cost × quality with the Pareto frontier, score heatmap per scenario, cost per scenario and per fully correct scenario, tokens, model time, and one cost/result chart per use case. `--judge <profile>` adds LLM rubric scores.

The evaluator can run on any free profile (`CP_EVALUATOR_PROFILE`) and returns only per-criterion scores in JSON; the total and pass are computed in code. `CP_EVALUATOR_BACKEND` selects `auto` (Jev if `TYPESAFE_API_KEY` is set, otherwise the evaluator profile, otherwise no score), `llm`, `jev`, or `none`. Without an evaluator, candidates still pass the deterministic guardrails but are marked unscored; `CP_REQUIRE_JEV=1` makes approval fail closed. The legacy `CP_LLM_MODEL`/`CP_LLM_BASE_URL`/`CP_LLM_API_KEY` variables still work as a profile named `env`.

`CP_FRAMEWORK_MODE` is read from the host environment and defaults to `USER`; set it to `ADMIN` only in the trusted local runtime. A chat command cannot change it. This environment variable is suitable for local framework tests, not an authentication boundary for a deployed service.

Session commands:

- `/learn <topic>` selects Aprendizado; `/setter <topic>` selects Problem Setter.
- `/difficulty <range>` records the requested rating range.
- `/statement <text>`, `/constraints <limits>`, and `/hypothesis <failure idea>` add Problem Setter context. Before generating stress cases, the user must also state a plausible failure/performance hypothesis; if they do not know one yet, Templates first teaches stress dimensions and asks them to choose one.
- To discuss code without pasting it into the terminal, mention a repository-relative path (for example, `cp_framework/app.py`) and ask the model to inspect it. The model has a read-only file tool restricted to the repository; it rejects secrets, virtual environments, binary files, and text files larger than 256 KiB. File contents are sent to the configured model, so do not request files containing secrets.
- `/sync` refreshes the local API snapshots; `/help` lists commands and the intended flow; `/sair` (`/exit` or `/quit`) ends the session and returns to the terminal.
- `/retomar` (`/resume`) returns to the paused stage of the other mode; `/consolidar` (`/consolidate`) writes a summary of topics, problems, and code snippets to `data/sessions/`; `/recomecar` (`/restart`) clears the chat and keeps that summary as initial context. `python -m cp_framework.app --contexto <file>` starts a new chat from a saved summary. The app warns once when the estimated context passes 80% of `CP_CONTEXT_BUDGET_TOKENS` (default 12000).
- For stress cases, include a complete `Problem statement:`, `Constraints:`, and your own fenced solution code in the conversation. If any are missing, the manager does not generate cases.
- Switching modes in free text ("agora quero criar meu próprio problema", "quero estudar busca binária antes") pauses the current stage and states where the user stopped. A new topic restarts the flow of the current mode. Requests for an immediate solution and attempts to change rules or claim admin access are detected in Guardrails; they never change the trusted profile.
- The Solver analyzes each problem internally on the first interaction (structured JSON). Templates use it for hints, test oracles, and statement inconsistencies; the learner receives the code only after showing pseudocode and asking for it.
- Out-of-scope requests and statements pasted in Aprendizado get the intended flow and a recommendation to use another chat. Answers follow the user's language (Portuguese or English).
- In Problem Setter, a short notice points out very similar or identical published Codeforces problems; the flow is not blocked.

Template examples ("Templates testados para utilizar no chat") and the decisions behind each behavior are in [docs/template-use-cases.md](docs/template-use-cases.md).

### Tests

```powershell
uv run python -m unittest discover -s tests -t .                       # offline: catalog, guardrails, templates, models, end-to-end chat against fake providers
$env:CP_LIVE_TESTS='1'; uv run python -m unittest tests.test_sources_live  # hits Codeforces and GitHub
```

### Run a service directly

Every process reads one JSON object from stdin and writes one JSON object to stdout. Sources can be called directly:

```powershell
'{"action":"sync"}' | python -m cp_framework.services.sources
```

Templates accepts `action: "render"`, a `template_id`, request/profile fields, and the source records. Guardrails accepts `action: "preflight"` before generation or `action: "postflight"` with a candidate afterward. Both require an ephemeral manager token injected by the session application and return `manager_required` when called outside that route. Their detailed JSON contracts are defined by the Python handler functions.

### Runtime boundaries

- The chat model (any profile) writes the prose response and the Solver's structured reference. If Jev is configured, it makes typed relevance judgments over non-catalog sources and can score candidates; otherwise scoring uses the evaluator profile or is skipped. Neither the evaluator nor Jev writes the response or makes the application's final policy decision.
- Guardrails checks are deterministic where possible. JEV scores are measurements, not proof of factual correctness. If JEV is unavailable, a deterministic-policy-approved candidate is marked `not_scored`; no score or evaluator pass is claimed.
- This first implementation supports learning and user-authored Problem Setter workflows. The Solver is a model-generated reference (structured JSON), not a source-reproduction pipeline: it does not retrieve competitor submissions, verify online judge verdicts, or run code, so its solutions and example checks are labeled as unverified.
- The session is in memory and ends with the application process. Service CLIs are stateless between calls. Administrator identity, rate limits, model budgets, retries, and network permissions need trusted host configuration before deployment.
