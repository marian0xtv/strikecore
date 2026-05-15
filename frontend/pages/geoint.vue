<script setup lang="ts">
definePageMeta({ title: 'GEOINT' })


const query = ref('')
const coords = reactive({ lat: '', lon: '' })
const result = ref<any>(null)
const loading = ref(false)
const toast = useToast()

async function search() {
  if (query.value) {
    loading.value = true
    try {
      const geo = await geocode(query.value)
      if (geo.lat) { coords.lat = geo.lat; coords.lon = geo.lon }
    } catch {}
    loading.value = false
  }
}

async function analyze() {
  if (!coords.lat || !coords.lon) return
  loading.value = true
  try {
    const res = await fetch(`/api/geoint?lat=${coords.lat}&lon=${coords.lon}`, {
      
    })
    result.value = await res.json()
  } catch (e: any) {
    toast.add({ title: 'Errore', description: e.message, color: 'red' })
  }
  loading.value = false
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-white">GEOINT</h1>
      <p class="text-sm text-gray-500 mt-1">Geospatial Intelligence — coordinate-based lookup</p>
    </div>

    <UCard class="bg-gray-900/50">
      <div class="grid grid-cols-3 gap-3">
        <UInput v-model="query" placeholder="Cerca luogo..." @keyup.enter="search" />
        <UInput v-model="coords.lat" placeholder="Latitudine" />
        <UInput v-model="coords.lon" placeholder="Longitudine" />
      </div>
      <div class="flex gap-2 mt-3">
        <UButton color="sky" variant="soft" :loading="loading" @click="search">Geocode</UButton>
        <UButton color="emerald" :loading="loading" @click="analyze">Analizza</UButton>
      </div>
    </UCard>

    <UCard v-if="result" class="bg-gray-900/50">
      <template #header>
        <h2 class="text-sm font-semibold text-emerald-400">Risultato GEOINT</h2>
      </template>
      <pre class="text-xs text-gray-300 font-mono whitespace-pre-wrap max-h-96 overflow-y-auto bg-gray-950 p-4 rounded-lg">{{ JSON.stringify(result, null, 2) }}</pre>
    </UCard>
  </div>
</template>
