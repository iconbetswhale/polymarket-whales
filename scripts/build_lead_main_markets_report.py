"""Package the corrected lead-wallet main-market study as a portable report."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "outputs" / "lead-cohort-main-markets-30-day-simulation-2026-07-28.json"
OUT = ROOT / "outputs" / "lead-main-markets-report"
DATABASE = OUT / "lead_main_markets_report.sqlite"
ARTIFACT = OUT / "artifact.json"
GENERATED_AT = "2026-07-29T00:40:00-04:00"


def path_rows(label: str, cohort: dict) -> list[dict]:
    rows = []
    for percentile, values in cohort["simulation"]["daily_bankroll_percentiles"].items():
        if isinstance(values, str):
            values = [float(value) for value in values.split()]
        for day, bankroll in enumerate(values):
            rows.append(
                {
                    "strategy": label,
                    "day": day,
                    "percentile": percentile.upper(),
                    "bankroll": round(float(bankroll), 2),
                }
            )
    return rows


def strategy_row(label: str, cohort: dict) -> dict:
    h = cohort["historical"]
    s = cohort["simulation"]
    return {
        "strategy": label,
        "wallets": ", ".join(cohort["wallets"]),
        "historical_bets": h["bets"],
        "wins": h["wins"],
        "losses": h["losses"],
        "historical_roi": h["stake_weighted_roi"],
        "bets_per_day": h["bets_per_calendar_day"],
        "average_bet_10000": h["average_initial_bet_on_10000"],
        "historical_max_drawdown_units": h["max_drawdown_units"],
        "historical_max_runup_units": h["max_runup_units"],
        "median_30d_bets": s["median_bets"],
        "probability_profitable": s["probability_profitable"],
        "ending_p05": s["final_bankroll"]["p05"],
        "ending_p50": s["final_bankroll"]["p50"],
        "ending_p95": s["final_bankroll"]["p95"],
        "median_30d_roi": s["roi"]["p50"],
        "median_30d_drawdown_units": s["max_drawdown_units"]["p50"],
        "p95_30d_drawdown_units": s["max_drawdown_units"]["p95"],
        "median_30d_runup_units": s["max_runup_units"]["p50"],
        "p95_30d_runup_units": s["max_runup_units"]["p95"],
    }


def market_rows(label: str, cohort: dict) -> list[dict]:
    rows = []
    for market, values in cohort["historical"]["by_market_type"].items():
        rows.append(
            {
                "strategy": label,
                "market": market.title(),
                "bets": values["bets"],
                "wins": values["wins"],
                "losses": values["losses"],
                "win_rate": values["win_rate"],
                "roi": values["stake_weighted_roi"],
                "profit_units": values["profit_units"],
                "max_drawdown_units": values["max_drawdown_units"],
                "max_runup_units": values["max_runup_units"],
            }
        )
    return rows


def write_table(connection: sqlite3.Connection, name: str, rows: list[dict]) -> None:
    columns = list(rows[0])
    types = {
        column: "TEXT" if isinstance(rows[0][column], str) else "REAL"
        for column in columns
    }
    connection.execute(f'DROP TABLE IF EXISTS "{name}"')
    connection.execute(
        f'CREATE TABLE "{name}" ('
        + ", ".join(f'"{column}" {types[column]}' for column in columns)
        + ")"
    )
    connection.executemany(
        f'INSERT INTO "{name}" VALUES ({", ".join("?" for _ in columns)})',
        [[row[column] for column in columns] for row in rows],
    )


def main() -> None:
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    three = payload["cohorts"]["THREE_LEADS"]
    four = payload["cohorts"]["FOUR_LEADS"]
    strategies = [
        strategy_row("Three lead wallets", three),
        strategy_row("Four lead wallets", four),
    ]
    markets = market_rows("Three lead wallets", three) + market_rows(
        "Four lead wallets", four
    )
    wallets = []
    for wallet, audit in payload["data_quality"]["wallets"].items():
        counts = audit["eligible_by_market_type"]
        wallets.append(
            {
                "wallet": wallet,
                "raw_closed": audit["raw_closed_rows"],
                "raw_current": audit["raw_current_rows"],
                "settled_current_added": audit["settled_current_rows_added"],
                "eligible_conditions": audit["eligible_signal_conditions"],
                "moneyline": counts.get("moneyline", 0),
                "spread": counts.get("spread", 0),
                "total": counts.get("total", 0),
            }
        )
    paths = path_rows("Three lead wallets", three) + path_rows(
        "Four lead wallets", four
    )

    OUT.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE) as connection:
        write_table(connection, "strategy_summary", strategies)
        write_table(connection, "market_summary", markets)
        write_table(connection, "wallet_audit", wallets)
        write_table(connection, "bankroll_paths", paths)
        connection.commit()

    base = {
        "engine": "SQLite",
        "language": "sql",
        "executed_at": GENERATED_AT,
        "filters": [
            "MLB positions dated 2026-03-01 through 2026-07-27",
            "Event moneyline, highest-volume full-game ±1.5 run line, and highest-volume full-game total only",
            "Configured wallet minimum-size thresholds after dollar-netting opposing positions",
            "Clean or minor-hedge lead direction; exact cohort ties and eligible opposition excluded",
            "5,000 30-day calendar-day block bootstrap paths",
        ],
        "metric_definitions": [
            "Risked dollars = initialValue, or totalBought shares × avgPrice when initialValue is unavailable.",
            "Stake-weighted ROI = settled profit units ÷ total staked units.",
            "One unit = 1% of current bankroll; the historical sizing proxy is 0.50u plus 0.25u per additional agreeing lead, capped at 1.50u.",
            "Probability profitable = share of simulated paths ending above the $10,000 starting bankroll.",
        ],
    }
    sources = [
        {
            "id": "strategy-source",
            "label": "Corrected strategy summary",
            "path": "outputs/lead-main-markets-report/lead_main_markets_report.sqlite",
            "query": {
                **base,
                "id": "lead_main_markets_strategy_v2",
                "description": "Corrected historical and simulated strategy-level results.",
                "sql": "SELECT * FROM strategy_summary ORDER BY strategy",
                "tables_used": ["lead_main_markets_report.sqlite.strategy_summary"],
            },
        },
        {
            "id": "market-source",
            "label": "Main-market performance",
            "path": "outputs/lead-main-markets-report/lead_main_markets_report.sqlite",
            "query": {
                **base,
                "id": "lead_main_markets_market_v2",
                "description": "Settled performance split by moneyline, main run line, and main total.",
                "sql": "SELECT * FROM market_summary ORDER BY strategy, market",
                "tables_used": ["lead_main_markets_report.sqlite.market_summary"],
            },
        },
        {
            "id": "wallet-source",
            "label": "Four-wallet position reconciliation",
            "path": "outputs/lead-main-markets-report/lead_main_markets_report.sqlite",
            "query": {
                **base,
                "id": "lead_main_markets_wallet_audit_v2",
                "description": "Raw and reconciled source coverage for every configured wallet.",
                "sql": "SELECT * FROM wallet_audit ORDER BY wallet",
                "tables_used": ["lead_main_markets_report.sqlite.wallet_audit"],
            },
        },
        {
            "id": "path-source",
            "label": "Thirty-day bankroll percentile paths",
            "path": "outputs/lead-main-markets-report/lead_main_markets_report.sqlite",
            "query": {
                **base,
                "id": "lead_main_markets_paths_v2",
                "description": "Five percentile paths for both 30-day block-bootstrap simulations.",
                "sql": "SELECT * FROM bankroll_paths ORDER BY strategy, day, percentile",
                "tables_used": ["lead_main_markets_report.sqlite.bankroll_paths"],
            },
        },
    ]

    charts = []
    for chart_id, label in (
        ("three-path", "Three lead wallets"),
        ("four-path", "Four lead wallets"),
    ):
        charts.append(
            {
                "id": chart_id,
                "title": f"{label}: 30-day bankroll outcomes",
                "subtitle": "P05, P25, median, P75, and P95 paths from 5,000 calendar-day block bootstraps.",
                "type": "line",
                "dataset": "bankroll_paths",
                "sourceId": "path-source",
                "transform": [{"type": "filter", "field": "strategy", "eq": label}],
                "encodings": {
                    "x": {"field": "day", "type": "quantitative", "label": "Day"},
                    "y": {
                        "field": "bankroll",
                        "type": "quantitative",
                        "label": "Bankroll",
                        "format": "currency",
                    },
                    "color": {
                        "field": "percentile",
                        "type": "nominal",
                        "label": "Percentile",
                    },
                    "tooltip": [
                        {"field": "day", "label": "Day"},
                        {"field": "percentile", "label": "Percentile"},
                        {"field": "bankroll", "label": "Bankroll", "format": "currency"},
                    ],
                },
                "layout": "full",
            }
        )

    tables = [
        {
            "id": "strategy-table",
            "title": "Corrected strategy comparison",
            "subtitle": "Observed history and resampled 30-day outcome ranges.",
            "dataset": "strategy_summary",
            "sourceId": "strategy-source",
            "layout": "full",
            "density": "dense",
            "defaultSort": {"field": "strategy", "direction": "asc"},
            "columns": [
                {"field": "strategy", "label": "Strategy", "type": "text"},
                {"field": "historical_bets", "label": "Bets", "format": "number"},
                {"field": "bets_per_day", "label": "Bets/day", "format": "number"},
                {"field": "average_bet_10000", "label": "Avg bet at $10k", "format": "currency"},
                {"field": "historical_roi", "label": "Historical ROI", "format": "percent"},
                {"field": "historical_max_drawdown_units", "label": "Historical max DD", "format": "number", "unit": "u"},
                {"field": "historical_max_runup_units", "label": "Historical max run-up", "format": "number", "unit": "u"},
                {"field": "median_30d_bets", "label": "30d median bets", "format": "number"},
                {"field": "median_30d_roi", "label": "30d median ROI", "format": "percent"},
                {"field": "probability_profitable", "label": "Profitable paths", "format": "percent"},
                {"field": "ending_p05", "label": "P05 bankroll", "format": "currency"},
                {"field": "ending_p50", "label": "Median bankroll", "format": "currency"},
                {"field": "ending_p95", "label": "P95 bankroll", "format": "currency"},
            ],
        },
        {
            "id": "market-table",
            "title": "Performance by main market",
            "subtitle": "Spread and total evidence is less wallet-diversified than moneyline evidence.",
            "dataset": "market_summary",
            "sourceId": "market-source",
            "layout": "full",
            "density": "dense",
            "defaultSort": {"field": "strategy", "direction": "asc"},
            "columns": [
                {"field": "strategy", "label": "Strategy", "type": "text"},
                {"field": "market", "label": "Market", "type": "text"},
                {"field": "bets", "label": "Bets", "format": "number"},
                {"field": "wins", "label": "Wins", "format": "number"},
                {"field": "losses", "label": "Losses", "format": "number"},
                {"field": "win_rate", "label": "Win rate", "format": "percent"},
                {"field": "roi", "label": "ROI", "format": "percent"},
                {"field": "profit_units", "label": "Profit", "format": "number", "unit": "u"},
                {"field": "max_drawdown_units", "label": "Max DD", "format": "number", "unit": "u"},
                {"field": "max_runup_units", "label": "Max run-up", "format": "number", "unit": "u"},
            ],
        },
        {
            "id": "wallet-table",
            "title": "Wallet-source reconciliation",
            "subtitle": "Settled current rows are added when the public closed feed omits them.",
            "dataset": "wallet_audit",
            "sourceId": "wallet-source",
            "layout": "full",
            "density": "dense",
            "defaultSort": {"field": "wallet", "direction": "asc"},
            "columns": [
                {"field": "wallet", "label": "Wallet", "type": "text"},
                {"field": "raw_closed", "label": "Raw closed", "format": "number"},
                {"field": "raw_current", "label": "Raw current", "format": "number"},
                {"field": "settled_current_added", "label": "Settled rows added", "format": "number"},
                {"field": "eligible_conditions", "label": "Eligible signals", "format": "number"},
                {"field": "moneyline", "label": "Moneyline", "format": "number"},
                {"field": "spread", "label": "Spread", "format": "number"},
                {"field": "total", "label": "Total", "format": "number"},
            ],
        },
    ]

    blocks = [
        {"id": "title", "type": "markdown", "layout": "full", "body": "# Corrected Lead-Wallet MLB Main-Market Study"},
        {
            "id": "summary",
            "type": "markdown",
            "layout": "full",
            "sourceId": "strategy-source",
            "body": (
                "## Technical Summary\n\n"
                "After reconciling all accessible settled positions, the **three-wallet** strategy contains "
                "**797 bets** and returned **1.99% historically**; its median 30-day ending bankroll is "
                "**$10,155.89**, with **57.88%** of paths profitable. The **four-wallet** strategy contains "
                "**809 bets** and returned **4.26% historically**; its median ending bankroll is "
                "**$10,397.12**, with **69.86%** of paths profitable. This replaces the invalid prior "
                "47–1 incremental claim."
            ),
        },
        {"id": "strategy-block", "type": "table", "tableId": "strategy-table", "layout": "full"},
        {
            "id": "findings",
            "type": "markdown",
            "layout": "full",
            "sourceId": "market-source",
            "body": (
                "## Key Findings\n\n"
                "Moneylines were modestly positive (**1.72%** three-wallet; **4.76%** four-wallet). "
                "Main totals were strongest at **10.67% ROI** across **160 bets**. Main ±1.5 run lines "
                "lost **22.82%** across **49 bets**. Totals came only from Wordylittleneck in the eligible "
                "sample, and spreads came only from Soarin22 and Wordylittleneck, so those splits are not "
                "four-wallet consensus evidence."
            ),
        },
        {"id": "market-block", "type": "table", "tableId": "market-table", "layout": "full"},
        {"id": "three-chart", "type": "chart", "chartId": "three-path", "layout": "full"},
        {"id": "four-chart", "type": "chart", "chartId": "four-path", "layout": "full"},
        {
            "id": "scope",
            "type": "markdown",
            "layout": "full",
            "body": (
                "## Scope and Data Definitions\n\n"
                "The audit covers reconciled settled MLB positions dated March 1 through July 27, 2026. "
                "Moneyline means the event-level full-game market. Main spread means the highest-lifetime-"
                "volume full-game ±1.5 market in Gamma metadata; first-five and alternate spreads are excluded. "
                "Main total means the highest-lifetime-volume full-game total; first-five and alternate totals "
                "are excluded."
            ),
        },
        {"id": "wallet-block", "type": "table", "tableId": "wallet-table", "layout": "full"},
        {
            "id": "method",
            "type": "markdown",
            "layout": "full",
            "body": (
                "## Methodology\n\n"
                "Closed positions were deduplicated by token. Settled redeemable current positions missing from "
                "the closed feed were then added, preserving unredeemed zero-value losses. Risk was measured as "
                "`initialValue`, or shares × average price when unavailable, and opposing sides were netted in "
                "dollars before wallet thresholds. A play requires an eligible clean/minor-hedge lead direction, "
                "with exact cohort ties or eligible opposition excluded. Entry price is the median average price "
                "among agreeing leads. The 30-day ranges use 5,000 calendar-day block bootstraps, preserving "
                "same-day multi-market clustering."
            ),
        },
        {
            "id": "limitations",
            "type": "markdown",
            "layout": "full",
            "body": (
                "## Limitations and Robustness\n\n"
                "Position snapshots do not reconstruct the executable two-hour price, fees, slippage, liquidity, "
                "or true pregame timing. Lifetime volume is only a proxy for identifying the main historical market. "
                "The fourth wallet creates **33 genuinely new plays**, finishing **21–12** at **52.46% historical "
                "ROI**; that increment is encouraging but small and moneyline-only. Bootstrap paths describe "
                "resampled history, not a guarantee or causal estimate."
            ),
        },
        {
            "id": "recommendation",
            "type": "markdown",
            "layout": "full",
            "body": (
                "## Recommended Next Steps\n\n"
                "Use the corrected four-wallet cohort as the stronger research candidate, but forward-test it "
                "before promotion. Keep spreads out of production until executable-price replay shows a positive "
                "edge. Test totals separately because their result is positive but comes from one wallet. Capture "
                "two-hour executable price, liquidity, fees, and CLV prospectively, then rerun by market and "
                "supporter count."
            ),
        },
        {
            "id": "questions",
            "type": "markdown",
            "layout": "full",
            "body": (
                "## Further Questions\n\n"
                "Does the fourth wallet remain additive after 100–200 forward plays? Do two-lead agreements retain "
                "their historical advantage after execution costs? Are totals genuinely transferable beyond one "
                "wallet, and can main-run-line losses be explained by price, side, or timing?"
            ),
        },
    ]

    manifest = {
        "version": 1,
        "surface": "report",
        "title": "Corrected Lead-Wallet MLB Main-Market Study",
        "description": "Four-wallet reconciliation and corrected three- versus four-lead MLB simulations.",
        "generatedAt": GENERATED_AT,
        "sources": sources,
        "charts": charts,
        "tables": tables,
        "blocks": blocks,
    }
    artifact = {
        "surface": "report",
        "manifest": manifest,
        "snapshot": {
            "version": 1,
            "generatedAt": GENERATED_AT,
            "status": "ready",
            "datasets": {
                "strategy_summary": strategies,
                "market_summary": markets,
                "wallet_audit": wallets,
                "bankroll_paths": paths,
            },
        },
        "sources": sources,
    }
    ARTIFACT.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(ARTIFACT)


if __name__ == "__main__":
    main()
