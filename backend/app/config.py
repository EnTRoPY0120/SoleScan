from dataclasses import dataclass
from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "SPF_DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'sneakers.sqlite3'}"
    )
    cache_ttl_seconds: int = int(os.getenv("SPF_CACHE_TTL", "600"))
    retailer_timeout_seconds: float = float(os.getenv("SPF_RETAILER_TIMEOUT", "20"))
    overall_timeout_seconds: float = float(os.getenv("SPF_OVERALL_TIMEOUT", "45"))
    user_agent: str = "SneakerPriceFinder/0.1 (local personal price comparison)"
    frontend_build: Path = ROOT / "frontend" / "build"


settings = Settings()

