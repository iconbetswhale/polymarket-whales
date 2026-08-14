from __future__ import annotations

import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "three-sharp-conviction-20000-2026-08-03.json"
OUTPUT = ROOT / "outputs" / "three-sharp-conviction-20000-report.html"


def money(value: float) -> str:
    return f"${value:,.0f}"


def units(value: float) -> str:
    return f"{value:+.2f}u"


def line(points: list[float], width: int, height: int, low: float, high: float) -> str:
    scale = max(high - low, 1.0)
    output = []
    for index, value in enumerate(points):
        x = index / max(len(points) - 1, 1) * width
        y = height - ((value - low) / scale * height)
        output.append(f"{x:.1f},{y:.1f}")
    return " ".join(output)


def build() -> str:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = []
    charts = []
    for days in ("7", "30", "60"):
        simulation = payload["windows"][days]["simulation"]
        observed = payload["windows"][days]["historical_replay"]
        profit = simulation["profit_units_on_initial_bankroll"]
        drawdown = simulation["maximum_drawdown_units"]
        rows.append(
            "<tr>"
            f"<td><strong>{days} days</strong></td>"
            f"<td>{simulation['bets']['median']:.0f}</td>"
            f"<td>{units(profit['median'])}</td>"
            f"<td>{units(profit['p05'])} to {units(profit['p95'])}</td>"
            f"<td>{simulation['probability_profitable']:.1%}</td>"
            f"<td>{drawdown['median']:.2f}u / {drawdown['p95']:.2f}u</td>"
            f"<td>{units(observed['profit_units_on_initial_bankroll'])}</td>"
            "</tr>"
        )
        paths = simulation["percentile_paths"]
        all_values = paths["p05"] + paths["median"] + paths["p95"]
        low, high = min(all_values), max(all_values)
        svg_lines = "".join(
            f'<polyline class="{klass}" points="{line(paths[key], 620, 180, low, high)}" />'
            for key, klass in (("p05", "tail"), ("median", "median"), ("p95", "tail"))
        )
        charts.append(
            f"<article class='chart'><h3>{days}-day bankroll paths</h3>"
            f"<div class='range'>{money(low)} — {money(high)}</div>"
            f"<svg viewBox='0 0 620 180' role='img' aria-label='{days}-day p05 median and p95 bankroll paths'>"
            f"<line x1='0' y1='90' x2='620' y2='90' class='grid'/>{svg_lines}</svg>"
            "<div class='legend'><span class='median-dot'></span>Median <span class='tail-dot'></span>P05 / P95</div></article>"
        )

    tiers = "".join(
        f"<li><strong>{tier['minimum_wallet_units']:g}u+</strong><span>{tier['multiplier']:.2f}×</span></li>"
        for tier in reversed(payload["conviction_tiers"][:-1])
    )
    quality = payload["data_quality"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(payload['title'])}</title>
<style>
:root{{--bg:#071015;--panel:#0d1b23;--line:#1d3440;--text:#f4f8fa;--muted:#8ba0aa;--green:#6ee74d;--cyan:#11b7ec}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 Inter,system-ui,sans-serif}}
main{{max-width:1180px;margin:auto;padding:48px 24px 72px}}.eyebrow{{color:var(--cyan);font-weight:800;letter-spacing:.14em;text-transform:uppercase;font-size:12px}}
h1{{font-size:42px;line-height:1.08;margin:10px 0 12px;max-width:900px}}.lede{{color:var(--muted);font-size:18px;max-width:900px}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:28px 0}}.card,.panel,.chart{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px}}
.card small,.range{{color:var(--muted)}}.card strong{{display:block;color:var(--green);font-size:28px;margin-top:4px}}
h2{{margin-top:36px}}table{{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line)}}th,td{{padding:13px 12px;text-align:right;border-bottom:1px solid var(--line)}}th:first-child,td:first-child{{text-align:left}}th{{color:var(--muted);font-size:12px;text-transform:uppercase}}
.charts{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:18px}}.chart h3{{margin:0}}svg{{width:100%;height:180px;margin-top:12px;overflow:visible}}polyline{{fill:none;vector-effect:non-scaling-stroke}}.median{{stroke:var(--green);stroke-width:3}}.tail{{stroke:#547080;stroke-width:1.5}}.grid{{stroke:#203740}}.legend{{font-size:12px;color:var(--muted)}}.median-dot,.tail-dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin:0 6px 0 12px;background:var(--green)}}.tail-dot{{background:#547080}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:18px}}ul{{padding:0;margin:0;list-style:none}}li{{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--line)}}.note{{color:var(--muted)}}code{{color:#b9d8e5;word-break:break-all}}
@media(max-width:800px){{main{{padding:28px 14px}}h1{{font-size:32px}}.cards,.charts,.two{{grid-template-columns:1fr}}table{{font-size:12px}}th,td{{padding:9px 6px}}}}
</style></head><body><main>
<div class="eyebrow">Decision report · generated {payload['generated_on']}</div>
<h1>Conviction-weighted three-sharp model</h1>
<p class="lede">20,000 seeded calendar-day bootstrap paths per horizon on a {money(payload['starting_bankroll'])} bankroll. Position size is normalized to each sharp’s own historical unit before the capped conviction adjustment is applied.</p>
<section class="cards"><div class="card"><small>Historical source</small><strong>{payload['source_play_count']} bets</strong><span>{payload['source_date_range']['start']} to {payload['source_date_range']['end']}</span></div>
<div class="card"><small>Median historical stake</small><strong>{quality['stake_units']['median']:.2f}u</strong><span>Mean {quality['stake_units']['mean']:.2f}u</span></div>
<div class="card"><small>Relative-size coverage</small><strong>{quality['relative_unit_coverage']:.0%}</strong><span>{quality['capped_at_3u_count']} historical bets hit the 3u cap</span></div></section>
<h2>Outcome summary</h2><table><thead><tr><th>Horizon</th><th>Median bets</th><th>Median profit</th><th>P05–P95 profit</th><th>Profitable</th><th>Median / P95 drawdown</th><th>Actual replay</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<section class="charts">{''.join(charts)}</section>
<section class="two"><article class="panel"><h2>Conviction tiers</h2><ul>{tiers}</ul><p class="note">Base 1.00× below 1.5u. Wallet quality weights and the existing +15%/+30% consensus multipliers remain in place; total stake is capped at 3u.</p></article>
<article class="panel"><h2>Interpretation</h2><p>The 60-day horizon has the strongest simulated reliability, but the paths reuse a limited historical regime. The P05 result is more decision-useful than the maximum observed path. Historical replay is not an executable-price backtest.</p><p class="note">Reproducibility SHA-256:<br><code>{payload['reproducibility_sha256']}</code></p></article></section>
<h2>Scope and caveats</h2><div class="panel"><p>{html.escape(payload['scope'])}</p><p>{html.escape(payload['simulation_method'])}</p><p class="note">{html.escape(payload['entry_price_limitation'])}</p></div>
</main></body></html>"""


if __name__ == "__main__":
    OUTPUT.write_text(build(), encoding="utf-8")
    print(OUTPUT)
