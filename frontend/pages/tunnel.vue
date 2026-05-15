<script setup lang="ts">
definePageMeta({ title: 'Tunnel' })

const { data: tunnel, refresh } = useTunnelStatus()
const toast = useToast()
const loading = ref(false)

async function start() {
  loading.value = true
  try { await tunnelStart(); await refresh(); toast.add({ title: 'Tunnel avviato', color: 'emerald' }) }
  catch (e: any) { toast.add({ title: 'Errore', description: e.message, color: 'red' }) }
  loading.value = false
}

async function stop() {
  loading.value = true
  try { await tunnelStop(); await refresh(); toast.add({ title: 'Tunnel fermato', color: 'amber' }) }
  catch (e: any) { toast.add({ title: 'Errore', description: e.message, color: 'red' }) }
  loading.value = false
}

async function restart() {
  loading.value = true
  try { await tunnelRestart(); await refresh(); toast.add({ title: 'Tunnel riavviato', color: 'emerald' }) }
  catch (e: any) { toast.add({ title: 'Errore', description: e.message, color: 'red' }) }
  loading.value = false
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-white">Cloudflare Tunnel</h1>
      <p class="text-sm text-gray-500 mt-1">Espone la dashboard e i tracking endpoint su internet</p>
    </div>

    <UCard class="bg-gray-900/50">
      <div class="flex items-center justify-between mb-4">
        <div class="flex items-center gap-3">
          <span class="w-3 h-3 rounded-full" :class="tunnel?.running ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'" />
          <span class="text-lg font-semibold text-white">{{ tunnel?.running ? 'Active' : 'Inactive' }}</span>
        </div>
        <div class="flex gap-2">
          <UButton v-if="!tunnel?.running" color="emerald" :loading="loading" @click="start">Start</UButton>
          <UButton v-if="tunnel?.running" color="amber" variant="soft" :loading="loading" @click="restart">Restart</UButton>
          <UButton v-if="tunnel?.running" color="red" variant="soft" :loading="loading" @click="stop">Stop</UButton>
        </div>
      </div>
      <div v-if="tunnel?.url" class="bg-gray-950 rounded-lg p-3">
        <p class="text-xs text-gray-500 mb-1">Public URL:</p>
        <code class="text-emerald-400 text-sm break-all">{{ tunnel.url }}</code>
      </div>
    </UCard>
  </div>
</template>
