<script setup lang="ts">
definePageMeta({ title: 'Tasks' })


const command = ref('')
const output = ref('')
const running = ref(false)
const toast = useToast()

async function runCommand() {
  if (!command.value) return
  running.value = true
  output.value = ''
  try {
    const res = await execCommand(command.value)
    output.value = res.output || res.stdout || JSON.stringify(res, null, 2)
  } catch (e: any) {
    output.value = `Error: ${e.message}`
  }
  running.value = false
}

const templates = [
  { label: 'Username Hunt', cmd: 'investigate {target} with username_hunt' },
  { label: 'Email Intel', cmd: 'investigate {target} with email_intel' },
  { label: 'Phone Intel', cmd: 'investigate {target} with phone_intel' },
  { label: 'Social Scrape', cmd: 'investigate {target} with social_scrape' },
  { label: 'Breach Check', cmd: 'investigate {target} with breach_check' },
  { label: 'Deep Lookup', cmd: 'deep-lookup {target}' },
]
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-white">Task Dispatch</h1>
      <p class="text-sm text-gray-500 mt-1">Esegui comandi StrikeCore</p>
    </div>

    <!-- Command input -->
    <UCard class="bg-gray-900/50">
      <div class="flex gap-2">
        <UInput
          v-model="command"
          placeholder="Comando StrikeCore..."
          size="lg"
          class="flex-1 font-mono"
          @keyup.enter="runCommand"
        />
        <UButton color="emerald" size="lg" :loading="running" @click="runCommand" icon="i-heroicons-play">
          Run
        </UButton>
      </div>
    </UCard>

    <!-- Templates -->
    <div class="grid grid-cols-3 gap-3">
      <UButton
        v-for="t in templates"
        :key="t.label"
        variant="soft"
        color="gray"
        block
        class="justify-start"
        @click="command = t.cmd"
      >
        <UIcon name="i-heroicons-play" class="w-4 h-4 mr-2 text-emerald-400" />
        {{ t.label }}
      </UButton>
    </div>

    <!-- Output -->
    <UCard v-if="output" class="bg-gray-900/50">
      <template #header>
        <h2 class="text-sm font-semibold text-gray-300">Output</h2>
      </template>
      <pre class="text-xs text-gray-300 font-mono whitespace-pre-wrap max-h-96 overflow-y-auto bg-gray-950 p-4 rounded-lg">{{ output }}</pre>
    </UCard>
  </div>
</template>
