"""Download-and-send cog.

Reply to a message containing a link with `.dl` and the bot downloads the
media with yt-dlp (in-process, never through a shell) and sends it back to
the channel. Files are written to a temporary directory and deleted
immediately after upload, so nothing is cached on disk or in memory.

Spotify links are DRM-locked for yt-dlp, so a Spotify *track* URL is resolved
to a YouTube search (title + artist pulled from the track's OpenGraph tags)
and downloaded as an audio-only file. Album/playlist/artist links are
rejected with a friendly message.

If the media exceeds the server's upload limit it is refused and nothing is
sent.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import discord
from discord.ext import commands

try:
    import yt_dlp
    from yt_dlp.utils import (
        DownloadError as YtDlDownloadError,
        ExtractorError,
        GeoRestrictedError,
        UnsupportedError,
    )
except ImportError:
    yt_dlp = None
    YtDlDownloadError = ExtractorError = GeoRestrictedError = UnsupportedError = ()

try:
    from yt_dlp.networking.impersonate import ImpersonateTarget

    _IMPERSONATE_TARGET = ImpersonateTarget("chrome")
except Exception:
    _IMPERSONATE_TARGET = None

from utils.embeds import error_embed as _raw_error_embed


def _safe_error_embed(
    *, title: str = "Error", description: str | None = None, **kwargs
):
    # Cap every embed this cog sends at Discord's limits so a long Detail/error
    # string can never 400 us with "50035 Invalid Form Body".
    if description and len(description) > 4096:
        description = description[:4093] + "..."
    if title and len(title) > 256:
        title = title[:253] + "..."
    return _raw_error_embed(title=title, description=description, **kwargs)


error_embed = _safe_error_embed

# ---------------------------------------------------------------------------
# Hard-coded bot token (single-file deployment override)
#
# The token normally comes from config.py (env vars DISCORD_TOKEN / TOKEN).
# For deployments where pasting it into the code is preferred, put it below
# and it is injected into the running main script (`python main.py`, whose
# `bot.run(TOKEN)` reads its own module global). If the bot is launched some
# other way the main module has no `TOKEN` global and this is a silent no-op
# (config.py / env vars still apply). Leave the placeholder alone to keep the
# current behaviour.
# ---------------------------------------------------------------------------
BOT_TOKEN_OVERRIDE = "PASTE_YOUR_BOT_TOKEN_HERE"


def _inject_bot_token() -> None:
    token = (BOT_TOKEN_OVERRIDE or "").strip()
    if not token or token.startswith("PASTE_"):
        return
    main_module = sys.modules.get("__main__")
    if main_module is not None:
        setattr(main_module, "TOKEN", token)


_inject_bot_token()

DEFAULT_UPLOAD_LIMIT = 25 * 1024 * 1024  # 25 MiB (DMs / unknown guild limit)
DOWNLOAD_TIMEOUT_SECONDS = 600
CONCURRENCY_LIMIT = 2
MAX_CLIP_PARTS = 10

# Project root (the folder holding main.py). The cookies live in config/.
_BOT_ROOT = Path(__file__).resolve().parent.parent


def _cookies_file() -> str | None:
    """Absolute path to the uploaded ``config/cookies.txt``, or ``None`` if absent.

    Only the config folder is searched: the working directory and the temp dir
    are not trusted, since a file planted there would be used as cookies.
    Returns ``None`` when no non-empty file exists so callers can fall back.
    """
    for cand in (
        _BOT_ROOT / "config" / "cookies.txt",
    ):
        try:
            if cand.is_file() and cand.stat().st_size > 0:
                return str(cand.resolve())
        except OSError:
            continue
    return None

# This member gets one .dl download per rolling 8h window.
_LIMITED_USER_ID = 383330685139550208
_LIMIT_WINDOW_SECONDS = 0.5 * 60 * 60

_URL_RE = re.compile(r"https?://[^\s<>]+")

# Spotify is DRM-locked for yt-dlp (KnownDRMIE), so open.spotify.com URLs are
# intercepted and the track is resolved through a YouTube search instead.
_SPOTIFY_TRACK_RE = re.compile(
    r"https?://(?:open|play)\.spotify\.com(?:/intl-[a-z]{2})?(?:/user/[^/]+)?/track/(?P<id>[A-Za-z0-9]+)",
    re.IGNORECASE,
)
_SPOTIFY_NONTRACK_RE = re.compile(
    r"https?://(?:open|play)\.spotify\.com(?:/intl-[a-z]{2})?(?:/user/[^/]+)?/(?P<kind>album|playlist|artist)/[A-Za-z0-9]+",
    re.IGNORECASE,
)
_SPOTIFY_URI_RE = re.compile(r"spotify:(?P<kind>track):(?P<id>[A-Za-z0-9]+)", re.IGNORECASE)
_OG_RE = re.compile(
    r'<meta[^>]+property="(?P<prop>og:title|og:description)"[^>]+content="(?P<value>[^"]*)"'
)

# Douyin is not supported: its edge WAF (ArgusSecurity) only serves videos to
# real browsers, and this host can't provide the Chromium system libraries a
# real browser needs. Douyin links are still detected so the commands explain
# that kindly instead of crashing on a raw yt-dlp error.
_DOUYIN_HOSTS = {
    "douyin.com",
    "www.douyin.com",
    "m.douyin.com",
    "v.douyin.com",
    "iesdouyin.com",
    "www.iesdouyin.com",
    "v.iesdouyin.com",
}
_DOUYIN_UNSUPPORTED_MESSAGE = (
    "Douyin isn't supported on this host: its gate only serves video to real "
    "browsers, and the host lacks the Chromium system libraries needed to run "
    "one. Try a YouTube or other link instead."
)

_TIKTOK_PHOTO_UNSUPPORTED_MESSAGE = (
    "TikTok photo posts (slideshows) can't be downloaded: yt-dlp only supports "
    "TikTok videos. Send a link to a TikTok video instead."
)
_TIKTOK_NOT_A_VIDEO_MESSAGE = (
    "That TikTok link isn't a single video (it's a profile, tag, sound, live or "
    "discover page). Send a link to a specific TikTok video instead."
)

_PRIVATE_KEYWORDS = (
    "private video",
    "this video is private",
    "requires login",
    "login required",
    "member-only",
    "members only",
    "age-restricted",
    "only available to",
    "not available in your country",
    "unavailable in your country",
    "subscription",
)


_NETWORK_KEYWORDS = (
    "network",
    "unable to download",
    "connection",
    "timed out",
    "timeout",
    "dns",
    "tls",
    "ssl",
    "read error",
    "http error 5",
    "429",
    "too many requests",
    "rate limit",
)






class DownloadError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class FileTooLargeError(DownloadError):
    """Oversized media.

    Carries the measured size, the current server upload limit, and the media
    length so the command can report how much of the file would actually fit.
    When the file is already on disk ``filepath``/``media_info`` are attached so
    it can be cut down and re-sent after the user confirms.
    """

    def __init__(self, size: int, limit: int, duration_seconds: float | None = None):
        self.size = size
        self.limit = limit
        self.duration_seconds = duration_seconds
        self.filepath: Path | None = None
        self.media_info: dict | None = None
        super().__init__("The media is too large to send on Discord.")


def extract_url(text: str) -> str | None:
    """Return the first http(s) URL in ``text`` (strip trailing punctuation)."""
    match = _URL_RE.search(text or "")
    if not match:
        return None
    url = match.group(0).rstrip(".,;:!?)]}>")
    return url


async def _reply_url(ctx: commands.Context) -> tuple[str | None, discord.Message | None]:
    """Pull a media URL out of the message ``ctx`` replies to.

    Returns ``(url, replied_message)``; either can be ``None``.
    """
    reference = ctx.message.reference
    replied = None
    if reference is not None and reference.message_id is not None:
        try:
            replied = await ctx.channel.fetch_message(reference.message_id)
        except (discord.HTTPException, discord.Forbidden):
            replied = reference.resolved
    if replied is None or not isinstance(replied, discord.Message):
        return None, None
    url = extract_url(replied.content)
    if url is None and replied.attachments:
        url = replied.attachments[0].url
    if url is None:
        return None, replied
    if url.startswith("https://media.discordapp.net") or url.startswith("https://cdn.discordapp.com"):
        url = url.split("?")[0]
    return url, replied


def _is_douyin_url(url: str) -> bool:
    """Return whether ``url`` belongs to Douyin (any host or link shape)."""
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in _DOUYIN_HOSTS




def _tiktok_unsupported_message(url: str) -> str | None:
    """Explain why a TikTok URL can't be downloaded, or return ``None`` if it looks like a video.

    yt-dlp only extracts individual videos. Photo posts (slideshows) and pages such
    as profiles, tags, sounds, live streams and discover pages are rejected with a
    clear message instead of yt-dlp's generic "Unsupported URL".
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    if not (host == "tiktok.com" or host.endswith(".tiktok.com")):
        return None
    if host in ("vm.tiktok.com", "vt.tiktok.com"):
        return None  # short links: yt-dlp resolves them to the target
    path = parsed.path
    if "/photo/" in path:
        return _TIKTOK_PHOTO_UNSUPPORTED_MESSAGE
    if "/video/" in path or path.startswith("/t/"):
        return None
    return _TIKTOK_NOT_A_VIDEO_MESSAGE


def _is_spotify_url(url: str) -> bool:
    return bool(
        _SPOTIFY_TRACK_RE.search(url)
        or _SPOTIFY_NONTRACK_RE.search(url)
        or _SPOTIFY_URI_RE.search(url)
    )


def _spotify_search_query(url: str) -> str:
    """Resolve a Spotify track to a ``ytsearch1:`` query for yt-dlp.

    Spotify pages are server-rendered with OpenGraph tags, so we pull the
    track title + artist from the HTML and search for them on YouTube. Only
    single tracks are supported; albums/playlists/artists get a clear error.
    """
    match = _SPOTIFY_TRACK_RE.search(url) or _SPOTIFY_URI_RE.search(url)
    if match:
        track_url = f"https://open.spotify.com/track/{match.group('id')}"
        try:
            req = urllib.request.Request(
                track_url, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", "replace")
        except Exception:
            raise DownloadError(
                "Couldn't read that Spotify track. Try a direct YouTube link instead."
            ) from None

        title: str | None = None
        artist = ""
        for m in _OG_RE.finditer(html):
            prop, value = m.group("prop"), m.group("value")
            if prop == "og:title":
                title = value
            elif prop == "og:description" and not artist:
                artist = value.split("·")[0].strip()
        if not title:
            raise DownloadError(
                "Couldn't read that Spotify track. Try a direct YouTube link instead."
            )
        query = " ".join(p for p in (title, artist) if p)
        return f"ytsearch1:{query}"

    if _SPOTIFY_NONTRACK_RE.search(url):
        raise DownloadError(
            "Only Spotify **track** links can be downloaded. "
            "Album/playlist/artist links aren't supported yet — send a single "
            "track link instead."
        )
    raise DownloadError("This URL isn't supported for downloading.")


def _head_size_guard(url: str, max_filesize: int) -> None:
    """Refuse obvious oversized *direct* file links before yt-dlp downloads them.

    Platform pages don't report a useful Content-Length, so this is only a
    fast guard for plain direct-file URLs. When the size is unknown it's
    skipped and the size check that runs after yt-dlp finishes does the job.
    """
    try:
        req = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            length = resp.headers.get("Content-Length")
        if length and int(length) > max_filesize:
            raise DownloadError("The media is too large to send on Discord.")
    except DownloadError:
        raise
    except Exception:
        pass


_FFMPEG_NAME = "ffmpeg"


def _find_ffmpeg() -> str | None:
    """Locate ffmpeg: standard PATH first, then the imageio-ffmpeg wheel.

    imageio-ffmpeg ships a static ffmpeg binary and is a dependency, so on
    hosts where ffmpeg isn't installed system-wide (Windows dev, some shared
    hosting) the bot can still merge audio+video.
    """
    path = shutil.which(_FFMPEG_NAME)
    if path:
        return path
    try:
        import imageio_ffmpeg

        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and Path(path).exists():
            return path
    except Exception:
        pass
    return None


def _missing_requirements() -> list[str]:
    """Return human-readable messages for missing dependencies, if any."""
    missing: list[str] = []
    if yt_dlp is None:
        missing.append(
            "The `yt-dlp` package is not installed. Run `pip install -r requirements.txt`."
        )
    if _find_ffmpeg() is None:
        missing.append(
            "ffmpeg is not available, so YouTube and similar sites that split "
            "audio/video into separate streams can't be merged. Direct files and "
            "most social platforms still work. Install ffmpeg (`apt install ffmpeg` "
            "on Linux, or keep `imageio-ffmpeg` installed) to unlock full support."
        )
    return missing


def _retry_rmtree(path: Path, attempts: int = 5, delay: float = 0.25) -> None:
    """Delete a temp dir, retrying past transient Windows file locks.

    Downloads are still being scanned/indexed by the OS shortly after write,
    so a single rmtree can hit WinError 32. Give it a few quick retries and
    only give up silently at the end so the bot never crashes on cleanup.
    """
    for i in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except OSError:
            if i == attempts - 1:
                return
            time.sleep(delay)


def map_download_error(exc: Exception) -> str:
    """Human message for a yt-dlp failure, without leaking raw output."""
    if isinstance(exc, UnsupportedError):
        return "This URL isn't supported for downloading."

    message = str(exc).lower()

    # Specific, actionable failures are checked BEFORE the generic
    # private/restricted keywords, otherwise broad phrases like "sign in"
    # would swallow the more helpful messages below.
    if "could not find chrome cookies database" in message or (
        "could not find" in message and "cookies database" in message
    ):
        return (
            "No YouTube cookies are available on this host (Chrome isn't "
            "installed here). Put a `cookies.txt` (Netscape format) in the config folder "
            "and restart the bot."
        )
    if "sign in to confirm" in message or "are not a bot" in message:
        return (
            "YouTube is asking to confirm you're not a bot (anti-bot challenge). "
            "Put a valid `cookies.txt` (Netscape format) in the config folder and "
            "restart the bot, then try again."
        )
    if "only images are available" in message:
        return (
            "YouTube returned only images for this video (age/region/bot check). "
            "Put a valid `cookies.txt` (Netscape format) in the config folder and "
            "restart the bot, or try a different link."
        )
    if "ffmpeg" in message or "ffprobe" in message:
        return (
            "This download needs ffmpeg (audio conversion or audio+video merge) "
            "and it isn't available on this host. Install ffmpeg "
            "(`apt install ffmpeg` on Linux, or keep `imageio-ffmpeg` installed)."
        )
    if "requested format" in message or "no format matches" in message or "format is not available" in message:
        return (
            "No playable single-file version is available for this link. "
            "This often happens on hosted bots due to a missing JS runtime/PO "
            "token. Try a different source or ensure cookies are configured."
        )

    if "http error 403" in message or "http error 401" in message:
        return (
            "Download was temporarily blocked by the platform (anti-bot check "
            "or rate limit). Please try again in a few minutes."
        )
    if isinstance(exc, GeoRestrictedError):
        return "This content is private or restricted and can't be downloaded."
    if any(k in message for k in _PRIVATE_KEYWORDS):
        return "This content is private or restricted and can't be downloaded."

    if "max-filesize" in message or ("larger than" in message and "file" in message):
        return "The media is too large to send on Discord."

    if any(k in message for k in _NETWORK_KEYWORDS):
        return "Network failure while downloading."
    # Checked after the network keywords so 429/rate-limit wins over the generic
    # "http error 4x" fallback below.
    if "http error 4" in message or "http error 410" in message:
        return "The media is unavailable."
    if "unsupported" in message or "is not a valid url" in message:
        return "This URL isn't supported for downloading."

    if isinstance(exc, (YtDlDownloadError, ExtractorError)):
        return "Couldn't download this media."

    return "Couldn't download this media."


def _format_mb(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _format_duration(total_seconds: float) -> str:
    total_seconds = int(round(total_seconds))
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _duration_seconds(info) -> float | None:
    """Media length in seconds from a yt-dlp info dict.

    Some providers report milliseconds, so any absurdly large value (>1 day)
    is normalised to seconds.
    """
    try:
        duration = float((info or {}).get("duration") or 0)
    except (TypeError, ValueError):
        return None
    if duration <= 0:
        return None
    if duration > 86400:
        duration /= 1000.0
    return duration


def _too_large_embed(error: FileTooLargeError) -> discord.Embed:
    """Embed reporting an oversized download and the largest chunk that fits.

    Uses the *current* server limit (boost-aware), so the answer changes as the
    server's upload allowance does.
    """
    size_mb = error.size / (1024 * 1024)
    limit_mb = error.limit / (1024 * 1024)
    duration = error.duration_seconds
    lines = [
        "**This media is too big to send on Discord.**",
        "",
        f"File size: {size_mb:.1f} MB",
        f"Server limit: {limit_mb:.1f} MB (varies with this server's boost level)",
        "Total length: " + (_format_duration(duration) if duration else "unknown"),
        "",
    ]
    if duration and error.size > 0:
        first_region = duration * (error.limit / error.size)
        lines.append(
            f"Largest chunk that fits from the start: ~{_format_duration(first_region)}"
        )
    else:
        lines.append("Couldn't estimate the largest chunk — the length is unknown.")
    if error.filepath is None or error.duration_seconds is None:
        # No parked file to work on, so the buttons below won't appear.
        lines.extend(
            [
                "",
                "This file wasn't kept, so it can't be cut automatically. "
                "Try `.dsplit` (smallest number of equal parts that fit) or "
                "`.dclip <start> <end>` to grab a specific section.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Use the buttons below: **Send the first part** cuts the largest "
                "start section that fits, or **Send all parts** splits the whole "
                "media into equal parts and sends them in order.",
            ]
        )
    return error_embed(description="\n".join(lines))


def _trim_first_region(
    source: Path, limit: int, duration_seconds: float | None
) -> tuple[Path, float]:
    """Cut the largest prefix of ``source`` that fits under ``limit``.

    Returns ``(clip_path, clipped_seconds)``. The first attempt copies streams
    (fast, no re-encode); keyframe granularity can push the result a few
    percent over the target, so the region is shortened and retried. If the
    copy fails entirely the clip is re-encoded instead.
    """
    ffmpeg = _find_ffmpeg()
    if ffmpeg is None:
        raise DownloadError(
            "ffmpeg is required to send only the first part of this video."
        )
    total = source.stat().st_size
    region = duration_seconds or 0.0
    if total > 0 and region > 0:
        region = region * (limit / total)
    if region <= 0:
        raise DownloadError("Couldn't work out how much of the video to cut.")
    out = source.parent / "first_part.mp4"

    def _run(cmd: list[str]) -> None:
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=600)
        except Exception:
            pass

    for attempt in range(6):
        _run(
            [
                ffmpeg, "-y",
                "-ss", "0",
                "-i", str(source),
                "-t", f"{region:.2f}",
                "-c", "copy",
                str(out),
            ]
        )
        if out.exists():
            if out.stat().st_size <= limit:
                return out, region
            region *= 0.92  # slightly over: shorten and retry
        else:
            # Stream-copy failed for this container; fall back to a re-encode.
            if attempt == 0:
                _run(
                    [
                        ffmpeg, "-y",
                        "-ss", "0",
                        "-i", str(source),
                        "-t", f"{region:.2f}",
                        "-c:v", "libx264",
                        "-preset", "veryfast",
                        "-c:a", "aac",
                        str(out),
                    ]
                )
                if out.exists() and out.stat().st_size <= limit:
                    return out, region
            region *= 0.92
    if out.exists():
        return out, region
    raise DownloadError("Couldn't cut the first part of this video.")


class FirstPartConfirmView(discord.ui.View):
    """\"Confirm first, then send\": lets the requester cut and send just the
    first region of a video that was too big for Discord."""

    def __init__(
        self,
        *,
        channel,
        author_id: int,
        filepath: Path,
        limit: int,
        duration_seconds: float | None,
        title: str | None,
        sender_name: str | None,
    ):
        super().__init__(timeout=300)
        self._channel = channel
        self._author_id = author_id
        self._filepath = filepath
        self._limit = limit
        self._duration_seconds = duration_seconds
        self._title = (title or "Downloaded media")[:80]
        self._sender_name = sender_name or "Unknown"
        self._done = False

    def _cleanup(self) -> None:
        if self._filepath is None:
            return
        try:
            if self._filepath.parent.is_dir():
                _retry_rmtree(self._filepath.parent)
        finally:
            self._filepath = None

    async def on_timeout(self) -> None:
        self._cleanup()

    @discord.ui.button(label="Send the first part", style=discord.ButtonStyle.secondary)
    async def _send_first_part(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if interaction.user.id != self._author_id:
            await interaction.response.send_message(
                "Only the person who requested this download can confirm.",
                ephemeral=True,
            )
            return
        if self._done:
            return
        self._done = True
        await interaction.response.defer()
        try:
            loop = asyncio.get_running_loop()
            clip_path, clip_seconds = await loop.run_in_executor(
                None,
                _trim_first_region,
                self._filepath,
                self._limit,
                self._duration_seconds,
            )
        except Exception as exc:
            message = exc.message if isinstance(exc, DownloadError) else map_download_error(exc)
            await self._channel.send(embed=error_embed(description=message))
            self._cleanup()
        else:
            file = discord.File(clip_path, filename=clip_path.name)
            try:
                await self._channel.send(
                    content=(
                        f"**{self._sender_name} -> {self._title}** "
                        f"(first {_format_duration(clip_seconds)})"
                    ),
                    file=file,
                )
            finally:
                file.close()
            self._cleanup()
        try:
            await interaction.message.edit(view=None)
        except discord.HTTPException:
            pass


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def _ffmpeg_duration(path: Path) -> float | None:
    """Probe media length (seconds) from ffmpeg's own header dump."""
    ffmpeg = _find_ffmpeg()
    if ffmpeg is None:
        return None
    try:
        result = subprocess.run(
            [ffmpeg, "-i", str(path)], capture_output=True, timeout=60
        )
        match = _DURATION_RE.search(result.stderr.decode("utf-8", "replace"))
    except Exception:
        return None
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return float(hours) * 3600 + float(minutes) * 60 + float(seconds)


def _parse_timestamp(value: str) -> float | None:
    """Parse ``ss``, ``mm:ss`` or ``hh:mm:ss`` into seconds (comma or dot decimals)."""
    text = (value or "").strip().replace(",", ".")
    if not text:
        return None
    chunks = text.split(":")
    if len(chunks) > 3:
        return None
    total = 0.0
    for chunk in chunks:
        try:
            number = float(chunk)
        except ValueError:
            return None
        if number < 0:
            return None
        total = total * 60 + number
    return total


def _parse_clip_args(raw: str | None) -> tuple[float, float | None, int | None, str | None]:
    """Parse ``start [end] [parts]`` for `.dclip`.

    A second value smaller than the start reads as a part count rather than an
    end time, so `.dclip 1:30 3` means "from 1:30 to the end, in 3 parts".
    Returns ``(start, end, parts, error)``.
    """
    tokens = (raw or "").split()
    if not tokens:
        return (
            0.0,
            None,
            None,
            "Usage: `.dclip <start> [end] [parts]` — e.g. `.dclip 1:30 2:45` or `.dclip 1:30 2:45 3`.",
        )
    start = _parse_timestamp(tokens[0])
    if start is None:
        return (
            0.0,
            None,
            None,
            f"`{tokens[0]}` isn't a timestamp. Use seconds (`90`), `m:ss` (`1:30`) or `h:mm:ss` (`1:02:03`).",
        )

    end: float | None = None
    parts: int | None = None
    for token in tokens[1:]:
        value = _parse_timestamp(token)
        if end is None and parts is None and value is not None and value > start:
            end = value
            continue
        if parts is None and token.isdigit() and int(token) >= 2:
            parts = int(token)
            continue
        return 0.0, None, None, f"`{token}` isn't a timestamp or a part count."

    if parts is not None and parts > MAX_CLIP_PARTS:
        return 0.0, None, None, f"At most **{MAX_CLIP_PARTS}** parts are supported."
    return start, end, parts, None


def _format_range(start: float, end: float | None) -> str:
    left = _format_duration(start)
    right = _format_duration(end) if end is not None else "end"
    return f"{left} → {right}"


def _clip_looks_usable(path: Path, length: float) -> bool:
    """Whether a freshly cut file really holds the requested duration.

    Guards against ffmpeg quietly handing back the whole file (or an empty
    shell) when the requested range doesn't exist.
    """
    if not path.exists() or path.stat().st_size <= 0:
        return False
    produced = _ffmpeg_duration(path)
    if produced is None:
        return False  # no readable duration header means a broken/empty cut
    return abs(produced - length) <= max(1.5, 0.2 * length)


def _cut_region(source: Path, start: float, length: float) -> Path:
    """Cut ``length`` seconds starting at ``start`` out of ``source``.

    Fast seek + stream copy first; if that can't produce a usable file (odd
    container, cut not on a keyframe) the region is re-encoded so the cut lands
    exactly on the requested timestamp.
    """
    ffmpeg = _find_ffmpeg()
    if ffmpeg is None:
        raise DownloadError(
            "Clipping needs ffmpeg to be installed "
            "(`apt install ffmpeg` on Linux, or keep `imageio-ffmpeg` installed)."
        )
    if length <= 0:
        raise DownloadError("That timestamp range is empty.")
    out = source.parent / f"clip_{int(start)}_{int(start + length)}.mp4"

    def _run(cmd: list[str]) -> None:
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=3600)
        except Exception:
            pass

    def _usable() -> bool:
        return _clip_looks_usable(out, length)

    for transcode in (False, True):
        cmd = [
            ffmpeg, "-y",
            "-ss", f"{start:.3f}",
            "-i", str(source),
            "-t", f"{length:.3f}",
        ]
        if transcode:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac"]
        else:
            cmd += ["-c", "copy"]
        cmd.append(str(out))
        _run(cmd)
        if _usable():
            return out
        try:
            if out.exists():
                out.unlink()
        except OSError:
            pass
    raise DownloadError("Couldn't cut that part of the video.")


def _split_into_parts(
    source: Path,
    n_parts: int,
    workdir: Path,
    duration_seconds: float | None = None,
) -> list[Path]:
    """Evenly split ``source`` into ``n_parts`` equal-duration mp4 segments.

    A per-part seek+cut with stream copy (fast) is tried first. Keyframe
    granularity can make exact boundaries impossible to honour with ``-c copy``,
    so if no parts come out the whole file is re-encoded with keyframes forced
    at every boundary and cut again. Returns the ``part_*.mp4`` paths.
    """
    ffmpeg = _find_ffmpeg()
    if ffmpeg is None:
        raise DownloadError(
            "Splitting a video needs ffmpeg to be installed "
            "(`apt install ffmpeg` on Linux, or keep `imageio-ffmpeg`)."
        )
    n_parts = max(1, int(n_parts))
    duration = duration_seconds or _ffmpeg_duration(source)
    if not duration or duration <= 0:
        raise DownloadError(
            "Couldn't read the video's length, so it can't be split evenly."
        )
    segment_time = duration / n_parts

    for stale in workdir.glob("part_*.mp4"):
        try:
            stale.unlink()
        except OSError:
            pass

    def _cut(src: Path, start: float, length: float, out: Path, transcode: bool) -> None:
        cmd = [
            ffmpeg, "-y",
            "-ss", f"{start:.3f}",
            "-i", str(src),
            "-t", f"{length:.3f}",
        ]
        if transcode:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac"]
        else:
            cmd += ["-c", "copy"]
        cmd.append(str(out))
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=1800)
        except Exception:
            pass

    for i in range(n_parts):
        start = i * segment_time
        if start >= duration - 0.05:
            break
        _cut(source, start, segment_time, workdir / f"part_{i + 1:03d}.mp4", transcode=False)

    parts = sorted(workdir.glob("part_*.mp4"))
    if parts:
        return parts

    # Nothing cut with stream copy: force keyframes at every boundary, then cut.
    encoded = workdir / "_encoded.mp4"
    boundaries = ",".join(
        f"{i * segment_time:.3f}" for i in range(1, n_parts)
    )
    try:
        subprocess.run(
            [
                ffmpeg, "-y",
                "-i", str(source),
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-c:a", "aac",
                "-force_key_frames", boundaries,
                str(encoded),
            ],
            check=False,
            capture_output=True,
            timeout=3600,
        )
    except Exception:
        pass
    if encoded.exists():
        for i in range(n_parts):
            start = i * segment_time
            if start >= duration - 0.05:
                break
            _cut(encoded, start, segment_time, workdir / f"part_{i + 1:03d}.mp4", transcode=False)
        parts = sorted(workdir.glob("part_*.mp4"))
        if parts:
            return parts
    raise DownloadError("Couldn't split the media into parts.")


def _split_plan_embed(
    size: int,
    limit: int,
    duration_seconds: float | None,
    n_parts: int,
) -> discord.Embed:
    lines = [
        "**Splitting this media into equal parts**",
        "",
        f"File size: {_format_mb(size)}",
        f"Server limit: {_format_mb(limit)} (varies with this server's boost level)",
        f"Parts: {n_parts} (≈ {size / max(1, n_parts) / (1024 * 1024):.1f} MB each)",
    ]
    if duration_seconds:
        lines.append(f"≈ {_format_duration(duration_seconds / max(1, n_parts))} each")
    lines.extend(["", "Press the button to send all parts."])
    return error_embed(description="\n".join(lines))


def _split_min_parts_embed(
    size: int,
    limit: int,
    duration_seconds: float | None,
    min_parts: int,
) -> discord.Embed:
    lines = [
        "**Not enough parts for this server's limit**",
        "",
        f"File size: {_format_mb(size)}",
        f"Server limit: {_format_mb(limit)}",
        f"This needs at least **{min_parts}** equal parts to fit.",
    ]
    if duration_seconds:
        lines.append(f"≈ {_format_duration(duration_seconds / max(1, min_parts))} per part")
    lines.extend(["", f"Try `.dsplit {min_parts}`."])
    return error_embed(description="\n".join(lines))


def _clip_plan_embed(
    range_text: str,
    size: int,
    limit: int,
    n_parts: int,
    part_seconds: float | None,
) -> discord.Embed:
    lines = [
        "**Clipping this media**",
        "",
        f"Range: {range_text}",
        f"Clip size: {_format_mb(size)}",
        f"Server limit: {_format_mb(limit)} (varies with this server's boost level)",
        f"Parts: {n_parts} (≈ {size / max(1, n_parts) / (1024 * 1024):.1f} MB each)",
    ]
    if part_seconds:
        lines.append(f"≈ {_format_duration(part_seconds)} each")
    lines.extend(["", "Press the button to send all parts."])
    return error_embed(description="\n".join(lines))


def _clip_too_big_embed(
    size: int, limit: int, min_parts: int, args: str
) -> discord.Embed:
    return error_embed(
        description=(
            "**That clip is too big for this server**\n\n"
            f"Clip size: {_format_mb(size)}\n"
            f"Server limit: {_format_mb(limit)}\n"
            f"Needs at least **{min_parts}** parts to fit.\n\n"
            f"Try `.dclip {args} {min_parts}`."
        )
    )


class SplitConfirmView(discord.ui.View):
    """Confirm-first view that sends every part of a split download."""

    def __init__(
        self,
        *,
        channel,
        author_id: int,
        workdir: Path,
        parts: list[Path],
        title: str | None,
        sender_name: str | None,
        n_parts: int,
    ):
        super().__init__(timeout=600)
        self._channel = channel
        self._author_id = author_id
        self._workdir = workdir
        self._parts = parts
        self._title = (title or "Downloaded media")[:80]
        self._sender_name = sender_name or "Unknown"
        self._n_parts = max(1, n_parts)
        self._done = False

    def _cleanup(self) -> None:
        if self._workdir is None:
            return
        try:
            if self._workdir.is_dir():
                _retry_rmtree(self._workdir)
        finally:
            self._workdir = None
            self._parts = []

    async def on_timeout(self) -> None:
        self._cleanup()

    @discord.ui.button(label="Send all parts", style=discord.ButtonStyle.secondary)
    async def _send_all(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if interaction.user.id != self._author_id:
            await interaction.response.send_message(
                "Only the person who requested this download can confirm.",
                ephemeral=True,
            )
            return
        if self._done:
            return
        self._done = True
        await interaction.response.defer()
        try:
            total = len(self._parts)
            for idx, part in enumerate(self._parts, start=1):
                if not part.exists():
                    continue
                file = discord.File(part, filename=part.name)
                try:
                    await self._channel.send(
                        content=(
                            f"**{self._sender_name} -> {self._title}** "
                            f"(part {idx}/{self._n_parts})"
                        ),
                        file=file,
                    )
                finally:
                    file.close()
                if idx < total:
                    await asyncio.sleep(0.5)  # breathing room for Discord limits
        finally:
            self._cleanup()
            try:
                await interaction.message.edit(view=None)
            except discord.HTTPException:
                pass


class DownloadCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._semaphore: asyncio.Semaphore | None = None
        self._limited_last_use: dict[int, float] = {}

    def _lock(self) -> asyncio.Semaphore:
        # Created lazily so the semaphore binds to the running (bot) loop,
        # not the loop used during add_cog() in startcog().
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        return self._semaphore

    def _upload_limit(self, ctx: commands.Context) -> int:
        guild = getattr(ctx, "guild", None)
        if guild is not None:
            return max(guild.filesize_limit or DEFAULT_UPLOAD_LIMIT, 1)
        return DEFAULT_UPLOAD_LIMIT

    async def _handle_too_large(
        self,
        ctx: commands.Context,
        error: FileTooLargeError,
        sender_name: str,
    ) -> None:
        """Report an oversized download and offer to cut+send the first part."""
        embed = _too_large_embed(error)
        if error.filepath is None or error.duration_seconds is None:
            # The size was known before download (or the length is unknown), so
            # there is no parked file to cut — just report the numbers.
            await ctx.send(embed=embed)
            return
        view = FirstPartConfirmView(
            channel=ctx.channel,
            author_id=ctx.author.id,
            filepath=error.filepath,
            limit=error.limit,
            duration_seconds=error.duration_seconds,
            title=(error.media_info or {}).get("title"),
            sender_name=sender_name,
        )
        await ctx.send(embed=embed, view=view)

    @staticmethod
    def _download_blocking(
        url: str,
        workdir: Path,
        max_filesize: int,
        cancel_event: threading.Event | None = None,
        audio_only: bool = False,
        audio_codec: str | None = None,
    ) -> tuple[Path, dict]:
        def _check_cancel(d: dict) -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise DownloadError("Download timed out.")

        if _is_douyin_url(url):
            raise DownloadError(_DOUYIN_UNSUPPORTED_MESSAGE)
        tiktok_message = _tiktok_unsupported_message(url)
        if tiktok_message is not None:
            raise DownloadError(tiktok_message)

        opts: dict = {
            "outtmpl": str(workdir / "%(title).80B.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "socket_timeout": 30,
            "retries": 2,
            "fragment_retries": 2,
            # Keep temp filenames ASCII so emoji/unicode titles in recorded
            # media can't break the filesystem on Windows (cp1252) hosts.
            "restrictfilenames": True,
        }
        ffmpeg_path = _find_ffmpeg()
        if audio_codec:
            # Full audio re-encode (e.g. MP3): pull the best audio stream and
            # convert it with ffmpeg, which is a hard requirement here.
            if ffmpeg_path is None:
                raise DownloadError(
                    "MP3 downloads need ffmpeg to convert the audio. Install it "
                    "on the host (`apt install ffmpeg` on Linux, or keep "
                    "`imageio-ffmpeg` installed)."
                )
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_codec,
                    "preferredquality": "192",
                }
            ]
            if os.path.dirname(ffmpeg_path):
                opts["ffmpeg_location"] = os.path.dirname(ffmpeg_path)
        elif audio_only:
            # Music-only downloads prefer a small, Discord-playable file. The
            # video/audio merge and 1080p video selection only apply otherwise.
            opts["format"] = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"
        elif ffmpeg_path is not None:
            opts["format"] = "bv*[height<=1080]+ba/b[height<=1080]/b"
            opts["merge_output_format"] = "mp4"
            if os.path.dirname(ffmpeg_path):
                opts["ffmpeg_location"] = os.path.dirname(ffmpeg_path)
        else:
            # Without ffmpeg we fall back to best single-file format (matching
            # the proven LinkShare backend defaults). This gives a usable media
            # file on most platforms; split-only videos fail cleanly with a
            # friendly "needs ffmpeg" message.
            opts["format"] = "best[ext=mp4]/best"

        # Impersonate a real browser TLS fingerprint so anti-bot platforms like
        # TikTok don't reject the request. Falls back gracefully to no
        # impersonation if curl_cffi is unavailable.
        if _IMPERSONATE_TARGET is not None:
            opts["impersonate"] = _IMPERSONATE_TARGET
        # Use the cookies.txt uploaded in the config folder for authentication
        # (YouTube bot checks and similar). yt-dlp's `cookiefile` is the
        # library equivalent of the CLI's `--cookies`.
        cookies = _cookies_file()
        if cookies:
            opts["cookiefile"] = cookies
        else:
            # No cookies file found: continue without it rather than failing.
            # Some platforms still work, and the error mapper explains how to
            # add one if a download is blocked.
            pass
        if cancel_event is not None:
            opts["progress_hooks"] = [_check_cancel]

        if url.startswith("http"):
            _head_size_guard(url, max_filesize)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception:
            # A stale/invalid cookie file is the most common failure; retry
            # once without it before giving up.
            opts2 = dict(opts)
            opts2.pop("cookiefile", None)
            with yt_dlp.YoutubeDL(opts2) as ydl:
                info = ydl.extract_info(url, download=False)

        if cancel_event is not None and cancel_event.is_set():
            raise DownloadError("Download timed out.")

        size = info.get("filesize") or info.get("filesize_approx") or 0
        req = (info.get("requested_downloads") or [{}])[0]
        size = size or req.get("filesize") or req.get("filesize_approx") or 0
        if size and size > max_filesize:
            raise FileTooLargeError(size, max_filesize, _duration_seconds(info))

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception:
            opts2 = dict(opts)
            opts2.pop("cookiefile", None)
            with yt_dlp.YoutubeDL(opts2) as ydl:
                info = ydl.extract_info(url, download=True)

        if cancel_event is not None and cancel_event.is_set():
            raise DownloadError("Download timed out.")

        files = [p for p in workdir.iterdir() if p.is_file()]
        if not files:
            raise DownloadError("Downloaded file not found.")
        return max(files, key=lambda p: p.stat().st_size), info

    async def _download_and_send(self, ctx: commands.Context, url: str, audio_only: bool = False, audio_codec: str | None = None, sender_name: str | None = None) -> None:
        limit = self._upload_limit(ctx)
        workdir = Path(tempfile.mkdtemp(prefix="village_dl_"))
        processing_msg = None
        try:
            processing_msg = await ctx.send("Downloading…")
        except (discord.HTTPException, discord.Forbidden):
            processing_msg = None
        pending_cleanup = True
        try:
            loop = asyncio.get_running_loop()
            cancel_event = threading.Event()
            async with self._lock():
                try:
                    filepath, info = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            self._download_blocking,
                            url,
                            workdir,
                            limit,
                            cancel_event,
                            audio_only,
                            audio_codec,
                        ),
                        timeout=DOWNLOAD_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    cancel_event.set()
                    raise DownloadError("The download timed out.")
                except DownloadError:
                    raise
                except Exception as exc:
                    raise DownloadError(map_download_error(exc)) from None

            size = filepath.stat().st_size
            if size > limit:
                # Park the file so the user can confirm cutting the first part
                # that fits; cleanup is then deferred to the confirm view.
                err = FileTooLargeError(size, limit, _duration_seconds(info))
                err.filepath = filepath
                err.media_info = info
                pending_cleanup = False
                raise err

            filename = filepath.name
            # Passing the path means File opens (and owns) the handle: media is
            # streamed from disk, never buffered in RAM, and discord.py closes
            # it after uploading. We also close() explicitly so the temp file is
            # never left locked on Windows even if the send is only mocked.
            file = discord.File(filepath, filename=filename)
            try:
                await ctx.send(
                    content=f"**{(sender_name or 'Unknown')[:100]} -> {str(info.get('title') or 'Downloaded media')[:1500]}**",
                    file=file,
                )
            finally:
                file.close()
        finally:
            # Remove the "Downloading…" message whether the media arrived or
            # the download failed, so only the result (or error) stays.
            if processing_msg is not None:
                try:
                    await processing_msg.delete()
                except (discord.HTTPException, discord.Forbidden):
                    pass
            if pending_cleanup:
                _retry_rmtree(workdir)

    @commands.command(name="dl")
    async def dl(self, ctx: commands.Context):
        """Reply to a message with a link to download the media and send it here (Spotify tracks supported). Removes the link message and command on success."""
        now = time.time()
        last = self._limited_last_use.get(_LIMITED_USER_ID)
        if ctx.author.id == _LIMITED_USER_ID and last and now - last < _LIMIT_WINDOW_SECONDS:
            available_at = int(last + _LIMIT_WINDOW_SECONDS)
            await ctx.send(
                embed=error_embed(
                    description=f"⏳ You've used `.dl` recently. It's ready again <t:{available_at}:R>."
                )
            )
            return

        if yt_dlp is None:
            await ctx.send(
                embed=error_embed(
                    description=(
                        "The `yt-dlp` package isn't installed, so downloads are "
                        "disabled.\n\nOn the host run:\n```\npip install -r requirements.txt\n```"
                    )
                )
            )
            return

        reference = ctx.message.reference
        replied = None
        if reference is not None and reference.message_id is not None:
            try:
                replied = await ctx.channel.fetch_message(reference.message_id)
            except (discord.HTTPException, discord.Forbidden):
                replied = reference.resolved
        if replied is None or not isinstance(replied, discord.Message):
            await ctx.send(
                embed=error_embed(
                    description="Reply to a message containing a media link.",
                )
            )
            return

        url = extract_url(replied.content)
        if url is None and replied.attachments:
            url = replied.attachments[0].url
        if url is None:
            await ctx.send(
                embed=error_embed(
                    description="Reply to a message containing a media link.",
                )
            )
            return
        if url and (url.startswith("https://media.discordapp.net") or url.startswith("https://cdn.discordapp.com")):
            url = url.split("?")[0]

        audio_only = False
        if _is_spotify_url(url):
            try:
                url = _spotify_search_query(url)
                audio_only = True
            except DownloadError as e:
                await ctx.send(embed=error_embed(description=e.message))
                return

        sender_name = replied.author.display_name if replied and getattr(replied, "author", None) else "Unknown"
        try:
            await self._download_and_send(
                ctx, url, audio_only=audio_only, sender_name=sender_name
            )
        except FileTooLargeError as e:
            await self._handle_too_large(ctx, e, sender_name)
            return
        except DownloadError as e:
            await ctx.send(embed=error_embed(description=e.message))
            return
        except Exception as e:
            await ctx.send(embed=error_embed(description=map_download_error(e)))
            print(f"DL error: {e}")
            return

        # Only reached on success: remove the reply header plus the command
        # message so the channel only shows the downloaded clip. Both messages
        # belong to users, so deletion needs Manage Messages; other failures
        # (no permission, blocked, race) are silently ignored.
        if ctx.author.id == _LIMITED_USER_ID:
            self._limited_last_use[_LIMITED_USER_ID] = now
        for msg in (replied, ctx.message):
            try:
                if msg is not None:
                    await msg.delete()
            except (discord.HTTPException, discord.Forbidden):
                pass

    @commands.command(name="mdl")
    async def mdl(self, ctx: commands.Context):
        """Reply to a message with a link to get its audio as an MP3 (YouTube, Spotify, and other providers). Removes the link message and command on success."""
        if yt_dlp is None:
            await ctx.send(
                embed=error_embed(
                    description=(
                        "The `yt-dlp` package isn't installed, so downloads are "
                        "disabled.\n\nOn the host run:\n```\npip install -r requirements.txt\n```"
                    )
                )
            )
            return

        if _find_ffmpeg() is None:
            await ctx.send(
                embed=error_embed(
                    description=(
                        "MP3 downloads need ffmpeg to convert the audio. Install "
                        "it on the host (`apt install ffmpeg` on Linux, or keep "
                        "`imageio-ffmpeg` installed)."
                    )
                )
            )
            return

        reference = ctx.message.reference
        replied = None
        if reference is not None and reference.message_id is not None:
            try:
                replied = await ctx.channel.fetch_message(reference.message_id)
            except (discord.HTTPException, discord.Forbidden):
                replied = reference.resolved
        if replied is None or not isinstance(replied, discord.Message):
            await ctx.send(
                embed=error_embed(
                    description="Reply to a message containing a media link.",
                )
            )
            return

        url = extract_url(replied.content)
        if url is None and replied.attachments:
            url = replied.attachments[0].url
        if url is None:
            await ctx.send(
                embed=error_embed(
                    description="Reply to a message containing a media link.",
                )
            )
            return
        if url and (url.startswith("https://media.discordapp.net") or url.startswith("https://cdn.discordapp.com")):
            url = url.split("?")[0]

        if _is_spotify_url(url):
            try:
                url = _spotify_search_query(url)
            except DownloadError as e:
                await ctx.send(embed=error_embed(description=e.message))
                return

        sender_name = replied.author.display_name if replied and getattr(replied, "author", None) else "Unknown"
        try:
            await self._download_and_send(
                ctx,
                url,
                audio_codec="mp3",
                sender_name=sender_name,
            )
        except FileTooLargeError as e:
            await self._handle_too_large(ctx, e, sender_name)
            return
        except DownloadError as e:
            await ctx.send(embed=error_embed(description=e.message))
            return
        except Exception as e:
            await ctx.send(embed=error_embed(description=map_download_error(e)))
            print(f"MDL error: {e}")
            return

        # Only reached on success: remove the reply header plus the command
        # message so the channel only shows the resulting MP3.
        for msg in (replied, ctx.message):
            try:
                if msg is not None:
                    await msg.delete()
            except (discord.HTTPException, discord.Forbidden):
                pass

    @commands.command(name="dsplit")
    async def dsplit(self, ctx: commands.Context, parts: int | None = None):
        """Reply to a message with a link to download it and send it split into N equal parts. `.dsplit 2` = 2 parts; without a number it uses the minimum parts that fit Discord's upload limit. Confirms before sending."""
        if yt_dlp is None:
            await ctx.send(
                embed=error_embed(
                    description=(
                        "The `yt-dlp` package isn't installed, so downloads are "
                        "disabled.\n\nOn the host run:\n```\npip install -r requirements.txt\n```"
                    )
                )
            )
            return

        if _find_ffmpeg() is None:
            await ctx.send(
                embed=error_embed(
                    description=(
                        "Splitting a video needs ffmpeg to be installed "
                        "(`apt install ffmpeg` on Linux, or keep "
                        "`imageio-ffmpeg` installed)."
                    )
                )
            )
            return

        reference = ctx.message.reference
        replied = None
        if reference is not None and reference.message_id is not None:
            try:
                replied = await ctx.channel.fetch_message(reference.message_id)
            except (discord.HTTPException, discord.Forbidden):
                replied = reference.resolved
        if replied is None or not isinstance(replied, discord.Message):
            await ctx.send(
                embed=error_embed(
                    description="Reply to a message containing a media link.",
                )
            )
            return

        url = extract_url(replied.content)
        if url is None and replied.attachments:
            url = replied.attachments[0].url
        if url is None:
            await ctx.send(
                embed=error_embed(
                    description="Reply to a message containing a media link.",
                )
            )
            return
        if url and (url.startswith("https://media.discordapp.net") or url.startswith("https://cdn.discordapp.com")):
            url = url.split("?")[0]

        if _is_spotify_url(url):
            try:
                url = _spotify_search_query(url)
            except DownloadError as e:
                await ctx.send(embed=error_embed(description=e.message))
                return

        limit = self._upload_limit(ctx)
        workdir = Path(tempfile.mkdtemp(prefix="village_split_"))
        processing_msg = None
        try:
            processing_msg = await ctx.send("Downloading…")
        except (discord.HTTPException, discord.Forbidden):
            processing_msg = None
        parked = False
        try:
            loop = asyncio.get_running_loop()
            filepath, info = await loop.run_in_executor(
                None,
                self._download_blocking,
                url,
                workdir,
                10 * 1024**3,  # don't refuse on size: the split handles it
                None,
                False,
                None,
            )
            size = filepath.stat().st_size
            duration = _duration_seconds(info)
            # A small margin absorbs keyframe drift from stream-copy cuts so a
            # part can't sneak just over the limit.
            per_part_limit = int(limit * 0.94)
            min_parts = max(1, (size + per_part_limit - 1) // per_part_limit)
            n_parts = parts if parts and parts > 0 else min_parts
            if n_parts < min_parts:
                await ctx.send(embed=_split_min_parts_embed(size, limit, duration, min_parts))
                return

            part_files = await loop.run_in_executor(
                None, _split_into_parts, filepath, n_parts, workdir, duration
            )
            if any(p.stat().st_size > limit for p in part_files):
                await ctx.send(embed=_split_min_parts_embed(size, limit, duration, min_parts))
                return

            parked = True
            sender_name = replied.author.display_name if replied and getattr(replied, "author", None) else "Unknown"
            view = SplitConfirmView(
                channel=ctx.channel,
                author_id=ctx.author.id,
                workdir=workdir,
                parts=part_files,
                title=info.get("title"),
                sender_name=sender_name,
                n_parts=n_parts,
            )
            await ctx.send(embed=_split_plan_embed(size, limit, duration, n_parts), view=view)
        except FileTooLargeError as e:
            await ctx.send(embed=_too_large_embed(e))
        except DownloadError as e:
            await ctx.send(embed=error_embed(description=e.message))
        except Exception as e:
            await ctx.send(embed=error_embed(description=map_download_error(e)))
            print(f"DSPLIT error: {e}")
        finally:
            if processing_msg is not None:
                try:
                    await processing_msg.delete()
                except (discord.HTTPException, discord.Forbidden):
                    pass
            if not parked:
                _retry_rmtree(workdir)

    @commands.command(name="dclip")
    async def dclip(self, ctx: commands.Context, *, args: str = None):
        """Reply to a link to clip a timestamp range. `.dclip 1:30 2:45` = 1:30 to 2:45; add a part count to also split it, e.g. `.dclip 1:30 2:45 3`. Timestamps accept `90`, `1:30` or `1:02:03`."""
        if yt_dlp is None:
            await ctx.send(
                embed=error_embed(
                    description=(
                        "The `yt-dlp` package isn't installed, so downloads are "
                        "disabled.\n\nOn the host run:\n```\npip install -r requirements.txt\n```"
                    )
                )
            )
            return

        if _find_ffmpeg() is None:
            await ctx.send(
                embed=error_embed(
                    description=(
                        "Clipping needs ffmpeg to be installed "
                        "(`apt install ffmpeg` on Linux, or keep "
                        "`imageio-ffmpeg` installed)."
                    )
                )
            )
            return

        start, end, parts, parse_error = _parse_clip_args(args)
        if parse_error is not None:
            await ctx.send(embed=error_embed(description=parse_error))
            return

        url, replied = await _reply_url(ctx)
        if replied is None or url is None:
            await ctx.send(
                embed=error_embed(
                    description="Reply to a message containing a media link.",
                )
            )
            return

        if _is_spotify_url(url):
            try:
                url = _spotify_search_query(url)
            except DownloadError as e:
                await ctx.send(embed=error_embed(description=e.message))
                return

        limit = self._upload_limit(ctx)
        workdir = Path(tempfile.mkdtemp(prefix="village_clip_"))
        processing_msg = None
        try:
            processing_msg = await ctx.send("Downloading…")
        except (discord.HTTPException, discord.Forbidden):
            processing_msg = None
        parked = False
        try:
            loop = asyncio.get_running_loop()
            cancel_event = threading.Event()
            async with self._lock():
                try:
                    filepath, info = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            self._download_blocking,
                            url,
                            workdir,
                            10 * 1024**3,  # don't refuse on size: the clip handles it
                            cancel_event,
                            False,
                            None,
                        ),
                        timeout=DOWNLOAD_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    cancel_event.set()
                    raise DownloadError("The download timed out.")
                except DownloadError:
                    raise
                except Exception as exc:
                    raise DownloadError(map_download_error(exc)) from None

            duration = _duration_seconds(info)
            title = info.get("title") if info else None
            sender_name = replied.author.display_name if replied and getattr(replied, "author", None) else "Unknown"

            if duration and start >= duration - 0.1:
                raise DownloadError(
                    f"That starts past the end of the video, which is only "
                    f"{_format_duration(duration)} long."
                )
            if end is not None and duration and end > duration:
                end = duration
            if end is not None and end <= start:
                raise DownloadError("The end timestamp has to be after the start one.")
            length = (end - start) if end is not None else (duration - start if duration else None)
            if not length or length <= 0:
                raise DownloadError(
                    "Couldn't read the video's length, so an open-ended clip isn't possible. "
                    "Give an end timestamp, e.g. `.dclip 1:30 2:45`."
                )

            clip_path = await loop.run_in_executor(
                None, _cut_region, filepath, start, length
            )
            clip_size = clip_path.stat().st_size
            range_text = _format_range(start, end)

            if parts and parts > 1:
                per_part_limit = int(limit * 0.94)
                min_parts = max(2, (clip_size + per_part_limit - 1) // per_part_limit)
                if parts < min_parts:
                    await ctx.send(
                        embed=_clip_too_big_embed(
                            clip_size, limit, min_parts, " ".join((args or "").split())
                        )
                    )
                    return
                part_files = await loop.run_in_executor(
                    None, _split_into_parts, clip_path, parts, workdir, length
                )
                if any(p.stat().st_size > limit for p in part_files):
                    await ctx.send(
                        embed=_clip_too_big_embed(
                            clip_size, limit, min_parts, " ".join((args or "").split())
                        )
                    )
                    return

                parked = True
                view = SplitConfirmView(
                    channel=ctx.channel,
                    author_id=ctx.author.id,
                    workdir=workdir,
                    parts=part_files,
                    title=title,
                    sender_name=sender_name,
                    n_parts=parts,
                )
                await ctx.send(
                    embed=_clip_plan_embed(range_text, clip_size, limit, parts, length / parts),
                    view=view,
                )
                return

            if clip_size > limit:
                per_part_limit = int(limit * 0.94)
                min_parts = max(2, (clip_size + per_part_limit - 1) // per_part_limit)
                await ctx.send(
                    embed=_clip_too_big_embed(
                        clip_size, limit, min_parts, " ".join((args or "").split())
                    )
                )
                return

            file = discord.File(clip_path, filename=clip_path.name)
            try:
                await ctx.send(
                    content=(
                        f"**{(sender_name or 'Unknown')[:100]} -> "
                        f"{str(title or 'Downloaded media')[:1500]}** ({range_text})"
                    ),
                    file=file,
                )
            finally:
                file.close()
        except FileTooLargeError as e:
            await ctx.send(embed=_too_large_embed(e))
        except DownloadError as e:
            await ctx.send(embed=error_embed(description=e.message))
        except Exception as e:
            await ctx.send(embed=error_embed(description=map_download_error(e)))
            print(f"DCLIP error: {e}")
        finally:
            if processing_msg is not None:
                try:
                    await processing_msg.delete()
                except (discord.HTTPException, discord.Forbidden):
                    pass
            if not parked:
                _retry_rmtree(workdir)


def setup(bot):
    bot.add_cog(DownloadCog(bot))
    print("[download_cog] loaded")