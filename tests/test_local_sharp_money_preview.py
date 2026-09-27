"""Safety and shape checks for the isolated Sharp Money browser preview."""

from pathlib import Path

from local_sharp_money_preview import make_preview_app


def test_sample_feed_uses_real_page_without_live_endpoints():
    app = make_preview_app()
    client = app.test_client()

    page = client.get("/sharp-money")
    assert page.status_code == 200
    assert b"sharp-money.js" in page.data
    assert b"sharp-money-ledger-preview.css" in page.data
    assert page.headers["Cache-Control"] == "no-store"

    feed = client.get("/api/sharp-money/live")
    assert feed.status_code == 200
    assert feed.headers["Cache-Control"] == "no-store"
    assert feed.json["previewOnly"] is True
    assert feed.json["fabricatedData"] is True
    assert len(feed.json["signals"]) == 5
    assert all(signal["depthAvailable"] for signal in feed.json["signals"])
    assert all(
        not row["deepLink"] and not row["oppositeDeepLink"]
        for signal in feed.json["signals"]
        for row in signal["comparisonLines"]
    )
    first = next(signal for signal in feed.json["signals"] if signal["selection"] == "Under 8.5")
    rows = {row["providerKey"]: row for row in first["comparisonLines"]}
    assert rows["betonlineag"]["americanOdds"] == 110
    assert rows["fanduel"]["americanOdds"] == 110
    assert rows["fanduel"]["americanOdds"] == rows["betonlineag"]["americanOdds"]
    assert rows["betonlineag"]["americanOdds"] > rows["prophetx"]["americanOdds"]
    assert rows["prophetx"]["oppositeAvailableLiquidity"] == 31500
    assert rows["novig"]["oppositeAvailableLiquidity"] == 24300
    assert first["liquiditySources"] == {"prophetx": 31500, "novig": 24300}

    assert client.post("/api/sharp-money/control").status_code == 405
    assert client.post("/api/personal-bets").status_code == 405
    assert client.get("/api/trades").status_code == 403
    assert client.get("/trades").status_code == 403
    assert app.extensions["tracker_service"]._started is False


def test_local_tracker_page_keeps_sample_bets_separate_from_real_tracker():
    app = make_preview_app()
    client = app.test_client()

    nav = client.get("/tracker")
    assert nav.status_code == 302
    assert nav.location.endswith("/tracker?preview=1&view=model&section=bets")

    tracker = client.get("/tracker?preview=1&view=model&section=bets")
    assert tracker.status_code == 200
    assert b"Local sample tracker" in tracker.data
    assert b"No wager was placed or added to your real Bet Tracker" in tracker.data
    assert b"sharp-money-ledger-preview.css" in tracker.data
    assert tracker.headers["Cache-Control"] == "no-store"
    assert client.get("/api/model-tracker").status_code == 403
    assert client.get("/api/personal-tracker").status_code == 403


def test_local_play_card_alignment_and_licensed_tennis_portraits():
    root = Path(__file__).resolve().parents[1]
    css = (root / "static/sharp-money-ledger-preview.css").read_text(encoding="utf-8")
    script = (root / "static/sharp-money.js").read_text(encoding="utf-8")

    assert ".sharp-ledger-head > span:nth-child(4) { text-align: center" in css
    assert ".sharp-ledger-net { color: #53d982; font: 800 20px/1 var(--il-font-ui); white-space: nowrap; text-align: center" in css
    assert ".sharp-ledger-book b { color: #f4f5fa; font-size: 16px; margin-left: 2px; }" in css
    assert '.sharp-ledger-side small { display: block; color: #76dfa2; font: 800 10px' in css
    assert '.sharp-ledger-opposite-line .sharp-ledger-side small { color: #d5a8ff; }' in css
    assert '.sharp-ledger-play-line { background: linear-gradient(90deg,rgba(30,106,66,.26)' in css
    assert '.sharp-ledger-opposite-line { display: grid; grid-template-columns: 230px minmax(0,1fr) 76px 95px;' in css
    assert '.sharp-ledger-books,' in css
    assert '.sharp-ledger-exchanges { grid-column: 2; display: flex; align-items: center; gap: 18px;' in css
    assert '.sharp-ledger-exchanges { grid-column: 1; }' in css
    assert '.sharp-ledger-exchange > span:nth-child(2) { font-size: 19px; }' in css
    assert '.sharp-ledger-exchange b { margin-left: 3px; color: #dbe4e9; font-size: 16px; }' in css
    assert '.sharp-ledger-exchange strong { margin-left: 3px; color: #d0a1fa; font-size: 13px; }' in css
    assert '.sharp-ledger-detail h3 { margin: 0; color: #f0f3f8; font: 800 20px/1.2' in css
    assert '.sharp-ledger-detail p { margin: 5px 0 13px; color: #8795aa; font: 550 14px/1.4' in css
    assert '.sharp-ledger-odds-head { color: #76869b; font: 750 14px/1.2' in css
    assert '.sharp-ledger-depth-item { position: relative; min-height: 36px; color: #d2dae6; font: 650 16px/1.2' in css
    assert '.sharp-ledger-depth-item > span:first-child > span:last-child,' in css
    assert '.sharp-ledger-odds-item > span:first-child > span:last-child { font-size: 18px; }' in css
    assert '.sharp-ledger-depth-item strong small { color: #8d9aac; font-size: 14px; font-weight: 600; text-transform: uppercase; white-space: nowrap;' in css
    assert '.sharp-ledger-depth-item.exchange strong:last-of-type { color: #71dc9b; font-size: 14px; }' in css
    assert '.sharp-ledger-depth-note { display: flex; gap: 7px; margin-top: 12px; color: #8798ae; font: 550 14px/1.35' in css
    assert '.sharp-ledger-odds-item { min-height: 36px; color: #d2dae6; font: 700 16px/1.2' in css
    assert '<small>REC BET</small>' in script
    assert '.sharp-ledger-view-tabs button { display: inline-flex; align-items: center; gap: 6px; min-height: 30px;' in css
    assert 'font: 750 14px/1 var(--il-font-ui);' in css
    assert 'linear-gradient(135deg,rgba(248,250,252,.72),rgba(131,142,158,.34) 52%,rgba(220,225,232,.66)) border-box' in css
    assert 'linear-gradient(135deg,rgba(111,222,159,.62),rgba(156,111,211,.45)) border-box' not in css
    assert '.sharp-search > i { position: absolute;' in css
    assert 'padding: 0 14px 0 40px !important;' in css
    assert 'font: 600 14px/normal var(--il-font-ui);' in css
    assert '.sharp-bankroll-button { min-width: 104px;' in css
    assert '.sharp-bankroll-button small { color: var(--il-text-muted); font: 700 11.5px/1.1 var(--il-font-ui);' in css
    assert '.sharp-bankroll-button strong { color: var(--il-text-primary); font: 700 16px/1.2 var(--il-font-data);' in css
    assert '.sharp-toolbar-unit-size { min-width: 90px;' in css
    assert '.sharp-toolbar-unit-size small { color: var(--il-text-muted); font: 700 10.5px/1.1 var(--il-font-ui);' in css
    assert '.sharp-toolbar-unit-size strong { color: var(--il-text-primary); font: 700 15px/1.2 var(--il-font-data);' in css
    assert '.sharp-profile-button.sharp-icon-button { width: 38px; min-width: 38px; height: 38px; min-height: 38px;' in css
    assert 'border-radius: 50%; background: var(--il-brand-strong);' in css
    assert '.sharp-profile-button .sharp-profile-initial { position: static;' in css
    assert 'background: transparent; color: inherit; font: inherit;' in css
    assert '"Jannik Sinner": {' in script
    assert '"Frances Tiafoe": {' in script
    assert "upload.wikimedia.org/wikipedia/commons/thumb/" in script
    assert "https://creativecommons.org/licenses/by-sa/4.0/" in script
    assert "sharp-ledger-photo-credits" in script
    assert "function primaryQuotes(signal)" in script
    assert "function previewSportsbookLine(quotes)" in script
    assert 'sharp-ledger-book-separator' in script
    assert 'odds(quotes[0].americanOdds)' in script
    assert 'class="sharp-ledger-books"' in script
    assert '.sharp-ledger-book.tied { grid-column: 1 / -1; }' in css
    assert "atptour.com/-/media/alias/player-headshot" not in script


def test_sample_track_button_opens_prefilled_tracker_menu_before_saving():
    root = Path(__file__).resolve().parents[1]
    script = (root / "static/sharp-money.js").read_text(encoding="utf-8")
    tracker_script = (root / "static/app.js").read_text(encoding="utf-8")

    assert "openPreviewTracker(signal, trackButton)" in script
    assert "dialog.showModal()" in script
    assert "Track a sportsbook bet" in script
    assert "sharp-preview-tracker-sportsbook" in script
    assert "sharp-preview-tracker-odds" in script
    assert "sharp-preview-tracker-stake" in script
    assert "sharp-preview-tracker-fees" in script
    assert "sharp-preview-tracker-selected-tags" in script
    assert 'localStorage.setItem(previewTrackedStorageKey, JSON.stringify([trackedBet' in script
    assert 'window.location.assign("/tracker?preview=1&view=model&section=bets")' in script
    assert 'iconlabs-sharp-money-preview-hidden-v1' in script
    assert 'data-preview-list-view="live"' in script
    assert 'data-preview-list-view="hidden"' in script
    assert 'id="sharp-preview-view-tabs"' in (root / "templates/sharp_money.html").read_text(encoding="utf-8")
    template = (root / "templates/sharp_money.html").read_text(encoding="utf-8")
    assert 'id="sharp-bankroll-popover-button"' in template
    assert 'data-account-open' in template
    assert 'class="sharp-filter-dialog"' in template
    assert 'id="sharp-menu-refresh"' in template
    assert 'id="sharp-menu-pause"' in template
    assert 'sharp-ledger-sport' not in script
    assert 'Highest Liquidity' not in script
    assert 'sharp-ledger-toolbar-filter' not in script
    assert 'window.setInterval(() => { if (!state.refreshPaused) load(); }, 30000);' in script
    assert 'localStorage.setItem(previewBankrollStorageKey, String(amount))' in script
    assert 'ph-caret-up' in script
    assert 'ph-caret-down' in script
    assert 'data-preview-restore=' in script
    assert 'Track/Hide <i class="ph ${tracked ? "ph-check" : "ph-plus"}' in script
    assert 'id="sharp-preview-tracker-hide-submit"' in script
    assert 'Track and Hide' in script
    assert 'const hideAfterSave = event.submitter?.id === "sharp-preview-tracker-hide-submit";' in script
    assert 'hidePreviewSignal(signal.id);' in script
    assert '...(Array.isArray(bet.tags) ? bet.tags.filter' in tracker_script
    assert "trackPreviewBet(signal)" not in script
