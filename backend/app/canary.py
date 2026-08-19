import asyncio

import structlog

from .config import settings
from .schemas import SearchRequest


log = structlog.get_logger()


class CanaryMonitor:
    """Scheduled known-product check that detects retailer contract degradation."""

    def __init__(self, manager, interval_seconds: int | None = None) -> None:
        self.manager = manager
        self.interval_seconds = interval_seconds or settings.canary_interval_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if settings.canary_enabled and self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            try:
                summary = await self.run_once()
                log.info("retailer_canary_complete", **summary)
            except Exception as exc:
                log.warning("retailer_canary_failed", error=type(exc).__name__)

    async def run_once(self) -> dict:
        created = await self.manager.create(
            SearchRequest(query="GEL-KAYANO 14", brand="ASICS", uk_size="9"),
            bypass_cache=True,
        )
        deadline = asyncio.get_running_loop().time() + settings.overall_timeout_seconds + 5
        result = self.manager.get(str(created.id))
        while result.state != "complete" and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.1)
            result = self.manager.get(str(created.id))
        degraded = [
            status.retailer_id or status.retailer
            for status in result.retailers
            if status.outcome not in {"offers_found", "valid_empty"}
        ]
        return {
            "search_id": str(created.id),
            "checked": len(result.retailers) - len(degraded),
            "total": len(result.retailers),
            "degraded": degraded,
        }
