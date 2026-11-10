import json
from unittest.mock import Mock

import pytest

from free_play_relay.relay import (
    AmbiguousPost, Discord, RelayError, Store, X, candidate, deliver,
    format_text, image_attachments, poll, validate_text,
)


def play(message_id="10", **overrides):
    return {"id": message_id, "type": 0, "content": "**SLEEPER FREE PLAY**\n\nJames Cook discount slip ⚡\n\n🚀 **3.6X PAYOUT** 💰\n\nTail the play here 👇\nhttps://e.slpr.link/1425669118043901952\n\nLet’s bring it home 🔒💸\n\n@everyone", "attachments": [], **overrides}


def test_approved_example():
    assert format_text(play()["content"]) == "SLEEPER FREE PLAY\n\nJames Cook discount slip ⚡\n\n🚀 3.6X PAYOUT 💰\n\nLet’s bring it home 🔒💸\n\n@OddsJam"


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
    assert format_text("<:sleeper:123> SLEEPER FREE PLAY <:sleeper:123>") == "🪩 SLEEPER FREE PLAY 🪩\n\n@OddsJam"


def test_links_only_are_not_posted():
    assert format_text("Tail the play here 👇\nhttps://example.com\n@everyone") == ""


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
