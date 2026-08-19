<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  export let query = '';
  export let ukSize = '';
  export let brand = '';
  export let colourway = '';
  export let department = 'any';
  export let pinCode = '';
  export let searching = false;
  export let verificationActive = false;
  const dispatch = createEventDispatcher<{ search: void }>();
</script>

<form on:submit|preventDefault={() => dispatch('search')} aria-label="Sneaker search">
  <label class="wide">Sneaker model <span>*</span><input bind:value={query} placeholder="e.g. Air Jordan 1 Low" autocomplete="off" /></label>
  <label>UK size <span>*</span><input bind:value={ukSize} placeholder="8.5" inputmode="decimal" /></label>
  <label>Brand<input bind:value={brand} placeholder="Nike" /></label>
  <label>Colourway<input bind:value={colourway} placeholder="Black / White" /></label>
  <label>Department<select bind:value={department}><option value="any">Any</option><option value="men">Men</option><option value="women">Women</option><option value="kids">Kids</option></select></label>
  <label>PIN code<input bind:value={pinCode} placeholder="Optional" inputmode="numeric" maxlength="6" /></label>
  <button class="search" disabled={searching || verificationActive}>{verificationActive ? 'Verification in progress…' : searching ? 'Checking stores…' : 'Search prices'} <span aria-hidden="true">→</span></button>
</form>

<style>
  form{display:grid;grid-template-columns:2fr 1fr 1fr;gap:1px;background:#d7d9d4;border:1px solid #d7d9d4;box-shadow:6px 6px 0 #203f31;margin:52px 0 28px;border-radius:2px;overflow:hidden}label{background:#fff;padding:18px 20px;font-size:12px;text-transform:uppercase;letter-spacing:1.3px;font-weight:800}label span{color:#e65336}input,select{display:block;width:100%;border:0;border-bottom:1px solid #c5c9c5;background:transparent;padding:12px 0 8px;outline:none;color:#111915;text-transform:none;letter-spacing:normal;font-weight:500}input:focus,select:focus{border-color:#193c2d;box-shadow:0 1px #193c2d}.wide{grid-column:span 2}.search{border:0;background:#d8ff45;text-transform:uppercase;font-size:14px;letter-spacing:1.3px;font-weight:900;cursor:pointer;padding:22px}.search:hover{background:#c6ef2f}.search span{font-size:24px;margin-left:15px}.search:disabled{opacity:.65;cursor:wait}
  @media(max-width:820px){form{grid-template-columns:1fr 1fr;margin-top:26px}.wide{grid-column:span 2}.search{grid-column:span 2}}
  @media(max-width:520px){form{grid-template-columns:1fr}.wide,.search{grid-column:auto}}
</style>
