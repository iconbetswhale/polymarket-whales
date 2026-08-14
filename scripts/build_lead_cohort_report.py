"""Build a bounded Data Analytics report artifact for lead-sharp simulations."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "outputs" / "lead-cohort-30-day-simulation-2026-07-28.json"
OUTPUT_DIR = ROOT / "outputs" / "lead-cohort-report"
OUTPUT = OUTPUT_DIR / "artifact.json"
DATABASE = OUTPUT_DIR / "lead_cohort_report.sqlite"
GENERATED_AT = "2026-07-28T12:00:00-04:00"
SUMMARY_SOURCE_ID = "lead-cohort-summary-query"
THREE_SOURCE_ID = "three-lead-path-query"
FOUR_SOURCE_ID = "four-lead-path-query"


def percentile_rows(cohort_key: str, cohort_label: str, cohort: dict) -> list[dict]:
    simulation = cohort["simulation"]
    historical = cohort["historical"]
    rows: list[dict] = []
    for percentile, values in simulation["daily_bankroll_percentiles"].items():
        if isinstance(values, str):
            values = [float(value) for value in values.split()]
        for day, bankroll in enumerate(values):
            rows.append(
                {
                    "day": day,
                    "percentile": percentile.upper(),
                    "bankroll": round(float(bankroll), 2),
                    "cohort": cohort_label,
                    "wallet_count": len(cohort["wallets"]),
                    "simulations": simulation["simulations"],
                    "starting_bankroll": simulation["starting_bankroll"],
                    "median_bets_30d": simulation["median_bets"],
                    "probability_profitable": simulation["probability_profitable"],
                    "historical_bets": historical["bets"],
                    "observed_bets_per_day": historical["bets_per_calendar_day"],
                    "average_stake_units": historical["average_stake_units"],
                }
            )
    return rows


def summary_row(
    label: str,
    cohort: dict,
    incremental_bets: int = 0,
    incremental_wins: int = 0,
) -> dict:
    historical = cohort["historical"]
    holdout = cohort["july_holdout"]
    stress = cohort["price_stress"]
    simulation = cohort["simulation"]
    final = simulation["final_bankroll"]
    roi = simulation["roi"]
    return {
        "strategy": label,
        "lead_wallets": ", ".join(cohort["wallets"]),
        "historical_bets": historical["bets"],
        "bets_per_day": round(historical["bets_per_calendar_day"], 2),
        "median_bet_per_100": round(historical["median_bet_per_100_bankroll"], 2),
        "average_bet_per_100": round(historical["average_stake_units"], 2),
        "median_initial_bet_10000": round(historical["median_bet_on_10000_bankroll"], 2),
        "historical_roi": historical["stake_weighted_roi"],
        "july_holdout_roi": holdout["stake_weighted_roi"],
        "two_cent_stress_roi": stress["two_cents_worse_roi"],
        "five_cent_stress_roi": stress["five_cents_worse_roi"],
        "median_30d_bets": simulation["median_bets"],
        "probability_profitable": simulation["probability_profitable"],
        "ending_bankroll_p05": round(final["p05"], 2),
        "ending_bankroll_p50": round(final["p50"], 2),
        "ending_bankroll_p95": round(final["p95"], 2),
        "median_30d_roi": roi["p50"],
        "median_30d_profit": round(simulation["median_profit_dollars"], 2),
        "incremental_bets": incremental_bets,
        "incremental_wins": incremental_wins,
        "incremental_losses": incremental_bets - incremental_wins,
    }


def materialize_sqlite(
    summary: list[dict],
    three_paths: list[dict],
    four_paths: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE) as connection:
        connection.execute("DROP TABLE IF EXISTS strategy_summary")
        connection.execute("DROP TABLE IF EXISTS three_lead_paths")
        connection.execute("DROP TABLE IF EXISTS four_lead_paths")

        summary_columns = list(summary[0])
        summary_types = {
            key: "TEXT" if isinstance(summary[0][key], str) else "REAL"
            for key in summary_columns
        }
        connection.execute(
            "CREATE TABLE strategy_summary ("
            + ", ".join(f'"{key}" {summary_types[key]}' for key in summary_columns)
            + ")"
        )
        connection.executemany(
            "INSERT INTO strategy_summary VALUES ("
            + ", ".join("?" for _ in summary_columns)
            + ")",
            [[row[key] for key in summary_columns] for row in summary],
        )

        path_columns = list(three_paths[0])
        path_types = {
            key: "TEXT" if isinstance(three_paths[0][key], str) else "REAL"
            for key in path_columns
        }
        for table_name, rows in (
            ("three_lead_paths", three_paths),
            ("four_lead_paths", four_paths),
        ):
            connection.execute(
                f'CREATE TABLE "{table_name}" ('
                + ", ".join(f'"{key}" {path_types[key]}' for key in path_columns)
                + ")"
            )
            connection.executemany(
                f'INSERT INTO "{table_name}" VALUES ('
                + ", ".join("?" for _ in path_columns)
                + ")",
                [[row[key] for key in path_columns] for row in rows],
            )
        connection.commit()

        connection.row_factory = sqlite3.Row
        selected_summary = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM strategy_summary ORDER BY strategy ASC"
            )
        ]
        selected_three = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM three_lead_paths ORDER BY day ASC, percentile ASC"
            )
        ]
        selected_four = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM four_lead_paths ORDER BY day ASC, percentile ASC"
            )
        ]
    return selected_summary, selected_three, selected_four


def main() -> None:
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    three = payload["cohorts"]["THREE_LEADS"]
    four = payload["cohorts"]["FOUR_LEADS"]

    base_query = {
        "engine": "SQLite",
        "language": "sql",
        "executed_at": GENERATED_AT,
        "filters": [
            "Settled 2026 MLB standard moneylines from March 1 through July 26, 2026",
            "Configured wallet minimum-size thresholds",
            "Clean or minor-hedge lead positions only",
            "Skip exact cohort ties and any eligible lead opposition",
            "5,000 bootstrap paths over 30 calendar days",
        ],
        "metric_definitions": [
            "Stake-weighted ROI = total settled profit divided by total dollars staked.",
            "Median bet per $100 = historical median stake units where 1 unit equals 1% of bankroll.",
            "Probability profitable = share of simulated paths ending above the $10,000 starting bankroll.",
            "Price stress shifts each historical entry probability 2 or 5 cents worse before recalculating settled ROI.",
        ],
    }
    summary_source = {
        "id": SUMMARY_SOURCE_ID,
        "label": "Lead strategy comparison query",
        "path": "outputs/lead-cohort-report/lead_cohort_report.sqlite",
        "query": {
            **base_query,
            "description": (
                "Returns reviewed sizing, frequency, historical ROI, holdout ROI, execution "
                "stress, and simulated outcome metrics for both lead-wallet strategies."
            ),
            "id": "lead_cohort_summary_v1",
            "sql": "SELECT * FROM strategy_summary ORDER BY strategy ASC",
            "tables_used": ["lead_cohort_report.sqlite.strategy_summary"],
        },
    }
    three_source = {
        "id": THREE_SOURCE_ID,
        "label": "Three-lead bankroll percentile paths",
        "path": "outputs/lead-cohort-report/lead_cohort_report.sqlite",
        "query": {
            **base_query,
            "description": (
                "Returns reviewed day-level bankroll percentile paths for the three-lead strategy."
            ),
            "id": "three_lead_paths_v1",
            "sql": (
                "SELECT * FROM three_lead_paths "
                "ORDER BY day ASC, percentile ASC"
            ),
            "tables_used": ["lead_cohort_report.sqlite.three_lead_paths"],
        },
    }
    four_source = {
        "id": FOUR_SOURCE_ID,
        "label": "Four-lead bankroll percentile paths",
        "path": "outputs/lead-cohort-report/lead_cohort_report.sqlite",
        "query": {
            **base_query,
            "description": (
                "Returns reviewed day-level bankroll percentile paths for the four-lead strategy."
            ),
            "id": "four_lead_paths_v1",
            "sql": (
                "SELECT * FROM four_lead_paths "
                "ORDER BY day ASC, percentile ASC"
            ),
            "tables_used": ["lead_cohort_report.sqlite.four_lead_paths"],
        },
    }

    three_ids = {row["condition_id"] for row in three["play_ledger"]}
    incremental_four = [
        row for row in four["play_ledger"] if row["condition_id"] not in three_ids
    ]
    incremental_wins = sum(bool(row["won"]) for row in incremental_four)
    raw_summary = [
        summary_row("Three lead sharps", three),
        summary_row(
            "Four lead sharps",
            four,
            incremental_bets=len(incremental_four),
            incremental_wins=incremental_wins,
        ),
    ]
    three_paths = percentile_rows("THREE_LEADS", "Three lead sharps", three)
    four_paths = percentile_rows("FOUR_LEADS", "Four lead sharps", four)
    summary, three_paths, four_paths = materialize_sqlite(
        raw_summary, three_paths, four_paths
    )
    sources = [summary_source, three_source, four_source]

    manifest = {
        "version": 1,
        "surface": "report",
        "title": "Lead Sharp Strategy Outcomes",
        "description": (
            "Thirty-day scenario ranges for following three versus four lead wallets, "
            "with bankroll, frequency, sizing, ROI, and execution-stress context."
        ),
        "generatedAt": GENERATED_AT,
        "sources": sources,
        "charts": [
            {
                "id": "three-lead-paths",
                "title": "Three-lead 30-day bankroll outcomes",
                "subtitle": (
                    "The median path ends near $10.24k, while the middle 50% spans roughly "
                    "$9.88k to $10.63k."
                ),
                "type": "line",
                "dataset": "three_lead_paths",
                "sourceId": THREE_SOURCE_ID,
                "encodings": {
                    "x": {"field": "day", "type": "quantitative", "label": "Day"},
                    "y": {
                        "field": "bankroll",
                        "type": "quantitative",
                        "format": "currency",
                        "label": "Bankroll",
                    },
                    "color": {
                        "field": "percentile",
                        "type": "nominal",
                        "label": "Outcome percentile",
                    },
                    "tooltip": [
                        {"field": "day", "label": "Day"},
                        {"field": "percentile", "label": "Percentile"},
                        {"field": "bankroll", "format": "currency", "label": "Bankroll"},
                    ],
                },
                "valueFormat": "currency",
                "layout": "full",
            },
            {
                "id": "four-lead-paths",
                "title": "Four-lead 30-day bankroll outcomes",
                "subtitle": (
                    "The median path ends near $11.19k, but this uplift is concentrated in "
                    "an unusually strong 48-bet incremental sample."
                ),
                "type": "line",
                "dataset": "four_lead_paths",
                "sourceId": FOUR_SOURCE_ID,
                "encodings": {
                    "x": {"field": "day", "type": "quantitative", "label": "Day"},
                    "y": {
                        "field": "bankroll",
                        "type": "quantitative",
                        "format": "currency",
                        "label": "Bankroll",
                    },
                    "color": {
                        "field": "percentile",
                        "type": "nominal",
                        "label": "Outcome percentile",
                    },
                    "tooltip": [
                        {"field": "day", "label": "Day"},
                        {"field": "percentile", "label": "Percentile"},
                        {"field": "bankroll", "format": "currency", "label": "Bankroll"},
                    ],
                },
                "valueFormat": "currency",
                "layout": "full",
            },
        ],
        "tables": [
            {
                "id": "strategy-comparison",
                "title": "Strategy comparison",
                "subtitle": (
                    "Automatically selected sizing and frequency, plus historical, holdout, "
                    "stress, and simulated outcomes."
                ),
                "dataset": "strategy_summary",
                "sourceId": SUMMARY_SOURCE_ID,
                "layout": "full",
                "density": "dense",
                "defaultSort": {"field": "strategy", "direction": "asc"},
                "columns": [
                    {"field": "strategy", "label": "Strategy", "type": "text"},
                    {"field": "bets_per_day", "label": "Bets/day", "format": "number"},
                    {
                        "field": "median_bet_per_100",
                        "label": "Median bet / $100",
                        "format": "currency",
                    },
                    {
                        "field": "average_bet_per_100",
                        "label": "Average bet / $100",
                        "format": "currency",
                    },
                    {
                        "field": "median_initial_bet_10000",
                        "label": "Median bet at $10k",
                        "format": "currency",
                    },
                    {
                        "field": "historical_roi",
                        "label": "Historical ROI",
                        "format": "percent",
                    },
                    {
                        "field": "july_holdout_roi",
                        "label": "July holdout ROI",
                        "format": "percent",
                    },
                    {
                        "field": "five_cent_stress_roi",
                        "label": "ROI at +5c worse",
                        "format": "percent",
                    },
                    {
                        "field": "median_30d_bets",
                        "label": "30d median bets",
                        "format": "number",
                    },
                    {
                        "field": "median_30d_roi",
                        "label": "30d median ROI",
                        "format": "percent",
                    },
                    {
                        "field": "probability_profitable",
                        "label": "Profitable paths",
                        "format": "percent",
                    },
                    {
                        "field": "ending_bankroll_p05",
                        "label": "P05 bankroll",
                        "format": "currency",
                    },
                    {
                        "field": "ending_bankroll_p50",
                        "label": "Median bankroll",
                        "format": "currency",
                    },
                    {
                        "field": "ending_bankroll_p95",
                        "label": "P95 bankroll",
                        "format": "currency",
                    },
                ],
            }
        ],
        "blocks": [
            {
                "id": "title",
                "type": "markdown",
                "layout": "full",
                "body": "# Lead Sharp Strategy Outcomes",
            },
            {
                "id": "executive-summary",
                "type": "markdown",
                "layout": "full",
                "sourceId": SUMMARY_SOURCE_ID,
                "body": (
                    "## Executive Summary\n\n"
                    "Using an automatically selected median starting stake of **$0.50 per "
                    "$100 bankroll** (**$50 on $10,000**), the three-lead strategy produces "
                    "a median 30-day ending bankroll of **$10,238.84** (**+2.39%**) with "
                    "**67.44%** of simulated paths profitable. The four-lead strategy produces "
                    "a median of **$11,186.91** (**+11.87%**) with **97.18%** profitable paths. "
                    "Observed frequency is **3.78 bets/day** for three leads and **4.01 bets/day** "
                    "for four leads. The four-lead advantage is promising but fragile: the "
                    "incremental historical slice was 47 wins in 48 plays, so it should be "
                    "forward-tested before being treated as a stable expectation."
                ),
            },
            {
                "id": "comparison-heading",
                "type": "markdown",
                "layout": "full",
                "body": (
                    "## Selected Inputs and Outcome Range\n\n"
                    "The report fixes stake size and daily frequency from observed cohort "
                    "medians rather than exposing user-adjustable assumptions."
                ),
            },
            {
                "id": "comparison-table-block",
                "type": "table",
                "tableId": "strategy-comparison",
                "layout": "full",
            },
            {
                "id": "three-heading",
                "type": "markdown",
                "layout": "full",
                "sourceId": SUMMARY_SOURCE_ID,
                "body": (
                    "## Three Lead Sharps\n\n"
                    "This is the more conservative baseline. Its 30-day median profit is "
                    "**$238.84**, with a 5th-to-95th percentile ending range of "
                    "**$9,393.69 to $11,178.64**. At five cents worse execution, historical "
                    "ROI falls to **-4.76%**, showing that entry quality is material."
                ),
            },
            {
                "id": "three-chart-block",
                "type": "chart",
                "chartId": "three-lead-paths",
                "layout": "full",
            },
            {
                "id": "four-heading",
                "type": "markdown",
                "layout": "full",
                "sourceId": SUMMARY_SOURCE_ID,
                "body": (
                    "## Four Lead Sharps\n\n"
                    "Adding Formal-Cupcake raises the simulated median 30-day profit to "
                    "**$1,186.91** and the 5th-to-95th percentile ending range to "
                    "**$10,150.28 to $12,262.84**. The July holdout ROI is **10.24%**, and "
                    "the five-cent-worse stress ROI remains **7.20%**. These results still "
                    "need prospective validation because the incremental sample is unusually "
                    "strong."
                ),
            },
            {
                "id": "four-chart-block",
                "type": "chart",
                "chartId": "four-lead-paths",
                "layout": "full",
            },
            {
                "id": "recommendations",
                "type": "markdown",
                "layout": "full",
                "body": (
                    "## Recommendation\n\n"
                    "Use the three-lead cohort as the conservative planning baseline. Run the "
                    "four-lead cohort in shadow mode until it accumulates a meaningful forward "
                    "sample at executable two-hour prices and available liquidity. Preserve the "
                    "same bankroll-scaled sizing rule, but block a play when the achievable "
                    "price is materially worse than the simulated entry."
                ),
            },
            {
                "id": "further-questions",
                "type": "markdown",
                "layout": "full",
                "body": (
                    "## Further Questions\n\n"
                    "The next validation should compare closing-line value, two-hour executable "
                    "price, and liquidity-adjusted ROI by wallet, agreement count, favorite versus "
                    "underdog, and price band. That will show whether the fourth lead adds durable "
                    "signal or mainly selects a narrow historical pocket."
                ),
            },
            {
                "id": "caveats",
                "type": "markdown",
                "layout": "full",
                "sourceId": SUMMARY_SOURCE_ID,
                "body": (
                    "## Caveats\n\n"
                    "This is a bootstrap scenario model built from settled positions, not a "
                    "forecast guarantee. It does not reconstruct the exact two-hour executable "
                    "price, exchange fees, slippage, available liquidity, correlated same-game "
                    "risk, or the live model's composite fair price. Historical results may "
                    "contain selection bias. In particular, the four-lead uplift is driven by an "
                    "incremental 48-play slice that finished 47-1, which is too extreme to assume "
                    "will persist."
                ),
            },
        ],
    }

    artifact = {
        "surface": "report",
        "manifest": manifest,
        "snapshot": {
            "version": 1,
            "generatedAt": GENERATED_AT,
            "status": "ready",
            "datasets": {
                "strategy_summary": summary,
                "three_lead_paths": three_paths,
                "four_lead_paths": four_paths,
            },
        },
        "sources": sources,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
