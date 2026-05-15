<script setup lang="ts">
definePageMeta({ title: 'Investigations' })


const investigations = ref<any[]>([])
const loading = ref(true)

onMounted(async () => {
  try {
    const pb = await fetch(`/api/gateway/phonebook`, {
      
    }).then(r => r.json())

    const targetMap = new Map<string, any>()
    for (const p of pb.phones || []) {
      if (!targetMap.has(p.target)) {
        targetMap.set(p.target, { target: p.target, phones: 0, emails: 0 })
      }
      targetMap.get(p.target)!.phones++
    }
    investigations.value = Array.from(targetMap.values())
  } catch { }
  loading.value = false
})

const columns = [
  { key: 'target', label: 'Target' },
  { key: 'phones', label: 'Phones' },
  { key: 'actions', label: '' },
]
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-white">Investigations</h1>
        <p class="text-sm text-gray-500 mt-1">{{ investigations.length }} active targets</p>
      </div>
    </div>

    <UCard class="bg-gray-900/50">
      <UTable :rows="investigations" :columns="columns" :loading="loading">
        <template #target-data="{ row }">
          <NuxtLink :to="`/investigations/${row.target}`" class="text-emerald-400 hover:underline font-mono text-sm">
            {{ row.target }}
          </NuxtLink>
        </template>
        <template #phones-data="{ row }">
          <UBadge color="purple" variant="subtle" size="xs">{{ row.phones }}</UBadge>
        </template>
        <template #actions-data="{ row }">
          <UButton :to="`/investigations/${row.target}`" variant="ghost" size="xs" icon="i-heroicons-arrow-right" />
        </template>
      </UTable>
    </UCard>
  </div>
</template>
