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
import tempfile
import threading
import time
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

from utils.embeds import error_embed

DEFAULT_UPLOAD_LIMIT = 25 * 1024 * 1024  # 25 MiB (DMs / unknown guild limit)
DOWNLOAD_TIMEOUT_SECONDS = 600
CONCURRENCY_LIMIT = 2

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

_PRIVATE_KEYWORDS = (
    "private",
    "private video",
    "requires login",
    "sign in",
    "log in",
    "login",
    "members",
    "member-only",
    "restricted",
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


def extract_url(text: str) -> str | None:
    """Return the first http(s) URL in ``text`` (strip trailing punctuation)."""
    match = _URL_RE.search(text or "")
    if not match:
        return None
    url = match.group(0).rstrip(".,;:!?)]}>")
    return url


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
    if isinstance(exc, GeoRestrictedError):
        return "This content is private or restricted and can't be downloaded."

    message = str(exc).lower()

    if any(k in message for k in _PRIVATE_KEYWORDS):
        return "This content is private or restricted and can't be downloaded."
    if "http error 403" in message or "http error 401" in message:
        return "This content is private or restricted and can't be downloaded."

    if "max-filesize" in message or ("larger than" in message and "file" in message):
        return "The media is too large to send on Discord."

    if "http error 4" in message or "http error 410" in message:
        return "The media is unavailable."
    if "unsupported" in message or "is not a valid url" in message:
        return "This URL isn't supported for downloading."
    if "requested format" in message or "no format matches" in message:
        return (
            "No playable single-file version is available for this link. "
            "It needs audio+video merging, which requires ffmpeg to be installed."
        )

    if any(k in message for k in _NETWORK_KEYWORDS):
        return "Network failure while downloading."
    if isinstance(exc, (YtDlDownloadError, ExtractorError)):
        return "Couldn't download this media."

    return "Couldn't download this media."


class DownloadCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._semaphore: asyncio.Semaphore | None = None

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

    @staticmethod
    def _download_blocking(
        url: str,
        workdir: Path,
        max_filesize: int,
        cancel_event: threading.Event | None = None,
        audio_only: bool = False,
    ) -> tuple[Path, dict]:
        def _check_cancel(d: dict) -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise DownloadError("Download timed out.")

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
        if audio_only:
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
        if cancel_event is not None:
            opts["progress_hooks"] = [_check_cancel]

        if url.startswith("http"):
            _head_size_guard(url, max_filesize)

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if cancel_event is not None and cancel_event.is_set():
            raise DownloadError("Download timed out.")

        size = info.get("filesize") or info.get("filesize_approx") or 0
        req = (info.get("requested_downloads") or [{}])[0]
        size = size or req.get("filesize") or req.get("filesize_approx") or 0
        if size and size > max_filesize:
            raise DownloadError("The media is too large to send on Discord.")

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        if cancel_event is not None and cancel_event.is_set():
            raise DownloadError("Download timed out.")

        files = [p for p in workdir.iterdir() if p.is_file()]
        if not files:
            raise DownloadError("Downloaded file not found.")
        return max(files, key=lambda p: p.stat().st_size), info

    async def _download_and_send(self, ctx: commands.Context, url: str, audio_only: bool = False) -> None:
        limit = self._upload_limit(ctx)
        workdir = Path(tempfile.mkdtemp(prefix="village_dl_"))
        processing_msg = await ctx.send("Downloading…")
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
                raise DownloadError("The media is too large to send on Discord.")

            filename = filepath.name
            # Passing the path means File opens (and owns) the handle: media is
            # streamed from disk, never buffered in RAM, and discord.py closes
            # it after uploading. We also close() explicitly so the temp file is
            # never left locked on Windows even if the send is only mocked.
            file = discord.File(filepath, filename=filename)
            try:
                await ctx.send(
                    content=f"**{info.get('title') or 'Downloaded media'}** "
                    f"({size / 1024 / 1024:.1f} MiB)",
                    file=file,
                )
            finally:
                file.close()
        finally:
            # Remove the "Downloading…" message whether the media arrived or
            # the download failed, so only the result (or error) stays.
            try:
                await processing_msg.delete()
            except discord.HTTPException:
                pass
            _retry_rmtree(workdir)

    @commands.command(name="dl")
    async def dl(self, ctx: commands.Context):
        """Reply to a message with a link to download the media and send it here (Spotify tracks supported). Removes the link message and command on success."""
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
        if url.startswith("https://media.discordapp.net") or url.startswith("https://cdn.discordapp.com"):
            url = url.split("?")[0]

        audio_only = False
        if _is_spotify_url(url):
            try:
                url = _spotify_search_query(url)
                audio_only = True
            except DownloadError as e:
                await ctx.send(embed=error_embed(description=e.message))
                return

        try:
            await self._download_and_send(ctx, url, audio_only=audio_only)
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
        for msg in (replied, ctx.message):
            try:
                await msg.delete()
            except discord.HTTPException:
                pass


def setup(bot):
    bot.add_cog(DownloadCog(bot))