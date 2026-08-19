<script lang="ts">
  import OfferResults from './OfferResults.svelte';
  import RetailerStatuses from './RetailerStatuses.svelte';
  import type { Offer, RetailerStatus, SearchResult } from '$lib/types';
  export let sectionOffers: Offer[] = [];
  export let sectionRetailers: RetailerStatus[] = [];
  export let sectionSearching = false;
  export let cached = false;
  export let resultRequest: SearchResult['request'] | null = null;
  export let resolvedQuery: string | null = null;
  export let searchOriginal: () => void = () => undefined;
  export let inputsChanged = false;
  export let visible = false;
  export let canRefresh = false;
  export let refresh: () => void;
  export let searchId = '';
  export let activeRetailerId = '';
  export let sessionSecondsRemaining = 0;
  export let recheckedRetailerId: string | null = null;
  export let verificationAttempt = 0;
  export let connect: (retailerId: string) => Promise<void> = async () => undefined;
  export let complete: (retailerId: string) => Promise<void> = async () => undefined;
  export let closeSession: (retailerId: string) => Promise<void> = async () => undefined;
  export let forgetSession: (retailerId: string) => Promise<void> = async () => undefined;
  $: eyebrow = sectionSearching ? 'COMPARISON IN PROGRESS' : cached ? 'CACHED COMPARISON' : 'COMPARISON READY';
  $: offerLabel = `${sectionOffers.length} matching offer${sectionOffers.length === 1 ? '' : 's'}`;
  $: checkedCount = sectionRetailers.filter((item) => item.outcome === 'offers_found' || item.outcome === 'valid_empty').length;
  $: unavailableCount = sectionRetailers.filter((item) => item.outcome && item.outcome !== 'offers_found' && item.outcome !== 'valid_empty').length;
  $: needsSessionCount = sectionRetailers.filter((item) => item.state === 'needs_session').length;
</script>
<section class="results" aria-live="polite" hidden={!visible}>
  <div class="result-head">
    <div><p class="eyebrow">{eyebrow}</p><h2>{offerLabel}</h2>{#if resultRequest}<p class="request-title">{resolvedQuery || resultRequest.query} · UK {resultRequest.uk_size}</p>{/if}{#if resolvedQuery && resultRequest}<p class="correction">Showing results for <strong>{resolvedQuery}</strong> instead of “{resultRequest.query}”. <button on:click={searchOriginal}>Search original text</button></p>{/if}<p class="result-note">{checkedCount} of {sectionRetailers.length} retailers checked{#if unavailableCount} · {unavailableCount} unavailable{/if}{#if needsSessionCount} · {needsSessionCount} need verification{/if}.</p>{#if needsSessionCount}<p class="session-note">Verification sessions are for consent or verification screens only—never enter retailer login credentials.</p>{/if}{#if inputsChanged}<p class="changed">Inputs changed—search again to use the edited values.</p>{/if}</div>
    {#if canRefresh}<button class="refresh" on:click={refresh}>↻ Refresh live prices</button>{/if}
  </div>
  <RetailerStatuses retailers={sectionRetailers} statusesSearching={sectionSearching} {searchId} {activeRetailerId} {sessionSecondsRemaining} {recheckedRetailerId} {verificationAttempt} {connect} {complete} {closeSession} {forgetSession} />
  <OfferResults resultOffers={sectionOffers} resultsSearching={sectionSearching} />
</section>
<style>.results{padding:36px 0}.result-head{display:flex;justify-content:space-between;align-items:end;border-bottom:1px solid #cdd0cb;padding-bottom:24px}.eyebrow{font-size:12px;letter-spacing:2.2px;font-weight:800;color:#657169}.result-head h2{font-size:clamp(32px,4vw,48px);letter-spacing:-1.5px;margin:7px 0 3px}.request-title{font-weight:800;margin:2px 0 4px}.correction{font-size:14px;color:#394b42;margin:6px 0}.correction button{border:0;background:none;padding:0;color:#075d3d;font-weight:800;text-decoration:underline;cursor:pointer}.result-note{color:#6a746e;font-size:15px;margin:0}.session-note{color:#694d00;font-size:13px;margin:7px 0 0}.changed{color:#8c4b13;font-size:14px;font-weight:800;margin:9px 0 0}.refresh{background:#fff;border:1px solid #263b31;padding:12px 16px;cursor:pointer}.refresh:hover{background:#193c2d;color:white}@media(max-width:820px){.result-head{align-items:start;gap:18px;flex-wrap:wrap}.result-head h2{font-size:30px}}</style>
