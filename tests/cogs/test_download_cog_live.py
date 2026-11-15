"""Live integration tests for the Download cog.

These hit the network and are skipped unless LIVE_DL=1 is set:

    LIVE_DL=1 python -m pytest cogs/tests/test_download_cog_live.py -q
"""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from cogs.download_cog import DownloadCog, DownloadError, extract_url

pytestmark = pytest.mark.skipif(
    os.getenv("LIVE_DL") != "1",
    reason="set LIVE_DL=1 to run network-dependent tests",
)

DIRECT_URL = "https://www.w3schools.com/html/mov_bbb.mp4"  # ~788 KB direct mp4


@pytest.fixture
def cog():
    return DownloadCog(MagicMock())


def make_ctx(guild_limit: int = 25 * 1024 * 1024, replied_content: str | None = None):
    guild = MagicMock()
    guild.filesize_limit = guild_limit

    replied = MagicMock(spec=discord.Message)
    replied.content = replied_content or DIRECT_URL
    replied.attachments = []

    channel = MagicMock()
    channel.fetch_message = AsyncMock(return_value=replied)

    ctx = MagicMock()
    ctx.guild = guild
    ctx.channel = channel
    ctx.message.reference.message_id = 123
    ctx.send = AsyncMock()
    return ctx


class TestLiveDownloadBlocking:
    def test_downloads_small_direct_file(self, cog):
        d = Path(tempfile.mkdtemp(prefix="village_dl_"))
        try:
            f, info = cog._download_blocking(DIRECT_URL, d, 200 * 1024 * 1024, None)
            assert f.exists() and f.stat().st_size > 0
            assert f.suffix == ".mp4"
            assert info.get("title")
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_size_abort_aborts_download(self, cog):
        d = Path(tempfile.mkdtemp(prefix="village_dl_"))
        try:
            with pytest.raises(DownloadError) as ei:
                cog._download_blocking(DIRECT_URL, d, 100 * 1024, None)
            assert "too large" in ei.value.message
            assert [p for p in d.iterdir() if p.is_file()] == []
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_cancel_event_aborts(self, cog):
        import shutil
        import threading
        d = Path(tempfile.mkdtemp(prefix="village_dl_"))
        try:
            ev = threading.Event()
            ev.set()
            with pytest.raises(Exception) as ei:
                cog._download_blocking(DIRECT_URL, d, 200 * 1024 * 1024, ev)
            assert "timed out" in str(ei.value).lower()
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestLiveDownloadAndSend:
    def test_sends_file_and_cleans_tmpdir(self, cog):
        ctx = make_ctx(replied_content=DIRECT_URL)
        before = set(p.name for p in Path(tempfile.gettempdir()).glob("village_dl_*"))
        asyncio.run(cog._download_and_send(ctx, DIRECT_URL))
        after = set(p.name for p in Path(tempfile.gettempdir()).glob("village_dl_*"))
        assert after == before  # temp dir is gone
        sent = [c for c in ctx.send.await_args_list]
        assert len(sent) == 2  # "Downloading…" + media
        file_arg = sent[-1].kwargs.get("file")
        assert file_arg is not None
        assert file_arg.filename.endswith(".mp4")

    def test_too_large_after_download_is_refused_and_cleaned(self, cog):
        ctx = make_ctx(guild_limit=1)  # 1 byte limit
        with pytest.raises(DownloadError) as ei:
            asyncio.run(cog._download_and_send(ctx, DIRECT_URL))
        assert "too large" in ei.value.message


class TestLiveCommand:
    def test_no_reply_shows_error(self, cog):
        ctx = MagicMock()
        ctx.message.reference = MagicMock()
        ctx.message.reference.message_id = None
        ctx.send = AsyncMock()
        asyncio.run(cog.dl.callback(cog, ctx))
        sent = ctx.send.call_args.kwargs.get("embed")
        assert "Reply to a message containing a media link" in sent.description

    def test_reply_without_link_shows_error(self, cog):
        ctx = make_ctx(replied_content="just some text, no link")
        asyncio.run(cog.dl.callback(cog, ctx))
        sent = ctx.send.call_args.kwargs.get("embed")
        assert "Reply to a message containing a media link" in sent.description

    def test_reply_with_link_sends_media(self, cog):
        ctx = make_ctx(replied_content=f"check this out {DIRECT_URL}")
        asyncio.run(cog.dl.callback(cog, ctx))
        assert ctx.send.await_count == 2  # "Downloading…" + media
        # The "Downloading…" message gets deleted afterwards.
        processing = ctx.send.await_args_list[0]
        assert processing.args and processing.args[0] == "Downloading…"