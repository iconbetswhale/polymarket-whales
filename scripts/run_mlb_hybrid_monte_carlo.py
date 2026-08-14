from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mlb_monte_carlo import SimulationConfig, run_analysis
from scripts.simulate_mlb_wallet_portfolios import run as run_wallet_replay


def percentage(value: Any) -> str:
    return f"{float(value) * 100:.1f}%"


def render_report(result: dict[str, Any]) -> str:
    config = result["configuration"]
    baseline = {
        model: data["BASELINE"]["portfolio"]
        for model, data in result["monte_carlo"].items()
    }
    safest = min(
        baseline,
        key=lambda model: (
            baseline[model]["maximum_drawdown"]["p95"],
            -baseline[model]["median_roi"],
        ),
    )
    preferred = "CONFIDENCE_HALF_KELLY"
    preferred_base = baseline[preferred]
    lines = [
        "# MLB Hybrid Strategy: Execution-Stressed Simulation",
        "",
        f"Generated from {result['sample']['total']} historical hybrid signals.",
        f"Simulation: {config['paths']:,} paths x {config['horizon_calendar_days']} calendar days.",
        "",
        "## Decision",
        "",
        (
            "This is a proxy-risk simulation, not a timestamp-perfect live "
            "backtest. It is useful for comparing sizing and execution stress, "
            "but the absolute ROI remains provisional until forward as-of data exists."
        ),
        "",
        (
            f"The modeled confidence-half-Kelly proxy is profitable in "
            f"{percentage(preferred_base['probability_profitable'])} of baseline "
            f"paths, with median ROI {percentage(preferred_base['median_roi'])} "
            f"and 95th-percentile maximum drawdown "
            f"{percentage(preferred_base['maximum_drawdown']['p95'])}."
        ),
        (
            f"The lowest modeled drawdown choice is {safest.replace('_', ' ').title()}."
        ),
        "",
        "## Sizing Comparison",
        "",
        "| Sizing | Median ROI | Profitable | P95 max DD | P(loss >=20%) |",
        "|---|---:|---:|---:|---:|",
    ]
    for model, metrics in baseline.items():
        lines.append(
            "| "
            + " | ".join(
                [
                    model.replace("_", " ").title(),
                    percentage(metrics["median_roi"]),
                    percentage(metrics["probability_profitable"]),
                    percentage(metrics["maximum_drawdown"]["p95"]),
                    percentage(metrics["probability_losing"]["20_percent"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Stress Sensitivity",
            "",
            "| Stress | Median ROI | Profitable | P95 max DD |",
            "|---|---:|---:|---:|",
        ]
    )
    for stress, data in result["monte_carlo"][preferred].items():
        metrics = data["portfolio"]
        lines.append(
            "| "
            + " | ".join(
                [
                    stress.replace("_", " ").title(),
                    percentage(metrics["median_roi"]),
                    percentage(metrics["probability_profitable"]),
                    percentage(metrics["maximum_drawdown"]["p95"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Bias And Data Status",
            "",
            "Observed: " + ", ".join(result["scope"]["observed_fields"]) + ".",
            "",
            "Modeled: " + ", ".join(result["scope"]["modeled_fields"]) + ".",
            "",
            "Still unavailable: " + ", ".join(result["scope"]["unavailable_fields"]) + ".",
            "",
            (
                "The train/validation/test split is chronological, but wallet "
                "selection itself was informed by this historical dataset. That "
                "remaining selection bias is why forward shadow tracking is required."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "mlb_hybrid_monte_carlo_100k.json",
    )
    parser.add_argument("--wallets", type=Path, default=ROOT / "wallets.json")
    parser.add_argument("--source-report", type=Path)
    parser.add_argument("--output-directory", type=Path)
    args = parser.parse_args()

    config = SimulationConfig.from_json(args.config)
    started = time.perf_counter()
    if args.source_report:
        source = json.loads(args.source_report.read_text(encoding="utf-8"))
    else:
        source = run_wallet_replay(
            args.wallets,
            through_date=config.test_end,
            holdout_start=config.train_end,
            iterations=1_000,
            seed=config.seed,
            include_play_ledger=True,
            provider_cache_dir=(
                ROOT
                / config.output_directory
                / "provider-cache"
            ),
        )
    plays = source["play_ledger"]["HYBRID_CONSENSUS_2"]
    result = run_analysis(plays, config)
    result["runtime_seconds_total"] = round(time.perf_counter() - started, 3)

    output_directory = args.output_directory or ROOT / config.output_directory
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_directory / "executive-summary.md").write_text(
        render_report(result),
        encoding="utf-8",
    )
    source_path = output_directory / "source-replay.json"
    source_path.write_text(
        json.dumps(source, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "paths": config.paths,
                "signals": len(plays),
                "runtime_seconds": result["runtime_seconds_total"],
                "results": str(output_directory / "results.json"),
                "report": str(output_directory / "executive-summary.md"),
                "source": str(source_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
