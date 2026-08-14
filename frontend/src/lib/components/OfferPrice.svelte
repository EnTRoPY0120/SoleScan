<script lang="ts">import { inr } from '$lib/format'; import type { Offer } from '$lib/types'; export let priceOffer: Offer;</script>
<div class="price">
  <small>{priceOffer.shipping_paise === null ? 'PRICE · SHIPPING UNKNOWN' : 'DELIVERED TOTAL'}</small><strong>{inr(priceOffer.effective_price_paise)}</strong>
  {#if priceOffer.shipping_paise === null}<p>Shipping added at checkout</p>{:else if priceOffer.shipping_paise > 0}<p>Includes {inr(priceOffer.shipping_paise)} shipping</p>{:else}<p>Free shipping</p>{/if}
  <a href={priceOffer.product_url} target="_blank" rel="noopener noreferrer">View at {priceOffer.retailer} ↗</a>
</div>
<style>.price{padding:27px;border-left:1px solid #e1e2de;display:flex;flex-direction:column;align-items:flex-end;text-align:right}.price small{font-size:12px;letter-spacing:1px}.price strong{font-size:34px;margin-top:9px;line-height:1.2}.price p{font-size:14px;color:#647068;flex:1}.price a{background:#193c2d;color:#fff;text-decoration:none;padding:12px 15px;font-size:14px;font-weight:700}@media(max-width:820px){.price{grid-column:2/4;border-left:0;border-top:1px solid #ddd;align-items:flex-start;text-align:left}.price p{margin:8px 0 16px}}@media(max-width:520px){.price strong{font-size:32px}}</style>
