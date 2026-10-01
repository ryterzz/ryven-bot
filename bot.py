from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import sqlite3
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from music import Music


BOT_NAME = "𝑟ỿ∨ᥱ𝑛 bot"
BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "ryven.sqlite3"

RULE_NAMES = ("banned_words", "patterns", "links", "invites", "caps", "spam", "mentions")
ACTION_NAMES = ("delete", "warn", "timeout", "kick", "ban", "delete_warn", "delete_timeout")

RULE_LABELS = {
    "banned_words": "Banned words",
    "patterns": "Custom patterns",
    "links": "Links",
    "invites": "Discord invites",
    "caps": "Excessive caps",
    "spam": "Spam/flooding",
    "mentions": "Mention limits",
}

RULE_DESCRIPTIONS = {
    "banned_words": "Blocks words and phrases you add.",
    "patterns": "Blocks custom regular-expression patterns.",
    "links": "Blocks normal HTTP/HTTPS links.",
    "invites": "Blocks Discord invite links.",
    "caps": "Flags messages with too much uppercase text.",
    "spam": "Flags users sending too many messages too quickly.",
    "mentions": "Limits mass user and role mentions.",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "log_channel_id": None,
    "exempt_role_ids": [],
    "exempt_channel_ids": [],
    "ignored_user_ids": [],
    "rules": {
        "banned_words": {"enabled": False, "action": "delete_warn", "words": []},
        "patterns": {"enabled": False, "action": "delete_warn", "patterns": []},
        "links": {"enabled": False, "action": "delete"},
        "invites": {"enabled": True, "action": "delete"},
        "caps": {"enabled": False, "action": "warn", "ratio": 0.75, "min_chars": 12},
        "spam": {"enabled": False, "action": "delete_timeout", "max_messages": 5, "window_seconds": 8},
        "mentions": {"enabled": False, "action": "timeout", "max_mentions": 5},
    },
}


def merged_config(saved: dict[str, Any] | None) -> dict[str, Any]:
    result = copy.deepcopy(DEFAULT_CONFIG)
    if not saved:
        return result

    for key, value in saved.items():
        if key == "rules" and isinstance(value, dict):
            for rule_name, rule_config in value.items():
                if rule_name in result["rules"] and isinstance(rule_config, dict):
                    result["rules"][rule_name].update(rule_config)
        elif key in result:
            result[key] = value
    return result


class ConfigStore:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS guild_config (guild_id INTEGER PRIMARY KEY, config_json TEXT NOT NULL)"
        )
        self.connection.commit()

    def get(self, guild_id: int) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT config_json FROM guild_config WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return merged_config(json.loads(row[0]) if row else None)

    def save(self, guild_id: int, config: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO guild_config(guild_id, config_json) VALUES(?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET config_json = excluded.config_json",
            (guild_id, json.dumps(config)),
        )
        self.connection.commit()


class RyvenBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.store = ConfigStore(DATABASE_PATH)

    async def setup_hook(self) -> None:
        await self.add_cog(Automod(self))
        await self.add_cog(Music(self))

        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"Synced {len(synced)} slash commands to guild {guild_id}.")
        else:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} global slash commands.")

    async def on_ready(self) -> None:
        await self.change_presence(activity=discord.Game(name="protecting the server"))
        print(f"{BOT_NAME} is online as {self.user}.")


class Automod(commands.Cog):
    automod = app_commands.Group(name="automod", description="Configure 𝑟ỿ∨ᥱ𝑛 bot's automod.")

    def __init__(self, bot: RyvenBot):
        self.bot = bot
        self.recent_messages: defaultdict[tuple[int, int], deque[float]] = defaultdict(deque)

    @staticmethod
    def _rule_choice(name: str) -> app_commands.Choice[str]:
        return app_commands.Choice(name=name, value=name)

    @staticmethod
    def _action_choice(name: str) -> app_commands.Choice[str]:
        return app_commands.Choice(name=name, value=name)

    async def _moderator_only(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message("This command only works inside a server.", ephemeral=True)
            return False
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("You need the **Manage Server** permission.", ephemeral=True)
            return False
        return True

    def _config(self, guild_id: int) -> dict[str, Any]:
        return self.bot.store.get(guild_id)

    def _save(self, guild_id: int, config: dict[str, Any]) -> None:
        self.bot.store.save(guild_id, config)

    @automod.command(name="setup", description="Set up a safe starter automod configuration.")
    async def setup(self, interaction: discord.Interaction) -> None:
        if not await self._moderator_only(interaction):
            return
        config = self._config(interaction.guild.id)
        config["enabled"] = True
        # Keep the starter setup useful but conservative: invite filtering on,
        # more disruptive rules available to enable individually.
        config["rules"]["invites"]["enabled"] = True
        self._save(interaction.guild.id, config)

        embed = discord.Embed(
            title="𝑟ỿ∨ᥱ𝑛 bot is ready",
            description="Your starter automod setup is enabled. Nothing disruptive is turned on yet.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Try these next",
            value=(
                "`/automod setlog #mod-logs`\n"
                "`/automod addword example`\n"
                "`/automod enable banned_words`\n"
                "`/automod help`"
            ),
            inline=False,
        )
        embed.set_footer(text="You can change everything later with /automod status")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @automod.command(name="help", description="Show friendly automod setup help.")
    async def help(self, interaction: discord.Interaction) -> None:
        if not await self._moderator_only(interaction):
            return
        embed = discord.Embed(
            title="𝑟ỿ∨ᥱ𝑛 bot · Automod help",
            description="Use these commands to configure your server without touching any files.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Quick start",
            value=(
                "`/automod setup` — create a safe starter setup\n"
                "`/automod status` — view current settings\n"
                "`/automod setlog #channel` — choose the mod-log channel"
            ),
            inline=False,
        )
        embed.add_field(
            name="Common rules",
            value="\n".join(f"`{name}` — {RULE_DESCRIPTIONS[name]}" for name in RULE_NAMES),
            inline=False,
        )
        embed.add_field(
            name="Example",
            value=(
                "`/automod addword spoilers`\n"
                "`/automod action banned_words delete_warn`\n"
                "`/automod enable banned_words`"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @automod.command(name="status", description="Show the current automod configuration.")
    async def status(self, interaction: discord.Interaction) -> None:
        if not await self._moderator_only(interaction):
            return
        config = self._config(interaction.guild.id)
        enabled = "enabled" if config["enabled"] else "disabled"
        embed = discord.Embed(
            title="𝑟ỿ∨ᥱ𝑛 bot · Automod status",
            description=f"Automod is **{enabled}**.",
            color=discord.Color.green() if config["enabled"] else discord.Color.red(),
        )
        lines = []
        for rule_name, rule in config["rules"].items():
            state = "on" if rule["enabled"] else "off"
            lines.append(f"**{RULE_LABELS[rule_name]}:** {state} · `{rule['action']}`")
        log_channel = interaction.guild.get_channel(config["log_channel_id"]) if config["log_channel_id"] else None
        embed.add_field(name="Rules", value="\n".join(lines), inline=False)
        embed.add_field(name="Log channel", value=log_channel.mention if log_channel else "Not set", inline=False)
        embed.set_footer(text="Need help? Try /automod help")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @automod.command(name="enable", description="Enable a rule or all automod.")
    @app_commands.describe(rule="The rule to enable, or all")
    @app_commands.choices(rule=[app_commands.Choice(name="all", value="all")] + [app_commands.Choice(name=name, value=name) for name in RULE_NAMES])
    async def enable(self, interaction: discord.Interaction, rule: app_commands.Choice[str]) -> None:
        if not await self._moderator_only(interaction):
            return
        config = self._config(interaction.guild.id)
        if rule.value == "all":
            config["enabled"] = True
            for item in config["rules"].values():
                item["enabled"] = True
        else:
            config["enabled"] = True
            config["rules"][rule.value]["enabled"] = True
        self._save(interaction.guild.id, config)
        await interaction.response.send_message(f"Enabled `{rule.value}`.", ephemeral=True)

    @automod.command(name="disable", description="Disable a rule or all automod.")
    @app_commands.describe(rule="The rule to disable, or all")
    @app_commands.choices(rule=[app_commands.Choice(name="all", value="all")] + [app_commands.Choice(name=name, value=name) for name in RULE_NAMES])
    async def disable(self, interaction: discord.Interaction, rule: app_commands.Choice[str]) -> None:
        if not await self._moderator_only(interaction):
            return
        config = self._config(interaction.guild.id)
        if rule.value == "all":
            config["enabled"] = False
        else:
            config["rules"][rule.value]["enabled"] = False
        self._save(interaction.guild.id, config)
        await interaction.response.send_message(f"Disabled `{rule.value}`.", ephemeral=True)

    @automod.command(name="action", description="Set what happens when a rule is triggered.")
    @app_commands.describe(rule="The rule", action="The response")
    @app_commands.choices(rule=[app_commands.Choice(name=name, value=name) for name in RULE_NAMES])
    @app_commands.choices(action=[app_commands.Choice(name=name, value=name) for name in ACTION_NAMES])
    async def action(self, interaction: discord.Interaction, rule: app_commands.Choice[str], action: app_commands.Choice[str]) -> None:
        if not await self._moderator_only(interaction):
            return
        config = self._config(interaction.guild.id)
        config["rules"][rule.value]["action"] = action.value
        self._save(interaction.guild.id, config)
        await interaction.response.send_message(f"`{rule.value}` will now use `{action.value}`.", ephemeral=True)

    @automod.command(name="addword", description="Add a banned word or phrase.")
    @app_commands.describe(word="The word or phrase to block")
    async def addword(self, interaction: discord.Interaction, word: str) -> None:
        if not await self._moderator_only(interaction):
            return
        word = word.strip().casefold()
        config = self._config(interaction.guild.id)
        if not word:
            await interaction.response.send_message("The word cannot be empty.", ephemeral=True)
            return
        if word not in config["rules"]["banned_words"]["words"]:
            config["rules"]["banned_words"]["words"].append(word)
            self._save(interaction.guild.id, config)
        await interaction.response.send_message(f"Added `{word}` to banned words.", ephemeral=True)

    @automod.command(name="removeword", description="Remove a banned word or phrase.")
    @app_commands.describe(word="The word or phrase to unblock")
    async def removeword(self, interaction: discord.Interaction, word: str) -> None:
        if not await self._moderator_only(interaction):
            return
        word = word.strip().casefold()
        config = self._config(interaction.guild.id)
        try:
            config["rules"]["banned_words"]["words"].remove(word)
        except ValueError:
            pass
        self._save(interaction.guild.id, config)
        await interaction.response.send_message(f"Removed `{word}` from banned words.", ephemeral=True)

    @automod.command(name="addpattern", description="Add a regular-expression pattern to block.")
    @app_commands.describe(pattern="A Python regular-expression pattern")
    async def addpattern(self, interaction: discord.Interaction, pattern: str) -> None:
        if not await self._moderator_only(interaction):
            return
        try:
            re.compile(pattern)
        except re.error as error:
            await interaction.response.send_message(f"That pattern is invalid: `{error}`", ephemeral=True)
            return
        config = self._config(interaction.guild.id)
        if pattern not in config["rules"]["patterns"]["patterns"]:
            config["rules"]["patterns"]["patterns"].append(pattern)
            self._save(interaction.guild.id, config)
        await interaction.response.send_message("Pattern added.", ephemeral=True)

    @automod.command(name="removepattern", description="Remove a regular-expression pattern.")
    @app_commands.describe(pattern="The exact pattern to remove")
    async def removepattern(self, interaction: discord.Interaction, pattern: str) -> None:
        if not await self._moderator_only(interaction):
            return
        config = self._config(interaction.guild.id)
        try:
            config["rules"]["patterns"]["patterns"].remove(pattern)
        except ValueError:
            pass
        self._save(interaction.guild.id, config)
        await interaction.response.send_message("Pattern removed.", ephemeral=True)

    @automod.command(name="setlog", description="Set the channel for moderation logs.")
    @app_commands.describe(channel="The text channel where logs should be sent")
    async def setlog(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not await self._moderator_only(interaction):
            return
        config = self._config(interaction.guild.id)
        config["log_channel_id"] = channel.id
        self._save(interaction.guild.id, config)
        await interaction.response.send_message(f"Moderation logs will go to {channel.mention}.", ephemeral=True)

    @automod.command(name="exemptchannel", description="Toggle automod exemption for a channel.")
    @app_commands.describe(channel="The channel", exempt="Whether the channel should be exempt")
    async def exemptchannel(self, interaction: discord.Interaction, channel: discord.TextChannel, exempt: bool) -> None:
        if not await self._moderator_only(interaction):
            return
        config = self._config(interaction.guild.id)
        channel_ids = config["exempt_channel_ids"]
        if exempt and channel.id not in channel_ids:
            channel_ids.append(channel.id)
        elif not exempt and channel.id in channel_ids:
            channel_ids.remove(channel.id)
        self._save(interaction.guild.id, config)
        state = "exempt" if exempt else "included"
        await interaction.response.send_message(f"{channel.mention} is now {state} from automod.", ephemeral=True)

    @automod.command(name="exemptrole", description="Toggle automod exemption for a role.")
    @app_commands.describe(role="The role", exempt="Whether members with this role should be exempt")
    async def exemptrole(self, interaction: discord.Interaction, role: discord.Role, exempt: bool) -> None:
        if not await self._moderator_only(interaction):
            return
        config = self._config(interaction.guild.id)
        role_ids = config["exempt_role_ids"]
        if exempt and role.id not in role_ids:
            role_ids.append(role.id)
        elif not exempt and role.id in role_ids:
            role_ids.remove(role.id)
        self._save(interaction.guild.id, config)
        state = "exempt" if exempt else "included"
        await interaction.response.send_message(f"Members with {role.mention} are now {state} from automod.", ephemeral=True)

    @automod.command(name="setspam", description="Configure the spam threshold.")
    @app_commands.describe(max_messages="Messages allowed", window_seconds="Time window in seconds")
    async def setspam(self, interaction: discord.Interaction, max_messages: app_commands.Range[int, 2, 30], window_seconds: app_commands.Range[int, 2, 60]) -> None:
        if not await self._moderator_only(interaction):
            return
        config = self._config(interaction.guild.id)
        rule = config["rules"]["spam"]
        rule["max_messages"] = max_messages
        rule["window_seconds"] = window_seconds
        self._save(interaction.guild.id, config)
        await interaction.response.send_message(f"Spam is set to {max_messages} messages per {window_seconds} seconds.", ephemeral=True)

    @automod.command(name="setcaps", description="Configure the caps threshold.")
    @app_commands.describe(ratio="Uppercase ratio from 0.50 to 1.00", min_chars="Minimum alphabetic characters")
    async def setcaps(self, interaction: discord.Interaction, ratio: app_commands.Range[float, 0.5, 1.0], min_chars: app_commands.Range[int, 3, 200]) -> None:
        if not await self._moderator_only(interaction):
            return
        config = self._config(interaction.guild.id)
        config["rules"]["caps"]["ratio"] = ratio
        config["rules"]["caps"]["min_chars"] = min_chars
        self._save(interaction.guild.id, config)
        await interaction.response.send_message(f"Caps is set to {ratio:.0%} uppercase over {min_chars} letters.", ephemeral=True)

    @automod.command(name="setmentions", description="Configure the mention threshold.")
    @app_commands.describe(max_mentions="Maximum user and role mentions")
    async def setmentions(self, interaction: discord.Interaction, max_mentions: app_commands.Range[int, 1, 50]) -> None:
        if not await self._moderator_only(interaction):
            return
        config = self._config(interaction.guild.id)
        config["rules"]["mentions"]["max_mentions"] = max_mentions
        self._save(interaction.guild.id, config)
        await interaction.response.send_message(f"Mention limit set to {max_mentions}.", ephemeral=True)

    def _is_exempt(self, message: discord.Message, config: dict[str, Any]) -> bool:
        if message.author.id in config["ignored_user_ids"] or message.channel.id in config["exempt_channel_ids"]:
            return True
        return isinstance(message.author, discord.Member) and any(
            role.id in config["exempt_role_ids"] for role in message.author.roles
        )

    def _violation(self, message: discord.Message, config: dict[str, Any]) -> tuple[str, str] | None:
        content = message.content
        folded = content.casefold()
        rules = config["rules"]

        if rules["banned_words"]["enabled"] and any(word in folded for word in rules["banned_words"]["words"]):
            return "banned_words", "banned word or phrase"

        if rules["patterns"]["enabled"]:
            for pattern in rules["patterns"]["patterns"]:
                try:
                    if re.search(pattern, content, re.IGNORECASE):
                        return "patterns", "blocked pattern"
                except re.error:
                    continue

        if rules["invites"]["enabled"] and re.search(r"(?:discord(?:\.gg|\.com/invite)/)[\w-]+", folded):
            return "invites", "Discord invite link"

        if rules["links"]["enabled"] and re.search(r"https?://\S+", content, re.IGNORECASE):
            return "links", "link"

        if rules["caps"]["enabled"]:
            letters = [character for character in content if character.isalpha()]
            if len(letters) >= rules["caps"]["min_chars"]:
                uppercase_ratio = sum(character.isupper() for character in letters) / len(letters)
                if uppercase_ratio >= rules["caps"]["ratio"]:
                    return "caps", "excessive capitalization"

        if rules["mentions"]["enabled"]:
            mention_count = len(message.mentions) + len(message.role_mentions)
            if message.mention_everyone:
                mention_count += rules["mentions"]["max_mentions"]
            if mention_count >= rules["mentions"]["max_mentions"]:
                return "mentions", "too many mentions"

        if rules["spam"]["enabled"]:
            key = (message.guild.id, message.author.id)
            now = message.created_at.timestamp()
            recent = self.recent_messages[key]
            while recent and now - recent[0] > rules["spam"]["window_seconds"]:
                recent.popleft()
            recent.append(now)
            if len(recent) > rules["spam"]["max_messages"]:
                return "spam", "message flooding"
        return None

    async def _log(self, message: discord.Message, config: dict[str, Any], rule_name: str, reason: str, action: str) -> None:
        channel_id = config.get("log_channel_id")
        channel = message.guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return
        embed = discord.Embed(title="Automod action", color=discord.Color.orange())
        embed.add_field(name="User", value=f"{message.author.mention} (`{message.author.id}`)", inline=False)
        embed.add_field(name="Rule", value=rule_name)
        embed.add_field(name="Action", value=action)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Message", value=discord.utils.escape_markdown(message.content[:900]) or "[no text]")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _take_action(self, message: discord.Message, config: dict[str, Any], rule_name: str, reason: str) -> None:
        action = config["rules"][rule_name]["action"]
        if "delete" in action:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

        if "warn" in action:
            try:
                await message.channel.send(
                    f"{message.author.mention}, your message was removed: **{reason}**.",
                    delete_after=8,
                )
            except discord.HTTPException:
                pass

        member = message.author if isinstance(message.author, discord.Member) else None
        if member and action in {"timeout", "delete_timeout"}:
            try:
                await member.timeout(timedelta(minutes=10), reason=f"Automod: {reason}")
            except discord.HTTPException:
                pass
        elif member and action == "kick":
            try:
                await member.kick(reason=f"Automod: {reason}")
            except discord.HTTPException:
                pass
        elif member and action == "ban":
            try:
                await member.ban(reason=f"Automod: {reason}", delete_message_seconds=0)
            except discord.HTTPException:
                pass

        await self._log(message, config, rule_name, reason, action)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        config = self._config(message.guild.id)
        if not config["enabled"] or self._is_exempt(message, config):
            return
        violation = self._violation(message, config)
        if violation:
            await self._take_action(message, config, violation[0], violation[1])


async def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is missing. Copy .env.example to .env and add your bot token.")
    async with RyvenBot() as bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
