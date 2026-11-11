import json
from unittest.mock import Mock

import pytest

from free_play_relay.relay import (
    AmbiguousPost, Discord, RelayError, Store, X, candidate, deliver,
    CHANNEL_ID, WINS_CHANNEL_ID, WINS_AUTHOR_ID, format_message,
    api_failure, safe_error, format_text, image_attachments, poll, validate_text,
)


def win(message_id="20", platform="underdog", payout="3.5", **overrides):
    return {"id": message_id, "channel_id": WINS_CHANNEL_ID, "type": 0,
            "author": {"id": WINS_AUTHOR_ID},
            "content": f'**CASH THE <@&1473834953996505189> <:{platform}:123> PLAY POSTED IN VIP**🐶\n\n✅ {payout}X PAYOUT💰\n\n[**GET 25% OFF VIP DFS/SPORTSBOOK/EXCHANGE PLAYS WITH CODE “BAKER25” **](https://example.com/join) 🔗\n\n@everyone',
            "attachments": [{"id": "image1", "content_type": "image/png", "size": 100, "url": "https://cdn.discordapp.com/test.png"}], **overrides}


@pytest.mark.parametrize("platform,symbol", [("sleeper", "💤"), ("prizepicks", "🟣"), ("dabble", "🟣"), ("underdog", "🐶"), ("chalkboard", "⚪")])
@pytest.mark.parametrize("payout", ["3.5", "10", "3.25"])
def test_vip_win_format_and_actual_payout(platform, symbol, payout):
    text = format_message(win(platform=platform, payout=payout))
    assert text == f'CASH THE {platform.upper()} PLAY POSTED IN VIP{symbol}📈\n\n✅ {payout}X PAYOUT💰\n\nGET 25% OFF VIP DFS/SPORTSBOOK/EXCHANGE PLAYS WITH CODE “BAKER25”👇\n\n@OddsJam'


def test_vip_wins_only_from_baker_and_not_free_play_wins():
    assert candidate(win())
    assert not candidate(win(author={"id": "another-person"}))
    assert not candidate(win(content=win()["content"].replace("IN VIP", f"IN <#{CHANNEL_ID}>")))
    assert not candidate(win(content=win()["content"].replace("IN VIP", "IN FREE PLAYS")))
    assert not candidate(win(content="Nice hit!"))
    assert not candidate(win(type=6))


def test_win_requires_unambiguous_payout_and_image():
    with pytest.raises(RelayError):
        format_message(win(content=win()["content"].replace("3.5X PAYOUT", "PAYOUT")))
    with pytest.raises(RelayError):
        format_message(win(content=win()["content"] + "\n10X PAYOUT"))
    with pytest.raises(RelayError):
        format_message(win(attachments=[]))


def test_independent_channel_cursors_and_history_skip(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    store.ingest([], "10")
    discord = Mock()
    discord.newest.return_value = [win()]
    poll(discord, store, WINS_CHANNEL_ID)
    assert store.cursor() == "10"
    assert store.cursor(WINS_CHANNEL_ID) == "20"
    assert store.claim(WINS_CHANNEL_ID) is None
    store.ingest([win("21")], "21", WINS_CHANNEL_ID)
    assert store.claim() is None
    assert store.claim(WINS_CHANNEL_ID)["id"] == "21"


def test_wins_failure_does_not_block_free_play_delivery(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    store.ingest([win()], "20", WINS_CHANNEL_ID)
    assert store.claim(WINS_CHANNEL_ID)
    store.finish("20", "blocked", error="manual review")
    store.ingest([play()], "10")
    x = Mock(spec=["post", "upload"])
    x.post.return_value = "1234"
    deliver(store, x)
    assert store.problems(WINS_CHANNEL_ID)
    assert not store.problems(CHANNEL_ID)
    x.post.assert_called_once()


def test_win_delivery_refreshes_attachment_from_wins_channel(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    store.ingest([win()], "20", WINS_CHANNEL_ID)
    x = Mock(spec=["post", "upload", "discord"])
    x.discord.get.return_value = win()
    x.upload.return_value = "image-id"
    x.post.return_value = "tweet-id"
    deliver(store, x, WINS_CHANNEL_ID)
    x.discord.get.assert_called_once_with(f"/channels/{WINS_CHANNEL_ID}/messages/20")
    x.post.assert_called_once_with(format_message(win()), ["image-id"])
    assert store.db.execute("SELECT status,post_id FROM jobs WHERE id='20'").fetchone()[:] == ("sent", "tweet-id")


def test_old_database_migration_retains_cursor_and_jobs(tmp_path):
    import sqlite3
    path = tmp_path / "state.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL); INSERT INTO metadata VALUES('cursor','99'); CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',post_id TEXT,error TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);")
    db.execute("INSERT INTO jobs(id,payload) VALUES (?,?)", ("10", json.dumps(play())))
    db.commit()
    db.close()
    store = Store(path)
    assert store.cursor() == "99"
    assert store.cursor(WINS_CHANNEL_ID) is None
    assert store.claim()["channel_id"] == CHANNEL_ID


def play(message_id="10", **overrides):
    return {"id": message_id, "type": 0, "content": "**SLEEPER FREE PLAY**\n\nJames Cook discount slip ⚡\n\n🚀 **3.6X PAYOUT** 💰\n\nTail the play here 👇\nhttps://e.slpr.link/1425669118043901952\n\nLet’s bring it home 🔒💸\n\n@everyone", "attachments": [], **overrides}


def test_approved_example():
    assert format_text(play()["content"]) == "💤 SLEEPER FREE PLAY 💤\n\nJames Cook discount slip ⚡\n\n🚀 3.6X PAYOUT 💰\n\nLet’s bring it home 🔒💸\n\n@OddsJam"


@pytest.mark.parametrize("link", ["https://e.slpr.link/123", "http://example.com", "www.example.com/test", "prizepicks.onelink.me/gCQS/shareEntry?a=b", "[Click](https://example.com)", "<https://example.com>"])
def test_no_links_survive(link):
    text = format_text("FREE PLAY\n" + link + "\n@everyone <@123> <@&456>\n@OddsJam")
    assert "http" not in text
    assert "example.com" not in text
    assert "onelink" not in text
    assert "@everyone" not in text
    assert text.count("@OddsJam") == 1


def test_custom_emojis_and_tail_line():
    assert format_text("<:prizepicks:123> **PRIZEPICKS FREE PLAY** <:prizepicks:123>\n\nTail it here👇\nhttps://example.com") == "🟣 PRIZEPICKS FREE PLAY 🟣\n\n@OddsJam"
    assert format_text("<:sleeper:123> SLEEPER FREE PLAY <:sleeper:123>") == "💤 SLEEPER FREE PLAY 💤\n\n@OddsJam"


@pytest.mark.parametrize("platform,symbol", [("SLEEPER", "💤"), ("PRIZEPICKS", "🟣"), ("DABBLE", "🟣"), ("UNDERDOG", "🐶"), ("CHALKBOARD", "⚪")])
@pytest.mark.parametrize("decoration", ["", "<:custom:123>", "🪩"])
def test_platform_headers_and_blank_line_spacing(platform, symbol, decoration):
    content = f"{decoration} **{platform} FREE PLAY**{decoration}\nFirst line\nSecond line\n\n\nThird line\n@OddsJam"
    assert format_text(content) == f"{symbol} {platform} FREE PLAY {symbol}\n\nFirst line\n\nSecond line\n\nThird line\n\n@OddsJam"


def test_links_only_are_not_posted():
    assert format_text("Tail the play here 👇\nhttps://example.com\n@everyone") == ""


@pytest.mark.parametrize("instruction", ["Get your entry in 👇", "Lock in your picks👇", "[LINK](https://example.com)", "Go get it for FREE ⏬"])
def test_platform_link_instructions_removed(instruction):
    assert format_text("FREE PLAY\n\n" + instruction + "\nhttps://example.com\n\nLet’s get this money 💸🔒") == "FREE PLAY\n\nLet’s get this money 💸🔒\n\n@OddsJam"


def test_length_and_url_guards():
    with pytest.raises(RelayError):
        validate_text("FREE PLAY https://example.com")
    with pytest.raises(RelayError):
        format_text("FREE PLAY\n" + "a" * 300)


def test_candidates_exclude_chatter_but_include_bot_plays():
    assert candidate(play(author={"bot": True}))
    assert not candidate(play(content="nice hit!"))
    assert not candidate(play(type=6))


def test_media_never_silently_dropped():
    with pytest.raises(RelayError):
        image_attachments({"attachments": [{"content_type": "video/mp4"}]})
    with pytest.raises(RelayError):
        image_attachments({"attachments": [{"content_type": "image/png", "size": 6_000_000}]})


def test_first_run_skips_history(tmp_path):
    discord = Mock()
    discord.newest.return_value = [play()]
    store = Store(tmp_path / "state.sqlite3")
    poll(discord, store)
    assert store.cursor() == "10"
    assert store.claim() is None


def test_restart_duplicate_and_concurrent_claim(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = Store(path)
    store.ingest([play()], "10")
    store.ingest([play()], "10")
    other = Store(path)
    assert store.claim()["id"] == "10"
    assert other.claim() is None
    assert other.problems()[0]["status"] == "sending"


def test_success_not_reposted(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    store.ingest([play()], "10")
    x = Mock(spec=["post", "upload"])
    x.post.return_value = "1234"
    deliver(store, x)
    deliver(store, x)
    x.post.assert_called_once()
    assert store.db.execute("SELECT status,post_id FROM jobs").fetchone()[:] == ("sent", "1234")


def test_unknown_post_outcome_pauses_delivery(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    store.ingest([play(), play("11")], "11")
    x = Mock(spec=["post", "upload"])
    x.post.side_effect = AmbiguousPost("timeout")
    with pytest.raises(AmbiguousPost):
        deliver(store, x)
    with pytest.raises(RelayError):
        deliver(store, x)
    x.post.assert_called_once()
    assert store.problems()[0]["status"] == "uncertain"


def test_failed_upload_does_not_post_text_alone(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    store.ingest([play(attachments=[{"id": "1", "content_type": "image/png", "size": 200, "url": "https://cdn.discordapp.com/test.png"}])], "10")
    x = Mock(spec=["post", "upload"])
    x.upload.side_effect = RelayError("upload failed")
    with pytest.raises(RelayError):
        deliver(store, x)
    x.post.assert_not_called()
    assert store.problems()[0]["error"] == "uploading images: upload failed"


def test_publishing_failure_retains_api_diagnostic(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    store.ingest([play()], "10")
    x = Mock(spec=["post", "upload"])
    response = Mock(status_code=403)
    response.json.return_value = {"title": "Forbidden", "detail": "Publishing access is restricted"}
    x.post.side_effect = api_failure(response, "X create post")
    with pytest.raises(RelayError, match="publishing tweet: X create post HTTP 403"):
        deliver(store, x)
    assert "Publishing access is restricted" in store.problems()[0]["error"]
    with pytest.raises(RelayError, match="Publishing access is restricted"):
        deliver(store, x)
    x.post.assert_called_once()


def test_api_diagnostics_redact_credentials_and_signed_urls(monkeypatch):
    monkeypatch.setenv("X_ACCESS_TOKEN", "private-token-value")
    response = Mock(status_code=401)
    response.json.return_value = {"detail": "Denied private-token-value https://example.com/image?secret=value", "errors": [{"message": "Token rejected"}]}
    error = str(api_failure(response, "X media upload"))
    assert "Token rejected" in error
    assert "private-token-value" not in error
    assert "secret=value" not in error
    import requests
    assert safe_error(requests.Timeout("https://example.com/private-token-value")) == "Network failure (Timeout)"


def test_pagination_catches_more_than_100(tmp_path):
    discord = Discord("test")
    discord.get = Mock(side_effect=[
        [play(str(i)) for i in range(250, 150, -1)],
        [play(str(i)) for i in range(150, 50, -1)],
        [play(str(i)) for i in range(50, 0, -1)],
    ])
    assert [m["id"] for m in discord.since("10")] == [str(i) for i in range(11, 251)]
    assert discord.get.call_args_list[1].kwargs["before"] == "151"


def test_x_timeout_is_ambiguous():
    import requests
    x = X.__new__(X)
    x.session = Mock()
    x.session.post.side_effect = requests.Timeout()
    with pytest.raises(AmbiguousPost):
        x.post("FREE PLAY\n\n@OddsJam", [])
    assert x.session.post.call_count == 1
