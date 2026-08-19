<script lang="ts">
  import '@fontsource-variable/manrope';
  import ResultsSection from '$lib/components/ResultsSection.svelte';
  import SearchForm from '$lib/components/SearchForm.svelte';
  import { beginSearch, cancelRetailerSession, completeRetailerSession, connectSearchEvents, inputMatchesRequest, loadSearch, startRetailerSession, validateSearch, type SearchInput } from '$lib/search';
  import type { Offer, RetailerStatus, SearchResult } from '$lib/types';

  let query = '';
  let ukSize = '';
  let brand = '';
  let colourway = '';
  let department = 'any';
  let pinCode = '';
  let searching = false;
  let error = '';
  let searchId = '';
  let offers: Offer[] = [];
  let retailers: RetailerStatus[] = [];
  let cached = false;
  let events: ReturnType<typeof connectSearchEvents> | null = null;
  let displayedRequest: SearchResult['request'] | null = null;
  let resolvedQuery: string | null = null;
  $: inputsChanged = Boolean(displayedRequest && !inputMatchesRequest(input(), displayedRequest));

  function input(): SearchInput {
    return { query, ukSize, brand, colourway, department, pinCode };
  }

  function applyResult(result: SearchResult) {
    offers = result.offers;
    retailers = result.retailers;
    cached = result.cached;
    displayedRequest = result.request;
    resolvedQuery = result.resolved_query;
    if (result.state === 'complete') searching = false;
  }

  async function reload() {
    applyResult(await loadSearch(searchId));
  }

  function watchEvents() {
    if (!searching) return;
    events = connectSearchEvents(searchId, {
      update: () => { reload().catch(() => undefined); },
      complete: applyResult,
      disconnect: () => {
        reload().catch(() => { error = 'Live updates disconnected. Results may be incomplete.'; });
      }
    });
  }

  async function startSearch() {
    if (!prepareSearch()) return;
    await runSearch();
  }

  function prepareSearch(): boolean {
    error = validateSearch(input());
    return !error;
  }

  function errorMessage(cause: unknown): string {
    return cause instanceof Error ? cause.message : 'Search failed.';
  }

  async function runSearch(allowQueryCorrection = true) {
    searching = true;
    cached = false;
    offers = [];
    retailers = [];
    resolvedQuery = null;
    events?.close();
    try {
      const started = await beginSearch(input(), '', allowQueryCorrection);
      searchId = started.id;
      cached = started.cached;
      await reload();
      watchEvents();
    } catch (cause) {
      error = errorMessage(cause);
      searching = false;
    }
  }

  async function searchOriginal() {
    if (!displayedRequest || searching) return;
    query = displayedRequest.query;
    await runSearch(false);
  }

  async function refreshDisplayed() {
    if (!searchId || searching) return;
    searching = true;
    error = '';
    events?.close();
    try {
      const started = await beginSearch(input(), searchId);
      searchId = started.id;
      await reload();
      watchEvents();
    } catch (cause) {
      error = errorMessage(cause);
      searching = false;
    }
  }

  async function connectRetailer(retailerId: string) {
    if (!searchId) return;
    // Open synchronously from the click handler so popup blockers do not
    // discard the viewer while the API creates the assisted context.
    const viewer = window.open('', 'sole-scan-assisted-retailer', 'popup,width=1280,height=900');
    try {
      const session = await startRetailerSession(retailerId, searchId);
      if (viewer) viewer.location.href = session.viewer_url;
      else window.open(session.viewer_url, 'sole-scan-assisted-retailer', 'popup,width=1280,height=900');
    } catch (cause) {
      viewer?.close();
      throw cause;
    }
  }

  async function completeRetailer(retailerId: string) {
    if (!searchId) return;
    events?.close();
    try {
      const started = await completeRetailerSession(retailerId, searchId);
      searchId = started.id;
      searching = true;
      await reload();
      watchEvents();
    } catch (cause) {
      throw cause;
    }
  }

  async function cancelRetailer(retailerId: string) {
    await cancelRetailerSession(retailerId);
    await reload();
  }
</script>

<svelte:head><title>Indian Sneaker Price Finder</title><meta name="description" content="Compare sneaker prices and UK-size stock across Indian retailers." /></svelte:head>

<header><a class="brand" href="/" aria-label="Sneaker Price Finder home"><span>SOLE</span><b>SCAN</b></a></header>
<main>
  <SearchForm bind:query bind:ukSize bind:brand bind:colourway bind:department bind:pinCode {searching} on:search={startSearch} />
  <div class="alert" role="alert" hidden={!error}>{error}</div>
  <ResultsSection sectionOffers={offers} sectionRetailers={retailers} sectionSearching={searching} {cached} resultRequest={displayedRequest} {resolvedQuery} {searchOriginal} {inputsChanged} visible={Boolean(searching || searchId)} canRefresh={Boolean(searchId && !searching)} refresh={refreshDisplayed} {searchId} connect={connectRetailer} complete={completeRetailer} cancel={cancelRetailer} />
  <aside class="disclaimer"><b>Before you buy</b><p>Prices, stock, shipping, seller status, returns, and coupon eligibility can change. Always reconfirm every detail on the retailer’s product and checkout pages.</p></aside>
</main>
<footer>Built for local, personal price comparison · INR only · No affiliate tracking</footer>

<style>
  :global(*){box-sizing:border-box}:global(body){margin:0;background:#f7f5ef;color:#111915;font-family:"Manrope Variable",Manrope,ui-sans-serif,sans-serif;font-size:16px;line-height:1.5;-webkit-font-smoothing:antialiased}:global(button),:global(input),:global(select){font:inherit;font-size:16px}:global(h1),:global(h2),:global(h3){font-family:inherit;font-weight:750}:global([hidden]){display:none!important}header{height:68px;padding:0 max(5vw,24px);display:flex;align-items:center;border-bottom:1px solid #d5d5cf;background:rgba(247,245,239,.96);position:sticky;top:0;z-index:5;backdrop-filter:blur(12px)}.brand{text-decoration:none;color:#111915;font-size:23px;letter-spacing:-1px}.brand span{font-weight:900}.brand b{font-weight:300}main{width:min(1280px,92vw);margin:auto}.alert{border-left:4px solid #cc412d;background:#fff0ed;padding:16px 20px;margin:22px 0}.disclaimer{display:flex;gap:32px;background:#172b22;color:#fff;padding:27px 32px;margin:38px 0 74px;border-radius:3px}.disclaimer b{white-space:nowrap}.disclaimer p{margin:0;color:#bdc8c2;line-height:1.55;font-size:15px}footer{text-align:center;border-top:1px solid #ccd0ca;padding:27px;color:#6c766f;font-size:12px;letter-spacing:1px;text-transform:uppercase}@media(max-width:820px){header{height:60px}.disclaimer{display:block}.disclaimer p{margin-top:11px}}@media(max-width:520px){main{width:min(94vw,1280px)}}
</style>
