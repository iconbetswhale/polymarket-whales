"""Run the real Sharp Money page locally with synthetic data.

Usage: python local_sharp_money_preview.py
Open:  http://127.0.0.1:8767/sharp-money

This server exposes the Sharp Money and Bet Tracker pages, static files, and a
simulated Sharp Money feed. Sample tracking stays in browser-local storage;
the server never accepts tracker mutations or invokes live bet endpoints.
"""

from __future__ import annotations

import time

from flask import jsonify, redirect, request

from app import create_app
from sharp_money_preview import temporary_sharp_money_preview_payload


def sample_payload() -> dict:
    payload = temporary_sharp_money_preview_payload()
    payload.update(
        {
            "signalMode": "direct_order_book",
            "depthProviders": ["NoVIG", "ProphetX"],
            "advancedOrderBookEnabled": False,
        }
    )
    for signal in payload["signals"]:
        signal["depthAvailable"] = True
        signal["crossedLiquidity"] = signal["liquidity"]
        # The fixture has no actual market links. Keep every row local-only.
        for row in signal["comparisonLines"]:
            row["deepLink"] = ""
            row["oppositeDeepLink"] = ""
            if row["providerKey"] in {"novig", "prophetx"}:
                # The sample sharp has taken the selected side, leaving depth
                # available for a counterparty on the opposing exchange side.
                row["availableLiquidity"], row["oppositeAvailableLiquidity"] = (
                    row["oppositeAvailableLiquidity"], row["availableLiquidity"]
                )
            if row["providerKey"] == "betonlineag":
                row["americanOdds"] = {
                    "Under 8.5": 110,
                    "New York Liberty -4.5": 105,
                    "New York Yankees": 140,
                    "Jannik Sinner -2.5": -105,
                    "Detroit Tigers": 145,
                }[signal["selection"]]
                row["oppositeAmericanOdds"] = {
                    "Under 8.5": -120,
                    "New York Liberty -4.5": -120,
                    "New York Yankees": -155,
                    "Jannik Sinner -2.5": -115,
                    "Detroit Tigers": -160,
                }[signal["selection"]]
        if signal["selection"] == "Under 8.5":
            betonline = next(
                row for row in signal["comparisonLines"]
                if row["providerKey"] == "betonlineag"
            )
            signal["comparisonLines"].append(
                {
                    **betonline,
                    "providerName": "FanDuel",
                    "providerKey": "fanduel",
                    "logoUrl": "/static/assets/sportsbooks/fanduel.png",
                }
            )
        signal["liquiditySources"] = {
            row["providerKey"]: row["oppositeAvailableLiquidity"]
            for row in signal["comparisonLines"]
            if row["providerKey"] in {"novig", "prophetx"}
        }

        selected = signal["selection"]
        away, home = signal["awayTeam"], signal["homeTeam"]
        if signal["market"]["kind"] == "moneyline":
            signal["outcomes"][1]["name"] = home if selected == away else away
        elif signal["market"]["kind"] == "spread":
            line = float(signal["market"]["line"])
            opposite_team = home if selected.startswith(away) else away
            signal["outcomes"][1]["name"] = f"{opposite_team} +{abs(line):g}"
    return payload


def make_preview_app():
    preview_app = create_app(start_background=False)
    preview_app.jinja_env.globals["asset_version"] = f"local-preview-{time.time_ns()}"

    def local_only_gate():
        if request.method not in {"GET", "HEAD"}:
            return jsonify({"error": "Local preview is read-only"}), 405
        if request.path == "/tracker" and request.args.get("preview") != "1":
            return redirect("/tracker?preview=1&view=model&section=bets")
        if request.path in {"/sharp-money", "/tracker", "/api/sharp-money/live"}:
            return None
        if request.path.startswith("/static/"):
            return None
        return jsonify({"error": "Not available in the Sharp Money preview"}), 403

    # Run before the main app's session, tracker, and provider request hooks.
    preview_app.before_request_funcs.setdefault(None, []).insert(0, local_only_gate)

    def no_preview_cache(response):
        response.headers["Cache-Control"] = "no-store"
        if request.path == "/tracker" and response.mimetype == "text/html":
            page = response.get_data(as_text=True)
            stylesheet = '<link rel="stylesheet" href="/static/sharp-money-ledger-preview.css">'
            notice = ('<div class="sharp-local-tracker-notice" role="status">'
                      '<strong>Local sample tracker</strong><span>Fictional plays saved in this browser only. '
                      'No wager was placed or added to your real Bet Tracker.</span></div>')
            page = page.replace('<section class="tracker-page il-data-grid-page">',
                                '<section class="tracker-page il-data-grid-page">' + notice, 1)
            response.set_data(page.replace("</head>", f"{stylesheet}</head>", 1))
        return response

    # Flask runs after-request hooks in reverse order; this override runs last.
    preview_app.after_request_funcs.setdefault(None, []).insert(0, no_preview_cache)

    def sample_feed():
        response = jsonify(sample_payload())
        response.headers["Cache-Control"] = "no-store"
        return response

    preview_app.view_functions["api_sharp_money_live"] = sample_feed
    return preview_app


if __name__ == "__main__":
    make_preview_app().run(host="127.0.0.1", port=8767, debug=False, use_reloader=False)
