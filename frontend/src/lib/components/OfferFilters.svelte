<script lang="ts">
  export let sort = 'price';
  export let selectedRetailer = 'all';
  export let availableOnly = true;
  export let retailerNames: string[] = [];
</script>
<div class="controls">
  <label>Sort <select bind:value={sort}><option value="price">Lowest delivered price</option><option value="match">Best match</option><option value="retailer">Retailer</option></select></label>
  <label>Retailer <select bind:value={selectedRetailer}><option value="all">All retailers</option>{#each retailerNames as name}<option value={name}>{name}</option>{/each}</select></label>
  <label class="check"><input type="checkbox" bind:checked={availableOnly} /> In stock only</label>
</div>
<style>.controls{display:flex;flex-wrap:wrap;align-items:end;gap:20px;border-block:1px solid #c9ccc5;padding:16px 0;margin-bottom:16px}.controls label{font-size:12px;letter-spacing:1px;text-transform:uppercase;font-weight:800}.controls select{display:block;border:0;border-bottom:1px solid #c5c9c5;background:transparent;padding:12px 0 8px;min-width:190px}.controls .check{display:flex;align-items:center;gap:8px;padding-bottom:8px}.check input{width:auto}@media(max-width:820px){.controls{align-items:center}.controls label{min-width:170px}}</style>
