# Competitive Programming Skills and Hooks

This repository contains the competitive-programming skills and the Python hooks they use.

## Skills

The skills are in [`skills/`](skills/). The VS Code slash-command entry point is in
[`.github/skills/competitive/`](.github/skills/competitive/).

## Hooks

The hook entry points are in [`hooks/`](hooks/); shared runtime support is kept in
[`hooks/_support/`](hooks/_support/). They read a JSON request from standard input and
write a JSON response to standard output.

Install the Python dependencies with:

```powershell
uv sync
```

Invoke a hook directly with:

```powershell
uv run python -m hooks.sources
uv run python -m hooks.templates
uv run python -m hooks.guardrails
uv run python -m hooks.stress_tests
```

Model profiles used by the model-backed hooks are stored in
[`hooks/_support/models.json`](hooks/_support/models.json). Keep API keys in environment
variables or the repository's ignored `.env` file.
