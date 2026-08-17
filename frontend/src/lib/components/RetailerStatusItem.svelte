<script lang="ts">
  import type { RetailerStatus } from '$lib/types';
  export let retailer: RetailerStatus;
  export let searchId = '';
  export let connect: (retailerId: string) => void = () => undefined;
  export let complete: (retailerId: string) => void = () => undefined;
  const icons: Record<RetailerStatus['state'], string> = { pending: '·', running: '◌', complete: '✓', partial: '◐', cached: '✓', blocked: '⊘', error: '!', timeout: '!', needs_session: '◉' };
  const baseDetail: Partial<Record<RetailerStatus['state'], string>> = { pending: 'Waiting…', running: 'Checking now…' };
  
  $: statusDetail = (() => {
    const state = retailer.state;
    const reasonCode = retailer.reason_code;
    const offerCount = retailer.offer_count;

    if (state === 'needs_session') return 'Verification needed — connect retailer';
    // Partial state
    if (state === 'partial') {
      return 'Partial results (some products unavailable)';
    }
    
    // Blocked states with specific reason codes
    if (state === 'blocked') {
      if (reasonCode === 'verification_challenge') {
        return 'Access blocked — verification challenge';
      }
      if (reasonCode === 'host_cooldown') {
        return 'Auto-paused';
      }
      if (reasonCode === 'http_403' || reasonCode === 'http_401') {
        return 'Access denied by retailer';
      }
      return `Not checked · ${retailer.error || 'retailer unavailable'}`;
    }
    
    // Error states with specific reason codes
    if (state === 'error') {
      if (reasonCode === 'transport_protocol') {
        return 'Transport error (HTTP/2 incompatibility)';
      }
      if (reasonCode === 'catalog_shell') {
        return 'Retailer layout has changed';
      }
      if (reasonCode === 'catalog_contract_changed') {
        return 'Retailer catalog format changed';
      }
    }
    
    // Complete state
    if (state === 'complete') {
      if (offerCount === 0) {
        return 'No results found';
      }
      return `${offerCount} result${offerCount !== 1 ? 's' : ''} found`;
    }
    
    // Default fallback
    return retailer.error || baseDetail[state] || `${offerCount} found`;
  })();
</script>
<div class:error-state={retailer.state === 'error' || retailer.state === 'timeout'} class:blocked={retailer.state === 'blocked' || retailer.state === 'needs_session'} class:partial={retailer.state === 'partial'} class:done={retailer.state === 'complete' || retailer.state === 'cached'}>
  <span>{icons[retailer.state]}</span><span>{retailer.retailer}<small>{statusDetail}</small>{#if retailer.state === 'needs_session' && retailer.session_capable}<button disabled={!searchId} on:click={() => connect(retailer.retailer_id || retailer.retailer)}>Connect retailer</button><button disabled={!searchId} on:click={() => complete(retailer.retailer_id || retailer.retailer)}>Done — refresh</button>{/if}</span>
</div>
<style>div{min-width:0;background:#e8e7e1;padding:12px 13px;display:flex;gap:10px;font-size:13px;border-radius:2px}span:first-child{font-weight:900}small{display:block;color:#68736d;margin-top:4px;font-size:12px;line-height:1.35;overflow-wrap:anywhere}button{display:inline-block;margin-top:7px;color:#174b36;background:transparent;border:0;padding:0;font-size:12px;font-weight:800;cursor:pointer}.done{background:#e3f2d4}.partial{background:#fff3cd;color:#856404;border:1px solid #ffc107}.error-state{background:#f7ddd7;color:#8c291b}.blocked{background:#f3e5bd;color:#694d00;border:1px dashed #b08c2f}</style>
