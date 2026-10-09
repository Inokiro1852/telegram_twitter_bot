# telegram_twitter_bot

A Telegram bot that turns links to **Twitter/X** and **Bluesky** posts into native Telegram messages, with the post text and its photos, videos or GIFs attached. It works in two ways:

- **Send a link to the bot** (or in a group where it is present). The bot replies with the post and deletes your original message (if it has rights).
- **Inline mode.** Type `@your_bot <link>` in any chat and pick a variant.

Built with Python and [aiogram 3](https://docs.aiogram.dev/). Post data comes from the public [FxEmbed](https://github.com/FxEmbed/FxEmbed) APIs (`api.fxtwitter.com` and `api.fxbsky.app`).

## Features

- Supports `x.com`, `twitter.com` and `bsky.app` post links.
- Sends the post author, text and a link back to the original post.
- Handles **photos** (albums), **videos** and **GIFs**. Text-only posts are sent as plain text.
- **Spoiler mode**: media and text are hidden behind a spoiler.
- **Image stitching**: multiple photos can be merged into a single image.
- **Quote posts**: optionally send the quoted post too, in either order.
- **Inline mode** with ready-made variants (default, spoiler, reply, spoiler + reply, reversed reply).
- Automatic fallback: if Telegram can't load the media from its URL, the bot downloads it and uploads the file itself.
- Retries on network errors and timeouts when talking to the APIs.

## Usage

### Sending a link to the bot

Send a message that **starts with the link**. You can add options after it, separated by spaces:

| Option | Cyrillic alias | Effect |
| ------ | -------------- | ------ |
| `s`  | `с`  | Hide text and media behind a spoiler |
| `g`  | `к`  | Stitch multiple photos into one image (instead of an album) |
| `r`  | `р`  | If the post quotes another post, also send the quoted post as a reply |
| `rr` | `рр` | Reversed reply: send the quoted post first, then the main post as a reply to it |

Examples:

```
https://x.com/exhausted_dan/status/2108445810606387345
https://x.com/ctc_rec/status/2108498356821692553 s g
https://x.com/sangchu_backup/status/2108572351801762285 s r
```

After the post is sent, the bot tries to delete your original message. In groups this only works if the bot has the *Delete messages* permission.

### Inline mode

Type the bot's username and a link in any chat:

```
@your_bot https://x.com/user/status/1234567890
```

Telegram shows these variants: **default**, **with spoiler**, **with reply**, **with spoiler and reply**. Add ` r` after the link to get the **reversed reply** variants instead (`rr`, `srr`).

After you choose one, the placeholder message ("Fetching tweet...") is edited into the finished post. When a post quotes another post, a **Reply** button is added that opens an inline query for the quoted link.

> TODO: list the slash commands from `handlers/commands.py` (e.g. `/start`, `/help`) and say which are admin-only.

## Project structure

```
.
├── main.py             # Entry point: creates the bot, registers routers, starts polling
├── config.py           # Loads settings from .env
├── filters.py          # Custom filters (IsAdmin)
├── handlers/
│   ├── commands.py     # Slash commands
│   ├── inline.py       # Inline mode: query results + editing the chosen message
│   └── bot_funcs.py    # Link handling in normal messages, API calls, caption + image helpers
├── requirements.txt
└── pyproject.toml      # Ruff formatting config (single quotes)
```

## Requirements

- Python 3.10 or newer
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

## Setup

1. **Clone the repository**

   ```bash
   git clone https://github.com/Inokiro1852/telegram_twitter_bot.git
   cd telegram_twitter_bot
   ```

2. **Create a virtual environment and install dependencies**

   ```bash
   python -m venv .venv
   .venv\Scripts\activate #Linux: source .venv/bin/activate        
   pip install -r requirements.txt
   ```

3. **Configure the bot in @BotFather**

   - `/mybots` → your bot → *Bot Settings* → *Inline Mode* → **Turn on**.
   - `/setinlinefeedback` → choose your bot → **Enabled** (100%). This is required: the bot only learns which variant you picked through inline feedback, and without it inline results stay stuck on "Fetching tweet...".
   - Optional, for use in groups: *Group Privacy* → **Turn off**, so the bot can see messages that contain links.

4. **Create a `.env` file** in the project root:

   ```env
   BOT_TOKEN=123456:your-bot-token-from-botfather
   DUMP_CHAT_ID=123456789
   ```

   | Variable       | Description |
   | -------------- | ----------- |
   | `BOT_TOKEN`    | Token from @BotFather. |
   | `DUMP_CHAT_ID` | Chat the bot uses to pre-upload media for inline mode. It is also compared to the sender's user ID by the `IsAdmin` filter, so use **your own Telegram user ID** (a private chat with the bot). |

   To find your user ID, message a bot such as [@userinfobot](https://t.me/userinfobot), then open a chat with your own bot and press **Start** so it is allowed to message you.

5. **Run the bot**

   ```bash
   python main.py
   ```

   The bot uses long polling, so no public server or webhook is needed. Logs go to stdout.

## How it works

1. A link is matched against the Twitter/X and Bluesky URL patterns.
2. The bot requests the post data from the FxEmbed API (10 s timeout, up to 2 retries with increasing delay).
3. A caption is built from the author name and post text (HTML-escaped and cut to fit Telegram's 1024-character caption limit).
4. Media is sent by URL. If Telegram rejects it, the bot downloads the file (60 s timeout, 2 retries) and uploads it directly.
5. **Inline mode** can't send new media, so the bot first posts a placeholder message and then *edits* it into the final post. For spoilers it also sends the media to the dump chat first, because Telegram otherwise doesn't apply the spoiler on the first send.
6. **Stitched images** are placed side by side, scaled to the same height, kept within Telegram's size limits (width + height under 10,000 px) and saved as a JPEG under 10 MB.

## Limitations

- **Depends on third-party services.** If the FxEmbed APIs (or the original sites) change, rate-limit or go down, fetching fails. Private, deleted or age-restricted posts won't work, and errors are shown as a generic "Some error occurred."
- **Only the first video is sent.** If a post has several videos, the rest are ignored, and a post with video won't also send its photos.
- **Only one level of quoted posts.** A quoted post's own quote is not followed. Polls, cards and threads are not supported.
- **Only the first word is treated as the link** in a normal message. Links in the middle of a sentence are ignored, and only the first link is processed.
- **Inline mode cannot send albums.** Posts with several photos are always stitched into one image there.
- **Inline mode adds uploads.** Inline media (and spoiler media) is also sent to the dump chat, so that chat fills up with files over time and spoiler posts are slower.
- **File size limits.** Telegram only fetches media by URL up to about 20 MB. If that fails, the fallback upload is limited to 50 MB, so larger videos can't be sent.
- **Caption length.** Long post text is truncated to fit Telegram's 1024-character caption limit.
- **Single instance.** Long polling means only one copy of the bot can run per token.
- **Admin ID and dump chat share one setting (for now)**, so `DUMP_CHAT_ID` must be your private chat with the bot (not a group or channel).
- **No Docker or webhook setup**, so it is currently meant to run locally or on a simple VPS.

## Development

The project uses [Ruff](https://docs.astral.sh/ruff/) with single quotes:

```bash
pip install ruff
ruff format .
```

## License

Code released under the MIT License. 