from __future__ import annotations

import logging

from flask import Flask, jsonify, render_template, request

from config import get_settings
from position_tracker import TrackerService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(start_background: bool = True) -> Flask:
    settings = get_settings()
    tracker = TrackerService(settings, auto_start=False)

    app = Flask(__name__)
    app.extensions["tracker_service"] = tracker
    app.config["SETTINGS"] = settings

    @app.before_request
    def ensure_tracker_started():
        if start_background:
            tracker.start()

    @app.route("/")
    def index():
        return render_template("index.html", title="IconBets Polymarket Wallet Tracker")

    @app.route("/history")
    def history():
        return render_template("history.html", title="IconBets Position History")

    @app.route("/health")
    def health():
        snapshot = tracker.get_snapshot()
        status = snapshot["status"]
        return jsonify(
            {
                "app_status": status["app_status"],
                "database_status": status["database"],
                "enabled_wallet_count": status["enabled_wallet_count"],
                "valid_wallet_count": status["valid_wallet_count"],
                "invalid_wallet_count": status["invalid_wallet_count"],
                "last_refresh_attempt": status["last_refresh_attempt"],
                "last_successful_refresh": status["last_successful_refresh"],
                "position_count": status["position_count"],
                "recent_trade_count": status["recent_trade_count"],
                "api_status": status["api_status"],
            }
        )

    @app.route("/api/status")
    def api_status():
        return jsonify(tracker.get_snapshot()["status"])

    @app.route("/api/positions")
    def api_positions():
        snapshot = tracker.get_snapshot()
        return jsonify({"data": snapshot["positions"], "status": snapshot["status"]})

    @app.route("/api/wallets")
    def api_wallets():
        snapshot = tracker.get_snapshot()
        return jsonify({"data": snapshot["wallets"], "status": snapshot["status"]})

    @app.route("/api/trades")
    def api_trades():
        snapshot = tracker.get_snapshot()
        return jsonify({"data": snapshot["trades"], "status": snapshot["status"]})

    @app.route("/api/trades-to-play")
    def api_trades_to_play():
        snapshot = tracker.get_snapshot()
        return jsonify({"data": snapshot.get("trades_to_play", []), "status": snapshot["status"]})

    @app.route("/api/history")
    def api_history():
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 50, type=int)
        return jsonify(tracker.database.get_events_page(page=page, per_page=per_page))

    @app.route("/api/consensus")
    def api_consensus():
        snapshot = tracker.get_snapshot()
        return jsonify({"data": snapshot["consensus"], "status": snapshot["status"]})

    @app.route("/api/unit-analysis")
    def api_unit_analysis():
        snapshot = tracker.get_snapshot()
        return jsonify({"data": snapshot["unit_analysis"], "status": snapshot["status"]})

    return app


app = create_app(start_background=True)


if __name__ == "__main__":
    app.extensions["tracker_service"].start()
    settings = get_settings()
    app.run(host="0.0.0.0", port=settings.dashboard_port, debug=False)
