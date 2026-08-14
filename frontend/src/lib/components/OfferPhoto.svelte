<script lang="ts">export let imageUrl: string | null; export let alt: string;</script>
<div class="photo">{#if imageUrl}<img src={imageUrl} {alt} loading="lazy" />{:else}<span aria-hidden="true">◒</span>{/if}</div>
<style>.photo{display:flex;align-items:center;justify-content:center;background:#f0f0eb;overflow:hidden}.photo img{width:100%;height:100%;object-fit:contain}.photo span{font-size:58px;color:#bdc4be}@media(max-width:520px){.photo{min-height:120px}}</style>
