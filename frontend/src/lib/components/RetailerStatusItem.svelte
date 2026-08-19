<script lang="ts">
  import type { RetailerStatus } from '$lib/types';
  import { retailerStatusDetail } from '$lib/retailer-status';
  export let retailer: RetailerStatus;
  export let searchId = '';
  export let activeRetailerId = '';
  export let sessionSecondsRemaining = 0;
  export let recheckedRetailerId: string | null = null;
  export let verificationAttempt = 0;
  export let connect: (retailerId: string) => Promise<void> = async () => undefined;
  export let complete: (retailerId: string) => Promise<void> = async () => undefined;
  export let closeSession: (retailerId: string) => Promise<void> = async () => undefined;
  export let forgetSession: (retailerId: string) => Promise<void> = async () => undefined;
  let actionError = '';
  let actionPending = false;
  const icons: Record<RetailerStatus['state'], string> = { pending: '·', running: '◌', complete: '✓', partial: '◐', cached: '✓', blocked: '⊘', error: '!', timeout: '!', needs_session: '◉' };
  $: statusDetail = retailerStatusDetail(retailer);
  $: retailerId = retailer.retailer_id || retailer.retailer;
  $: isActive = activeRetailerId === retailerId;
  $: anotherActive = Boolean(activeRetailerId && !isActive);
  $: rechecked = recheckedRetailerId === retailerId;
  $: retailerVerificationAttempt = rechecked ? verificationAttempt : 0;
  $: verificationWorked = rechecked && (retailer.outcome === 'offers_found' || retailer.outcome === 'valid_empty');
  $: verificationFailed = rechecked && retailer.outcome === 'verification_required';
  $: minutes = Math.floor(Math.max(0, sessionSecondsRemaining) / 60);
  $: seconds = Math.max(0, sessionSecondsRemaining) % 60;

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
  <span>{icons[retailer.state]}</span><span>{retailer.retailer}<small>{verificationWorked ? `Verification worked — ${statusDetail}` : verificationFailed ? 'Verification did not carry over' : statusDetail}</small>
  {#if retailer.state === 'needs_session' && retailer.session_capable}
    {#if isActive}
      <small>Clear only the consent or verification screen in the open retailer window. Never log in.</small>
      <small>{minutes}:{String(seconds).padStart(2, '0')} remaining</small>
      <button disabled={!searchId || actionPending} on:click={() => perform(complete)}>I cleared verification</button>
      <button disabled={actionPending} on:click={() => perform(closeSession)}>Close without saving</button>
    {:else if retailerVerificationAttempt < 2}
      <button disabled={!searchId || actionPending || anotherActive} on:click={() => perform(connect)}>{retailerVerificationAttempt ? 'Open again' : 'Open retailer verification'}</button>
    {/if}
  {/if}
  {#if retailer.session_state === 'retained' && !verificationFailed}<small>Verification retained for up to 1 hour</small><button disabled={actionPending || Boolean(activeRetailerId)} on:click={() => perform(forgetSession)}>Forget verification</button>{/if}
  {#if actionError}<small class="action-error" role="alert">{actionError}</small>{/if}</span>
</div>
<style>div{min-width:0;background:#e8e7e1;padding:12px 13px;display:flex;gap:10px;font-size:13px;border-radius:2px}span:first-child{font-weight:900}small{display:block;color:#68736d;margin-top:4px;font-size:12px;line-height:1.35;overflow-wrap:anywhere}button{display:inline-block;margin:7px 10px 0 0;color:#174b36;background:transparent;border:0;padding:0;font-size:12px;font-weight:800;cursor:pointer}button:disabled{cursor:wait;opacity:.55}.action-error{color:#8c291b;font-weight:700}.done{background:#e3f2d4}.partial{background:#fff3cd;color:#856404;border:1px solid #ffc107}.error-state{background:#f7ddd7;color:#8c291b}.blocked{background:#f3e5bd;color:#694d00;border:1px dashed #b08c2f}</style>
