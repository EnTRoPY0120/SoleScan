<script lang="ts">
  import OfferCard from './OfferCard.svelte';
  import type { Offer } from '$lib/types';
  export let items: Offer[] = [];
</script>
<div class="offer-grid">{#each items as offer, index}<OfferCard {offer} rank={index + 1} />{/each}</div>
<style>.offer-grid{display:grid;gap:12px}</style>
