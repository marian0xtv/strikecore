<script setup lang="ts">
definePageMeta({ title: 'Sub-Agents' })

const agents = [
  { name: 'recon', desc: 'Reconnaissance & OSINT discovery', color: 'emerald' },
  { name: 'webapp', desc: 'Web application analysis', color: 'sky' },
  { name: 'bugbounty', desc: 'Bug bounty automation', color: 'amber' },
  { name: 'ctf', desc: 'CTF challenge solver', color: 'purple' },
  { name: 'cloud', desc: 'Cloud infrastructure recon', color: 'cyan' },
  { name: 'binary', desc: 'Binary analysis & reverse eng.', color: 'red' },
  { name: 'osint', desc: 'Open source intelligence', color: 'green' },
  { name: 'socint', desc: 'Social intelligence gathering', color: 'pink' },
  { name: 'geoint', desc: 'Geospatial intelligence', color: 'orange' },
]
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-white">Sub-Agents</h1>
      <p class="text-sm text-gray-500 mt-1">{{ agents.length }} specialized agents available</p>
    </div>

    <div class="grid grid-cols-3 gap-4">
      <UCard v-for="a in agents" :key="a.name" class="bg-gray-900/50">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center gap-2">
            <UIcon name="i-heroicons-cpu-chip" class="w-5 h-5" :class="`text-${a.color}-400`" />
            <span class="text-sm font-semibold text-white">{{ a.name }}</span>
          </div>
          <UBadge color="emerald" variant="subtle" size="xs">Ready</UBadge>
        </div>
        <p class="text-xs text-gray-500">{{ a.desc }}</p>
      </UCard>
    </div>
  </div>
</template>
