from .base import RetailerDefinition
from .brandman import BrandmanAdapter
from .browser import BrowserMarketplaceAdapter
from .converse import ConverseAdapter
from .puma import PumaAdapter
from .onitsuka import OnitsukaAdapter
from .shopify import ShopifyCatalogAdapter
from .structured import StructuredDataAdapter
from .vegnonveg import VegNonVegAdapter


DEFINITIONS = [
    RetailerDefinition("nike", "Nike India", "official", "https://www.nike.com/in/w?q={query}&vst={query}", adapter_type="structured", collection_mode="manual"),
    RetailerDefinition("adidas", "Adidas India", "official", "https://www.adidas.co.in/search?q={query}", adapter_type="structured", collection_mode="manual"),
    PumaAdapter.definition,  # adapter_type="puma"
    RetailerDefinition("asics", "ASICS India", "official", "https://www.asics.co.in/catalogsearch/result/?q={query}", adapter_type="structured", collection_mode="manual"),
    BrandmanAdapter.definition,  # adapter_type="brandman"
    RetailerDefinition("converse", "Converse India", "official", "https://www.converse.in/search?q={query}", adapter_type="converse"),
    RetailerDefinition("reebok", "Reebok India", "official", "https://reebok.abfrl.in/c/search?search_query={query}", uses_browser=True, adapter_type="browser", collection_mode="manual"),
    OnitsukaAdapter.definition,
    VegNonVegAdapter.definition,  # adapter_type="vegnonveg"
    RetailerDefinition("superkicks", "Superkicks", "boutique", "https://www.superkicks.in/search?q={query}", adapter_type="shopify"),
    RetailerDefinition("limited_edt", "Limited Edt", "boutique", "https://limitededt.in/search?q={query}", adapter_type="shopify"),
    RetailerDefinition("foot_locker", "Foot Locker India", "official", "https://www.footlocker.co.in/search?q={query}", uses_browser=True, adapter_type="browser", collection_mode="manual"),
    RetailerDefinition("myntra", "Myntra", "marketplace", "https://www.myntra.com/{query}", uses_browser=True, adapter_type="browser", collection_mode="manual"),
    RetailerDefinition("ajio", "AJIO", "marketplace", "https://www.ajio.com/search/?text={query}", uses_browser=True, adapter_type="browser", collection_mode="manual"),
    RetailerDefinition("nykaa_fashion", "Nykaa Fashion", "marketplace", "https://www.nykaafashion.com/catalogsearch/result/?q={query}", uses_browser=True, adapter_type="browser", collection_mode="manual"),
]


def _build_adapter(definition: RetailerDefinition):
    t = definition.adapter_type
    if t == "puma":
        return PumaAdapter()
    if t == "onitsuka":
        return OnitsukaAdapter()
    if t == "converse":
        return ConverseAdapter()
    if t == "brandman":
        return BrandmanAdapter()
    if t == "vegnonveg":
        return VegNonVegAdapter()
    if t == "shopify":
        return ShopifyCatalogAdapter(definition)
    if t == "browser" or definition.uses_browser:
        return BrowserMarketplaceAdapter(definition)
    return StructuredDataAdapter(definition)


ADAPTERS = [_build_adapter(d) for d in DEFINITIONS if d.enabled]
