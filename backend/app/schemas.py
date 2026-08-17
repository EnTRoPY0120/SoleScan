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


class ProductDepartment(str, Enum):
    men = "men"
    women = "women"
    kids = "kids"
    unisex = "unisex"
    unknown = "unknown"


class ProductCategory(str, Enum):
    footwear = "footwear"
    non_footwear = "non_footwear"
    unknown = "unknown"


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

    @model_validator(mode="after")
    def reject_brand_conflict(self) -> "SearchRequest":
        # Import lazily to avoid a schemas -> normalization import cycle.
        from .normalization import query_brand_conflict
        conflict = query_brand_conflict(self)
        if conflict:
            raise ValueError(f"Query contains a conflicting brand: {conflict}")
        return self


class ConditionalOffer(BaseModel):
    kind: Literal["coupon", "bank", "membership", "other"] = "other"
    description: str
    amount_paise: int | None = Field(default=None, ge=0)


class Offer(BaseModel):
    retailer: str
    seller: str | None = None
    confidence: Literal["exact"] = "exact"
    product_name: str
    brand: str | None = None
    model: str | None = None
    colourway: str | None = None
    category: ProductCategory = ProductCategory.unknown
    department: ProductDepartment = ProductDepartment.unknown
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
    # Internal ranking evidence; kept explicit so serialized cached offers are
    # stable across pydantic versions.
    colour_match: bool = True
    last_checked: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("confidence", mode="before")
    @classmethod
    def legacy_confidence_is_exact_contract(cls, value: str | None) -> str:
        # Older rows used strong/possible/weak confidence.  They remain
        # readable, but the active API exposes only accepted exact offers.
        return "exact"

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
    retailer_id: str | None = None
    retailer: str
    state: Literal["pending", "running", "complete", "partial", "error", "blocked", "timeout", "cached", "needs_session"]
    offer_count: int = 0
    error: str | None = None
    elapsed_ms: int | None = None
    reason_code: str | None = None
    http_status: int | None = None
    retry_count: int = 0
    circuit_state: Literal["closed", "open", "half_open"] = "closed"
    source: str | None = None
    retry_at: datetime | None = None
    session_capable: bool = False
    session_state: Literal["none", "starting", "active", "expired"] = "none"


class SearchResult(BaseModel):
    id: UUID
    request: SearchRequest
    state: Literal["running", "complete"]
    offers: list[Offer]
    retailers: list[RetailerStatus]
    created_at: datetime
    completed_at: datetime | None = None
    cached: bool = False


class RetailerInfo(BaseModel):
    id: str
    name: str
    kind: Literal["official", "boutique", "marketplace"]
    enabled: bool
    collection_mode: Literal["automatic"]
    source: str
    health: Literal["healthy", "unavailable", "unknown"]
    last_error: str | None = None
    paused: bool = False
    retry_at: datetime | None = None
    session_capable: bool = False
    session_state: Literal["none", "starting", "active", "expired"] = "none"


class RetailerSessionStart(BaseModel):
    search_id: UUID


class RetailerSessionComplete(BaseModel):
    search_id: UUID
    # The UI sets this only after the user has cleared a visible consent or
    # verification screen.  Credentials and challenge answers are never sent
    # to the API.
    challenge_cleared: bool | None = None
