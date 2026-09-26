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
import importlib.util
import os
import re
import shutil
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

from utils.embeds import error_embed

DEFAULT_UPLOAD_LIMIT = 25 * 1024 * 1024  # 25 MiB (DMs / unknown guild limit)
DOWNLOAD_TIMEOUT_SECONDS = 600
CONCURRENCY_LIMIT = 2

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

# Douyin blocks every non-browser request to its video endpoints since the
# 2026-09-14 policy change (edge WAF "ArgusSecurity ... Uifid Not Found"),
# which is why yt-dlp's DouyinIE is broken upstream. Douyin URLs are therefore
# handled by a real-browser Playwright path (implemented in this file, below)
# that captures the SDK-signed detail response and downloads the CDN URL. yt-dlp is
# kept as fallback in case the policy relaxes, then the block is explained
# instead of leaking an opaque error. Detection is host-based so any link
# shape works.
_DOUYIN_HOSTS = {
    "douyin.com",
    "www.douyin.com",
    "m.douyin.com",
    "v.douyin.com",
    "iesdouyin.com",
    "www.iesdouyin.com",
    "v.iesdouyin.com",
}
_DOUYIN_ERROR_HINTS = (
    "uifid",
    "argus",
    "aweme",
    "douyin",
    "s_v_web_id",
    "fresh cookies",
    "verify_center",
    "secsdk",
    "style check",
    "403",
)
_DOUYIN_BLOCK_MESSAGE = (
    "Douyin now blocks automated downloads.\n\n"
    "Since September 14, 2026 Douyin's anti-bot gate (ArgusSecurity) rejects "
    "every non-browser request to video links with `403 Uifid Not Found`, so "
    "yt-dlp and similar tools can't fetch the video anymore. This affects all "
    "downloaders, not just this bot.\n\n"
    "What still works:\n"
    "- Open the link in the Douyin app or website and save it there.\n"
    "- Use a browser-based downloader (Douyin's own share/download flow or a "
    "desktop tool like Douzy), which the gate allows.\n\n"
    "`.dl` will keep trying automatically in case Douyin relaxes the block."
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

# Prefix for errors raised by the Playwright Douyin path. It lets the .dl
# command show the specific browser error instead of the generic block text.
_DOUYIN_PW_PREFIX = "**Douyin:** "

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


# ---------------------------------------------------------------------------
# Douyin real-browser path.
#
# Since 2026-09-14 Douyin's edge WAF (ArgusSecurityPlugin) rejects every
# non-browser request with ``403 Uifid Not Found``, which broke yt-dlp's
# DouyinIE and every pure-HTTP approach (a_bogus/x_bogus can't mint the
# ``uifid`` cookie the SDK signature needs). The only route that still works is
# to load the video page in a real browser:
#
# 1. Open the ``/video/{aweme_id}`` page in Chrome; the page's own JS SDK
#    signs the ``/aweme/v1/web/aweme/detail`` request.
# 2. Capture that JSON response and take the highest bit-rate, no-watermark
#    ``play_addr`` URL.
# 3. Download the (already CDN-signed) URL over plain HTTPS with a browser
#    Referer — CDN URLs don't need the SDK.
#
# If the API response is never observed (SDK change, captcha), the currently
# playing ``<video>`` element's ``currentSrc`` is used as a fallback.
#
# The sync Playwright API is used so the whole flow can run inside a worker
# thread (see DownloadCog._download_blocking). A module-level threading.Lock
# serializes access to the shared browser process, which is also what keeps the
# thread-unsafe Playwright sync API safe.
# ---------------------------------------------------------------------------

try:
    from curl_cffi import requests as _slash_requests
except Exception:
    _slash_requests = None

# uuu_265.mp4 is Douyin's always-on placeholder/preload clip, not the target
# video. Skip any currentSrc that matches it.
_PLACEHOLDER_SRC = "uuu_265.mp4"

# Playwright sync API is thread-unsafe; one download at a time.
_BROWSER_LOCK = threading.Lock()
_BROWSER = None
_PLA = None

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_AWEME_ID_RES = (
    re.compile(r"/video/(?P<id>\d{18,20})"),
    re.compile(r"/note/(?P<id>\d{18,20})"),
    re.compile(r"modal_id=(?P<id>\d{18,20})"),
    re.compile(r"/(?P<id>\d{18,20})(?:[?/]|$)"),
)

_SHORT_LINK_HOSTS = {
    "v.douyin.com",
    "v.iesdouyin.com",
    "iesdouyin.com",
}

# Playwright names for installed real browsers.
_CHANNEL_PATHS = (
    ("C:/Program Files/Google/Chrome/Application/chrome.exe", "chrome"),
    ("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe", "chrome"),
    ("C:/Program Files/Google/Chrome/Application/msedge.exe", "msedge"),
    ("C:/Program Files (x86)/Google/Chrome/Application/msedge.exe", "msedge"),
    ("C:/Program Files/Microsoft/Edge/Application/msedge.exe", "msedge"),
    ("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "msedge"),
    ("/usr/bin/google-chrome", "chrome"),
    ("/usr/bin/google-chrome-stable", "chrome"),
    ("/usr/bin/chromium", "chromium"),
    ("/usr/bin/chromium-browser", "chromium"),
    ("/snap/bin/chromium", "chromium"),
)

# Rootless/container hosts can't raise the Chromium seccomp sandbox; without
# this flag the browser refuses to start there.
_LINUX_EXTRA_ARGS = ("--no-sandbox", "--disable-dev-shm-usage")


class DouyinDownloadError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _safe_name(title: str, maxlen: int = 80) -> str:
    """Restricted, ASCII-only filename so unicode titles can't break Windows."""
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", title or "Douyin video")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    return cleaned[:maxlen] or "Douyin_video"


def extract_aweme_id(url: str) -> str | None:
    """Extract the Douyin aweme id from any link shape (short links resolved)."""
    if not url:
        return None
    url = url.split("#")[0].split("?")[0] if "modal_id" not in url else url
    for pattern in _AWEME_ID_RES:
        match = pattern.search(url)
        if match:
            return match.group("id")

    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host in _SHORT_LINK_HOSTS:
        resolved = _resolve_short_link(url)
        if resolved and resolved != url:
            for pattern in _AWEME_ID_RES:
                match = pattern.search(resolved)
                if match:
                    return match.group("id")
    return None


def _resolve_short_link(url: str, timeout: int = 20) -> str | None:
    """Follow Douyin share short-link redirects to the canonical page URL."""
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.geturl()
    except Exception:
        return None


def _detect_channel() -> str | None:
    """Return a Playwright channel name for an installed real browser, else None."""
    for path, name in _CHANNEL_PATHS:
        if os.path.isfile(path):
            return name
    exe = shutil.which("google-chrome") or shutil.which("chromium-browser") or shutil.which("microsoft-edge")
    if exe:
        name = os.path.basename(exe).lower()
        for key, channel in (("chrome", "chrome"), ("chromium", "chromium"), ("edge", "msedge")):
            if key in name:
                return channel
    return None


def is_ready() -> bool:
    """Return whether a browser backend is available for Douyin downloads."""
    if not importlib.util.find_spec("playwright"):
        return False
    if _detect_channel() is None:
        # Bundled Chromium (installed via `python -m playwright install chromium`)
        # is the fallback for hosts without a system browser.
        browsers_dir = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        if not browsers_dir:
            if sys.platform == "win32":
                local = os.environ.get("LOCALAPPDATA")
                browsers_dir = os.path.join(local, "ms-playwright") if local else None
            else:
                browsers_dir = (
                    str(Path.home() / ".cache" / "ms-playwright")
                    if Path.home()
                    else None
                )
        if not browsers_dir or not os.path.isdir(browsers_dir):
            return False
        if not any("chromium" in name for name in os.listdir(browsers_dir)):
            return False
        return True
    return True


def _resolve_headless() -> bool:
    """Headless mode. Defaults to headed (a real window) because Douyin's WAF
    is harsher on automated contexts; set DOUYIN_HEADED=0 to force headless."""
    return os.environ.get("DOUYIN_HEADED", "1") != "1"


def _get_browser(playwright):
    """Launch (once) and return the shared browser instance."""
    global _BROWSER
    if _BROWSER is not None:
        return _BROWSER
    channel = _detect_channel()
    extra_args = list(_LINUX_EXTRA_ARGS) if sys.platform != "win32" else []
    launch_kwargs = {
        "headless": _resolve_headless(),
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--lang=zh-CN",
            "--mute-audio",
            *extra_args,
        ],
    }
    if channel:
        launch_kwargs["channel"] = channel
    try:
        _BROWSER = playwright.chromium.launch(**launch_kwargs)
    except Exception as exc:
        raise DouyinDownloadError(
            "Couldn't start a browser for Douyin. "
            "Install Google Chrome/Edge or run `python -m playwright install chromium`."
        ) from exc
    return _BROWSER


def _is_http_url(u: str | None) -> bool:
    return bool(u and (u.startswith("http://") or u.startswith("https://")))


def _pick_video_url(detail: dict, current_src: str | None) -> str | None:
    """Choose the best no-watermark URL from the detail JSON, else currentSrc.

    Some ``play_addr`` entries are ``blob:`` in-memory stream URLs that can't be
    fetched outside the browser, so only real http(s) URLs are considered.
    """
    if detail:
        ad = detail.get("aweme_detail") or {}
        video = ad.get("video") or {}
        bit_rates = video.get("bit_rate") or []
        urls: list[tuple[int, str]] = []
        for b in bit_rates:
            pa = (b.get("play_addr") or {}).get("url_list") or []
            for u in pa:
                if _is_http_url(u):
                    urls.append((b.get("bit_rate") or 0, u))
        urls.sort(reverse=True)
        for _br, u in urls:
            return u
        pa = (video.get("play_addr") or {}).get("url_list") or []
        for u in pa:
            if _is_http_url(u):
                return u
    if current_src:
        wide_url = current_src.replace("\\/", "/")
        if _is_http_url(wide_url) and _PLACEHOLDER_SRC not in wide_url:
            return wide_url
    return None


def _stream_download(url: str, dest: Path, max_filesize: int, cancel_event) -> None:
    """Download a CDN URL to ``dest``, enforcing the size limit and mp4 sanity."""
    headers = {
        "User-Agent": _UA,
        "Referer": "https://www.douyin.com/",
        "Accept": "*/*",
    }
    if _slash_requests is not None:
        resp = _slash_requests.get(url, impersonate="chrome", headers=headers, timeout=60, stream=True)
        status = resp.status_code
        length = resp.headers.get("content-length")
        if status != 200:
            raise DouyinDownloadError(f"Douyin CDN returned HTTP {status} while downloading.")
        if length and int(length) > max_filesize:
            raise DouyinDownloadError("The media is too large to send on Discord.")
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(65536):
                if cancel_event is not None and cancel_event.is_set():
                    raise DouyinDownloadError("Download timed out.")
                if chunk:
                    fh.write(chunk)
        _check_mp4(dest)
        return

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as fh:
        length = resp.headers.get("Content-Length")
        if length and int(length) > max_filesize:
            raise DouyinDownloadError("The media is too large to send on Discord.")
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            if cancel_event is not None and cancel_event.is_set():
                raise DouyinDownloadError("Download timed out.")
            fh.write(chunk)
    _check_mp4(dest)


def _check_mp4(path: Path) -> None:
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
        if head and head[4:8] != b"ftyp":
            raise DouyinDownloadError("Douyin returned a non-video response.")
    except OSError as exc:
        raise DouyinDownloadError("Couldn't write the Douyin download.") from exc


def _ensure_playwright():
    """Start the shared Playwright driver once (thread-safe under _BROWSER_LOCK)."""
    global _PLA
    if _PLA is None:
        from playwright.sync_api import sync_playwright

        _PLA = sync_playwright().start()
    return _PLA


def download_douyin_video(
    url: str,
    workdir: Path,
    max_filesize: int,
    cancel_event=None,
) -> tuple[Path, dict]:
    """Download a Douyin video through a real browser.

    Returns ``(path, info)`` where ``info`` has ``title``/``author``/``duration``.
    Raises :class:`DouyinDownloadError` with a user-facing message on failure.
    """
    if not importlib.util.find_spec("playwright"):
        raise DouyinDownloadError(
            "Douyin needs a real browser (Playwright) to download. "
            "Install it on the host with `pip install playwright && python -m playwright install chromium`."
        )

    workdir = Path(workdir)
    aweme_id = extract_aweme_id(url)
    if not aweme_id:
        raise DouyinDownloadError("Couldn't find the video id in that Douyin link.")

    video_url: str | None = None
    detail: dict | None = None
    with _BROWSER_LOCK:
        pw = _ensure_playwright()
        browser = _get_browser(pw)
        context = browser.new_context(
            user_agent=_UA,
            viewport={"width": 1680, "height": 1050},
            locale="zh-CN",
        )
        page = context.new_page()

        def _on_response(resp) -> None:
            nonlocal detail
            if detail is None and "aweme/v1/web/aweme/detail" in resp.url and resp.status == 200:
                import json

                try:
                    detail = json.loads(resp.text())
                except Exception:
                    return

        page.on("response", _on_response)
        try:
            try:
                page.goto(
                    f"https://www.douyin.com/video/{aweme_id}",
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
            except Exception:
                pass

            current_src: str | None = None
            start = time.time()
            src_seen_at: float | None = None
            while time.time() - start < 30:
                if cancel_event is not None and cancel_event.is_set():
                    raise DouyinDownloadError("Download timed out.")
                if detail is not None:
                    break
                page.wait_for_timeout(1000)
                # A small nudge over the player triggers Douyin's hover-play.
                page.mouse.move(840, 525)
                try:
                    cs = page.evaluate(
                        "() => { const v = document.querySelector('video'); return v ? (v.currentSrc || v.src) || null : null; }"
                    )
                except Exception:
                    cs = None
                if cs and _PLACEHOLDER_SRC not in cs:
                    current_src = cs
                    if src_seen_at is None:
                        src_seen_at = time.time()
                # currentSrc is good enough; give the SDK a few more seconds
                # to answer with the no-watermark detail first.
                if src_seen_at is not None and time.time() - src_seen_at > 12:
                    break

            video_url = _pick_video_url(detail, current_src)
            if not video_url:
                raise DouyinDownloadError(_verify_or_timeout_message(page))
        finally:
            try:
                context.close()
            except Exception:
                pass

    raw_title = (detail or {}).get("aweme_detail", {}).get("desc") or ""
    author = (detail or {}).get("aweme_detail", {}).get("author", {}).get("nickname", "")
    duration = (detail or {}).get("aweme_detail", {}).get("duration", 0)

    # ASCII-only filenames (Windows cp1252 hosts). When the title is mostly
    # non-ASCII it would collapse to near-empty, so fall back to the id.
    if len(re.sub(r"[^A-Za-z0-9]", "", raw_title)) < 3:
        name = f"Douyin_{aweme_id}"
    else:
        name = _safe_name(raw_title)
    dest = workdir / f"{name}.mp4"
    _stream_download(video_url, dest, max_filesize, cancel_event)

    info = {"title": raw_title[:80] or name, "author": author, "duration": duration}
    return dest, info


def _verify_or_timeout_message(page) -> str:
    """Distinguish 'show us a check' from a plain timeout."""
    try:
        text = page.content()[:4096]
        low = text.lower()
        if any(marker in low for marker in ("verify_center", "secsdk", "captcha", "验证")):
            if _resolve_headless():
                return (
                    "Douyin asked for a visual check. The browser has no visible "
                    "window here (host is headless), so it can't be solved from "
                    "Discord — retry later, or try again from the desktop machine "
                    "where the browser window is visible."
                )
            return (
                "Douyin asked for a visual check. This is shown in the browser "
                "window the bot opened; solve it once and retry the command."
            )
    except Exception:
        pass
    return (
        "Douyin didn't answer within a reasonable time (the video page needs to "
        "load and autoplay in the browser window). Please retry in a moment."
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


def _is_douyin_url(url: str) -> bool:
    """Return whether ``url`` belongs to Douyin (any host or link shape)."""
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in _DOUYIN_HOSTS


def _douyin_failure_message(error_message: str) -> str | None:
    """Map a Douyin download failure to the block explanation, else None."""
    low = (error_message or "").lower()
    if any(hint in low for hint in _DOUYIN_ERROR_HINTS):
        return _DOUYIN_BLOCK_MESSAGE
    return None


def _douyin_user_message(error_message: str, is_douyin: bool) -> str:
    """Pick the message to show for a failed download.

    Douyin errors from the Playwright path carry _DOUYIN_PW_PREFIX and are
    specific enough to show directly; errors from the yt-dlp fallback map to
    the generic block explanation.
    """
    if not is_douyin:
        return error_message
    if error_message.startswith(_DOUYIN_PW_PREFIX):
        return error_message[len(_DOUYIN_PW_PREFIX):]
    return _douyin_failure_message(error_message) or error_message


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
        return (
            "Download was temporarily blocked by the platform (anti-bot check "
            "or rate limit). Please try again in a few minutes."
        )

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

        # Douyin blocks every non-browser request (Argus WAF, "Uifid Not
        # Found"), so it gets the real-browser Playwright path first. yt-dlp
        # remains as fallback for other sites and in case the policy relaxes.
        if _is_douyin_url(url) and is_ready():
            try:
                return download_douyin_video(
                    url, workdir, max_filesize=max_filesize, cancel_event=cancel_event
                )
            except DouyinDownloadError as exc:
                raise DownloadError(_DOUYIN_PW_PREFIX + exc.message) from None

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

    async def _download_and_send(self, ctx: commands.Context, url: str, audio_only: bool = False, sender_name: str | None = None) -> None:
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
                    content=f"**{sender_name or 'Unknown'} -> {info.get('title') or 'Downloaded media'}**",
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

        douyin_url = _is_douyin_url(url)
        try:
            await self._download_and_send(
                ctx, url, audio_only=audio_only, sender_name=replied.author.display_name
            )
        except DownloadError as e:
            await ctx.send(embed=error_embed(description=_douyin_user_message(e.message, douyin_url)))
            return
        except Exception as e:
            message = _douyin_user_message(map_download_error(e), douyin_url)
            await ctx.send(embed=error_embed(description=message))
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
                await msg.delete()
            except discord.HTTPException:
                pass


def setup(bot):
    bot.add_cog(DownloadCog(bot))