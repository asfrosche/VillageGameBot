"""Tests for Download cog."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cogs import download_cog
from cogs.download_cog import (
    DownloadError,
    DownloadCog,
    extract_url,
    map_download_error,
    _is_douyin_url,
    _douyin_failure_message,
    _douyin_user_message,
    _is_spotify_url,
    _spotify_search_query,
)
from cogs.download_cog import (
    DouyinDownloadError,
    extract_aweme_id,
    is_ready,
    download_douyin_video,
    _pick_video_url,
)

DOUYIN_VIDEO = "https://www.douyin.com/video/7667116669306670363"


class TestDownloadCog:
    """Validate the command exists and has required metadata."""

    def test_dl_exists(self):
        assert hasattr(DownloadCog, 'dl')

    def test_dl_has_help(self):
        method = getattr(DownloadCog, 'dl')
        doc = getattr(method, 'help', None) or getattr(method, '__doc__', None)
        assert doc is not None and len(doc.strip()) > 0

    def test_extract_url_simple(self):
        assert extract_url("watch https://www.youtube.com/watch?v=jNQXAC9IVRw now") == (
            "https://www.youtube.com/watch?v=jNQXAC9IVRw"
        )

    def test_extract_url_no_trailing_punct(self):
        assert extract_url("See (https://media.w3.org/2010/05/sintel/trailer.mp4).") == (
            "https://media.w3.org/2010/05/sintel/trailer.mp4"
        )

    def test_extract_url_none(self):
        assert extract_url("no link here") is None


class TestDouyinSupport:
    """Douyin sees every non-browser request blocked; surface it clearly."""

    def test_douyin_url_detected(self):
        assert _is_douyin_url("https://v.douyin.com/O_Yovvp6qKg/")
        assert _is_douyin_url("https://www.douyin.com/video/7688145246340812095")
        assert _is_douyin_url(
            "https://www.iesdouyin.com/share/video/7688145246340812095?region=CN"
        )
        assert _is_douyin_url("https://m.douyin.com/share/video/7688145246340812095")

    def test_douyin_url_not_detected(self):
        assert not _is_douyin_url("https://www.youtube.com/watch?v=jNQXAC9IVRw")
        assert not _is_douyin_url("https://v.tiktok.com/abc")
        assert not _is_douyin_url("https://example.com/douyin/not-real")

    def test_douyin_block_error_detected(self):
        msg = _douyin_failure_message(
            "Blocked by ArgusSecurityPlugin Uifid Not Found"
        )
        assert msg is not None and "douyin".lower() in msg.lower()
        assert (
            _douyin_failure_message(
                "Fresh cookies (not necessarily logged in) are needed. "
                "Please visit https://www.douyin.com and retry with your cookies file"
            )
            is not None
        )

    def test_douyin_block_not_mistaken_for_other_failures(self):
        assert _douyin_failure_message("The media is too large to send on Discord.") is None
        assert _douyin_failure_message("Network failure while downloading.") is None

    def test_playwright_error_keeps_specific_message(self):
        msg = _douyin_user_message(download_cog._DOUYIN_PW_PREFIX + "Douyin asked for a visual check.", True)
        assert "visual check" in msg
        assert not msg.startswith(download_cog._DOUYIN_PW_PREFIX)

    def test_ytdl_error_maps_to_block_message(self):
        msg = _douyin_user_message("Blocked by ArgusSecurityPlugin Uifid Not Found", True)
        assert msg == download_cog._DOUYIN_BLOCK_MESSAGE

    def test_non_douyin_error_unchanged(self):
        assert _douyin_user_message("The media is too large to send on Discord.", False) == (
            "The media is too large to send on Discord."
        )


class TestDouyinIdExtraction:
    def test_video_path(self):
        assert extract_aweme_id(
            "https://www.douyin.com/video/7667116669306670363?modeFrom=userCollection"
        ) == "7667116669306670363"

    def test_modal_id(self):
        assert extract_aweme_id(
            "https://www.douyin.com/jingxuan?modal_id=7667116669306670363&secUid=MS4wLjABAAAA"
        ) == "7667116669306670363"

    def test_note_path(self):
        assert extract_aweme_id(
            "https://www.douyin.com/note/7667116669306670363"
        ) == "7667116669306670363"

    def test_no_id(self):
        assert extract_aweme_id("https://www.douyin.com/user/xyz") is None

    def test_short_link_resolved(self):
        class _Resp:
            def geturl(self):
                return DOUYIN_VIDEO

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def read(self):
                return b""

        with patch.object(
            download_cog.urllib.request, "urlopen", return_value=_Resp()
        ):
            assert extract_aweme_id(
                "https://v.douyin.com/O_Yovvp6qKg/"
            ) == "7667116669306670363"


class TestDouyinPlaywrightPath:
    """Douyin URLs go through the real-browser path, not yt-dlp."""

    def _workdir(self, tmp_path):
        d = Path(tmp_path) / "out"
        d.mkdir()
        return d

    def test_douyin_uses_browser_downloader(self, tmp_path):
        fake = self._workdir(tmp_path) / "clip.mp4"
        fake.write_bytes(b"\x00" * 8)
        info = {"title": "Hello", "author": "A", "duration": 0}
        with patch.object(download_cog, "is_ready", return_value=True), patch.object(
            download_cog, "download_douyin_video", return_value=(fake, info)
        ) as m:
            path, got = DownloadCog._download_blocking(
                DOUYIN_VIDEO, tmp_path, 1 << 20
            )
        assert path == fake
        assert got == info
        m.assert_called_once()

    def test_douyin_browser_error_raises_prefixed(self, tmp_path):
        with patch.object(download_cog, "is_ready", return_value=True), patch.object(
            download_cog,
            "download_douyin_video",
            side_effect=DouyinDownloadError("Douyin asked for a visual check."),
        ):
            with pytest.raises(DownloadError) as excinfo:
                DownloadCog._download_blocking(DOUYIN_VIDEO, tmp_path, 1 << 20)
        assert excinfo.value.message.startswith(download_cog._DOUYIN_PW_PREFIX)

    def test_douyin_not_ready_falls_through_to_ytdl(self, tmp_path):
        class _FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return None

            def extract_info(self, url, download=False):
                raise RuntimeError("yt-dlp reached")

        calls = []
        with patch.object(download_cog, "is_ready", return_value=False), patch.object(
            download_cog,
            "yt_dlp",
            SimpleNamespace(YoutubeDL=_FakeYDL),
        ), patch.object(
            download_cog, "_head_size_guard", lambda url, limit: calls.append(url)
        ):
            with pytest.raises(RuntimeError):
                DownloadCog._download_blocking(DOUYIN_VIDEO, tmp_path, 1 << 20)
        assert calls, "head-size guard should be reached via yt-dlp fallback"


class TestPickVideoUrl:
    """Playlist priority: best HTTP bit_rate, then play_addr, then currentSrc."""

    def _detail(self, bit_rates, play_addr=None):
        return {
            "aweme_detail": {
                "video": {
                    "bit_rate": bit_rates,
                    "play_addr": {"url_list": play_addr or []},
                }
            }
        }

    def test_picks_highest_http_bit_rate(self):
        detail = self._detail(
            [
                {"bit_rate": 1000, "play_addr": {"url_list": ["https://cdn/x/1000.mp4?a=1"]}},
                {"bit_rate": 2000, "play_addr": {"url_list": ["https://cdn/x/2000.mp4?a=1"]}},
            ]
        )
        assert _pick_video_url(detail, None) == (
            "https://cdn/x/2000.mp4?a=1"
        )

    def test_skips_blob_urls(self):
        detail = self._detail(
            [
                {
                    "bit_rate": 2000,
                    "play_addr": {"url_list": ["blob:https://douyin.com/stream-2000"]},
                },
                {
                    "bit_rate": 900,
                    "play_addr": {"url_list": ["https://cdn/x/900.mp4?t=1"]},
                },
            ]
        )
        assert _pick_video_url(detail, None) == (
            "https://cdn/x/900.mp4?t=1"
        )

    def test_drops_all_blob_bit_rates_then_uses_play_addr(self):
        detail = self._detail(
            [{"bit_rate": 2000, "play_addr": {"url_list": ["blob:https://douyin.com/s"]}}],
            play_addr=["https://cdn/x/play.mp4?t=1"],
        )
        assert _pick_video_url(detail, None) == (
            "https://cdn/x/play.mp4?t=1"
        )

    def test_no_detail_falls_back_to_current_src(self):
        current = "https://v3-dy-o.zjcdn.com/aweme/720p.mp4?a=6383"
        assert _pick_video_url(None, current) == current

    def test_current_src_blob_or_placeholder_rejected(self):
        assert _pick_video_url(None, "blob:https://douyin.com/s") is None
        assert _pick_video_url(None, "http://x/uuu_265.mp4?a=1") is None


class TestSpotifySupport:
    """Spotify links are DRM-blocked by yt-dlp, so we resolve them via YouTube."""

    def test_spotify_detected(self):
        assert _is_spotify_url("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT")
        assert _is_spotify_url(
            "https://open.spotify.com/intl-de/track/4cOdK2wGLETKBW3PvgPWqT"
        )
        assert _is_spotify_url("https://open.spotify.com/album/1kPdW0C2iNhOGAWIlxmCJQ")
        assert _is_spotify_url("spotify:track:4cOdK2wGLETKBW3PvgPWqT")

    def test_non_spotify(self):
        assert not _is_spotify_url("https://www.youtube.com/watch?v=jNQXAC9IVRw")
        assert not _is_spotify_url("https://example.com/track/123")

    def test_query_built_from_og_tags(self):
        html = (
            "<html><head>"
            '<meta property="og:title" content="Despacito"/>'
            '<meta property="og:description" content="Luis Fonsi · Vida · Song · 2017"/>'
            "</head></html>".encode("utf-8")
        )
        _Readable = type(
            "Readable",
            (),
            {
                "read": lambda self: html,
                "__enter__": lambda self: self,
                "__exit__": lambda self, *a: None,
            },
        )
        with patch.object(
            download_cog.urllib.request, "urlopen", return_value=_Readable()
        ):
            query = _spotify_search_query(
                "https://open.spotify.com/track/6kJqabGU7LO0rBoa6g7YWH"
            )
        assert query == "ytsearch1:Despacito Luis Fonsi"

    def test_non_track_rejected(self):
        try:
            _spotify_search_query("https://open.spotify.com/album/1kPdW0C2iNhOGAWIlxmCJQ")
        except DownloadError as e:
            assert "track" in e.message
        else:
            raise AssertionError("expected DownloadError for album link")

    def test_fetch_failure_rejected(self):
        import urllib.request

        def _boom(*args, **kwargs):
            raise OSError("no network")

        with patch.object(urllib.request, "urlopen", side_effect=_boom):
            try:
                _spotify_search_query(
                    "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
                )
            except DownloadError as e:
                assert "Spotify" in e.message
            else:
                raise AssertionError("expected DownloadError on fetch failure")


class TestErrorMapping:
    """Ensure common yt-dlp failures map to user-safe messages."""

    def test_unsupported(self):
        from yt_dlp.utils import UnsupportedError
        msg = map_download_error(UnsupportedError("is not a valid URL"))
        assert "supported" in msg

    def test_too_large(self):
        msg = map_download_error(DownloadError("The file is larger than max-filesize"))
        assert "too large" in msg

    def test_restricted(self):
        msg = map_download_error(TypeError("This video is private"))
        assert "restricted" in msg

    def test_http_403_not_reported_as_private(self):
        msg = map_download_error(DownloadError("ERROR: Unable to download webpage: HTTP Error 403: Forbidden"))
        assert "private" not in msg
        assert "blocked" in msg and "again" in msg

    def test_http_401_not_reported_as_private(self):
        msg = map_download_error(DownloadError("HTTP Error 401: Unauthorized"))
        assert "private" not in msg

    def test_generic_does_not_leak(self):
        msg = map_download_error(RuntimeError("SECRET_URL https://weird.example/xyz"))
        assert "weird.example" not in msg
        assert len(msg) > 0