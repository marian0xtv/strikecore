<script setup lang="ts">
const route = useRoute()
const tid = route.params.tid as string
definePageMeta({ title: 'Target Detail' })


const data = ref<any>(null)
const loading = ref(true)

onMounted(async () => {
  try {
    const res = await fetch(`/api/findings/${tid}`, {
      
    })
    data.value = await res.json()
  } catch { }
  loading.value = false
})

const emails = computed(() => {
  if (!data.value?.emails) return []
  return Object.entries(data.value.emails).map(([email, info]: [string, any]) => ({
    email,
    confidence: info?.confidence_score || 0.5,
    sources: (info?.sources || []).join(', '),
  }))
})

const phones = computed(() => {
  if (!data.value?.phones) return []
  return Object.entries(data.value.phones).map(([number, info]: [string, any]) => ({
    number,
    confidence: info?.confidence_score || 0.5,
    carrier: info?.carrier || '',
    sources: (info?.sources || []).join(', '),
  }))
})

const profiles = computed(() => {
  if (!data.value?.profiles) return []
  return Object.entries(data.value.profiles).map(([url, info]: [string, any]) => ({
    url,
    platform: info?.platform || url.split('/')[2] || '?',
    username: info?.username || '',
  }))
})

const tabs = computed(() => [
  { label: 'Overview', icon: 'i-heroicons-squares-2x2' },
  { label: `Emails (${emails.value.length})`, icon: 'i-heroicons-envelope' },
  { label: `Phones (${phones.value.length})`, icon: 'i-heroicons-phone' },
  { label: `Profiles (${profiles.value.length})`, icon: 'i-heroicons-user' },
])

const emailCols = [
  { key: 'email', label: 'Email' },
  { key: 'confidence', label: 'Confidence' },
  { key: 'sources', label: 'Sources' },
]

const phoneCols = [
  { key: 'number', label: 'Number' },
  { key: 'confidence', label: 'Confidence' },
  { key: 'carrier', label: 'Carrier' },
  { key: 'sources', label: 'Sources' },
]
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center gap-3">
      <UButton to="/investigations" variant="ghost" icon="i-heroicons-arrow-left" size="xs" />
      <div>
        <h1 class="text-2xl font-bold text-white font-mono">{{ tid }}</h1>
        <p class="text-sm text-gray-500 mt-1">Investigation detail</p>
      </div>
    </div>

    <div v-if="loading" class="text-center py-16 text-gray-500">Loading investigation data...</div>

    <template v-else-if="data">
      <!-- Stats -->
      <div class="grid grid-cols-4 gap-4">
        <UCard class="bg-gray-900/50">
          <p class="text-xs text-gray-500">Emails</p>
          <p class="text-xl font-bold text-sky-400">{{ emails.length }}</p>
        </UCard>
        <UCard class="bg-gray-900/50">
          <p class="text-xs text-gray-500">Phones</p>
          <p class="text-xl font-bold text-purple-400">{{ phones.length }}</p>
        </UCard>
        <UCard class="bg-gray-900/50">
          <p class="text-xs text-gray-500">Profiles</p>
          <p class="text-xl font-bold text-emerald-400">{{ profiles.length }}</p>
        </UCard>
        <UCard class="bg-gray-900/50">
          <p class="text-xs text-gray-500">Connections</p>
          <p class="text-xl font-bold text-amber-400">{{ Object.keys(data.connections || {}).length }}</p>
        </UCard>
      </div>

      <!-- Tabs -->
      <UTabs :items="tabs">
        <template #item="{ item }">
          <UCard class="bg-gray-900/50 mt-4">
            <!-- Overview -->
            <div v-if="item.label === 'Overview'" class="text-sm text-gray-400 space-y-2">
              <p v-if="data.summary">{{ data.summary }}</p>
              <p v-else>Investigation data loaded. Use the tabs above to browse findings.</p>
              <div class="mt-4 flex gap-2">
                <UButton :href="`/target/${tid}/graph`" target="_blank" variant="soft" size="xs" icon="i-heroicons-share">
                  Graph
                </UButton>
                <UButton :href="`/target/${tid}/report`" target="_blank" variant="soft" size="xs" icon="i-heroicons-document-text">
                  Report
                </UButton>
                <UButton :href="`/target/${tid}/map`" target="_blank" variant="soft" size="xs" icon="i-heroicons-map">
                  Map
                </UButton>
                <UButton :href="`/target/${tid}/timeline`" target="_blank" variant="soft" size="xs" icon="i-heroicons-clock">
                  Timeline
                </UButton>
              </div>
            </div>

            <!-- Emails -->
            <UTable v-if="item.label.startsWith('Emails')" :rows="emails" :columns="emailCols">
              <template #email-data="{ row }">
                <code class="text-sky-400 text-xs">{{ row.email }}</code>
              </template>
              <template #confidence-data="{ row }">
                <UBadge :color="row.confidence > 0.7 ? 'emerald' : row.confidence > 0.4 ? 'amber' : 'red'" variant="subtle" size="xs">
                  {{ row.confidence.toFixed(1) }}
                </UBadge>
              </template>
              <template #sources-data="{ row }">
                <span class="text-xs text-gray-500">{{ row.sources }}</span>
              </template>
            </UTable>

            <!-- Phones -->
            <UTable v-if="item.label.startsWith('Phones')" :rows="phones" :columns="phoneCols">
              <template #number-data="{ row }">
                <code class="text-purple-400 text-xs">{{ row.number }}</code>
              </template>
              <template #confidence-data="{ row }">
                <UBadge :color="row.confidence > 0.7 ? 'emerald' : row.confidence > 0.4 ? 'amber' : 'red'" variant="subtle" size="xs">
                  {{ row.confidence.toFixed(1) }}
                </UBadge>
              </template>
            </UTable>

            <!-- Profiles -->
            <div v-if="item.label.startsWith('Profiles')" class="divide-y divide-gray-800">
              <div v-for="p in profiles" :key="p.url" class="flex items-center justify-between py-2">
                <div>
                  <UBadge color="sky" variant="subtle" size="xs" class="mr-2">{{ p.platform }}</UBadge>
                  <span class="text-sm text-gray-300">{{ p.username }}</span>
                </div>
                <a :href="p.url" target="_blank" class="text-xs text-emerald-400 hover:underline">{{ p.url }}</a>
              </div>
            </div>
          </UCard>
        </template>
      </UTabs>
    </template>
  </div>
</template>
