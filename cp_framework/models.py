"""Model profiles for OpenAI-compatible APIs, Ollama, and Copilot, selected by name.

Profiles live in models.json (no secrets). Each profile names the environment variable
that holds its API key, so keys stay in .env. Usage: python -m cp_framework.models list
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .config import HTTP_TIMEOUT_SECONDS, REPOSITORY_ROOT
from .envfile import load_env_file

DEFAULT_MODELS_FILE = REPOSITORY_ROOT / "models.json"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# OpenAI-compatible endpoints. The model id is always chosen per profile.
PROVIDERS: dict[str, dict[str, str]] = {
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"},
    "openai": {"base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "api_key_env": "GEMINI_API_KEY"},
    "mistral": {"base_url": "https://api.mistral.ai/v1", "api_key_env": "MISTRAL_API_KEY"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY"},
    "ollama": {"base_url": "http://localhost:11434", "api_key_env": ""},
    "copilot": {"base_url": "", "api_key_env": "COPILOT_GITHUB_TOKEN"},
    "custom": {"base_url": "", "api_key_env": ""},
}


class ProfileError(ValueError):
    pass


@dataclass
class ModelProfile:
    name: str
    model: str
    base_url: str = ""
    provider: str = "custom"
    api_key_env: str = ""
    chat_completions_url: str = ""
    temperature: float = 0.2
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    json_mode: bool = False
    price_input_per_mtok: float | None = None
    price_output_per_mtok: float | None = None
    free_tier: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    legacy_api_key: str | None = field(default=None, repr=False)

    @property
    def endpoint(self) -> str:
        if self.provider == "copilot":
            return f"copilot-sdk://{self.model}"
        if self.provider == "ollama":
            return self.base_url.rstrip("/")
        return self.chat_completions_url or f"{self.base_url.rstrip('/')}/chat/completions"

    def api_key(self) -> str | None:
        if self.legacy_api_key:
            return self.legacy_api_key
        return os.environ.get(self.api_key_env) if self.api_key_env else None

    def key_status(self) -> str:
        if self.provider == "copilot":
            if self.api_key_env and os.environ.get(self.api_key_env):
                return f"definida ({self.api_key_env})"
            return "GH_TOKEN definida" if os.environ.get("GH_TOKEN") else "via `gh auth token` (login do GitHub CLI)"
        if not self.api_key_env and not self.legacy_api_key:
            return "sem chave (servidor local)"
        return "definida" if self.api_key() else f"ausente ({self.api_key_env or 'CP_LLM_API_KEY'})"

    def is_ready(self) -> bool:
        if self.provider == "copilot":
            return bool(self.model)
        has_endpoint = bool(self.base_url or self.chat_completions_url)
        return bool(self.model and has_endpoint) and (not self.api_key_env or bool(self.api_key()))

    def is_free(self) -> bool:
        """Free = zero listed price, a provider free tier, or a local server without a key."""
        if self.free_tier or self.provider == "ollama":
            return True
        return self.price_input_per_mtok == 0 and self.price_output_per_mtok == 0

    def list_cost_usd(self, prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
        """Cost at the profile's list price, even when the call itself was free (for comparisons)."""
        if self.price_input_per_mtok is None or self.price_output_per_mtok is None:
            return None
        if prompt_tokens is None or completion_tokens is None:
            return None
        return (prompt_tokens * self.price_input_per_mtok + completion_tokens * self.price_output_per_mtok) / 1_000_000

    def cost_usd(self, prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
        """Cost actually billed: zero inside a free tier or on a local server."""
        if self.free_tier or self.provider == "ollama":
            return 0.0
        return self.list_cost_usd(prompt_tokens, completion_tokens)

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("legacy_api_key", None)
        return data


def models_file() -> Path:
    return Path(os.environ.get("CP_MODELS_FILE") or DEFAULT_MODELS_FILE)


def _profile_from_dict(name: str, data: dict[str, Any]) -> ModelProfile:
    provider = str(data.get("provider") or "custom")
    preset = PROVIDERS.get(provider, PROVIDERS["custom"])
    known = {f for f in ModelProfile.__dataclass_fields__ if f not in {"name", "legacy_api_key"}}
    values = {key: value for key, value in data.items() if key in known}
    values.setdefault("base_url", preset["base_url"])
    values.setdefault("api_key_env", preset["api_key_env"])
    values["provider"] = provider
    values["model"] = str(values.get("model") or "")
    return ModelProfile(name=name, **values)


def load_config(path: Path | None = None) -> dict[str, Any]:
    target = path or models_file()
    if not target.is_file():
        return {"default": None, "profiles": {}}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{target} não é um JSON válido: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("profiles", {}), dict):
        raise ProfileError(f"{target} precisa ter um objeto 'profiles'.")
    return {"default": data.get("default"), "profiles": data.get("profiles", {})}


def load_profiles(path: Path | None = None) -> dict[str, ModelProfile]:
    config = load_config(path)
    return {name: _profile_from_dict(name, data) for name, data in config["profiles"].items()}


def legacy_profile() -> ModelProfile | None:
    """Profile built from the original CP_LLM_* variables, kept for compatibility."""
    model = os.environ.get("CP_LLM_MODEL", "").strip()
    if not model:
        return None
    return ModelProfile(
        name="env",
        model=model,
        provider="custom",
        base_url=os.environ.get("CP_LLM_BASE_URL", "https://api.openai.com/v1"),
        chat_completions_url=os.environ.get("CP_LLM_CHAT_COMPLETIONS_URL", ""),
        temperature=float(os.environ.get("CP_LLM_TEMPERATURE", "0.2")),
        legacy_api_key=os.environ.get("CP_LLM_API_KEY") or None,
        api_key_env="CP_LLM_API_KEY" if os.environ.get("CP_LLM_API_KEY") else "",
    )


def active_profile_name() -> str | None:
    return os.environ.get("CP_LLM_PROFILE") or load_config().get("default") or None


def paid_allowed() -> bool:
    return os.environ.get("CP_ALLOW_PAID", "0").strip().lower() in {"1", "true", "yes"}


def ensure_allowed(profile: ModelProfile) -> ModelProfile:
    if not profile.is_free() and not paid_allowed():
        raise ProfileError(
            f"O perfil '{profile.name}' ({profile.model}) não é gratuito e o uso de modelos pagos está "
            "desativado. Escolha um perfil gratuito ou defina CP_ALLOW_PAID=1 de forma explícita."
        )
    return profile


def resolve_profile(name: str | None = None) -> ModelProfile:
    """Pick a profile by name, CP_LLM_PROFILE, the models.json default, or CP_LLM_* variables.

    Only free profiles are allowed unless CP_ALLOW_PAID=1.
    """
    requested = name or os.environ.get("CP_LLM_PROFILE")
    profiles = load_profiles()
    if requested:
        if requested == "env":
            fallback = legacy_profile()
            if fallback:
                return ensure_allowed(fallback)
        if requested not in profiles:
            available = ", ".join(sorted(profiles)) or "nenhum"
            raise ProfileError(f"Perfil de modelo '{requested}' não existe em {models_file()}. Disponíveis: {available}.")
        profile = profiles[requested]
    else:
        fallback = legacy_profile()
        default = load_config().get("default")
        if fallback:
            return ensure_allowed(fallback)
        if default and default in profiles:
            profile = profiles[default]
        else:
            raise ProfileError(
                "Nenhum modelo configurado: defina CP_LLM_PROFILE (perfil de models.json) ou CP_LLM_MODEL."
            )
    if not profile.model:
        raise ProfileError(f"O perfil '{profile.name}' não tem 'model' definido em {models_file()}.")
    return ensure_allowed(profile)


def forwarded_env(*profile_names: str | None) -> dict[str, str]:
    """Environment a child service needs to use the given profiles (only their own keys)."""
    env: dict[str, str] = {}
    for key in ("CP_LLM_PROFILE", "CP_MODELS_FILE", "CP_USAGE_LOG", "CP_SESSION_ID", "CP_ALLOW_PAID", "CP_LLM_MODEL",
                "CP_LLM_BASE_URL", "CP_LLM_CHAT_COMPLETIONS_URL", "CP_LLM_TEMPERATURE", "CP_LLM_API_KEY",
                "CP_LLM_RETRIES", "CP_LLM_RETRY_BASE_SECONDS", "CP_COPILOT_HOME", "COPILOT_CLI_PATH"):
        if key in os.environ:
            env[key] = os.environ[key]
    profiles = load_profiles()
    for name in profile_names:
        profile = profiles.get(name or "")
        if profile and profile.api_key_env and profile.api_key_env in os.environ:
            env[profile.api_key_env] = os.environ[profile.api_key_env]
        if profile and profile.provider == "copilot":
            # The SDK runtime needs the user profile folders (runtime cache, Node.js); the GitHub CLI
            # fallback (`gh auth token`) needs its config and install folders.
            for key in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "HOME", "COMSPEC",
                        "PROGRAMDATA", "ProgramFiles", "ProgramW6432", "SystemDrive", "COPILOT_CLI_EXTRACT_DIR",
                        "GH_TOKEN", "GH_CONFIG_DIR", "PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432",
                        "NUMBER_OF_PROCESSORS", "OS"):
                if key in os.environ:
                    env[key] = os.environ[key]
    return env


def fetch_openrouter_models() -> dict[str, dict[str, Any]]:
    request = Request(OPENROUTER_MODELS_URL, headers={"User-Agent": "competitive-programming-learning-framework/0.1"})
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        data = json.loads(response.read())
    return {item["id"]: item for item in data.get("data", []) if isinstance(item, dict) and item.get("id")}


def openrouter_profile_fields(model_id: str, catalog: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if model_id not in catalog:
        raise ProfileError(f"O OpenRouter não lista o modelo '{model_id}'. Use 'models search' para procurar.")
    info = catalog[model_id]
    pricing = info.get("pricing") or {}
    return {
        "price_input_per_mtok": round(float(pricing.get("prompt") or 0) * 1_000_000, 6),
        "price_output_per_mtok": round(float(pricing.get("completion") or 0) * 1_000_000, 6),
        "json_mode": "response_format" in (info.get("supported_parameters") or []),
        "notes": f"contexto {info.get('context_length')} tokens; preços do OpenRouter",
    }


def save_profile(name: str, data: dict[str, Any], make_default: bool = False, path: Path | None = None) -> Path:
    target = path or models_file()
    config = load_config(target)
    config["profiles"][name] = data
    if make_default or not config.get("default"):
        config["default"] = name
    target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _format_price(profile: ModelProfile) -> str:
    if profile.free_tier:
        return "camada gratuita"
    if profile.provider == "ollama":
        return "local"
    if profile.price_input_per_mtok is None or profile.price_output_per_mtok is None:
        return "preço ? (tratado como pago)"
    if profile.price_input_per_mtok == 0 and profile.price_output_per_mtok == 0:
        return "gratuito"
    unit = "AI credits do Copilot" if profile.provider == "copilot" else "PAGO"
    return f"{unit} ${profile.price_input_per_mtok:g}/${profile.price_output_per_mtok:g} por 1M tokens"


def describe_profiles() -> str:
    profiles = load_profiles()
    if not profiles:
        return f"Nenhum perfil em {models_file()}."
    active = active_profile_name()
    lines = []
    for name, profile in sorted(profiles.items()):
        marker = "*" if name == active else " "
        lines.append(
            f"{marker} {name}: {profile.provider} | {profile.model or '(sem modelo)'} | {_format_price(profile)} | "
            f"JSON {'sim' if profile.json_mode else 'não'} | chave {profile.key_status()}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    load_env_file()
    parser = argparse.ArgumentParser(prog="python -m cp_framework.models", description="Perfis de modelo.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="lista os perfis de models.json")
    search = sub.add_parser("search", help="procura modelos gratuitos no OpenRouter")
    search.add_argument("text", nargs="?", default="")
    search.add_argument("--include-paid", action="store_true", help="inclui modelos pagos na lista")
    search.add_argument("--json", action="store_true", help="só modelos que aceitam response_format")
    add = sub.add_parser("add", help="adiciona ou atualiza um perfil")
    add.add_argument("name")
    add.add_argument("--provider", default="openrouter", choices=sorted(PROVIDERS))
    add.add_argument("--model", required=True)
    add.add_argument("--base-url")
    add.add_argument("--api-key-env")
    add.add_argument("--price-in", type=float, help="USD por 1M tokens de entrada")
    add.add_argument("--price-out", type=float, help="USD por 1M tokens de saída")
    add.add_argument("--free-tier", action="store_true", help="modelo usado dentro da camada gratuita do provedor")
    add.add_argument("--reasoning-effort", choices=["low", "medium", "high", "xhigh", "max"])
    add.add_argument("--json-mode", choices=["true", "false"])
    add.add_argument("--default", action="store_true", help="torna este o perfil padrão")
    sub.add_parser("copilot", help="lista os modelos do Copilot disponíveis na conta (requer o Copilot SDK)")
    args = parser.parse_args(argv)

    if args.command == "list":
        print(describe_profiles())
        return
    if args.command == "copilot":
        from .copilot_backend import list_copilot_models, resolve_token, token_problem

        token, source = resolve_token(ModelProfile(name="copilot", model="", provider="copilot",
                                                   api_key_env=PROVIDERS["copilot"]["api_key_env"]))
        problem = token_problem(token, source)
        if problem:
            raise SystemExit(f"Erro: {problem}")
        print(f"Token via {source}.")
        for model in list_copilot_models(token):
            supports = (model.get("capabilities") or {}).get("supports") or {}
            billing = model.get("billing") or {}
            policy = (model.get("policy") or {}).get("state", "-")
            print(f"{model.get('id')} | {model.get('name', '')} | política {policy} | "
                  f"reasoning_effort {'sim' if supports.get('reasoning_effort') else 'não'} | "
                  f"cobrança {json.dumps(billing, ensure_ascii=False)}")
        return
    if args.command == "search":
        catalog = fetch_openrouter_models()
        rows = []
        for model_id, info in sorted(catalog.items()):
            pricing = info.get("pricing") or {}
            free = float(pricing.get("prompt") or 0) == 0 and float(pricing.get("completion") or 0) == 0
            if not args.include_paid and not free:
                continue
            if args.json and "response_format" not in (info.get("supported_parameters") or []):
                continue
            if args.text.lower() not in model_id.lower():
                continue
            fields = openrouter_profile_fields(model_id, catalog)
            price = "gratuito" if free else f"${fields['price_input_per_mtok']:g}/${fields['price_output_per_mtok']:g}"
            rows.append(f"{model_id} | {price} | JSON {'sim' if fields['json_mode'] else 'não'} | contexto {info.get('context_length')}")
        print("\n".join(rows) or "Nenhum modelo encontrado.")
        return

    data: dict[str, Any] = {"provider": args.provider, "model": args.model}
    if args.provider == "openrouter":
        data.update(openrouter_profile_fields(args.model, fetch_openrouter_models()))
    if args.base_url:
        data["base_url"] = args.base_url
    if args.api_key_env is not None:
        data["api_key_env"] = args.api_key_env
    if args.price_in is not None:
        data["price_input_per_mtok"] = args.price_in
    if args.price_out is not None:
        data["price_output_per_mtok"] = args.price_out
    if args.json_mode:
        data["json_mode"] = args.json_mode == "true"
    if args.free_tier:
        data["free_tier"] = True
    if args.reasoning_effort:
        data["reasoning_effort"] = args.reasoning_effort
    if args.provider == "copilot" and (args.price_in is None or args.price_out is None):
        from .copilot_backend import list_copilot_models, resolve_token, token_problem

        token, source = resolve_token(ModelProfile(name=args.name, model=args.model, provider="copilot",
                                                   api_key_env=PROVIDERS["copilot"]["api_key_env"]))
        problem = token_problem(token, source)
        if problem:
            raise SystemExit(f"Erro: {problem}")
        listed = {m.get("id"): m for m in list_copilot_models(token)}
        if args.model not in listed:
            raise SystemExit(f"Erro: o modelo '{args.model}' não está disponível na conta. Disponíveis: {', '.join(sorted(listed))}.")
        prices = (listed[args.model].get("billing") or {}).get("token_prices") or {}
        batch = prices.get("batch_size") or 1_000_000
        if prices.get("input_price") is None or prices.get("output_price") is None:
            raise SystemExit("Erro: a API não informou preços para este modelo; use --price-in e --price-out.")
        # AI credits (US$ 0,01) per `batch_size` tokens -> USD per 1M tokens.
        data["price_input_per_mtok"] = round(prices["input_price"] / 100 * 1_000_000 / batch, 6)
        data["price_output_per_mtok"] = round(prices["output_price"] / 100 * 1_000_000 / batch, 6)
        data["notes"] = f"preços da API do Copilot; contexto padrão {prices.get('max_prompt_tokens')} tokens"
    if args.provider == "custom" and not args.base_url:
        raise SystemExit("Para o provedor 'custom', informe --base-url.")
    target = save_profile(args.name, data, make_default=args.default)
    profile = load_profiles(target)[args.name]
    print(f"Perfil '{args.name}' salvo em {target}: {profile.model} ({_format_price(profile)}).")
    if not profile.is_free():
        print("Atenção: este perfil não é gratuito; ele só será usado com CP_ALLOW_PAID=1.")
    if profile.api_key_env and not profile.api_key() and profile.provider != "copilot":
        print(f"Coloque a chave em .env: {profile.api_key_env}=...")


if __name__ == "__main__":
    try:
        main()
    except (ProfileError, RuntimeError) as exc:
        raise SystemExit(f"Erro: {exc}") from None
