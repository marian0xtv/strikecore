<script setup lang="ts">
const route = useRoute()
const tid = route.params.id as string
definePageMeta({ title: 'Tracker Detail' })


const { data, refresh } = usePoll<any>(`/api/tracking/hits/${tid}`, 3000)
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center gap-3">
      <UButton to="/tracking" variant="ghost" icon="i-heroicons-arrow-left" size="xs" />
      <div>
        <h1 class="text-2xl font-bold text-white font-mono">{{ tid }}</h1>
        <p class="text-sm text-gray-500">Live tracking — polling ogni 3s</p>
      </div>
    </div>

    <div v-if="data" class="grid grid-cols-5 gap-4">
      <UCard class="bg-gray-900/50">
        <p class="text-xs text-gray-500">Total Hits</p>
        <p class="text-2xl font-bold text-cyan-400">{{ data.total }}</p>
      </UCard>
      <UCard class="bg-gray-900/50">
        <p class="text-xs text-gray-500">Unique IPs</p>
        <p class="text-2xl font-bold text-emerald-400">{{ data.unique_ips }}</p>
      </UCard>
      <UCard class="bg-gray-900/50">
        <p class="text-xs text-gray-500">Real Devices</p>
        <p class="text-2xl font-bold text-green-400">{{ data.real_devices }}</p>
      </UCard>
      <UCard class="bg-gray-900/50">
        <p class="text-xs text-gray-500">From Instagram</p>
        <p class="text-2xl font-bold text-pink-400">{{ data.ig_hits }}</p>
      </UCard>
      <UCard class="bg-gray-900/50">
        <p class="text-xs text-gray-500">GPS Fix</p>
        <p class="text-2xl font-bold" :class="data.has_gps ? 'text-emerald-400' : 'text-gray-600'">
          {{ data.has_gps ? 'YES' : 'No' }}
        </p>
      </UCard>
    </div>

    <UCard class="bg-gray-900/50">
      <p class="text-xs text-gray-500 text-center py-6">
        Per la mappa interattiva e il log completo degli hit, usa la vista Flask su
        <a :href="`/tracking/${tid}`" target="_blank" class="text-emerald-400 hover:underline">/tracking/{{ tid }}</a>
      </p>
    </UCard>
  </div>
</template>
