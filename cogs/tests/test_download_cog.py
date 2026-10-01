"""Tests for Download cog."""

from pathlib import Path
from unittest.mock import patch

import pytest

from cogs import download_cog
from cogs.download_cog import (
    DownloadError,
    DownloadCog,
    extract_url,
    map_download_error,
    _is_douyin_url,
    _is_spotify_url,
    _spotify_search_query,
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
    """Douyin is not supported on this host; links are still detected so the
    refusal message is friendly instead of a raw yt-dlp error."""

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

    def test_douyin_refused_with_friendly_message(self, tmp_path):
        with pytest.raises(DownloadError) as excinfo:
            DownloadCog._download_blocking(DOUYIN_VIDEO, tmp_path, 1 << 20)
        assert "Douyin" in excinfo.value.message
        assert "host" in excinfo.value.message


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