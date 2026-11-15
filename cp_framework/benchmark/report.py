"""Benchmark report: summary table, SVG charts (no dependencies), HTML and Markdown."""

from __future__ import annotations

import html
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .runner import combo_key, load_results
from .scenarios import SCENARIOS_BY_ID

FONT = "font-family='Segoe UI, Arial, sans-serif'"


def latest_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the last row per (profile, variant, scenario); later runs override budget skips."""
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        latest[(row["profile"], row["variant"], row["scenario"])] = row
    return list(latest.values())


def score_color(score: float | None) -> str:
    if score is None:
        return "#d0d0d0"
    return f"hsl({round(120 * max(0.0, min(1.0, score)))}, 62%, 46%)"


def money(value: float | None, digits: int = 4) -> str:
    return "-" if value is None else f"${value:.{digits}f}"


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[combo_key(row["profile"], row["variant"])].append(row)
    summary = []
    for combo, items in groups.items():
        ran = [r for r in items if r.get("status") in {"ok", "provider_error"}]
        ok = [r for r in ran if r.get("status") == "ok"]
        scores = [r["score"] for r in ok if r.get("score") is not None]
        list_costs = [r.get("list_cost_usd") for r in ran if isinstance(r.get("list_cost_usd"), (int, float))]
        successes = sum(1 for r in ok if r.get("success"))
        total_list = sum(list_costs) if list_costs else None
        summary.append({
            "combo": combo,
            "profile": items[0]["profile"],
            "model": items[0].get("model"),
            "provider": items[0].get("provider"),
            "variant": items[0]["variant"],
            "ran": len(ran),
            "errors": len(ran) - len(ok),
            "skipped": sum(1 for r in items if r.get("status") == "budget_skipped"),
            "successes": successes,
            "success_rate": successes / len(ok) if ok else None,
            "mean_score": sum(scores) / len(scores) if scores else None,
            "billed_usd": sum(r.get("cost_usd") or 0.0 for r in ran),
            "list_usd": total_list,
            "list_usd_per_scenario": (total_list / len(ran)) if total_list is not None and ran else None,
            "list_usd_per_success": (total_list / successes) if total_list is not None and successes else None,
            "prompt_tokens": sum(r.get("prompt_tokens") or 0 for r in ran),
            "completion_tokens": sum(r.get("completion_tokens") or 0 for r in ran),
            "reasoning_tokens": sum(r.get("reasoning_tokens") or 0 for r in ran),
            "avg_wall_s": (sum(r.get("wall_ms") or 0 for r in ran) / len(ran) / 1000) if ran else None,
            "avg_model_s": (sum(r.get("model_ms") or 0 for r in ran) / len(ran) / 1000) if ran else None,
            "avg_attempts": (sum(r.get("attempts") or 0 for r in ran) / len(ran)) if ran else None,
        })
    summary.sort(key=lambda s: (-(s["mean_score"] or 0), s["list_usd_per_scenario"] or 0))
    return summary


def pareto(points: list[tuple[str, float, float]]) -> set[str]:
    """Combos not dominated: no other is at most as costly and at least as good, strictly better in one."""
    frontier = set()
    for name, cost, score in points:
        dominated = any(
            (c <= cost and s >= score) and (c < cost or s > score) for n, c, s in points if n != name
        )
        if not dominated:
            frontier.add(name)
    return frontier


def _svg(width: int, height: int, body: list[str], title: str) -> str:
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}' {FONT} font-size='12'>"
        f"<title>{html.escape(title)}</title><rect width='100%' height='100%' fill='white'/>" + "".join(body) + "</svg>"
    )


def _text(x: float, y: float, value: str, anchor: str = "start", size: int = 12, weight: str = "normal", fill: str = "#222", rotate: int | None = None) -> str:
    transform = f" transform='rotate({rotate} {x:.1f} {y:.1f})'" if rotate else ""
    return f"<text x='{x:.1f}' y='{y:.1f}' text-anchor='{anchor}' font-size='{size}' font-weight='{weight}' fill='{fill}'{transform}>{html.escape(value)}</text>"


def heatmap(rows: list[dict[str, Any]], combos: list[str], scenarios: list[str]) -> str:
    cell_w, cell_h, left, top = 92, 26, 230, 150
    lookup = {(combo_key(r["profile"], r["variant"]), r["scenario"]): r for r in rows}
    width, height = left + cell_w * len(combos) + 20, top + cell_h * len(scenarios) + 20
    body = [_text(10, 22, "Nota por caso de uso (fração das verificações atendidas)", size=15, weight="bold")]
    for j, combo in enumerate(combos):
        body.append(_text(left + j * cell_w + cell_w / 2, top - 8, combo, anchor="start", size=11, rotate=-40))
    for i, scenario in enumerate(scenarios):
        y = top + i * cell_h
        title = SCENARIOS_BY_ID[scenario].title if scenario in SCENARIOS_BY_ID else scenario
        body.append(_text(left - 8, y + cell_h * 0.65, title[:34], anchor="end", size=11))
        for j, combo in enumerate(combos):
            row = lookup.get((combo, scenario))
            status = (row or {}).get("status")
            score = row.get("score") if row and status == "ok" else None
            label = "-" if row is None else {"budget_skipped": "orç.", "provider_error": "erro"}.get(status, f"{score:.0%}" if score is not None else "-")
            body.append(f"<rect x='{left + j * cell_w}' y='{y}' width='{cell_w - 2}' height='{cell_h - 2}' fill='{score_color(score)}' rx='3'/>")
            body.append(_text(left + j * cell_w + cell_w / 2, y + cell_h * 0.65, label, anchor="middle", size=11, fill="white" if score is not None else "#444"))
    return _svg(width, height, body, "Nota por caso de uso")


def scatter(summary: list[dict[str, Any]]) -> str:
    """Cost (log x, free models in their own band) × mean score (y zoomed to the data); numbered points."""
    points = [(s["combo"], s["list_usd_per_scenario"], s["mean_score"]) for s in summary
              if s["list_usd_per_scenario"] is not None and s["mean_score"] is not None]
    ran = {s["combo"]: s["ran"] for s in summary}
    full_count = max(ran.values(), default=0)
    width, left, top, bottom, free_band = 1040, 70, 40, 60, 70
    legend_w = 330
    height = max(460, top + bottom + 18 * len(points) + 20)
    body = [_text(10, 22, "Custo × qualidade (preço de lista por cenário; eixo x em log)", size=15, weight="bold")]
    if not points:
        return _svg(width, height, body + [_text(width / 2, height / 2, "sem dados de custo", anchor="middle")], "Custo × qualidade")
    paid = [c for _, c, _ in points if c > 0]
    lo = math.floor(math.log10(min(paid))) if paid else -4
    hi = math.ceil(math.log10(max(paid))) if paid else -1
    if hi <= lo:
        hi = lo + 1
    score_lo = max(0.0, math.floor((min(s for _, _, s in points) - 0.05) * 20) / 20)
    plot_left = left + free_band
    plot_w, plot_h = width - plot_left - legend_w - 20, height - top - bottom

    def px(cost: float) -> float:
        if cost <= 0:
            return left + free_band / 2
        return plot_left + (math.log10(cost) - lo) / (hi - lo) * plot_w

    def py(score: float) -> float:
        return top + (1 - (score - score_lo) / (1 - score_lo)) * plot_h

    body.append(f"<rect x='{left}' y='{top}' width='{free_band - 6}' height='{plot_h}' fill='#f4f8f4' stroke='#ccc'/>")
    body.append(_text(left + free_band / 2 - 3, top + plot_h + 18, "grátis", anchor="middle", size=11))
    body.append(f"<rect x='{plot_left}' y='{top}' width='{plot_w}' height='{plot_h}' fill='none' stroke='#999'/>")
    for k in range(lo, hi + 1):
        x = plot_left + (k - lo) / (hi - lo) * plot_w
        body.append(f"<line x1='{x:.1f}' y1='{top}' x2='{x:.1f}' y2='{top + plot_h}' stroke='#eee'/>")
        body.append(_text(x, top + plot_h + 18, f"${10**k:g}", anchor="middle", size=11))
    steps = 5
    for i in range(steps + 1):
        tick = score_lo + (1 - score_lo) * i / steps
        y = py(tick)
        body.append(f"<line x1='{left}' y1='{y:.1f}' x2='{plot_left + plot_w}' y2='{y:.1f}' stroke='#eee'/>")
        body.append(_text(left - 8, y + 4, f"{tick:.0%}", anchor="end", size=11))
    body.append(_text(plot_left + plot_w / 2, height - 14, "custo médio por cenário (USD, preço de lista)", anchor="middle"))
    body.append(_text(18, top + plot_h / 2, "nota média", anchor="middle", rotate=-90))
    # Free models would dominate everything at cost zero, so the paid frontier is shown as well.
    frontier = pareto(points) | pareto([p for p in points if p[1] > 0])
    ordered = sorted((p for p in points if p[0] in frontier and p[1] > 0), key=lambda p: p[1])
    if len(ordered) > 1:
        path = " ".join(f"{px(c):.1f},{py(s):.1f}" for _, c, s in ordered)
        body.append(f"<polyline points='{path}' fill='none' stroke='#1f77b4' stroke-dasharray='6 4' stroke-width='2'/>")
    legend_x = plot_left + plot_w + 24
    body.append(_text(legend_x, top + 2, "★ = fronteira de Pareto (grátis e pagos); linha = pagos", size=11, fill="#1f77b4"))
    placed: dict[tuple[int, int], int] = {}
    for index, (name, cost, score) in enumerate(sorted(points, key=lambda p: (p[1], -p[2])), start=1):
        x, y = px(cost), py(score)
        cell = (round(x / 14), round(y / 14))
        offset = placed.get(cell, 0)
        placed[cell] = offset + 1
        x += offset * 13
        on_frontier = name in frontier
        body.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='9' fill='{score_color(score)}' stroke='{'#1f77b4' if on_frontier else '#333'}' stroke-width='{2.5 if on_frontier else 1}'/>")
        body.append(_text(x, y + 4, str(index), anchor="middle", size=10, weight="bold", fill="white"))
        cost_label = "grátis" if cost <= 0 else money(cost)
        partial = f" (parcial {ran.get(name, 0)}/{full_count})" if ran.get(name, 0) < full_count else ""
        body.append(_text(legend_x, top + 22 + index * 18, f"{index}. {'★ ' if on_frontier else ''}{name} — {score:.0%}, {cost_label}{partial}", size=11))
    return _svg(width, height, body, "Custo × qualidade")


def bars(summary: list[dict[str, Any]], key: str, title: str, fmt: Any) -> str:
    items = [s for s in summary if isinstance(s.get(key), (int, float))]
    width, left, row_h, top = 760, 240, 24, 40
    height = top + row_h * max(1, len(items)) + 20
    body = [_text(10, 22, title, size=15, weight="bold")]
    peak = max((s[key] for s in items), default=0) or 1
    for i, s in enumerate(items):
        y = top + i * row_h
        w = (width - left - 120) * s[key] / peak
        body.append(_text(left - 8, y + 16, s["combo"], anchor="end", size=11))
        body.append(f"<rect x='{left}' y='{y + 3}' width='{max(1, w):.1f}' height='{row_h - 8}' fill='{score_color(s.get('mean_score'))}' rx='2'/>")
        body.append(_text(left + w + 6, y + 16, fmt(s[key]), size=11))
    return _svg(width, height, body, title)


def tokens_chart(summary: list[dict[str, Any]]) -> str:
    width, left, row_h, top = 760, 240, 24, 56
    height = top + row_h * max(1, len(summary)) + 20
    body = [_text(10, 22, "Tokens totais por combinação (entrada × saída × raciocínio)", size=15, weight="bold"),
            f"<rect x='{left}' y='32' width='12' height='10' fill='#4c78a8'/>", _text(left + 16, 41, "entrada", size=11),
            f"<rect x='{left + 80}' y='32' width='12' height='10' fill='#f58518'/>", _text(left + 96, 41, "saída", size=11),
            f"<rect x='{left + 150}' y='32' width='12' height='10' fill='#b279a2'/>", _text(left + 166, 41, "raciocínio (dentro da saída)", size=11)]
    peak = max((s["prompt_tokens"] + s["completion_tokens"] for s in summary), default=0) or 1
    scale = (width - left - 120) / peak
    for i, s in enumerate(summary):
        y = top + i * row_h
        body.append(_text(left - 8, y + 16, s["combo"], anchor="end", size=11))
        w_in, w_out = s["prompt_tokens"] * scale, s["completion_tokens"] * scale
        body.append(f"<rect x='{left}' y='{y + 3}' width='{w_in:.1f}' height='{row_h - 8}' fill='#4c78a8'/>")
        body.append(f"<rect x='{left + w_in:.1f}' y='{y + 3}' width='{w_out:.1f}' height='{row_h - 8}' fill='#f58518'/>")
        if s["reasoning_tokens"]:
            body.append(f"<rect x='{left + w_in:.1f}' y='{y + row_h - 8:.1f}' width='{s['reasoning_tokens'] * scale:.1f}' height='3' fill='#b279a2'/>")
        body.append(_text(left + w_in + w_out + 6, y + 16, f"{s['prompt_tokens'] + s['completion_tokens']:,}".replace(",", "."), size=11))
    return _svg(width, height, body, "Tokens")


def scenario_chart(rows: list[dict[str, Any]], scenario: str, combos: list[str]) -> str:
    lookup = {combo_key(r["profile"], r["variant"]): r for r in rows if r["scenario"] == scenario}
    width, left, row_h, top = 640, 220, 20, 34
    height = top + row_h * len(combos) + 12
    title = SCENARIOS_BY_ID[scenario].title if scenario in SCENARIOS_BY_ID else scenario
    costs = [r.get("list_cost_usd") or 0 for r in lookup.values()]
    peak = max(costs, default=0) or 1
    body = [_text(10, 20, f"{title} — custo (barra) e nota (cor)", size=13, weight="bold")]
    for i, combo in enumerate(combos):
        y = top + i * row_h
        row = lookup.get(combo)
        body.append(_text(left - 8, y + 14, combo, anchor="end", size=11))
        if row is None or row.get("status") not in {"ok", "provider_error"}:
            body.append(_text(left, y + 14, "não executado" if row is None else "pulado (orçamento)", size=11, fill="#888"))
            continue
        cost = row.get("list_cost_usd") or 0
        score = row.get("score") if row.get("status") == "ok" else None
        w = (width - left - 150) * cost / peak
        body.append(f"<rect x='{left}' y='{y + 3}' width='{max(2, w):.1f}' height='{row_h - 6}' fill='{score_color(score)}' rx='2'/>")
        label = f"{money(cost)} · " + ("erro do provedor" if row.get("status") == "provider_error" else f"{score:.0%}")
        body.append(_text(left + max(2, w) + 6, y + 14, label, size=11))
    return _svg(width, height, body, title)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def build_report(directory: Path, sources: list[Path] | None = None) -> tuple[Path, Path]:
    """Report for one run, or for several runs merged into `directory` (session links stay relative)."""
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for source in sources or [directory]:
        for row in load_results(source):
            prefix = "" if source.resolve() == directory.resolve() else f"../{source.name}/"
            rows.append({**row, "_session_prefix": prefix})
    rows = latest_rows(rows)
    summary = summarize(rows)
    combos = [s["combo"] for s in summary]
    scenarios = [s for s in SCENARIOS_BY_ID if any(r["scenario"] == s for r in rows)]
    charts_dir = directory / "charts"
    charts_dir.mkdir(exist_ok=True)
    charts = {
        "heatmap": heatmap(rows, combos, scenarios),
        "custo_qualidade": scatter(summary),
        "custo_por_cenario": bars(summary, "list_usd_per_scenario", "Custo médio por cenário (preço de lista)", lambda v: money(v)),
        "custo_por_sucesso": bars(summary, "list_usd_per_success", "Custo por cenário 100% correto", lambda v: money(v)),
        "tempo": bars(summary, "avg_model_s", "Tempo de modelo por cenário (s, soma das chamadas)", lambda v: f"{v:.1f}s"),
        "tokens": tokens_chart(summary),
    }
    for scenario in scenarios:
        charts[f"cenario_{scenario}"] = scenario_chart(rows, scenario, combos)
    for name, svg in charts.items():
        (charts_dir / f"{name}.svg").write_text(svg, encoding="utf-8")

    table_rows = [[
        html.escape(s["combo"]), html.escape(s.get("model") or ""), str(s["ran"]), _pct(s["success_rate"]), _pct(s["mean_score"]),
        money(s["list_usd"]), money(s["billed_usd"]), money(s["list_usd_per_scenario"]), money(s["list_usd_per_success"]),
        f"{s['avg_model_s']:.1f}s / {s['avg_wall_s']:.1f}s" if s["avg_wall_s"] is not None else "-",
        f"{s['avg_attempts']:.2f}" if s["avg_attempts"] is not None else "-", str(s["errors"]), str(s["skipped"]),
    ] for s in summary]
    headers = ["combinação", "modelo", "cenários", "100% corretos", "nota média", "custo lista", "cobrado", "custo/cenário",
               "custo/sucesso", "tempo modelo / total", "tentativas/cenário", "erros", "pulados"]
    detail_rows = []
    for r in sorted(rows, key=lambda r: (r["scenario"], combo_key(r["profile"], r["variant"]))):
        failed = [c["name"] for c in r.get("checks", []) if not c["passed"]]
        session_link = (
            f"<a href='{html.escape(r.get('_session_prefix', ''))}sessions/{html.escape(r['session_id'])}/turns.jsonl'>sessão</a>"
            if r.get("session_id") else "-"
        )
        detail_rows.append([
            html.escape(r["scenario"]), html.escape(combo_key(r["profile"], r["variant"])), html.escape(r.get("status", "")),
            _pct(r.get("score")), html.escape(", ".join(failed)) or "—", money(r.get("list_cost_usd")),
            str(r.get("llm_calls", "-")), session_link,
        ])
    sections = "".join(f"<div class='chart'>{charts[name]}</div>" for name in ("custo_qualidade", "heatmap", "custo_por_cenario", "custo_por_sucesso", "tokens", "tempo"))
    per_scenario = "".join(f"<div class='chart small'>{charts[f'cenario_{s}']}</div>" for s in scenarios)
    page = f"""<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>Benchmark {html.escape(directory.name)}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}}table{{border-collapse:collapse;margin:12px 0;font-size:13px}}
th,td{{border:1px solid #ddd;padding:4px 8px;text-align:left}}th{{background:#f3f3f3}}.chart{{margin:16px 0}}.small{{display:inline-block;margin:6px}}</style>
<h1>Benchmark {html.escape(directory.name)}</h1>
<p>Nota = fração das verificações objetivas do cenário atendidas pela resposta final. Custo de lista = tokens × preço do perfil
(Copilot: preço da API em AI credits, 1 crédito = US$ 0,01; OpenRouter: preço público), usado para comparar modelos.
“Cobrado” é o valor real: no Copilot vem do uso reportado pelo SDK (inclui desconto de cache); é zero em camadas gratuitas.
Tempo de modelo soma as chamadas; o total inclui processos e a inicialização do runtime do Copilot. Transcrições completas em
<code>sessions/</code>.</p>
<h2>Resumo</h2>{_table(headers, table_rows)}
{sections}
<h2>Por caso de uso</h2>{per_scenario}
<h2>Detalhes</h2>{_table(["cenário", "combinação", "status", "nota", "verificações falhas", "custo lista", "chamadas", "transcrição"], detail_rows)}
</html>"""
    html_path = directory / "report.html"
    html_path.write_text(page, encoding="utf-8")

    md = [f"# Benchmark {directory.name}", "", "| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    md += ["| " + " | ".join(html.unescape(cell) for cell in row) + " |" for row in table_rows]
    md += ["", "Gráficos em `charts/`; relatório completo em `report.html`; transcrições em `sessions/`."]
    md_path = directory / "summary.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return html_path, md_path
