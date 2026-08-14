from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "three-sharp-kelly-ab-2026-08-02.json"
OUT_DIR = ROOT / "outputs" / "three-sharp-kelly-ab"


def money(value: float) -> str:
    return f"${value:,.2f}" if value >= 0 else f"-${abs(value):,.2f}"


def build_rows(data: dict) -> tuple[list[dict], list[dict], list[dict]]:
    outcomes: list[dict] = []
    actuals: list[dict] = []
    paths: list[dict] = []
    for horizon in ("7", "30", "60"):
        window = data["windows"][horizon]
        simulation = window["simulation"]
        for arm_key, arm_label in (("flat", "Flat unit"), ("dynamic_kelly", "Dynamic Kelly")):
            arm = simulation[arm_key]
            outcomes.append(
                {
                    "horizon_days": int(horizon),
                    "arm": arm_label,
                    "expected_bets": simulation["expected_bets"],
                    "median_profit": arm["profit_dollars"]["median"],
                    "p05_profit": arm["profit_dollars"]["p05"],
                    "p95_profit": arm["profit_dollars"]["p95"],
                    "probability_profitable": arm["probability_profitable"],
                    "median_max_drawdown": arm["maximum_drawdown"]["median"],
                    "p95_max_drawdown": arm["maximum_drawdown"]["p95"],
                    "dynamic_ahead_probability": (
                        simulation["dynamic_minus_flat"]["probability_dynamic_finishes_ahead"]
                        if arm_key == "dynamic_kelly"
                        else None
                    ),
                }
            )
            historical = window["historical"][arm_key]
            actuals.append(
                {
                    "horizon_days": int(horizon),
                    "arm": arm_label,
                    "bets": historical["eligible_plays"],
                    "record": historical["record"],
                    "profit": historical["profit_dollars"],
                    "betting_roi": historical["betting_roi"],
                    "max_drawdown": historical["maximum_drawdown"],
                    "average_stake_units": historical["average_stake_units_all_eligible"],
                }
            )
            for percentile, values in arm["percentile_paths"].items():
                for day, bankroll in enumerate(values):
                    paths.append(
                        {
                            "horizon_days": int(horizon),
                            "arm": arm_label,
                            "series": f"{arm_label} {percentile}",
                            "percentile": percentile,
                            "day": day,
                            "bankroll": bankroll,
                        }
                    )
    return outcomes, actuals, paths


def build_artifact(data: dict) -> dict:
    outcomes, actuals, paths = build_rows(data)
    filters = [
        "Formal-Cupcake, Soarin22, and phonesculptor only",
        "Settled MLB full-game moneylines, main +/-1.5 run lines, and main full-game totals",
        "Cross-wallet contradictions excluded",
        "30-day warm-up followed by a 60-day evaluation pool",
        "5,000 paired calendar-day bootstrap paths per horizon",
    ]
    definitions = [
        "Flat unit stake = 0.50u times mean wallet copy weight times a 1.15 consensus multiplier for each additional agreeing wallet, capped at 1.50u.",
        "Dynamic Kelly fair probability = entry implied probability plus a prior-date-only supporter-count residual estimate, shrunk by 40 equivalent bets and capped at +/-5 percentage points.",
        "Dynamic stake = half-Kelly scaled once on the 30-day warm-up to match flat average exposure, capped at 1.50u.",
        "One unit = 1% of current bankroll; both arms compound from $10,000.",
        "Probability profitable = share of simulated paths ending above the $10,000 starting bankroll.",
    ]

    def make_source(source_id: str, label: str, table: str, description: str) -> dict:
        return {
            "id": source_id,
            "label": label,
            "path": "outputs/three-sharp-kelly-ab/kelly_ab_report.sqlite",
            "query": {
            "engine": "SQLite",
            "language": "sql",
            "executed_at": datetime.now(timezone.utc).isoformat(),
                "id": f"three_sharp_kelly_ab_{table}_v1",
                "description": description,
                "sql": f"SELECT * FROM {table}",
                "tables_used": [f"kelly_ab_report.sqlite.{table}"],
                "filters": filters,
                "metric_definitions": definitions,
            },
        }

    outcome_source = make_source("simulation-source", "Paired simulation outcomes", "simulation_outcomes", "Paired 7-, 30-, and 60-day outcome summaries.")
    actual_source = make_source("historical-source", "Observed trailing replays", "historical_outcomes", "Observed trailing-window results under each sizing arm.")
    path_source = make_source("path-source", "Bootstrap bankroll paths", "bankroll_paths", "Percentile bankroll paths from the paired bootstrap.")
    sources = [outcome_source, actual_source, path_source]
    sixty = data["windows"]["60"]["simulation"]
    body = (
        "## Technical Summary\n\n"
        f"The matched-risk **flat-unit arm wins this A/B test**. Over 60 simulated days, flat sizing produced a median profit of "
        f"**{money(sixty['flat']['profit_dollars']['median'])}** versus **{money(sixty['dynamic_kelly']['profit_dollars']['median'])}** for dynamic Kelly. "
        f"Dynamic Kelly finished ahead in only **{sixty['dynamic_minus_flat']['probability_dynamic_finishes_ahead']:.2%}** of paired paths and also had the larger median and P95 drawdown. "
        "The recommendation is to retain the existing weighted flat-unit formula and not deploy this Kelly estimator."
    )
    methodology = (
        "## Context & Methods\n\n"
        "This is a paired A/B replay: both arms receive the same sampled calendar days, plays, outcomes, and entry-price proxies. "
        "The Kelly arm is genuinely dynamic by edge and price, but its average exposure was calibrated on a separate 30-day warm-up so the comparison is about allocation quality rather than simply betting more. "
        "Edge estimates use only results settled before each play date; same-day outcomes never inform later same-day sizing."
    )
    caveats = (
        "## Limitations\n\n"
        "The entry price is a copy-weighted median wallet-entry proxy, not a timestamp-perfect executable line; no slippage is modeled. "
        "The evaluation pool contains 231 plays, and the bootstrap reuses those observed days, so the ranges express resampling uncertainty rather than every possible future regime. "
        "Wallet and game correlations may remain, and a different out-of-sample fair-probability model could produce a different Kelly result."
    )
    decision = (
        "## Decision & Next Steps\n\n"
        "Keep weighted flat sizing in production. If dynamic sizing is revisited, require a materially stronger out-of-sample probability model, timestamped executable prices, and a fresh holdout before rollout. "
        "Do not interpret the current result as proof that Kelly sizing is generally inferior; it shows that this specific walk-forward edge estimator does not improve this strategy."
    )
    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "Three-Sharp Dynamic Kelly A/B Test",
            "description": "Matched-exposure comparison of existing flat-unit sizing and walk-forward dynamic Kelly sizing.",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sources": sources,
            "charts": [
                {
                    "id": "median-profit-chart",
                    "title": "Median simulated profit by horizon",
                    "subtitle": "Both arms start at $10,000 and receive identical sampled plays.",
                    "type": "bar",
                    "dataset": "simulation_outcomes",
                    "sourceId": "simulation-source",
                    "encodings": {
                        "x": {"field": "horizon_days", "type": "ordinal", "label": "Horizon (days)"},
                        "y": {"field": "median_profit", "type": "quantitative", "label": "Median profit", "format": "currency"},
                        "color": {"field": "arm", "type": "nominal", "label": "Sizing arm"},
                        "tooltip": [
                            {"field": "horizon_days", "label": "Days"},
                            {"field": "arm", "label": "Sizing"},
                            {"field": "median_profit", "label": "Median profit", "format": "currency"},
                            {"field": "probability_profitable", "label": "Profitable paths", "format": "percent"},
                        ],
                    },
                    "layout": "full",
                },
                {
                    "id": "sixty-path-chart",
                    "title": "60-day simulated bankroll paths",
                    "subtitle": "P05, median, and P95 paths show lower central return and wider downside for dynamic Kelly.",
                    "type": "line",
                    "dataset": "bankroll_paths",
                    "sourceId": "path-source",
                    "transform": [
                        {"type": "filter", "field": "horizon_days", "eq": 60},
                        {"type": "filter", "field": "percentile", "in": ["p05", "median", "p95"]},
                    ],
                    "encodings": {
                        "x": {"field": "day", "type": "quantitative", "label": "Day"},
                        "y": {"field": "bankroll", "type": "quantitative", "label": "Bankroll", "format": "currency"},
                        "color": {"field": "series", "type": "nominal", "label": "Arm and percentile"},
                        "tooltip": [
                            {"field": "day", "label": "Day"},
                            {"field": "series", "label": "Series"},
                            {"field": "bankroll", "label": "Bankroll", "format": "currency"},
                        ],
                    },
                    "layout": "full",
                },
            ],
            "tables": [
                {
                    "id": "simulation-table",
                    "title": "7-, 30-, and 60-day simulation outcomes",
                    "subtitle": "5,000 paired calendar-day bootstrap paths per horizon.",
                    "dataset": "simulation_outcomes",
                    "sourceId": "simulation-source",
                    "layout": "full",
                    "density": "dense",
                    "defaultSort": {"field": "horizon_days", "direction": "asc"},
                    "columns": [
                        {"field": "horizon_days", "label": "Days", "format": "number"},
                        {"field": "arm", "label": "Sizing", "type": "text"},
                        {"field": "expected_bets", "label": "Expected bets", "format": "number"},
                        {"field": "median_profit", "label": "Median profit", "format": "currency"},
                        {"field": "p05_profit", "label": "P05 profit", "format": "currency"},
                        {"field": "p95_profit", "label": "P95 profit", "format": "currency"},
                        {"field": "probability_profitable", "label": "Profitable paths", "format": "percent"},
                        {"field": "median_max_drawdown", "label": "Median max DD", "format": "percent"},
                        {"field": "p95_max_drawdown", "label": "P95 max DD", "format": "percent"},
                    ],
                },
                {
                    "id": "historical-table",
                    "title": "Observed trailing-window replay",
                    "subtitle": "Same eligible plays and compounding rules; this is descriptive, not a separate holdout.",
                    "dataset": "historical_outcomes",
                    "sourceId": "historical-source",
                    "layout": "full",
                    "density": "dense",
                    "defaultSort": {"field": "horizon_days", "direction": "asc"},
                    "columns": [
                        {"field": "horizon_days", "label": "Days", "format": "number"},
                        {"field": "arm", "label": "Sizing", "type": "text"},
                        {"field": "bets", "label": "Bets", "format": "number"},
                        {"field": "record", "label": "Record", "type": "text"},
                        {"field": "average_stake_units", "label": "Avg stake", "format": "number", "unit": "u"},
                        {"field": "profit", "label": "Profit", "format": "currency"},
                        {"field": "betting_roi", "label": "Betting ROI", "format": "percent"},
                        {"field": "max_drawdown", "label": "Max DD", "format": "percent"},
                    ],
                },
            ],
            "blocks": [
                {"id": "title", "type": "markdown", "layout": "full", "body": "# Three-Sharp Dynamic Kelly A/B Test"},
                {"id": "summary", "type": "markdown", "layout": "full", "sourceId": "simulation-source", "body": body},
                {"id": "simulation-table-block", "type": "table", "tableId": "simulation-table", "layout": "full"},
                {"id": "median-profit-block", "type": "chart", "chartId": "median-profit-chart", "layout": "full"},
                {"id": "sixty-path-block", "type": "chart", "chartId": "sixty-path-chart", "layout": "full"},
                {"id": "historical-heading", "type": "markdown", "layout": "full", "sourceId": "historical-source", "body": "## Observed Replay\n\nThe realized trailing windows point in the same direction as the simulations: flat sizing earned more with lower drawdown in all three windows."},
                {"id": "historical-table-block", "type": "table", "tableId": "historical-table", "layout": "full"},
                {"id": "methods", "type": "markdown", "layout": "full", "sourceId": "simulation-source", "body": methodology},
                {"id": "limitations", "type": "markdown", "layout": "full", "sourceId": "simulation-source", "body": caveats},
                {"id": "decision", "type": "markdown", "layout": "full", "sourceId": "simulation-source", "body": decision},
            ],
        },
        "snapshot": {
            "version": 1,
            "status": "ready",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "datasets": {
                "simulation_outcomes": outcomes,
                "historical_outcomes": actuals,
                "bankroll_paths": paths,
            },
        },
        "sources": sources,
    }


def write_sqlite(data: dict) -> None:
    outcomes, actuals, paths = build_rows(data)
    database = OUT_DIR / "kelly_ab_report.sqlite"
    if database.exists():
        database.unlink()
    connection = sqlite3.connect(database)
    try:
        for table, rows in (("simulation_outcomes", outcomes), ("historical_outcomes", actuals), ("bankroll_paths", paths)):
            columns = list(rows[0])
            connection.execute(
                f"CREATE TABLE {table} ({', '.join(f'{column} REAL' if isinstance(rows[0][column], (int, float)) and not isinstance(rows[0][column], bool) else f'{column} TEXT' for column in columns)})"
            )
            connection.executemany(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [[row[column] for column in columns] for row in rows],
            )
        connection.commit()
    finally:
        connection.close()


def build_notebook(data: dict) -> None:
    def markdown(source: str) -> dict:
        return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}

    def code(source: str) -> dict:
        return {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": source.splitlines(keepends=True),
        }

    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3"},
        },
        "cells": [
            markdown("# Three-Sharp Dynamic Kelly A/B Test\n\nReproducible companion notebook for the matched-exposure 7-, 30-, and 60-day comparison."),
            markdown("## TL;DR\n\nThe existing weighted flat-unit arm outperformed the tested walk-forward dynamic Kelly arm at every horizon and with lower drawdown."),
            code(
                "from pathlib import Path\nimport json\nimport pandas as pd\n"
                "root = Path.cwd()\n"
                "if not (root / 'outputs').exists(): root = root.parent.parent\n"
                "data = json.loads((root / 'outputs' / 'three-sharp-kelly-ab-2026-08-02.json').read_text())\n"
                "data['as_of'], data['data']['eligible_plays'], data['data']['simulation_evaluation_plays']"
            ),
            markdown("## Context & Methods\n\nBoth arms receive the same sampled calendar days and outcomes. Kelly uses only prior-date results and is exposure-matched on a 30-day warm-up."),
            code(
                "rows=[]\nfor h in ['7','30','60']:\n"
                "    sim=data['windows'][h]['simulation']\n"
                "    for key,label in [('flat','Flat unit'),('dynamic_kelly','Dynamic Kelly')]:\n"
                "        a=sim[key]\n"
                "        rows.append({'days':int(h),'arm':label,'expected_bets':sim['expected_bets'],'median_profit':a['profit_dollars']['median'],'p05_profit':a['profit_dollars']['p05'],'p95_profit':a['profit_dollars']['p95'],'prob_profitable':a['probability_profitable'],'median_max_dd':a['maximum_drawdown']['median'],'p95_max_dd':a['maximum_drawdown']['p95']})\n"
                "results=pd.DataFrame(rows)\nresults"
            ),
            markdown("## Results"),
            code(
                "hist=[]\nfor h in ['7','30','60']:\n"
                "    for key,label in [('flat','Flat unit'),('dynamic_kelly','Dynamic Kelly')]:\n"
                "        x=data['windows'][h]['historical'][key]\n"
                "        hist.append({'days':int(h),'arm':label,'bets':x['eligible_plays'],'record':x['record'],'avg_stake_u':x['average_stake_units_all_eligible'],'profit':x['profit_dollars'],'betting_roi':x['betting_roi'],'max_drawdown':x['maximum_drawdown']})\n"
                "historical=pd.DataFrame(hist)\nhistorical"
            ),
            markdown("## Takeaways\n\nThe Kelly estimator did not allocate stake effectively enough to beat the simpler wallet-weighted flat formula. Keep flat sizing. A future Kelly retest should use timestamped executable prices and an independently validated probability model."),
        ],
    }
    (OUT_DIR / "three-sharp-kelly-ab.ipynb").write_text(json.dumps(notebook, indent=2), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    write_sqlite(data)
    artifact = build_artifact(data)
    (OUT_DIR / "artifact.json").write_text(
        json.dumps(artifact, indent=2), encoding="utf-8"
    )
    build_notebook(data)
    print(OUT_DIR / "artifact.json")
    print(OUT_DIR / "three-sharp-kelly-ab.ipynb")


if __name__ == "__main__":
    main()
