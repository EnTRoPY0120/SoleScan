# Use evidence-bearing retailer contracts

Every retailer integration will implement an explicit, tested contract and return a precise outcome rather than treating the absence of extracted products as proof of a layout change or empty catalog. Integrations prefer accessible structured data or retailer APIs, then validated retailer-specific HTML, with browser rendering only where required; retries are bounded and fallbacks must be explicitly supported by that retailer. This costs more per-retailer maintenance than a generic extractor but makes comparisons and failures trustworthy.
