<script lang="ts">
  import OfferList from './OfferList.svelte';
  import OfferFilters from './OfferFilters.svelte';
  import { sortOffers } from '$lib/format';
  import type { Offer } from '$lib/types';
  export let resultOffers: Offer[] = [];
  export let resultsSearching = false;
  let sort = 'price';
  let availableOnly = true;
  let selectedRetailer = 'all';
  $: retailerNames = [...new Set(resultOffers.map((offer) => offer.retailer))].sort();
  $: filtered = resultOffers.filter((offer) => (!availableOnly || offer.stock_status === 'in_stock') && (selectedRetailer === 'all' || offer.retailer === selectedRetailer));
  $: visibleOffers = sortOffers(filtered, sort);
</script>
{#if resultOffers.length}
  <OfferFilters bind:sort bind:selectedRetailer bind:availableOnly {retailerNames} />
  <OfferList items={visibleOffers} />
{:else if !resultsSearching}
  <div class="empty"><span>◎</span><div><h3>No exact footwear matches yet</h3><p>Try checking the model, brand, colourway, and size. Blocked retailers were not checked and do not mean “no stock”.</p></div></div>
{/if}
<style>.empty{display:flex;align-items:center;justify-content:center;gap:28px;text-align:left;padding:48px;background:#e9e8e2;border:1px solid #d9dbd6}.empty span{font-size:44px}.empty h3{font-size:23px;margin:0 0 8px}.empty p{margin:0;color:#66716b;max-width:650px;line-height:1.55;font-size:15px}@media(max-width:820px){.empty{align-items:flex-start;padding:30px 22px}}</style>
