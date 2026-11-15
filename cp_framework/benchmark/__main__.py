"""CLI: python -m cp_framework.benchmark {scenarios,estimate,run,report}."""

from __future__ import annotations

import argparse
import sys

from ..envfile import load_env_file

load_env_file()

from ..models import ProfileError, load_profiles  # noqa: E402
from . import report, runner  # noqa: E402
from .scenarios import SCENARIOS, select  # noqa: E402


def _list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m cp_framework.benchmark", description="Benchmark de modelos e prompts.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scenarios", help="lista os cenários")
    for name in ("estimate", "run"):
        cmd = sub.add_parser(name, help="estima o custo" if name == "estimate" else "executa o benchmark")
        cmd.add_argument("--profiles", required=True, help="perfis de models.json separados por vírgula, ou 'all'")
        cmd.add_argument("--variants", default="full,compact", help="full, compact ou ambos")
        cmd.add_argument("--scenarios", default="all", help="ids separados por vírgula, ou 'all'")
    run = sub.choices["run"]
    run.add_argument("--run-id", help="retoma ou nomeia a execução (padrão: run-<data-hora>)")
    run.add_argument("--budget-usd", type=float, default=1.0, help="gasto máximo cobrado (preço de lista dos perfis pagos)")
    run.add_argument("--allow-paid", action="store_true", help="permite perfis pagos, como os do Copilot (consome AI credits)")
    run.add_argument("--judge", help="perfil usado como avaliador LLM (opcional; aumenta o custo)")
    run.add_argument("--pause", type=float, default=0.0, help="pausa entre cenários (s), útil para limites de requisição")
    rep = sub.add_parser("report", help="gera de novo o relatório de uma execução, ou junta várias com --merge")
    rep.add_argument("run_id", help="execução (ou nome do relatório consolidado, com --merge)")
    rep.add_argument("--merge", help="execuções a juntar, separadas por vírgula")
    resc = sub.add_parser("rescore", help="recalcula as verificações a partir das transcrições (sem chamar modelos)")
    resc.add_argument("run_ids", help="execuções separadas por vírgula")
    args = parser.parse_args(argv)

    if args.command == "scenarios":
        for scenario in SCENARIOS:
            model_turns = sum(1 for t in scenario.turns if not t.startswith("/"))
            print(f"{scenario.id:22} | {scenario.category:11} | {model_turns} turno(s) com modelo | {len(scenario.checks)} verificações | {scenario.title}")
        return
    if args.command == "rescore":
        for run_id in _list(args.run_ids):
            directory = runner.run_dir(run_id)
            total, changed = runner.rescore(directory)
            report.build_report(directory)
            print(f"{run_id}: {total} resultados, {changed} com verificações alteradas; relatório atualizado.")
        return
    if args.command == "report":
        sources = [runner.run_dir(item) for item in _list(args.merge)] if args.merge else None
        missing = [str(s) for s in sources or [] if not (s / "results.jsonl").is_file()]
        if missing:
            raise SystemExit(f"Execuções sem results.jsonl: {', '.join(missing)}")
        html_path, _ = report.build_report(runner.run_dir(args.run_id), sources)
        print(f"Relatório: {html_path}")
        return

    profiles = sorted(load_profiles()) if args.profiles == "all" else _list(args.profiles)
    variants = _list(args.variants)
    unknown = [v for v in variants if v not in runner.VARIANTS]
    if unknown:
        raise SystemExit(f"Variante desconhecida: {unknown}. Use full e/ou compact.")
    scenarios = select(args.scenarios)
    if args.command == "estimate":
        print("perfil | modelo | variante | cenários | custo de lista estimado | cobrado estimado")
        for row in runner.estimate(profiles, variants, scenarios):
            print(f"{row['profile']} | {row['model']} | {row['variant']} | {row['scenarios']} | "
                  f"{report.money(row['list_cost_usd'])} | {report.money(row['billed_usd'])}")
        print("\nEstimativa por preço de lista; usa as médias de tokens de execuções anteriores quando existem.")
        return
    directory = runner.run(
        profiles, variants, scenarios, run_id=args.run_id, budget_usd=args.budget_usd, judge=args.judge,
        allow_paid=args.allow_paid, pause_seconds=args.pause,
    )
    html_path, md_path = report.build_report(directory)
    print(f"\nResultados: {directory / 'results.jsonl'}\nRelatório: {html_path}\nResumo: {md_path}")


if __name__ == "__main__":
    try:
        main()
    except (ProfileError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
