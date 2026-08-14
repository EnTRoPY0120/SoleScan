<script lang="ts">
  import OfferDetails from './OfferDetails.svelte';
  import OfferPhoto from './OfferPhoto.svelte';
  import OfferPrice from './OfferPrice.svelte';
  import type { Offer } from '$lib/types';
  export let offer: Offer;
  export let rank: number;
</script>
<article class:unavailable={offer.stock_status === 'out_of_stock'}>
  <div class="rank">#{rank}</div><OfferPhoto imageUrl={offer.image_url} alt={offer.product_name} />
  <OfferDetails detailOffer={offer} /><OfferPrice priceOffer={offer} />
</article>
<style>article{display:grid;grid-template-columns:40px 190px minmax(0,1fr) 245px;background:#fff;border:1px solid #d9dbd6;min-height:225px;position:relative;border-radius:3px;overflow:hidden;transition:transform .15s,box-shadow .15s}article:hover{transform:translateY(-2px);box-shadow:0 8px 24px #253d3020}.rank{padding:20px 0;text-align:center;font-weight:900;font-size:12px;background:#172b22;color:#fff}.unavailable{opacity:.63}@media(max-width:820px){article{grid-template-columns:34px 120px minmax(0,1fr)}}@media(max-width:520px){article{grid-template-columns:32px 90px minmax(0,1fr)}}</style>
