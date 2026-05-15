<script setup lang="ts">
definePageMeta({ title: 'Infrastructure' })


const { data: gwStatus } = useGatewayStatus()
const { data: tunnel } = useTunnelStatus()
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-white">Infrastructure</h1>
      <p class="text-sm text-gray-500 mt-1">Stato servizi e componenti</p>
    </div>

    <div class="grid grid-cols-3 gap-4">
      <UCard class="bg-gray-900/50">
        <div class="flex items-center justify-between mb-3">
          <span class="text-sm font-semibold text-white">Asterisk PBX</span>
          <UBadge :color="gwStatus?.asterisk?.running ? 'emerald' : 'red'" variant="subtle" size="xs">
            {{ gwStatus?.asterisk?.running ? 'Running' : 'Stopped' }}
          </UBadge>
        </div>
        <p class="text-xs text-gray-500">VoIP gateway per chiamate in uscita via SIP trunk.</p>
      </UCard>

      <UCard class="bg-gray-900/50">
        <div class="flex items-center justify-between mb-3">
          <span class="text-sm font-semibold text-white">Twilio</span>
          <UBadge :color="gwStatus?.twilio?.configured ? 'emerald' : 'amber'" variant="subtle" size="xs">
            {{ gwStatus?.twilio?.configured ? 'Configured' : 'Not Set' }}
          </UBadge>
        </div>
        <p class="text-xs text-gray-500">API programmabile per chiamate e SMS.</p>
      </UCard>

      <UCard class="bg-gray-900/50">
        <div class="flex items-center justify-between mb-3">
          <span class="text-sm font-semibold text-white">Cloudflare Tunnel</span>
          <UBadge :color="tunnel?.running ? 'emerald' : 'gray'" variant="subtle" size="xs">
            {{ tunnel?.running ? 'Active' : 'Off' }}
          </UBadge>
        </div>
        <p v-if="tunnel?.url" class="text-xs text-emerald-400 break-all">{{ tunnel.url }}</p>
        <p v-else class="text-xs text-gray-500">Espone la dashboard su internet tramite tunnel.</p>
      </UCard>
    </div>

    <UCard class="bg-gray-900/50">
      <template #header>
        <h2 class="text-sm font-semibold text-gray-300">Dashboard Flask</h2>
      </template>
      <p class="text-xs text-gray-500">
        Il backend Flask serve su <code class="text-emerald-400">{{ base }}</code>.
        Tutte le API, i tracking endpoint, e i route di redirect continuano a funzionare su Flask.
        Questo frontend Nuxt consuma le stesse API senza modifiche al backend.
      </p>
    </UCard>
  </div>
</template>
