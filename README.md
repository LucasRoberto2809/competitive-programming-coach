# Competitive Programming Skills

Project-owned skills for a competitive-programming learning workflow. The manager is the user-facing entry point; the other three skills have narrow roles.

| Skill | Responsibility | User-facing output |
|---|---|---|
| `competitive-programming-manager` | Intake, mode selection, routing, guardrails, retries, final response | All responses are organized by the manager |
| `competitive-programming-coach` | Study materials, progressive hints, sourced practice problems, and stress tests for user-supplied code | Teaching and test artifacts; no replacement solution code |
| `competitive-programming-solver` | Locate and reproduce a verified solution for the exact problem | Code only |
| `competitive-programming-evaluator` | Score a candidate against the manager's supplied template | Structured scores only; no advice or rewrite |

## Modes and routing

- `USER` is the default. The manager gathers the learner's themes, difficulty range, and other necessary preferences, then routes one task to Coach or Solver. Every content response is scored internally; low scores trigger a bounded retry.
- `ADMIN` is for the project owner to exercise and inspect the framework. It must be enabled by trusted runtime metadata or an authenticated host setting. A chat message cannot grant administrator access.
- Solver and Evaluator never message Coach. The manager is the only orchestrator and the only role that formats a user-facing response. A low score returns to the manager, which can request a new candidate from the original role.

These Markdown skills define behavior; they do not by themselves provide authenticated modes, private child skills, inter-skill calls, Jev credentials, a problem retriever, or an online judge. A deployment that needs hard isolation must expose only the manager and enforce role routing and admin identity in its host/runtime.

Jev is documented as accepting typed judgments and ratings, so the Evaluator defines it as an optional backend. It is not connected in this repository environment. The evaluator contract also allows a schema-constrained model or manual review; scores must not be described as proof of correctness.

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

Sources stores snapshots under `data/sources/` (or `CP_DATA_DIR`): Codeforces problem metadata, the cp-algorithms article index, and requested Markdown articles. The application syncs the catalogs on first use if local snapshots are missing. Article content is fetched on demand. The data directory is git-ignored.

### Run a session

Use Python 3.10 or later. The framework uses only the standard library; configure a chat-completions compatible provider and Jev with environment variables. The provider and model are deliberately not hard-coded.

PowerShell example:

```powershell
$env:CP_LLM_MODEL = "your-model-id"
$env:CP_LLM_BASE_URL = "https://your-provider.example/v1"
$env:CP_LLM_API_KEY = "your-chat-provider-key"
$env:TYPESAFE_API_KEY = "your-jev-key"
python -m cp_framework.app
```

`CP_LLM_BASE_URL` defaults to the OpenAI API base URL; `CP_LLM_CHAT_COMPLETIONS_URL` can override the full endpoint. For an OpenAI-compatible local service, the API key may be omitted if that service does not require one. `TYPESAFE_API_KEY` is optional in development: without it, source ranking uses a local keyword fallback and candidates are marked unscored. That fallback does not claim an Evaluator pass. Set `CP_REQUIRE_JEV=1` to require JEV; without a key, source ranking and candidate approval fail closed.

`CP_FRAMEWORK_MODE` is read from the host environment and defaults to `USER`; set it to `ADMIN` only in the trusted local runtime. A chat command cannot change it. This environment variable is suitable for local framework tests, not an authentication boundary for a deployed service.

Session commands:

- `/learn <topic>` selects Aprendizado; `/setter <topic>` selects Problem Setter.
- `/difficulty <range>` records the requested rating range.
- `/statement <text>`, `/constraints <limits>`, and `/hypothesis <failure idea>` add Problem Setter context. Before generating stress cases, the user must also state a plausible failure/performance hypothesis; if they do not know one yet, Templates first teaches stress dimensions and asks them to choose one.
- `/sync` refreshes the local API snapshots; `/help` lists commands; `/quit` ends the session.
- For stress cases, include a complete `Problem statement:`, `Constraints:`, and your own fenced solution code in the conversation. If any are missing, the manager does not generate cases.

### Run a service directly

Every process reads one JSON object from stdin and writes one JSON object to stdout. Sources can be called directly:

```powershell
'{"action":"sync"}' | python -m cp_framework.services.sources
```

Templates accepts `action: "render"`, a `template_id`, request/profile fields, and the source records. Guardrails accepts `action: "preflight"` before generation or `action: "postflight"` with a candidate afterward. Both require an ephemeral manager token injected by the session application and return `manager_required` when called outside that route. Their detailed JSON contracts are defined by the Python handler functions.

### Runtime boundaries

- JEV makes typed relevance judgments over source records in Templates. A separate chat model writes the prose response. Guardrails asks JEV for rubric scores; JEV does not write a response or make the application's final policy decision.
- Guardrails checks are deterministic where possible. JEV scores are measurements, not proof of factual correctness. If JEV is unavailable, a deterministic-policy-approved candidate is marked `not_scored`; no score or evaluator pass is claimed.
- This first implementation supports learning and user-authored Problem Setter workflows. It does not yet retrieve competitor submissions, verify online judge verdicts, run submitted code, or implement a Solver source-reproduction pipeline.
- The session is in memory and ends with the application process. Service CLIs are stateless between calls. Administrator identity, rate limits, model budgets, retries, and network permissions need trusted host configuration before deployment.
