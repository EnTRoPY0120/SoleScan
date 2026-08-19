<script lang="ts">
  import RetailerStatusItem from './RetailerStatusItem.svelte';
  import type { RetailerStatus } from '$lib/types';
  export let retailers: RetailerStatus[] = [];
  export let statusesSearching = false;
  export let searchId = '';
  export let activeRetailerId = '';
  export let sessionSecondsRemaining = 0;
  export let recheckedRetailerId: string | null = null;
  export let verificationAttempt = 0;
  export let connect: (retailerId: string) => Promise<void> = async () => undefined;
  export let complete: (retailerId: string) => Promise<void> = async () => undefined;
  export let closeSession: (retailerId: string) => Promise<void> = async () => undefined;
  export let forgetSession: (retailerId: string) => Promise<void> = async () => undefined;
  const terminalStates = new Set(['complete', 'partial', 'error', 'blocked', 'timeout', 'cached', 'needs_session']);
  $: completed = retailers.filter((item) => terminalStates.has(item.state)).length;
  $: progress = retailers.length ? completed / retailers.length * 100 : 2;
</script>
{#if statusesSearching}<div class="progress"><span style={`width: ${progress}%`}></span></div>{/if}
{#if retailers.length}<div class="retailer-strip">{#each retailers as retailer}<RetailerStatusItem {retailer} {searchId} {activeRetailerId} {sessionSecondsRemaining} {recheckedRetailerId} {verificationAttempt} {connect} {complete} {closeSession} {forgetSession} />{/each}</div>{/if}
<style>.progress{height:4px;background:#d7dbd4;margin:22px 0;overflow:hidden}.progress span{display:block;height:100%;background:#294d3c;transition:width .3s}.retailer-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:8px;padding:20px 0 28px}@media(max-width:820px){.retailer-strip{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:520px){.retailer-strip{grid-template-columns:1fr}}</style>
