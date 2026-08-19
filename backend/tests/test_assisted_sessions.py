import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.adapters.browser import AssistedBrowserSessions
from app.assisted_runtime import AssistedBrowserRuntime, AssistedBrowserUnavailableError


class FakeRuntime:
    def __init__(self, ready=True):
        self.ready = ready
        self.calls = 0

    async def ensure_ready(self):
        self.calls += 1
        if not self.ready:
            raise AssistedBrowserUnavailableError("not ready")


class FakePage:
    def __init__(self):
        self.url = None

    async def goto(self, url, **_kwargs):
        self.url = url

    def locator(self, _selector):
        return SimpleNamespace(inner_text=self.inner_text)

    async def inner_text(self):
        return "ordinary retailer page"


class FakeContext:
    def __init__(self):
        self.page = FakePage()

    async def new_page(self):
        return self.page

    async def storage_state(self, path):
        Path(path).write_text('{"cookies": []}')


class FakePool:
    def __init__(self):
        self.contexts = []
        self.released = []

    async def assisted_context(self, _storage_state=None):
        context = FakeContext()
        self.contexts.append(context)
        return context

    async def release(self, context):
        self.released.append(context)


async def test_assisted_session_requires_runtime_readiness(tmp_path):
    pool = FakePool()
    sessions = AssistedBrowserSessions(pool=pool, directory=tmp_path, runtime=FakeRuntime(ready=False))
    with pytest.raises(AssistedBrowserUnavailableError):
        await sessions.start("reebok", "search-1", "https://reebok.example/search")
    assert pool.contexts == []


async def test_assisted_session_start_complete_and_idle_expiry(tmp_path):
    pool = FakePool()
    sessions = AssistedBrowserSessions(pool=pool, directory=tmp_path, runtime=FakeRuntime())
    sessions.idle_seconds = 0.01
    started = await sessions.start("reebok", "search-1", "https://reebok.example/search")
    assert started["session_state"] == "active"
    assert sessions.state_for("reebok") == "active"
    await asyncio.sleep(0.03)
    assert sessions._active is None
    assert pool.released == pool.contexts

    await sessions.start("reebok", "search-2", "https://reebok.example/search")
    sessions.idle_seconds = 10
    completed = await sessions.complete("reebok", "search-2", challenge_cleared=True)
    assert completed["session_state"] == "active"
    assert (tmp_path / "reebok.json").stat().st_mode & 0o777 == 0o600


async def test_assisted_runtime_reports_missing_components(tmp_path):
    runtime = AssistedBrowserRuntime(display=":9876", vnc_port=59876, web_port=60876)
    with pytest.raises(AssistedBrowserUnavailableError, match="x_display, vnc, viewer"):
        await runtime.ensure_ready()


def test_stale_display_lock_cleanup_entrypoint(tmp_path):
    import subprocess

    display_number = "9876"
    lock = Path(f"/tmp/.X{display_number}-lock")
    socket = Path(f"/tmp/.X11-unix/X{display_number}")
    lock.write_text("99999999")
    script = Path(__file__).parents[2] / "docker" / "run-app.sh"
    subprocess.run(
        ["bash", str(script), "--clear-stale-display"], check=True,
        env={"PATH": "/usr/bin:/bin", "SPF_DISPLAY_NUMBER": display_number},
    )
    assert not lock.exists() and not socket.exists()
