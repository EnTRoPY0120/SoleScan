<script lang="ts">
  import { inr } from '$lib/format';
  import OfferPromos from './OfferPromos.svelte';
  import type { Offer } from '$lib/types';
  export let detailOffer: Offer;
  $: metadata = [detailOffer.brand, detailOffer.colourway, detailOffer.style_code].filter(Boolean).join(' · ');
  $: stockLabel = detailOffer.stock_status === 'in_stock'
    ? `UK ${detailOffer.requested_uk_size} in stock`
    : detailOffer.stock_status === 'out_of_stock' ? 'Size unavailable' : 'Size stock not verified';
</script>
<div class="offer-body">
  <div class="tags"><span class={`confidence ${detailOffer.confidence}`}>{detailOffer.confidence} match</span><span class:yes={detailOffer.stock_status === 'in_stock'} class:unknown={detailOffer.stock_status === 'unknown'}>{stockLabel}</span></div>
  <h3>{detailOffer.product_name}</h3><p class="meta">{metadata}</p>
  <div class="seller"><b>{detailOffer.retailer}</b>{#if detailOffer.seller}<small>Sold by {detailOffer.seller}</small>{/if}</div>
  {#if detailOffer.automatic_discount_paise}<p class="saving">Automatic discount −{inr(detailOffer.automatic_discount_paise)}</p>{/if}
  <OfferPromos promos={detailOffer.conditional_offers} />
</div>
<style>.offer-body{padding:25px}.tags{display:flex;flex-wrap:wrap;gap:8px}.tags span{font-size:12px;text-transform:uppercase;letter-spacing:.7px;padding:5px 8px;background:#eceeea}.tags .confidence{background:#e8dfff;color:#563695}.tags .exact,.tags .strong{background:#dff2c8;color:#244f1a}.tags span.yes{background:#d8ff45;color:#213016}.tags span.unknown{background:#e8edf4;color:#34485f}.offer-body h3{font-size:23px;line-height:1.28;margin:17px 0 6px;overflow-wrap:anywhere}.meta{font-size:14px;color:#727c76}.seller{margin-top:22px;font-size:15px}.seller small{display:block;color:#68736d;margin-top:4px;font-size:12px}.saving{color:#277047;font-size:14px}@media(max-width:820px){.offer-body{padding:19px}}@media(max-width:520px){.offer-body h3{font-size:21px}}</style>
