# be-everywhere-bot

A small Python app that **mesh-syncs** your posts across **X (Twitter)**, **Threads**, **Bluesky**, **Telegram**, **Mastodon**, **Instagram**, **LinkedIn**, and **RSS feeds**. When a new post appears on any connected account, it is reposted to every other account. The bot tracks what was already synced so nothing is duplicated — including posts it created itself (so a Twitter thread reposted to Telegram is never echoed back to Twitter).

## Features

- **Mesh sync** — every configured account syncs to every other
- **Multiple accounts per network** — connect several Twitter/Telegram/Mastodon accounts with `--label`
- **Thread support** — consecutive posts in the same conversation are merged when the destination allows
- **Duplicate protection** — `sync_mappings` + `mirrored_posts` prevent re-syncing and circular reposts
- **Smart filtering** (X) — skips retweets, quote tweets, `@`-replies, and replies to other people
- **Source-only marker** — append `/x` to a post to keep it on that network only (not mesh-synced)
- **Link unwrapping** — `t.co` and other shorteners are resolved before posting
- **Token renewal** — Meta (Threads, Instagram) 60-day tokens are refreshed automatically before they expire

## Requirements

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** (recommended)
- API credentials for each network you want to connect

## Quick start

```bash
git clone <repo-url> be-everywhere-bot
cd be-everywhere-bot
uv sync

# Configure accounts (repeat with different --label for multiple accounts)
uv run python main.py --auth=twitter
uv run python main.py --auth=telegram
uv run python main.py --auth=mastodon
uv run python main.py --auth=threads
uv run python main.py --auth=bluesky
uv run python main.py --auth=rss
uv run python main.py --auth=instagram
uv run python main.py --auth=linkedin

# Run continuous mesh sync
uv run python main.py
```

## Setup

### Connect accounts

```bash
uv run python main.py --auth=twitter --label=personal
uv run python main.py --auth=twitter --label=work
uv run python main.py --auth=telegram --label=main
uv run python main.py --auth=mastodon --label=fedi
uv run python main.py --auth=threads --label=main
uv run python main.py --auth=bluesky --label=main
uv run python main.py --auth=rss --label=blog
uv run python main.py --auth=instagram --label=main
uv run python main.py --auth=linkedin --label=main
```

Re-running `--auth` with the same network + label updates credentials.

Re-running `--auth` with the same network + label updates credentials.

Use `--label` to connect multiple accounts on the same network (e.g. personal and work Twitter).

---

### X (Twitter)

**Portal:** [developer.x.com](https://developer.x.com/en/portal/dashboard)

**What you need:** Bearer Token + your `@handle`

**Steps:**

1. Sign in at the [X Developer Portal](https://developer.x.com/en/portal/dashboard).
2. Create a **Project** and an **App** (or open an existing app).
3. Open the app → **Keys and tokens** tab.
4. Under **Bearer Token**, click **Generate** or **Regenerate** and copy the token.
5. Note your X username without `@` (e.g. `vas3k`).
6. Run `uv run python main.py --auth=twitter --label=main` and paste the token and username when prompted.

**Notes:** X API v2 is pay-per-use (~$0.001 per owned timeline read). Watch mode only polls recent posts to limit cost. Top up credits at the [developer portal](https://developer.x.com/en/portal/dashboard) if you get HTTP 402.

---

### Telegram

**Portals:** [@BotFather](https://t.me/BotFather) · [Telegram Bot API docs](https://core.telegram.org/bots)

**What you need:** Bot token + channel ID

**Steps:**

1. Open [@BotFather](https://t.me/BotFather) in Telegram and send `/newbot`.
2. Follow the prompts to name your bot and copy the **bot token** (looks like `123456:ABC-DEF…`).
3. Create a **channel** (or use an existing one) where posts should be synced.
4. Add your bot to the channel as an **administrator** (needs permission to post).
5. Find the channel ID:
   - Public channel: `@yourchannel`
   - Private channel: forward a message to [@userinfobot](https://t.me/userinfobot) or use the `-100…` numeric ID from your client
6. Run `uv run python main.py --auth=telegram --label=main` and paste the bot token and channel ID.

**Notes:** The Bot API cannot backfill full channel history — only posts received via `getUpdates` after the bot is set up are synced. For older content, backfill from X or Mastodon instead.

---

### Mastodon

**Portal:** your instance (e.g. [mastodon.social](https://mastodon.social))

**What you need:** Instance URL + access token with `read` and `write` scopes

**Steps:**

1. Log in to your Mastodon instance.
2. Go to **Preferences** → **Development** → **New application** (or open an existing app).
3. Enable scopes **read** and **write**, then create the application.
4. Copy the **Access token** shown for your account.
5. Note your instance base URL (e.g. `https://mastodon.social` — no trailing slash).
6. Run `uv run python main.py --auth=mastodon --label=main` and paste the URL and token.

---

### Threads

**Portal:** [developers.facebook.com](https://developers.facebook.com/apps/)

**What you need:** User access token with Threads scopes (optionally the Threads App Secret)

**Steps:**

1. Create or open an app at [Meta for Developers](https://developers.facebook.com/apps/).
2. Add the **Threads API** product to your app.
3. Under **Threads API** → tools / token generator, create a **User access token**.
4. Grant scopes **`threads_basic`** and **`threads_content_publish`**.
5. Copy the access token. Optionally copy the **Threads App secret** from **App settings** → **Basic**.
6. Run `uv run python main.py --auth=threads --label=main` and paste the token (App Secret and username are optional).

**Notes:** Publishing is limited to **250 posts per 24 hours** per profile. Media must be on a **public HTTPS URL** — posts from X/Mastodon usually work; Telegram-sourced media may publish as text-only. See [Meta access tokens](#meta-access-tokens) for how expiry is handled.

---

### Bluesky

**Portal:** Bluesky app → **Settings** → **Privacy and security** → **App passwords**

**What you need:** Handle + app password (not your login password)

**Steps:**

1. Log in to [Bluesky](https://bsky.app/) (web or app).
2. Open **Settings** → **Privacy and security** → **App passwords**.
3. Create a new app password and copy it (shown once).
4. Note your full handle (e.g. `you.bsky.social`).
5. Run `uv run python main.py --auth=bluesky --label=main` and enter handle and app password.
6. Press Enter for the default PDS (`https://bsky.social`) unless you use a custom server.

---

### RSS (source only)

**What you need:** Feed URL (RSS 2.0 or Atom)

**Steps:**

1. Find the feed URL for your blog or site (often `/feed`, `/feed.xml`, or `/atom.xml`).
2. Verify it loads in a browser or feed reader.
3. Run `uv run python main.py --auth=rss --label=blog` and paste the URL (e.g. `https://example.com/feed.xml`).

**Notes:** RSS is **read-only** — items sync out to your social accounts but nothing is posted back. Each item is published as **title**, **description/summary**, and a **link**. Use `--since=YYYY-MM-DD` on first run to import older items.

---

### Instagram (source only)

**Portal:** [developers.facebook.com](https://developers.facebook.com/apps/)

**What you need:** Instagram Business or Creator account + user access token

**Steps:**

1. Convert your Instagram account to **Business** or **Creator** (Instagram app → Account type).
2. Create or open an app at [Meta for Developers](https://developers.facebook.com/apps/).
3. Add the **Instagram** product → **API setup with Instagram login**.
4. Connect your Instagram account and generate a **User access token** with scope **`instagram_business_basic`**.
5. Copy the access token. Optionally copy the **App secret** from **App settings** → **Basic**.
6. Run `uv run python main.py --auth=instagram --label=main` and paste the token (App Secret and username are optional).

**Notes:** Instagram is **read-only** in mesh sync — feed posts and active **stories** (24 h window) flow out to other networks, never in. Media URLs expire; the bot downloads media at publish time. Accounts connected through **Facebook login** are also asked for the **Facebook App ID**, which Meta requires to renew that flavour of token. See [Meta access tokens](#meta-access-tokens).

---

### Meta access tokens

Threads and Instagram user tokens are valid for **60 days** and can be renewed for another 60 — but only while they are still valid. A token that lapses cannot be recovered and the account has to be connected again.

The bot handles this on its own:

- At `--auth` time a short-lived (1 hour) token is exchanged for a 60-day one when you supply the App Secret. Without the secret, an already-long-lived token is accepted as-is.
- Before every fetch or publish, the stored token is renewed if it has less than `META_TOKEN_MIN_REMAINING_DAYS` (14) left. The new token and its expiry are written back to `account_credentials`.
- Failed renewals are retried every `META_TOKEN_RETRY_HOURS` (6) rather than on every sync cycle — Meta rejects tokens younger than 24 hours, so a freshly connected account settles within a day.
- Accounts connected before this feature existed have no recorded expiry; the bot probes them until Meta reports one.

If the bot is stopped for more than 60 days the token expires anyway. You will see `Threads access token expired on … Re-authenticate: …` in the logs — re-run `--auth` for that network.

---

### LinkedIn

**Portal:** [linkedin.com/developers](https://www.linkedin.com/developers/apps)

**What you need:** Member access token with posting (and ideally reading) scopes

**Steps:**

1. Create an app at [LinkedIn Developers](https://www.linkedin.com/developers/apps) (linked to a Company Page).
2. Under **Products**, request **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect**.
3. Open the **Auth** tab and note your OAuth settings (redirect URL if you use the OAuth flow).
4. Generate a **member access token** with scopes:
   - `openid`, `profile`, `email` — identity
   - `w_member_social` — publish posts
   - `r_member_social` — read your posts (may require [LinkedIn approval](https://learn.microsoft.com/en-us/linkedin/marketing/lms-faq); without it the account can publish but not act as a source)
5. Run `uv run python main.py --auth=linkedin --label=main` and paste the token.

**Notes:** Long posts are split at 3,000 characters. Thread continuations are posted as comments. Images upload via the LinkedIn Images API (up to 20 per post). Video is not supported yet.

---

## Running

```bash
uv run python main.py                      # watch mode (default)
uv run python main.py --since=2026-01-01   # backfill from date
uv run python main.py --list-accounts      # show configured accounts
uv run python main.py -v                   # debug logging
```

## Testing

Tests use [pytest](https://docs.pytest.org/). Install dev dependencies and run the suite:

```bash
uv sync --dev
uv run pytest
```

Verbose output:

```bash
uv run pytest -v
```

Coverage includes every network module (`apis/twitter`, `telegram`, `mastodon`, `threads`, `bluesky`, `instagram`, `linkedin`, `rss`), shared helpers (`utils/`), sync engine, and database sync state.

CI runs the same suite on every push and pull request via GitHub Actions (`.github/workflows/tests.yml`).

### Watch mode

Polls on a **cron schedule** (see `WATCH_CRON` in `config.py`). For each account:

1. Fetches recent posts (skipping mirrored/sync-created posts)
2. Skips posts younger than **20 minutes** (editable window on source networks). Ignored on the first cycle after start/restart (`docker compose up`)
3. Publishes unsynced content to every other account
4. Records mappings so the same content is never reposted again

### Backfill (`--since`)

One-shot sync since the given date. Skips min-age filter, adds a **3 second delay** between publishes. Works for X and Mastodon history; Telegram only picks up posts received via `getUpdates` since the bot was configured.

### Docker

```bash
docker compose run --rm bot uv run python main.py --auth=twitter
docker compose run --rm bot uv run python main.py --auth=telegram
docker compose run --rm bot uv run python main.py --auth=mastodon
docker compose run --rm bot uv run python main.py --auth=threads
docker compose run --rm bot uv run python main.py --auth=bluesky
docker compose run --rm bot uv run python main.py --auth=rss
docker compose run --rm bot uv run python main.py --auth=instagram
docker compose run --rm bot uv run python main.py --auth=linkedin
docker compose up -d
```

### Project structure

```
be-everywhere-bot/
├── main.py                 # CLI: watch / --since / --auth / --list-accounts
├── config.py               # Timing, network limits, paths
├── apis/                   # One module per network (fetch + publish + auth)
├── utils/                  # Shared helpers (filters, URLs, outbound shaping, HTTP)
├── db/
│   ├── accounts.py         # Multi-account credentials
│   ├── sync_state.py       # Mappings, mirrored posts, sync watermarks
│   └── migrations/         # Schema migrations (auto-applied)
└── sync/
    └── engine.py           # Mesh sync orchestration
tests/                      # pytest suite
```

## Configuration

| Constant | Default | Description |
|----------|---------|-------------|
| `POST_MIN_AGE_MINUTES` | `30` | Min age for main posts before publishing; skipped on first watch cycle after start/restart and on `--since` |
| `WATCH_CRON` | `0,30 7-22 * * *` | Watch-mode cron schedule (UTC) |
| `BACKFILL_POST_DELAY_SECONDS` | `3` | Delay between posts in `--since` mode |
| `TWITTER_FETCH_MAX_PAGES` | `10` | Max X API pages per poll (safety cap) |
| `TWITTER_FETCH_PAGE_SIZE` | `10` | X tweets per page; next page only if all are new |
| `WATCH_OVERLAP_HOURS` | `6` | Re-fetch overlap for threads / retries |
| `META_TOKEN_MIN_REMAINING_DAYS` | `14` | Renew Meta tokens once this little of the 60 days is left |
| `META_TOKEN_RETRY_HOURS` | `6` | Backoff between failed Meta token renewals |
| `META_TOKEN_UNKNOWN_EXPIRY_DAYS` | `30` | Renewal cadence when Meta reports no expiry |

### Upgrading an existing install

Pull the new code, rebuild Docker if you use it, then start as usual:

```bash
# Local
uv sync
uv run python main.py          # migrates, then watch mode

# Docker
docker compose build
docker compose up -d           # migrates on container start
```


### Migrate only (no sync)

```bash
uv run python main.py --migrate

docker compose run --rm bot uv run python main.py --migrate
```

Use `-v` to see `Applying migration …` log lines.

## Database

SQLite at `data/be_everywhere.db` (auto-created, migrated on startup):

| Table | Purpose |
|-------|---------|
| `accounts` | Connected accounts (`network` + `label`) |
| `account_credentials` | Tokens and settings per account |
| `sync_mappings` | Propagation tracking (prevents re-sync) |
| `mirrored_posts` | Sync-created posts (prevents circular repost) |
| `account_sync_state` | Last fetch watermark per account |
| `schema_migrations` | Applied migration versions |

Legacy single-account schema is migrated automatically by `001_mesh_accounts`.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No accounts configured | Run `--auth=…` for each network |
| Post not synced yet | May be younger than 30 min in watch mode |
| Telegram history missing | Bot API can't backfill channels; use `--since` on X/Mastodon |
| Instagram stories missing | Stories expire after 24 h; run watch mode regularly |
| Circular repost | Should not happen — check `mirrored_posts` is populated |
| HTTP 402 on X | Top up API credits at developer.x.com |
| `Session has expired` on Threads/Instagram | Token lapsed past its 60-day window; re-run `--auth` for that network |

```bash
uv run python main.py -v   # debug logging
```

## License

Private / personal use. Adjust as needed.
