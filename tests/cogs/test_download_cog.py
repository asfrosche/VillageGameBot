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
    _cookies_file,
    _format_range,
    _is_douyin_url,
    _is_spotify_url,
    _parse_clip_args,
    _parse_timestamp,
    _spotify_search_query,
)

DOUYIN_VIDEO = "https://www.douyin.com/video/7667116669306670363"


class TestCookiesFile:
    """config/cookies.txt is found and used as yt-dlp's cookiefile."""

    def test_returns_absolute_path_when_present(self, tmp_path):
        (tmp_path / "config").mkdir()
        cookie = tmp_path / "config" / "cookies.txt"
        cookie.write_text("# Netscape HTTP Cookie File\n")
        with patch.object(download_cog, "_BOT_ROOT", tmp_path):
            result = _cookies_file()
        assert result == str(cookie.resolve())
        assert Path(result).is_absolute()

    def test_missing_file_returns_none(self, tmp_path, monkeypatch):
        # Point every search location at an empty dir so nothing is found.
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.chdir(empty)
        with patch.object(download_cog, "_BOT_ROOT", empty), patch.object(
            download_cog.tempfile, "gettempdir", lambda: str(empty)
        ):
            assert _cookies_file() is None

    def test_empty_file_is_ignored(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        (empty / "cookies.txt").write_text("")
        monkeypatch.chdir(empty)
        with patch.object(download_cog, "_BOT_ROOT", empty), patch.object(
            download_cog.tempfile, "gettempdir", lambda: str(empty)
        ):
            assert _cookies_file() is None


class TestDownloadCog:
    """Validate the command exists and has required metadata."""

    def test_dl_exists(self):
        assert hasattr(DownloadCog, 'dl')

    def test_dl_has_help(self):
        method = getattr(DownloadCog, 'dl')
        help_text = getattr(method, 'help', None) or getattr(method, 'description', None)
        assert help_text and help_text.strip(), 'command has no help text'

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


class TestDclip:
    """`.dclip` timestamp parsing: `<start> [end] [parts]`."""

    def test_dclip_exists(self):
        assert hasattr(DownloadCog, 'dclip')

    def test_dclip_has_help(self):
        method = getattr(DownloadCog, 'dclip')
        help_text = getattr(method, 'help', None) or getattr(method, 'description', None)
        assert help_text and help_text.strip(), 'command has no help text'

    @pytest.mark.parametrize(
        "text,expected",
        [("90", 90.0), ("1:30", 90.0), ("1:02:03", 3723.0), ("0", 0.0), ("1.5", 1.5)],
    )
    def test_parse_timestamp_valid(self, text, expected):
        assert _parse_timestamp(text) == expected

    @pytest.mark.parametrize("text", ["", "abc", "-5", "1:2:3:4", None])
    def test_parse_timestamp_invalid(self, text):
        assert _parse_timestamp(text) is None

    def test_parse_clip_args_start_only(self):
        assert _parse_clip_args("1:30") == (90.0, None, None, None)

    def test_parse_clip_args_start_and_end(self):
        assert _parse_clip_args("1:30 2:45") == (90.0, 165.0, None, None)

    def test_parse_clip_args_with_parts(self):
        assert _parse_clip_args("1:30 2:45 3") == (90.0, 165.0, 3, None)

    def test_parse_clip_args_small_second_value_is_parts(self):
        assert _parse_clip_args("1:30 3") == (90.0, None, 3, None)

    def test_parse_clip_args_missing_args(self):
        assert _parse_clip_args(None)[3] is not None

    def test_parse_clip_args_bad_timestamp(self):
        assert "isn't a timestamp" in _parse_clip_args("bad")[3]

    def test_parse_clip_args_too_many_parts(self):
        assert "at most" in _parse_clip_args("90 99 12")[3].lower()

    def test_format_range_open_ended(self):
        assert _format_range(90, None) == "1:30 → end"


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