# 𝑟ỿ∨ᥱ𝑛 bot

Discord moderation bot (automod) with a music cog, built on `discord.py`.
Configuration is per-server and stored in SQLite, so there are no config files
to edit — moderators use slash commands.

## Features

**Automod** — per-server rules, each with its own action:

| Rule | Catches |
| --- | --- |
| `banned_words` | Words and phrases you add |
| `patterns` | Custom Python regular expressions |
| `links` | Normal HTTP/HTTPS links |
| `invites` | Discord invite links (on by default) |
| `caps` | Messages that are too uppercase |
| `spam` | Too many messages in a short window |
| `mentions` | Mass user/role mentions |

Actions: `delete`, `warn`, `timeout`, `kick`, `ban`, `delete_warn`,
`delete_timeout`. Rules can be exempted per channel or per role.

**Music** — `/music join`, `/play`, `/pause`, `/resume`, `/skip`, `/stop`,
`/leave`, `/queue`. Streams audio via `yt-dlp` and `ffmpeg`.

## Commands

```
/automod setup             create a safe starter configuration
/automod help              automod setup help
/automod status            show current settings
/automod enable <rule>     enable a rule, or 'all'
/automod disable <rule>    disable a rule, or 'all'
/automod action <rule> <action>
/automod addword <word>    /automod removeword <word>
/automod addpattern <regex>  /automod removepattern <regex>
/automod setlog #channel   choose the moderation log channel
/automod exemptchannel #channel <true|false>
/automod exemptrole @role <true|false>
/automod setspam <max_messages> <window_seconds>
/automod setcaps <ratio> <min_chars>
/automod setmentions <max_mentions>
```

All automod commands are ephemeral replies and require the **Manage Server**
permission.

## Local setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then add DISCORD_TOKEN
sudo apt install ffmpeg # required for the music cog
python bot.py
```

Set `DISCORD_GUILD_ID` in `.env` so slash commands sync instantly to your
server instead of taking up to an hour via global sync.

## 24/7 hosting (Oracle Cloud Always-Free)

`deploy/install.sh` provisions everything on a Debian/Ubuntu host: system
packages, a virtualenv, and a `systemd` unit that restarts the bot on crash
and on reboot.

```bash
sudo bash deploy/install.sh
```

First run stops after creating `/opt/ryven-bot/.env`. Add `DISCORD_TOKEN`, then
re-run the script to start the service.

```bash
journalctl -u ryven-bot -f   # logs
systemctl restart ryven-bot  # restart after config changes
```

Override the defaults with `APP_DIR`, `SERVICE_USER`, or `REPO_URL` if needed.

## Bot token & permissions

Create a bot at <https://discord.com/developers/applications>, then enable
**Message Content Intent** under Bot settings — automod needs to read messages.

Required permissions: `Manage Server`, `Moderate Members`, `Kick Members`,
`Ban Members`, `Move Members`, `Connect`, `Speak`, `Embed Links`.

## Notes

- `ryven.sqlite3` holds per-server automod configuration and is gitignored.
- The token lives only in `.env`, which is gitignored and chmod 600 on deploy.