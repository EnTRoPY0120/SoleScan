import asyncio
import os
from pathlib import Path


class AssistedBrowserUnavailableError(RuntimeError):
    pass


class AssistedBrowserRuntime:
    """Readiness probe for the local Xvfb -> x11vnc -> websockify stack."""

    def __init__(self, display: str | None = None, host: str = "127.0.0.1", vnc_port: int = 5900, web_port: int = 6080):
        self.display = display or os.getenv("DISPLAY", ":99")
        self.host = host
        self.vnc_port = vnc_port
        self.web_port = web_port

    @property
    def x_socket(self) -> Path:
        number = self.display.removeprefix(":").split(".", 1)[0]
        return Path(f"/tmp/.X11-unix/X{number}")

    async def status(self) -> dict[str, bool]:
        return {
            "x_display": self.x_socket.exists(),
            "vnc": await self._port_open(self.vnc_port),
            "viewer": await self._port_open(self.web_port),
        }

    async def ensure_ready(self) -> None:
        state = await self.status()
        missing = [name for name, ready in state.items() if not ready]
        if missing:
            raise AssistedBrowserUnavailableError(
                f"Assisted browser runtime is not ready ({', '.join(missing)})"
            )

    async def _port_open(self, port: int) -> bool:
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, port), timeout=0.25,
            )
        except (OSError, TimeoutError):
            return False
        writer.close()
        await writer.wait_closed()
        return True


assisted_runtime = AssistedBrowserRuntime()
