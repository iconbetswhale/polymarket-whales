# Discord free plays to X

Dedicated worker for IconBets channel `1464472206334496829` in server
`1255342800258596898`, publishing to `@TheBakerr_` with `@OddsJam`.
It does not change the IconLabs web app, deploy manifest, or existing bots.

Optional Icon Wins support watches channel `1473901847009034383` in the same
server. Enable it with `RELAY_ICON_WINS_ENABLED=true`. Only `_thebakerr`'s
Discord author ID `1288282611034226709` and `CASH ... PLAY POSTED IN VIP`
headings qualify. Other authors, chatter, and wins for the Free Plays channel
are skipped. The owner will quote winning free-play tweets manually; no automatic
quote-posting or replies are enabled.

VIP win tweets use the platform name and approved emoji, 📈, the source's exact
listed payout, the original promotional text/code, and the cashed-slip image.
Markdown links become their label text, the orphaned 🔗 becomes 👇 on the BAKER25
promotion, and `@OddsJam` appears once at the end. One blank line separates each
text line. Missing/ambiguous payout amounts or missing cashed-slip attachments
pause that channel for review. This preserves the message's listed payout; it
does not perform OCR to compare the image against that text.

Each channel has an independent cursor and queue. The original `cursor` key and
legacy jobs remain assigned to Free Plays during the schema migration. First
activation of Icon Wins starts at its newest message, leaving existing wins
unpublished. A blocked win does not block Free Plays delivery.

## Output

New ordinary/reply messages containing `free play` (case insensitive) qualify,
including posts authored by bots or webhooks. Other channel chatter is skipped.
Preserves text, blank lines, normal emojis and up to four JPEG/PNG/WebP attachments.
Removes HTTP/HTTPS URLs, bare domains, Discord mentions, Markdown emphasis and
orphaned “tail here” instructions. Custom PrizePicks emojis become 🟣; Sleeper
emojis become 💤, Dabble uses 🟣, Underdog uses 🐶, and Chalkboard uses ⚪.
Standard platform `FREE PLAY` headings always receive the chosen emoji on both
sides, even without custom Discord emojis. Unsupported custom emojis are removed.
Every nonempty text line is separated by exactly one blank line. Adds `@OddsJam` once.

An independent final URL check rejects any URL left in the text. Posts over the
conservative weighted 280-character limit, unsupported attachments, and images
over 5 MB pause delivery for manual review instead of truncating or losing media.
Embed-only images and video/GIF posts are not supported by this first version.

## Configure

Install `python -m pip install -r free_play_relay/requirements.txt`.
Keep credentials in root `.env.local` (Git ignored) or process environment:

```
FREE_PLAY_DISCORD_BOT_TOKEN=...
X_API_KEY=...
X_API_SECRET=...
X_ACCESS_TOKEN=...
X_ACCESS_TOKEN_SECRET=...
RELAY_POSTING_ENABLED=false
RELAY_POLL_SECONDS=30
RELAY_STATE_PATH=/persistent/path/free-play-relay.sqlite3
RELAY_LOG_PATH=/persistent/path/free-play-relay.log
```

The dedicated Discord bot needs Message Content Intent enabled, and View Channel
plus Read Message History in the source channel. It needs no send-message,
administrator, moderation, or webhook permissions. Limit its channel visibility
to the intended channel in Discord's channel permissions.

X OAuth 1.0a credentials need read-and-write access for `@TheBakerr_`. The worker
verifies the destination username at startup. No direct-message access is used.
X must have sufficient prepaid credits; posting and verification may be billed.
Do not enable automatic recharge without the account owner's explicit approval.

## Run

From the repository root:

```
python -m free_play_relay.relay preview
python -m free_play_relay.relay preview --channel icon-wins
python -m free_play_relay.relay check
python -m free_play_relay.relay status
```

`preview` reads a recent qualifying play and prints the transformed text and image
count without posting or modifying the cursor. `check` verifies Discord channel
and X account without posting. After review and funding, set
`RELAY_POSTING_ENABLED=true`, then run:

```
python -m free_play_relay.relay run
```

First run starts at the newest Discord message and never publishes old history.
Subsequent polls queue every new qualifying play, including across restarts.
Polling is 30 seconds by default. Keep the worker running on an awake computer or
an always-on worker host with a persistent state file. Local execution stops when
the computer sleeps, signs out or shuts down. This repository does not provision
hosting or create a paid service automatically. On Windows, a current-user Task
Scheduler logon task can launch `pythonw.exe -m free_play_relay.relay run` with the
repository root as its working directory. Set `RELAY_LOG_PATH` for a background
worker; its output otherwise has no visible console. Configure the task to allow
battery operation, have no execution time limit, and restart on failure. It runs
only while that user is signed in; this is not cloud hosting.

## Delivery and recovery

SQLite cursor updates and queue inserts share a transaction. A primary key on
the Discord message ID and an atomic claim prevent duplicate jobs and concurrent
delivery. Retain this database across deployments; deleting it loses the ledger.

The X create-post request is attempted once. A timeout, server error, or incomplete
success response leaves an `uncertain` job. A worker crash after claim leaves
`sending`. These states pause further deliveries until someone checks the X
timeline and updates that job deliberately. A definite delivery failure leaves
`blocked`; fix credentials, credits, text, or media, then deliberately requeue.
There is no automatic resend of a potentially accepted post. Exact-once delivery
cannot be guaranteed across an external X request and a local database commit.

Inspect status without opening secrets: `python -m free_play_relay.relay status`.
If a post already exists, record its X ID and mark the job `sent`. If a definitive
failure occurred before posting, mark it `pending` only after resolving the cause.
Do not blindly reset `sending` or `uncertain` jobs. Attachment URLs are refreshed
from the original message before upload; captured play text is retained.

Run focused offline tests with `python -m pytest free_play_relay/test_relay.py -q`.
