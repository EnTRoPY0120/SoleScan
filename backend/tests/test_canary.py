from types import SimpleNamespace
from uuid import uuid4

from app.canary import CanaryMonitor


class FakeManager:
    def __init__(self):
        self.result = SimpleNamespace(
            id=uuid4(), state="complete",
            retailers=[
                SimpleNamespace(retailer_id="asics", retailer="ASICS India", outcome="offers_found"),
                SimpleNamespace(retailer_id="myntra", retailer="Myntra", outcome="transport_failure"),
            ],
        )

    async def create(self, request, *, bypass_cache=False):
        assert request.query == "GEL-KAYANO 14" and request.uk_size == "9"
        assert bypass_cache is True
        return self.result

    def get(self, _search_id):
        return self.result


async def test_canary_reports_precise_degraded_retailers():
    summary = await CanaryMonitor(FakeManager()).run_once()
    assert summary["checked"] == 1 and summary["total"] == 2
    assert summary["degraded"] == ["myntra"]
