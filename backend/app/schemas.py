from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class Department(str, Enum):
    any = "any"
    men = "men"
    women = "women"
    kids = "kids"


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=120)
    uk_size: str = Field(min_length=1, max_length=12)
    brand: str | None = Field(default=None, max_length=60)
    colourway: str | None = Field(default=None, max_length=100)
    department: Department = Department.any
    pin_code: str | None = Field(default=None, pattern=r"^[1-9][0-9]{5}$")

    @field_validator("query", "brand", "colourway", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class ConditionalOffer(BaseModel):
    kind: Literal["coupon", "bank", "membership", "other"] = "other"
    description: str
    amount_paise: int | None = Field(default=None, ge=0)


class Offer(BaseModel):
    retailer: str
    seller: str | None = None
    confidence: Literal["exact", "strong", "possible", "weak"] = "possible"
    product_name: str
    brand: str | None = None
    model: str | None = None
    colourway: str | None = None
    image_url: str | None = None
    style_code: str | None = None
    requested_uk_size: str
    size_available: bool
    stock_status: Literal["in_stock", "out_of_stock", "unknown"] | None = None
    listed_price_paise: int = Field(ge=0)
    automatic_discount_paise: int = Field(default=0, ge=0)
    shipping_paise: int | None = Field(default=None, ge=0)
    effective_price_paise: int = Field(ge=0)
    conditional_offers: list[ConditionalOffer] = Field(default_factory=list)
    product_url: str
    return_policy: str | None = None
    match_score: float = Field(ge=0, le=1)
    last_checked: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def normalize_stock_status(self) -> "Offer":
        # Old cache rows only contain size_available. Treat those values as the
        # explicit stock claim made by the old collector, then keep the legacy
        # boolean strictly aligned with confirmed in-stock data.
        if self.stock_status is None:
            self.stock_status = "in_stock" if self.size_available else "out_of_stock"
        self.size_available = self.stock_status == "in_stock"
        return self


class RetailerStatus(BaseModel):
    retailer: str
    state: Literal["pending", "running", "complete", "partial", "error", "blocked", "timeout", "cached", "manual"]
    offer_count: int = 0
    error: str | None = None
    elapsed_ms: int | None = None
    reason_code: str | None = None
    http_status: int | None = None
    retry_count: int = 0
    circuit_state: Literal["closed", "open", "half_open"] = "closed"
    source: str | None = None
    retry_at: datetime | None = None


class SearchResult(BaseModel):
    id: UUID
    request: SearchRequest
    state: Literal["running", "complete"]
    offers: list[Offer]
    weak_matches: list[Offer] = Field(default_factory=list)
    retailers: list[RetailerStatus]
    created_at: datetime
    completed_at: datetime | None = None
    cached: bool = False


class RetailerInfo(BaseModel):
    id: str
    name: str
    kind: Literal["official", "boutique", "marketplace"]
    enabled: bool
    collection_mode: Literal["automatic", "manual"]
    source: str
    health: Literal["healthy", "unavailable", "unknown"]
    last_error: str | None = None
    paused: bool = False
    retry_at: datetime | None = None
