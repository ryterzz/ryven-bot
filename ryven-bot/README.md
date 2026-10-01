# 𝑟ỿ∨ᥱ𝑛 bot

A personal Discord server bot with configurable automod.

## What is included

- Persistent per-server settings in SQLite
- Slash-command configuration
- Banned words and phrases
- Custom regular-expression patterns
- Discord invite and general link filtering
- Excessive capitalization detection
- Spam/flood detection
- Mention limits
- Configurable actions: delete, warn, timeout, kick, ban, and combinations
- Exempt channels and roles
- Moderation log channel

## Setup

1. Install Python 3.11 or newer.
2. Create a Discord application and bot in the Discord Developer Portal.
3. Set the bot's display name to `𝑟ỿ∨ᥱ𝑛 bot`.
4. Enable the **Message Content Intent** and **Server Members Intent**.
5. Invite the bot with the `bot` and `applications.commands` scopes. Give it only the permissions it needs; automod normally needs View Channels, Send Messages, Manage Messages, Embed Links, and Moderate Members.
6. Copy `.env.example` to `.env` and add the bot token. For faster command registration, also add your server ID as `DISCORD_GUILD_ID`.
7. Install and run:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   py -m pip install -r requirements.txt
   py bot.py
   ```

## Main commands

All configuration commands require **Manage Server**.

- `/automod status`
- `/automod enable <rule>` and `/automod disable <rule>`
- `/automod action <rule> <action>`
- `/automod addword <word>` and `/automod removeword <word>`
- `/automod addpattern <regex>` and `/automod removepattern <regex>`
- `/automod setlog <channel>`
- `/automod exemptchannel <channel> <true/false>`
- `/automod exemptrole <role> <true/false>`
- `/automod setspam <messages> <seconds>`
- `/automod setcaps <ratio> <minimum characters>`
- `/automod setmentions <maximum>`

The bot starts with only invite filtering enabled. Configure each rule before enabling it. Custom regular expressions are powerful, so only trusted server moderators should have access to the configuration commands.

## Important permissions

The bot's role must be above members it needs to timeout, kick, or ban. Discord also prevents a bot from moderating another member whose highest role is equal to or above the bot's role.
