<script lang="ts">
  import type { RetailerStatus } from '$lib/types';
  import { retailerStatusDetail } from '$lib/retailer-status';
  export let retailer: RetailerStatus;
  export let searchId = '';
  export let connect: (retailerId: string) => Promise<void> = async () => undefined;
  export let complete: (retailerId: string) => Promise<void> = async () => undefined;
  export let cancel: (retailerId: string) => Promise<void> = async () => undefined;
  let actionError = '';
  let actionPending = false;
  const icons: Record<RetailerStatus['state'], string> = { pending: '·', running: '◌', complete: '✓', partial: '◐', cached: '✓', blocked: '⊘', error: '!', timeout: '!', needs_session: '◉' };
  $: statusDetail = retailerStatusDetail(retailer);

  async function perform(action: (retailerId: string) => Promise<void>) {
    actionError = '';
    actionPending = true;
    try {
      await action(retailer.retailer_id || retailer.retailer);
    } catch (cause) {
      actionError = cause instanceof Error ? cause.message : 'Verification action failed.';
    } finally {
      actionPending = false;
    }
  }
</script>
<div class:error-state={retailer.state === 'error' || retailer.state === 'timeout'} class:blocked={retailer.state === 'blocked' || retailer.state === 'needs_session'} class:partial={retailer.state === 'partial'} class:done={retailer.state === 'complete' || retailer.state === 'cached'}>
  <span>{icons[retailer.state]}</span><span>{retailer.retailer}<small>{statusDetail}</small>{#if retailer.state === 'needs_session' && retailer.session_capable}<button disabled={!searchId || actionPending} on:click={() => perform(connect)}>Open verification session</button><button disabled={!searchId || actionPending} on:click={() => perform(complete)}>Done — refresh</button><button disabled={actionPending} on:click={() => perform(cancel)}>Cancel</button>{/if}{#if actionError}<small class="action-error" role="alert">{actionError}</small>{/if}</span>
</div>
<style>div{min-width:0;background:#e8e7e1;padding:12px 13px;display:flex;gap:10px;font-size:13px;border-radius:2px}span:first-child{font-weight:900}small{display:block;color:#68736d;margin-top:4px;font-size:12px;line-height:1.35;overflow-wrap:anywhere}button{display:inline-block;margin:7px 10px 0 0;color:#174b36;background:transparent;border:0;padding:0;font-size:12px;font-weight:800;cursor:pointer}button:disabled{cursor:wait;opacity:.55}.action-error{color:#8c291b;font-weight:700}.done{background:#e3f2d4}.partial{background:#fff3cd;color:#856404;border:1px solid #ffc107}.error-state{background:#f7ddd7;color:#8c291b}.blocked{background:#f3e5bd;color:#694d00;border:1px dashed #b08c2f}</style>
