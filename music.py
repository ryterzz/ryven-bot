from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp


YTDL_OPTIONS: dict[str, Any] = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "ignoreerrors": True,
    "source_address": "0.0.0.0",
}


@dataclass
class Track:
    title: str
    page_url: str


@dataclass
class MusicState:
    queue: deque[Track] = field(default_factory=deque)
    playlist: list[Track] = field(default_factory=list)
    current: Track | None = None
    loop_enabled: bool = True
    text_channel_id: int | None = None


class Music(commands.Cog):
    music = app_commands.Group(name="music", description="Play music in a voice channel.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, MusicState] = {}

    def _state(self, guild_id: int) -> MusicState:
        if guild_id not in self.states:
            self.states[guild_id] = MusicState()
        return self.states[guild_id]

    async def _join_user_channel(self, interaction: discord.Interaction) -> discord.VoiceClient:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise RuntimeError("This command only works inside a server.")
        if interaction.user.voice is None or interaction.user.voice.channel is None:
            raise RuntimeError("Join a voice channel first, then run this command again.")

        channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            if voice_client.channel != channel:
                await voice_client.move_to(channel)
            return voice_client
        return await channel.connect()

    @staticmethod
    def _extract_tracks_sync(source: str) -> list[Track]:
        lookup = source if source.startswith(("http://", "https://")) else f"ytsearch1:{source}"
        options = dict(YTDL_OPTIONS)
        options["extract_flat"] = "in_playlist"
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(lookup, download=False)

        if not info:
            return []
        entries = list(info.get("entries") or [])
        if not entries:
            entries = [info]

        tracks: list[Track] = []
        for entry in entries:
            if not entry:
                continue
            page_url = entry.get("webpage_url") or entry.get("original_url")
            if not page_url and entry.get("id"):
                page_url = f"https://www.youtube.com/watch?v={entry['id']}"
            if page_url:
                tracks.append(Track(title=entry.get("title") or "Unknown track", page_url=page_url))
        return tracks

    @staticmethod
    def _stream_url_sync(page_url: str) -> tuple[str, str]:
        options = dict(YTDL_OPTIONS)
        options["noplaylist"] = True
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(page_url, download=False)
        if not info or not info.get("url"):
            raise RuntimeError("Could not find an audio stream for that video.")
        return info["url"], info.get("title") or "Unknown track"

    async def _extract_tracks(self, source: str) -> list[Track]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._extract_tracks_sync, source)

    async def _stream_url(self, page_url: str) -> tuple[str, str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._stream_url_sync, page_url)

    async def _send_to_text_channel(self, guild_id: int, content: str) -> None:
        state = self._state(guild_id)
        if not state.text_channel_id:
            return
        channel = self.bot.get_channel(state.text_channel_id)
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(content)
            except discord.HTTPException:
                pass

    async def _start_next(self, guild_id: int) -> None:
        guild = self.bot.get_guild(guild_id)
        state = self._state(guild_id)
        voice_client = guild.voice_client if guild else None
        if voice_client is None or not voice_client.is_connected():
            return

        if not state.queue:
            if state.loop_enabled and state.playlist:
                state.queue.extend(state.playlist)
            else:
                state.current = None
                await self._send_to_text_channel(guild_id, "The queue is finished.")
                return

        track = state.queue.popleft()
        state.current = track
        try:
            stream_url, resolved_title = await self._stream_url(track.page_url)
            state.current = Track(title=resolved_title, page_url=track.page_url)
            source = discord.FFmpegOpusAudio(
                stream_url,
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                options="-vn",
            )

            def after(error: Exception | None) -> None:
                if error:
                    print(f"Music playback error in guild {guild_id}: {error}")
                future = asyncio.run_coroutine_threadsafe(self._track_finished(guild_id), self.bot.loop)
                try:
                    future.result()
                except Exception as callback_error:
                    print(f"Music callback error in guild {guild_id}: {callback_error}")

            voice_client.play(source, after=after)
            await self._send_to_text_channel(guild_id, f"▶️ Now playing **{resolved_title}**")
        except Exception as error:
            state.current = None
            await self._send_to_text_channel(guild_id, f"⚠️ I skipped that track: `{error}`")
            await self._start_next(guild_id)

    async def _track_finished(self, guild_id: int) -> None:
        state = self._state(guild_id)
        state.current = None
        await self._start_next(guild_id)

    @music.command(name="join", description="Join your current voice channel.")
    async def join(self, interaction: discord.Interaction) -> None:
        try:
            await self._join_user_channel(interaction)
            self._state(interaction.guild.id).text_channel_id = interaction.channel_id
            await interaction.response.send_message("🔊 Joined your voice channel.")
        except (RuntimeError, discord.DiscordException) as error:
            await interaction.response.send_message(f"⚠️ {error}", ephemeral=True)

    @music.command(name="play", description="Play a YouTube video, playlist, or search query.")
    @app_commands.describe(source="A YouTube link, playlist link, or song search")
    async def play(self, interaction: discord.Interaction, source: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("This command only works inside a server.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            voice_client = await self._join_user_channel(interaction)
            state = self._state(interaction.guild.id)
            state.text_channel_id = interaction.channel_id
            tracks = await self._extract_tracks(source)
            if not tracks:
                await interaction.followup.send("I couldn’t find any playable tracks from that source.")
                return

            state.playlist = tracks
            state.queue.extend(tracks)
            if voice_client.is_playing() or voice_client.is_paused():
                await interaction.followup.send(f"➕ Added **{len(tracks)}** track(s) to the repeat playlist.")
            else:
                await interaction.followup.send(f"🎶 Loaded **{len(tracks)}** track(s). Starting playback on repeat.")
                await self._start_next(interaction.guild.id)
        except (RuntimeError, discord.DiscordException) as error:
            await interaction.followup.send(f"⚠️ {error}")
        except Exception as error:
            await interaction.followup.send(f"⚠️ I couldn’t load that source: `{error}`")

    @music.command(name="pause", description="Pause the current track.")
    async def pause(self, interaction: discord.Interaction) -> None:
        voice_client = interaction.guild.voice_client if interaction.guild else None
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await interaction.response.send_message("⏸️ Paused.")
        else:
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)

    @music.command(name="resume", description="Resume the paused track.")
    async def resume(self, interaction: discord.Interaction) -> None:
        voice_client = interaction.guild.voice_client if interaction.guild else None
        if voice_client and voice_client.is_paused():
            voice_client.resume()
            await interaction.response.send_message("▶️ Resumed.")
        else:
            await interaction.response.send_message("Nothing is paused right now.", ephemeral=True)

    @music.command(name="skip", description="Skip the current track.")
    async def skip(self, interaction: discord.Interaction) -> None:
        voice_client = interaction.guild.voice_client if interaction.guild else None
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            voice_client.stop()
            await interaction.response.send_message("⏭️ Skipped.")
        else:
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)

    @music.command(name="queue", description="Show the current track and upcoming tracks.")
    async def queue(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("This command only works inside a server.", ephemeral=True)
            return
        state = self._state(interaction.guild.id)
        lines = [f"**Now:** {state.current.title if state.current else 'Nothing'}"]
        upcoming = list(state.queue)[:10]
        if upcoming:
            lines.append("\n".join(f"`{index}.` {track.title}" for index, track in enumerate(upcoming, 1)))
        else:
            lines.append("No tracks waiting.")
        loop_text = "on" if state.loop_enabled else "off"
        lines.append(f"\n**Repeat:** {loop_text}")
        await interaction.response.send_message("\n".join(lines))

    @music.command(name="loop", description="Turn playlist repeat on or off.")
    @app_commands.describe(enabled="Whether to repeat the loaded playlist")
    async def loop(self, interaction: discord.Interaction, enabled: bool) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("This command only works inside a server.", ephemeral=True)
            return
        self._state(interaction.guild.id).loop_enabled = enabled
        await interaction.response.send_message(f"🔁 Repeat is now **{'on' if enabled else 'off'}**.")

    @music.command(name="leave", description="Stop music and leave the voice channel.")
    async def leave(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("This command only works inside a server.", ephemeral=True)
            return
        voice_client = interaction.guild.voice_client
        state = self._state(interaction.guild.id)
        state.queue.clear()
        state.playlist.clear()
        state.current = None
        if voice_client:
            voice_client.stop()
            await voice_client.disconnect()
        await interaction.response.send_message("👋 Stopped playback and left the voice channel.")
