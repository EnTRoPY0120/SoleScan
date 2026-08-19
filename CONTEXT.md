# Sneaker Price Comparison

This context describes how a shopper identifies one sneaker and compares purchasable offers from retailers that deliver within India.

## Language

**Shopper**:
A person comparing sneaker offers in order to decide whether and where to buy.
_Avoid_: User, customer

**Comparison**:
A coverage-aware view of retailer checks for one sneaker and requested size, with exact purchasable offers ranked by delivered total and possible, stale, or unavailable results shown separately.
_Avoid_: Search results

**Comparison revision**:
A new comparison derived from an earlier comparison by replacing one retailer's observation while preserving the other retailer observations and their original times.
_Avoid_: Mutated comparison, full refresh

**Sneaker**:
A specific product identity distinguished by model or style code, colorway, and gender designation. Size is selected when comparing offers rather than defining a different sneaker.
_Avoid_: Search result, listing

**Exact match**:
An offer whose sneaker identity agrees on the attributes needed to establish that it is the same product.
_Avoid_: Match

**Resolved query**:
The sneaker identity SoleScan believes the shopper intended after applying only a high-confidence spelling correction. It may guide retailer checks, but it never relaxes exact-match verification of returned offers.
_Avoid_: Fuzzy match, approximate search

**Possible match**:
An offer that may refer to the sneaker but lacks enough identity evidence to qualify as an exact match. Possible matches never participate in the primary price ranking.
_Avoid_: Close enough, partial match

**Retailer**:
A declared seller whose offers can be purchased for delivery within India.
_Avoid_: Store, source

**Retailer tier**:
A priority group reflecting how directly and reliably a retailer represents sneaker identity: official brand retailers first, specialist sneaker retailers second, and marketplaces third.
_Avoid_: Retailer rank

**Offer**:
A retailer's size-specific opportunity to purchase a sneaker at an observed point in time.
_Avoid_: Product, result

**Delivered total**:
The known cost of an offer delivered to the shopper's Indian postcode, including the listed price and any known shipping, tax, duty, and discount components. Unknown components remain explicit rather than being treated as zero.
_Avoid_: Price, final price

**Purchasable offer**:
An offer currently available in the shopper's requested size. Offers without that size remain visible separately and do not participate in the primary price ranking.
_Avoid_: In stock

**Fresh offer**:
An offer observed within the accepted freshness window. The observation time is always visible, and the retailer remains authoritative at purchase time.
_Avoid_: Live price, current price

**Stale offer**:
An offer older than the accepted freshness window. It may be shown for reference but never represented or ranked as fresh.
_Avoid_: Cached price

**Valid empty result**:
A retailer response with enough evidence to conclude that it currently has no matching offers.
_Avoid_: No results

**Uncertain result**:
A retailer response that cannot establish either matching offers or a valid empty result. It does not participate in price ranking.
_Avoid_: No results, layout changed

**Retailer check**:
An attempt to obtain current offer evidence from one retailer. Its outcome distinguishes offers, a valid empty result, required verification, blocked access, a changed retailer contract, transport failure, and an unexpected service failure.
_Avoid_: Scrape, retailer status

**Verification session**:
A temporary assisted-browser session in which the shopper may clear retailer consent or anti-bot verification screens without entering retailer account credentials.
_Avoid_: Retailer connection, login session

**Verified retailer state**:
Temporary browser state produced after a shopper clears a retailer verification screen and reused only to recheck that retailer. It is not proof of account authentication or permission to bypass further access controls.
_Avoid_: Login, connected account, authenticated retailer
