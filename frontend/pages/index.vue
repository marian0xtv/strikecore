<script setup lang="ts">
definePageMeta({ title: 'Dashboard' })


// Fetch dashboard data from multiple endpoints
const { data: phonebook } = usePhonebook()
const { data: gwStatus } = useGatewayStatus()
const { data: tunnel } = useTunnelStatus()

// Investigations — fetch from page scrape or a known endpoint
const investigations = ref<any[]>([])
const stats = ref({ investigations: 0, phones: 0, emails: 0, profiles: 0 })

onMounted(async () => {
  try {
    // Fetch investigations list by scraping the store directory
    const res = await fetch(`/api/gateway/phonebook`, {
      
    })
    const data = await res.json()

    // Derive unique targets from phonebook
    const targets = new Set(data.phones?.map((p: any) => p.target) || [])
    stats.value.investigations = targets.size
    stats.value.phones = data.count || 0

    // Build investigations from unique targets
    investigations.value = Array.from(targets).map(t => ({ target: t }))
  } catch { }
})

const statCards = computed(() => [
  { label: 'Investigations', value: stats.value.investigations, icon: 'i-heroicons-magnifying-glass', color: 'text-sky-400' },
  { label: 'Phone Numbers', value: stats.value.phones, icon: 'i-heroicons-phone', color: 'text-purple-400' },
  { label: 'Call Results', value: gwStatus.value?.call_results_count || 0, icon: 'i-heroicons-signal', color: 'text-emerald-400' },
  { label: 'Active Trackers', value: 0, icon: 'i-heroicons-map-pin', color: 'text-red-400' },
])

const systemCards = computed(() => [
  { label: 'Asterisk PBX', ok: gwStatus.value?.asterisk?.running, onLabel: 'Online', offLabel: 'Offline' },
  { label: 'Twilio', ok: gwStatus.value?.twilio?.configured, onLabel: 'Configured', offLabel: 'Not Set' },
  { label: 'Tunnel', ok: tunnel.value?.running, onLabel: 'Active', offLabel: 'Off' },
])
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-white">Command Center</h1>
        <p class="text-sm text-gray-500 mt-1">StrikeCore C2 Intelligence Platform</p>
      </div>
      <UBadge color="emerald" variant="subtle">
        <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 mr-1.5 animate-pulse" />
        System Active
      </UBadge>
    </div>

    <!-- Stats Row -->
    <div class="grid grid-cols-4 gap-4">
      <UCard v-for="s in statCards" :key="s.label" class="bg-gray-900/50">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-xs text-gray-500">{{ s.label }}</p>
            <p class="text-2xl font-bold mt-1" :class="s.color">{{ s.value }}</p>
          </div>
          <UIcon :name="s.icon" class="w-8 h-8 text-gray-700" />
        </div>
      </UCard>
    </div>

    <!-- System Status + Quick Actions -->
    <div class="grid grid-cols-3 gap-4">
      <UCard v-for="sys in systemCards" :key="sys.label" class="bg-gray-900/50">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <span class="w-2.5 h-2.5 rounded-full" :class="sys.ok ? 'bg-emerald-400' : 'bg-red-400'" />
            <span class="text-sm text-gray-300">{{ sys.label }}</span>
          </div>
          <UBadge :color="sys.ok ? 'emerald' : 'red'" variant="subtle" size="xs">
            {{ sys.ok ? sys.onLabel : sys.offLabel }}
          </UBadge>
        </div>
      </UCard>
    </div>

    <!-- Recent Investigations -->
    <UCard class="bg-gray-900/50">
      <template #header>
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-semibold text-gray-300">Recent Investigations</h2>
          <UButton to="/investigations" variant="ghost" size="xs" trailing-icon="i-heroicons-arrow-right">
            View All
          </UButton>
        </div>
      </template>
      <div v-if="!investigations.length" class="text-center py-8 text-gray-600 text-sm">
        No investigations yet. Start one from the CLI.
      </div>
      <div v-else class="divide-y divide-gray-800">
        <NuxtLink
          v-for="inv in investigations.slice(0, 8)"
          :key="inv.target"
          :to="`/investigations/${inv.target}`"
          class="flex items-center justify-between py-3 px-1 hover:bg-gray-800/30 rounded transition-colors"
        >
          <div class="flex items-center gap-3">
            <UIcon name="i-heroicons-user-circle" class="w-5 h-5 text-gray-500" />
            <span class="text-sm text-gray-300">{{ inv.target }}</span>
          </div>
          <UIcon name="i-heroicons-chevron-right" class="w-4 h-4 text-gray-600" />
        </NuxtLink>
      </div>
    </UCard>

    <!-- Quick Actions -->
    <div class="grid grid-cols-4 gap-4">
      <UButton to="/gateway" block color="emerald" variant="soft" icon="i-heroicons-phone" class="justify-start">
        Gateway Telefonico
      </UButton>
      <UButton to="/tracking" block color="sky" variant="soft" icon="i-heroicons-map-pin" class="justify-start">
        IP Tracker
      </UButton>
      <UButton to="/email-tracker" block color="violet" variant="soft" icon="i-heroicons-envelope" class="justify-start">
        Email Tracker
      </UButton>
      <UButton to="/tasks" block color="amber" variant="soft" icon="i-heroicons-play" class="justify-start">
        Run Task
      </UButton>
    </div>
  </div>
</template>
