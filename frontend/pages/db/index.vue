<script setup lang="ts">
definePageMeta({ title: 'Database' })

</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-white">Database Browser</h1>
      <p class="text-sm text-gray-500 mt-1">SQLite database explorer</p>
    </div>
    <UCard class="bg-gray-900/50">
      <p class="text-xs text-gray-500 text-center py-8">
        Database browser disponibile sulla dashboard Flask:
        <a :href="`/db`" target="_blank" class="text-emerald-400 hover:underline">/db</a>
      </p>
    </UCard>
  </div>
</template>
