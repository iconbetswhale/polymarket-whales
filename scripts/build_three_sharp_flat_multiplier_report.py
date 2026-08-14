from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "three-sharp-flat-multipliers-2026-08-02.json"
OUT_DIR = ROOT / "outputs" / "three-sharp-flat-multipliers"


def rows_from(data: dict) -> list[dict]:
    rows = []
    for horizon in ("7", "30", "60"):
        simulation = data["windows"][horizon]["simulation"]
        for multiplier in map(str, data["multipliers"]):
            result = simulation["multipliers"][multiplier]
            rows.append(
                {
                    "horizon_days": int(horizon),
                    "multiplier": f"{multiplier}x",
                    "multiplier_value": int(multiplier),
                    "expected_bets": simulation["expected_bets"],
                    "average_stake_units": result["average_starting_stake_units"],
                    "median_profit": result["profit_dollars"]["median"],
                    "p05_profit": result["profit_dollars"]["p05"],
                    "p95_profit": result["profit_dollars"]["p95"],
                    "probability_profitable": result["probability_profitable"],
                    "median_max_drawdown": result["maximum_drawdown"]["median"],
                    "p95_max_drawdown": result["maximum_drawdown"]["p95"],
                    "maximum_observed_drawdown": result["maximum_drawdown"]["maximum_observed"],
                    "probability_losing_10_percent": result["probability_losing_10_percent"],
                    "probability_losing_20_percent": result["probability_losing_20_percent"],
                }
            )
    return rows


def source_record() -> dict:
    return {
        "id": "multiplier-source",
        "label": "Flat-sizing multiplier simulations",
        "path": "outputs/three-sharp-flat-multipliers/flat_multiplier_report.sqlite",
        "query": {
            "engine": "SQLite",
            "language": "sql",
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "id": "three_sharp_flat_multiplier_v1",
            "description": "Paired 7-, 30-, and 60-day bootstrap results for 1x through 5x current flat sizing.",
            "sql": "SELECT * FROM multiplier_outcomes ORDER BY horizon_days, multiplier_value",
            "tables_used": ["flat_multiplier_report.sqlite.multiplier_outcomes"],
            "filters": [
                "Formal-Cupcake, Soarin22, and phonesculptor only",
                "Settled MLB full-game moneylines, main +/-1.5 run lines, and main full-game totals",
                "Cross-wallet contradictions excluded",
                "Final 60-day evaluation pool after the existing 30-day warm-up",
                "5,000 paired calendar-day bootstrap paths per horizon",
            ],
            "metric_definitions": [
                "1x is the current weighted formula; 2x through 5x multiply every individual stake after wallet and consensus weighting.",
                "One unit equals 1% of current bankroll; bankroll and stakes compound from $10,000.",
                "P05 and P95 are the fifth and ninety-fifth percentiles of final profit across 5,000 paths.",
                "Maximum observed drawdown is the largest peak-to-trough percentage seen in any of the 5,000 resampled paths, not a forecasted hard limit.",
            ],
        },
    }


def write_database(rows: list[dict]) -> None:
    path = OUT_DIR / "flat_multiplier_report.sqlite"
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        columns = list(rows[0])
        definitions = []
        for column in columns:
            value = rows[0][column]
            definitions.append(f"{column} {'REAL' if isinstance(value, (int, float)) and not isinstance(value, bool) else 'TEXT'}")
        con.execute(f"CREATE TABLE multiplier_outcomes ({', '.join(definitions)})")
        con.executemany(
            f"INSERT INTO multiplier_outcomes ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            [[row[column] for column in columns] for row in rows],
        )
        con.commit()
    finally:
        con.close()


def build_artifact(data: dict, rows: list[dict]) -> dict:
    source = source_record()
    summary = (
        "## Technical Summary\n\n"
        "Increasing the multiplier raises median profit, but downside grows much faster. At 60 days, median profit rises from **$1,351 at 1x** to **$7,844 at 5x**, while median maximum drawdown rises from **4.41%** to **20.80%** and P95 drawdown rises from **7.90%** to **34.78%**. "
        "The 5x arm also produced a **64.49% maximum observed drawdown** in the 5,000-path sample."
    )
    decision = (
        "## Decision Guidance\n\n"
        "The simulation does not support treating 5x as a free profit multiplier. **2x is the most defensible aggressive test point**: it approximately doubles median profit while keeping the 60-day median drawdown below 9% and P95 drawdown near 15%. "
        "Move beyond 2x only if a 20%–35% simulated drawdown is acceptable and operationally survivable."
    )
    limits = (
        "## Limitations\n\n"
        "These are resampled outcomes from 231 evaluation plays, not independent future forecasts. Entry prices are wallet-entry proxies rather than timestamp-perfect executable prices, and slippage is not modeled. "
        "The observed maximum drawdown is sample-dependent and can be exceeded in live trading."
    )
    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "Three-Sharp Flat-Sizing Multiplier Stress Test",
            "description": "Profit ranges and drawdown tradeoffs for 1x through 5x current flat sizing.",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sources": [source],
            "charts": [
                {
                    "id": "profit-chart",
                    "title": "Median simulated profit by sizing multiplier",
                    "subtitle": "Higher exposure compounds returns and losses; all arms receive identical sampled plays.",
                    "type": "bar",
                    "dataset": "multiplier_outcomes",
                    "sourceId": "multiplier-source",
                    "encodings": {
                        "x": {"field": "multiplier", "type": "nominal", "label": "Sizing multiplier"},
                        "y": {"field": "median_profit", "type": "quantitative", "label": "Median profit", "format": "currency"},
                        "color": {"field": "horizon_days", "type": "nominal", "label": "Horizon (days)"},
                        "tooltip": [
                            {"field": "horizon_days", "label": "Days"},
                            {"field": "multiplier", "label": "Multiplier"},
                            {"field": "median_profit", "label": "Median profit", "format": "currency"},
                        ],
                    },
                    "layout": "full",
                },
                {
                    "id": "drawdown-chart",
                    "title": "P95 maximum drawdown by sizing multiplier",
                    "subtitle": "The high-downside drawdown estimate accelerates as exposure increases.",
                    "type": "line",
                    "dataset": "multiplier_outcomes",
                    "sourceId": "multiplier-source",
                    "encodings": {
                        "x": {"field": "multiplier_value", "type": "quantitative", "label": "Sizing multiplier"},
                        "y": {"field": "p95_max_drawdown", "type": "quantitative", "label": "P95 maximum drawdown", "format": "percent"},
                        "color": {"field": "horizon_days", "type": "nominal", "label": "Horizon (days)"},
                        "tooltip": [
                            {"field": "horizon_days", "label": "Days"},
                            {"field": "multiplier", "label": "Multiplier"},
                            {"field": "p95_max_drawdown", "label": "P95 max DD", "format": "percent"},
                        ],
                    },
                    "layout": "full",
                },
            ],
            "tables": [
                {
                    "id": "outcomes-table",
                    "title": "Complete profit and drawdown ranges",
                    "subtitle": "Starting bankroll $10,000; 5,000 paired simulations per horizon.",
                    "dataset": "multiplier_outcomes",
                    "sourceId": "multiplier-source",
                    "layout": "full",
                    "density": "dense",
                    "defaultSort": {"field": "horizon_days", "direction": "asc"},
                    "columns": [
                        {"field": "horizon_days", "label": "Days", "format": "number"},
                        {"field": "multiplier", "label": "Sizing", "type": "text"},
                        {"field": "average_stake_units", "label": "Avg stake", "format": "number", "unit": "u"},
                        {"field": "median_profit", "label": "Median profit", "format": "currency"},
                        {"field": "p05_profit", "label": "P05 profit", "format": "currency"},
                        {"field": "p95_profit", "label": "P95 profit", "format": "currency"},
                        {"field": "probability_profitable", "label": "Profitable paths", "format": "percent"},
                        {"field": "median_max_drawdown", "label": "Median max DD", "format": "percent"},
                        {"field": "p95_max_drawdown", "label": "P95 max DD", "format": "percent"},
                        {"field": "maximum_observed_drawdown", "label": "Worst observed DD", "format": "percent"},
                        {"field": "probability_losing_10_percent", "label": "Finish down 10%+", "format": "percent"},
                    ],
                }
            ],
            "blocks": [
                {"id": "title", "type": "markdown", "layout": "full", "body": "# Three-Sharp Flat-Sizing Multiplier Stress Test"},
                {"id": "summary", "type": "markdown", "layout": "full", "sourceId": "multiplier-source", "body": summary},
                {"id": "table", "type": "table", "tableId": "outcomes-table", "layout": "full"},
                {"id": "profit", "type": "chart", "chartId": "profit-chart", "layout": "full"},
                {"id": "drawdown", "type": "chart", "chartId": "drawdown-chart", "layout": "full"},
                {"id": "decision", "type": "markdown", "layout": "full", "sourceId": "multiplier-source", "body": decision},
                {"id": "limits", "type": "markdown", "layout": "full", "sourceId": "multiplier-source", "body": limits},
            ],
        },
        "snapshot": {"version": 1, "status": "ready", "generatedAt": datetime.now(timezone.utc).isoformat(), "datasets": {"multiplier_outcomes": rows}},
        "sources": [source],
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = rows_from(data)
    write_database(rows)
    artifact = build_artifact(data, rows)
    (OUT_DIR / "artifact.json").write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(OUT_DIR / "artifact.json")


if __name__ == "__main__":
    main()
