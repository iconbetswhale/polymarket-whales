from __future__ import annotations

from discord_notifier import DiscordNotifier


def sample_event(event_type="new_entry", position_size=1250):
    return {
        "event_type": event_type,
        "detected_at": "2026-07-12T17:00:00+00:00",
        "wallet_label": "Trader 1",
        "market_title": "Lakers vs Celtics",
        "outcome": "Yes",
        "position_size_usd": position_size,
        "current_value": 1300,
        "average_entry_price": 0.42,
        "current_price": 0.48,
        "market_url": "https://polymarket.com/event/example",
        "wallet_profile_url": "https://polymarket.com/profile/0xabc",
    }


def test_discord_notifier_filters_disabled_and_small_events():
    disabled = DiscordNotifier(None, {"new_entry"}, 0)
    assert disabled.should_notify(sample_event()) is False

    notifier = DiscordNotifier("https://discord.com/api/webhooks/test", {"new_entry"}, 2000)
    assert notifier.should_notify(sample_event(position_size=1250)) is False
    assert notifier.should_notify(sample_event(position_size=2500)) is True
    assert notifier.should_notify(sample_event(event_type="price_change", position_size=2500)) is False


def test_discord_notifier_posts_embed(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("discord_notifier.requests.post", fake_post)
    notifier = DiscordNotifier("https://discord.com/api/webhooks/test", {"new_entry"}, 0)

    assert notifier.notify(sample_event()) is True
    assert calls[0]["url"] == "https://discord.com/api/webhooks/test"
    assert calls[0]["json"]["username"] == "IconBets Wallet Alerts"
    assert calls[0]["json"]["embeds"][0]["title"] == "Trader 1 opened a new position"
