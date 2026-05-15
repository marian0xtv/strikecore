<script setup lang="ts">
definePageMeta({ title: 'Email Tracker' })


const form = reactive({ email: '', subject: '', template: 'instagram_notification' })
const result = ref<any>(null)
const toast = useToast()

const templates = [
  { label: 'Instagram Tag', value: 'instagram_notification' },
  { label: 'LinkedIn Connect', value: 'linkedin_connection' },
  { label: 'Google Security', value: 'google_security' },
  { label: 'Package Delivery', value: 'delivery_notification' },
  { label: 'Plain Pixel', value: 'plain_pixel' },
]

async function generate() {
  try {
    result.value = await generateEmailTracker(form.email, form.subject, form.template)
    toast.add({ title: 'Email tracker generato', color: 'emerald' })
  } catch (e: any) {
    toast.add({ title: 'Errore', description: e.message, color: 'red' })
  }
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-white">Email Tracker</h1>
      <p class="text-sm text-gray-500 mt-1">Zero-click IP logging via tracking pixel in email</p>
    </div>

    <UCard class="bg-gray-900/50">
      <template #header>
        <h2 class="text-sm font-semibold text-red-400">Genera Tracking Email</h2>
      </template>
      <div class="space-y-3">
        <UInput v-model="form.email" placeholder="Email del target" icon="i-heroicons-envelope" />
        <UInput v-model="form.subject" placeholder="Subject line" />
        <USelectMenu v-model="form.template" :options="templates" value-attribute="value" option-attribute="label" placeholder="Template" />
        <UButton color="red" block @click="generate">Genera Email</UButton>
      </div>
      <div v-if="result" class="mt-4 bg-gray-950 rounded-lg p-3 space-y-2 text-xs">
        <div>Tracking ID: <code class="text-cyan-400">{{ result.tracking_id }}</code></div>
        <div v-if="result.preview_url">
          <a :href="`${base}${result.preview_url}`" target="_blank" class="text-emerald-400 hover:underline">Preview email</a>
        </div>
      </div>
    </UCard>
  </div>
</template>
