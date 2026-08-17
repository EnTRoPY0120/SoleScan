<script lang="ts">
  import OfferResults from './OfferResults.svelte';
  import RetailerStatuses from './RetailerStatuses.svelte';
  import type { Offer, RetailerStatus, SearchResult } from '$lib/types';
  export let sectionOffers: Offer[] = [];
  export let sectionRetailers: RetailerStatus[] = [];
  export let sectionSearching = false;
  export let cached = false;
  export let resultRequest: SearchResult['request'] | null = null;
  export let inputsChanged = false;
  export let visible = false;
  export let canRefresh = false;
  export let refresh: () => void;
  export let searchId = '';
  export let connect: (retailerId: string) => void = () => undefined;
  export let complete: (retailerId: string) => void = () => undefined;
  $: eyebrow = sectionSearching ? 'SEARCH IN PROGRESS' : cached ? 'CACHED RESULTS' : 'SEARCH COMPLETE';
  $: offerLabel = `${sectionOffers.length} matching offer${sectionOffers.length === 1 ? '' : 's'}`;
  $: automaticCount = sectionRetailers.length;
  $: needsSessionCount = sectionRetailers.filter((item) => item.state === 'needs_session').length;
</script>
<section class="results" aria-live="polite" hidden={!visible}>
  <div class="result-head">
    <div><p class="eyebrow">{eyebrow}</p><h2>{offerLabel}</h2>{#if resultRequest}<p class="request-title">{resultRequest.query} · UK {resultRequest.uk_size}</p>{/if}<p class="result-note">{automaticCount} checked automatically{#if needsSessionCount} · {needsSessionCount} need verification in the assisted browser{/if}. Blocked stores were not checked.</p>{#if needsSessionCount}<p class="session-note">Assisted browser sessions are for consent or verification screens only—never enter retailer login credentials.</p>{/if}{#if inputsChanged}<p class="changed">Inputs changed—search again to use the edited values.</p>{/if}</div>
    {#if canRefresh}<button class="refresh" on:click={refresh}>↻ Refresh live prices</button>{/if}
  </div>
  <RetailerStatuses retailers={sectionRetailers} statusesSearching={sectionSearching} {searchId} {connect} {complete} />
  <OfferResults resultOffers={sectionOffers} resultsSearching={sectionSearching} />
</section>
<style>.results{padding:36px 0}.result-head{display:flex;justify-content:space-between;align-items:end;border-bottom:1px solid #cdd0cb;padding-bottom:24px}.eyebrow{font-size:12px;letter-spacing:2.2px;font-weight:800;color:#657169}.result-head h2{font-size:clamp(32px,4vw,48px);letter-spacing:-1.5px;margin:7px 0 3px}.request-title{font-weight:800;margin:2px 0 4px}.result-note{color:#6a746e;font-size:15px;margin:0}.session-note{color:#694d00;font-size:13px;margin:7px 0 0}.changed{color:#8c4b13;font-size:14px;font-weight:800;margin:9px 0 0}.refresh{background:#fff;border:1px solid #263b31;padding:12px 16px;cursor:pointer}.refresh:hover{background:#193c2d;color:white}@media(max-width:820px){.result-head{align-items:start;gap:18px;flex-wrap:wrap}.result-head h2{font-size:30px}}</style>
