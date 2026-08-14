<script lang="ts">import type { Offer } from '$lib/types'; export let promos: Offer['conditional_offers'] = [];</script>
{#each promos as promo}<details><summary>{promo.kind} offer</summary><p>{promo.description} — eligibility required; excluded from ranking.</p></details>{/each}
<style>details{font-size:13px;color:#634812;margin-top:9px}details p{max-width:440px;font-size:14px}</style>
