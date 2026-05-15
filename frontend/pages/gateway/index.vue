<script setup lang="ts">
definePageMeta({ title: 'Gateway Telefonico' })


const { data: phonebook, refresh: refreshPhonebook } = usePhonebook()
const { data: gwStatus } = useGatewayStatus()
const { data: tunnel } = useTunnelStatus()

// Dialpad state
const dialDisplay = ref('')
const callMethod = ref<'sniffer' | 'twilio' | 'asterisk'>('sniffer')

// Call sniffer results
const callResults = ref<any[]>([])

// Tracker data
const trackers = ref<any[]>([])
const newTracker = reactive({ label: '', dest: 'https://www.instagram.com' })
const createdTracker = ref<any>(null)

// Geo markers
const geoMarkers = ref<any[]>([])

// WA check state
const waResults = reactive<Record<string, string>>({})

const tab = ref(0)
const tabs = [
  { label: 'Rubrica', icon: 'i-heroicons-book-open' },
  { label: 'Pulsantiera', icon: 'i-heroicons-phone' },
  { label: 'Call Sniffer', icon: 'i-heroicons-signal' },
  { label: 'IP Tracker', icon: 'i-heroicons-map-pin' },
  { label: 'Geo Tracker', icon: 'i-heroicons-globe-alt' },
  { label: 'Setup', icon: 'i-heroicons-cog-6-tooth' },
]

const search = ref('')
const filteredPhones = computed(() => {
  const phones = phonebook.value?.phones || []
  if (!search.value) return phones
  const q = search.value.toLowerCase()
  return phones.filter((p: any) =>
    p.number.toLowerCase().includes(q) || p.target.toLowerCase().includes(q)
  )
})

// Dialpad functions
function dialPress(d: string) {
  if (d === '0' && !dialDisplay.value) { dialDisplay.value = '+'; return }
  dialDisplay.value += d
}
function dialBackspace() { dialDisplay.value = dialDisplay.value.slice(0, -1) }
function dialClear() { dialDisplay.value = '' }

const toast = useToast()

async function dialCall() {
  const num = dialDisplay.value
  if (!num) return

  if (callMethod.value === 'sniffer') {
    const label = num.replace(/[^0-9]/g, '')
    const cmd = `sudo call-sniffer -i wlp0s20f3 -t ${label} -d 90`
    await navigator.clipboard.writeText(cmd).catch(() => {})
    toast.add({ title: 'Comando copiato', description: cmd, color: 'emerald' })
    return
  }

  try {
    const res = await gatewayCall(num, callMethod.value)
    toast.add({ title: 'Chiamata avviata', description: `${res.status || 'OK'} → ${num}`, color: 'emerald' })
  } catch (e: any) {
    toast.add({ title: 'Errore', description: e.message, color: 'red' })
  }
}

function selectNumber(num: string) {
  dialDisplay.value = num
  tab.value = 1
}

async function waCheck(number: string) {
  const key = number.replace(/[^0-9]/g, '')
  waResults[key] = 'checking...'
  try {
    const res = await gatewayWaCheck(number)
    waResults[key] = res.registered ? 'yes' : 'no'
  } catch {
    waResults[key] = 'error'
  }
}

async function createNewTracker() {
  try {
    const res = await createTracker(newTracker.label, newTracker.dest)
    createdTracker.value = res
    toast.add({ title: 'Tracker creato', description: res.tracking_id, color: 'emerald' })
  } catch (e: any) {
    toast.add({ title: 'Errore', description: e.message, color: 'red' })
  }
}

// Load call results + trackers + geo on mount
onMounted(async () => {
  try {
    // Fetch by scraping the status endpoints
    const status = await fetch(`/api/gateway/status`, {
      
    }).then(r => r.json())
  } catch {}
})

const dialpadKeys = [
  ['1', ''], ['2', 'ABC'], ['3', 'DEF'],
  ['4', 'GHI'], ['5', 'JKL'], ['6', 'MNO'],
  ['7', 'PQRS'], ['8', 'TUV'], ['9', 'WXYZ'],
  ['*', ''], ['0', '+'], ['#', ''],
]

const phoneCols = [
  { key: 'number', label: 'Numero' },
  { key: 'target', label: 'Target' },
  { key: 'confidence', label: 'Conf.' },
  { key: 'sources', label: 'Fonti' },
  { key: 'wa', label: 'WhatsApp' },
  { key: 'actions', label: 'Azioni' },
]
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-white">Gateway Telefonico</h1>
        <p class="text-sm text-gray-500 mt-1">Rubrica, chiamate, sniffing, tracking</p>
      </div>
      <div class="flex gap-2">
        <UBadge :color="gwStatus?.asterisk?.running ? 'emerald' : 'red'" variant="subtle" size="xs">
          PBX {{ gwStatus?.asterisk?.running ? 'ON' : 'OFF' }}
        </UBadge>
        <UBadge :color="gwStatus?.twilio?.configured ? 'emerald' : 'amber'" variant="subtle" size="xs">
          Twilio {{ gwStatus?.twilio?.configured ? 'OK' : '?' }}
        </UBadge>
        <UBadge :color="tunnel?.running ? 'emerald' : 'gray'" variant="subtle" size="xs">
          Tunnel {{ tunnel?.running ? 'ON' : 'OFF' }}
        </UBadge>
      </div>
    </div>

    <!-- Tabs -->
    <UTabs v-model="tab" :items="tabs">
      <template #item="{ item, index }">

        <!-- ═══ RUBRICA ═══ -->
        <UCard v-if="index === 0" class="bg-gray-900/50 mt-4">
          <template #header>
            <div class="flex items-center justify-between">
              <h2 class="text-sm font-semibold text-gray-300">
                Rubrica Telefonica
                <UBadge color="purple" variant="subtle" size="xs" class="ml-2">{{ phonebook?.count || 0 }}</UBadge>
              </h2>
              <UInput v-model="search" icon="i-heroicons-magnifying-glass" placeholder="Cerca..." size="xs" class="w-48" />
            </div>
          </template>

          <UTable :rows="filteredPhones" :columns="phoneCols" :loading="!phonebook">
            <template #number-data="{ row }">
              <code class="text-purple-300 text-xs cursor-pointer hover:text-purple-200" @click="selectNumber(row.number)">
                {{ row.number }}
              </code>
            </template>
            <template #target-data="{ row }">
              <NuxtLink :to="`/investigations/${row.target}`" class="text-cyan-400 text-xs hover:underline">{{ row.target }}</NuxtLink>
            </template>
            <template #confidence-data="{ row }">
              <UBadge :color="row.confidence > 0.7 ? 'emerald' : row.confidence > 0.4 ? 'amber' : 'red'" variant="subtle" size="xs">
                {{ row.confidence?.toFixed(1) }}
              </UBadge>
            </template>
            <template #sources-data="{ row }">
              <span class="text-[10px] text-gray-500">{{ (row.sources || []).slice(0, 3).join(', ') }}</span>
            </template>
            <template #wa-data="{ row }">
              <template v-if="waResults[row.number?.replace(/[^0-9]/g, '')]">
                <UBadge v-if="waResults[row.number.replace(/[^0-9]/g, '')] === 'yes'" color="emerald" variant="subtle" size="xs">WA</UBadge>
                <UBadge v-else-if="waResults[row.number.replace(/[^0-9]/g, '')] === 'checking...'" color="amber" variant="subtle" size="xs">...</UBadge>
                <UBadge v-else color="gray" variant="subtle" size="xs">No</UBadge>
              </template>
              <span v-else class="text-gray-600 text-xs">-</span>
            </template>
            <template #actions-data="{ row }">
              <div class="flex gap-1">
                <UButton size="2xs" color="emerald" variant="ghost" icon="i-heroicons-phone" @click="selectNumber(row.number)" />
                <UButton size="2xs" color="red" variant="ghost" icon="i-heroicons-signal" @click="() => { const l = row.number.replace(/[^0-9]/g,''); navigator.clipboard.writeText(`sudo call-sniffer -i wlp0s20f3 -t ${l} -d 90`); toast.add({title:'Cmd copiato',color:'emerald'}) }" />
                <UButton size="2xs" color="sky" variant="ghost" label="WA" @click="waCheck(row.number)" />
              </div>
            </template>
          </UTable>
        </UCard>

        <!-- ═══ PULSANTIERA ═══ -->
        <div v-if="index === 1" class="mt-4 grid grid-cols-2 gap-6">
          <UCard class="bg-gray-900/50">
            <template #header>
              <h2 class="text-sm font-semibold text-gray-300">Dialpad</h2>
            </template>

            <!-- Display -->
            <div class="bg-gray-950 border border-gray-800 rounded-lg px-4 py-3 mb-4 text-center">
              <span class="text-2xl font-mono text-white tracking-wider">{{ dialDisplay || '+39...' }}</span>
            </div>

            <!-- Keys -->
            <div class="grid grid-cols-3 gap-2 max-w-xs mx-auto">
              <button
                v-for="[key, sub] in dialpadKeys"
                :key="key"
                class="h-14 rounded-lg bg-gray-800/50 border border-gray-700/50 hover:bg-gray-700/50 active:scale-95 transition-all flex flex-col items-center justify-center"
                @click="dialPress(key)"
              >
                <span class="text-lg text-white font-medium">{{ key }}</span>
                <span v-if="sub" class="text-[8px] text-gray-500">{{ sub }}</span>
              </button>
            </div>

            <!-- Action row -->
            <div class="grid grid-cols-3 gap-2 max-w-xs mx-auto mt-2">
              <UButton block color="gray" variant="soft" icon="i-heroicons-backspace" @click="dialBackspace" />
              <UButton block color="emerald" icon="i-heroicons-phone" @click="dialCall" />
              <UButton block color="red" variant="soft" label="CLR" @click="dialClear" />
            </div>

            <!-- Method selector -->
            <div class="mt-4 space-y-2">
              <p class="text-[10px] text-gray-500 uppercase font-semibold">Metodo</p>
              <URadioGroup
                v-model="callMethod"
                :options="[
                  { label: 'Call Sniffer (P2P)', value: 'sniffer' },
                  { label: 'Twilio API', value: 'twilio' },
                  { label: 'Asterisk PBX', value: 'asterisk' },
                ]"
                size="xs"
              />
            </div>
          </UCard>

          <!-- Quick dial -->
          <UCard class="bg-gray-900/50">
            <template #header>
              <h2 class="text-sm font-semibold text-gray-300">Numeri Rapidi</h2>
            </template>
            <div class="space-y-1">
              <button
                v-for="p in (phonebook?.phones || []).slice(0, 12)"
                :key="p.number"
                class="w-full flex items-center justify-between px-3 py-2 rounded-md hover:bg-gray-800/50 transition-colors"
                @click="selectNumber(p.number)"
              >
                <div>
                  <code class="text-purple-300 text-xs">{{ p.number }}</code>
                  <span class="text-gray-500 text-[10px] ml-2">{{ p.target }}</span>
                </div>
                <UIcon name="i-heroicons-phone" class="w-4 h-4 text-emerald-500" />
              </button>
              <div v-if="!phonebook?.phones?.length" class="text-center py-6 text-gray-600 text-xs">
                Nessun contatto in rubrica.
              </div>
            </div>
          </UCard>
        </div>

        <!-- ═══ CALL SNIFFER ═══ -->
        <UCard v-if="index === 2" class="bg-gray-900/50 mt-4">
          <template #header>
            <div class="flex items-center justify-between">
              <h2 class="text-sm font-semibold text-gray-300">Call Sniffer Results</h2>
              <code class="text-[10px] text-emerald-400 bg-gray-950 px-2 py-1 rounded">sudo call-sniffer -i wlp0s20f3 -t TARGET -d 90</code>
            </div>
          </template>
          <div class="bg-gray-950 rounded-lg p-3 mb-4 text-xs text-gray-500">
            <strong class="text-gray-400">Come funziona:</strong> WhatsApp, Telegram e Instagram usano UDP P2P per le chiamate vocali.
            L'IP pubblico del target viene rivelato nei STUN binding request. Il sniffer cattura questo traffico,
            filtra i server delle piattaforme, assegna un punteggio ai candidati e geolocalizza il risultato migliore.
          </div>
          <div class="text-center py-8 text-gray-600 text-sm">
            I risultati delle catture appaiono qui automaticamente.<br>
            Avvia <code class="text-emerald-400">call-sniffer</code> dal terminale durante una chiamata.
          </div>
        </UCard>

        <!-- ═══ IP TRACKER ═══ -->
        <div v-if="index === 3" class="mt-4 space-y-4">
          <!-- Create tracker -->
          <UCard class="bg-gray-900/50">
            <template #header>
              <div class="flex items-center justify-between">
                <h2 class="text-sm font-semibold text-gray-300">Crea Tracking Link</h2>
                <NuxtLink to="/tracking" class="text-xs text-emerald-400 hover:underline">Pagina completa &rarr;</NuxtLink>
              </div>
            </template>
            <div class="flex gap-2">
              <UInput v-model="newTracker.label" placeholder="Label (es. target_mario)" size="sm" class="flex-1" />
              <UInput v-model="newTracker.dest" placeholder="URL destinazione" size="sm" class="flex-1" />
              <UButton color="red" size="sm" @click="createNewTracker">Genera</UButton>
            </div>
            <div v-if="createdTracker" class="mt-3 grid grid-cols-2 gap-2">
              <div class="bg-gray-950 rounded p-2">
                <span class="text-emerald-400 text-[10px] font-semibold">Reel</span>
                <code class="block text-emerald-300 text-[10px] break-all mt-0.5">{{ createdTracker.links?.short_redirect }}</code>
              </div>
              <div class="bg-gray-950 rounded p-2">
                <span class="text-sky-400 text-[10px] font-semibold">GeoLocate</span>
                <code class="block text-sky-300 text-[10px] break-all mt-0.5">{{ createdTracker.links?.geo_locate }}</code>
              </div>
              <div class="bg-gray-950 rounded p-2">
                <span class="text-violet-400 text-[10px] font-semibold">Preview</span>
                <code class="block text-violet-300 text-[10px] break-all mt-0.5">{{ createdTracker.links?.link_preview }}</code>
              </div>
              <div class="bg-gray-950 rounded p-2">
                <span class="text-amber-400 text-[10px] font-semibold">Pixel</span>
                <code class="block text-amber-300 text-[10px] break-all mt-0.5">{{ createdTracker.links?.pixel }}</code>
              </div>
            </div>
          </UCard>
        </div>

        <!-- ═══ GEO TRACKER ═══ -->
        <UCard v-if="index === 4" class="bg-gray-900/50 mt-4">
          <template #header>
            <h2 class="text-sm font-semibold text-gray-300">Geo Tracker</h2>
          </template>
          <div id="geomap" class="h-[500px] rounded-lg bg-gray-950" />
          <div class="flex gap-4 mt-3 text-[10px]">
            <div class="flex items-center gap-1"><span class="w-3 h-3 rounded-full bg-pink-500" /> Call Sniffer</div>
            <div class="flex items-center gap-1"><span class="w-3 h-3 rounded-full bg-cyan-400" /> IP Tracker</div>
            <div class="flex items-center gap-1"><span class="w-3 h-3 rounded-full bg-emerald-400" /> GPS Precision</div>
          </div>
        </UCard>

        <!-- ═══ SETUP ═══ -->
        <div v-if="index === 5" class="mt-4 grid grid-cols-3 gap-4">
          <UCard class="bg-gray-900/50">
            <template #header>
              <div class="flex items-center justify-between">
                <span class="text-sm font-semibold text-red-400">Asterisk PBX</span>
                <UBadge :color="gwStatus?.asterisk?.running ? 'emerald' : 'red'" variant="subtle" size="xs">
                  {{ gwStatus?.asterisk?.running ? 'ONLINE' : 'OFFLINE' }}
                </UBadge>
              </div>
            </template>
            <div class="space-y-2 text-xs text-gray-500">
              <p>SIP trunk per chiamate in uscita con auto-PCAP.</p>
              <code class="block bg-gray-950 p-2 rounded text-emerald-300 text-[10px]">cd ~/strikecore/voip && podman-compose up -d</code>
            </div>
          </UCard>

          <UCard class="bg-gray-900/50">
            <template #header>
              <div class="flex items-center justify-between">
                <span class="text-sm font-semibold text-sky-400">Twilio Bridge</span>
                <UBadge :color="gwStatus?.twilio?.configured ? 'emerald' : 'amber'" variant="subtle" size="xs">
                  {{ gwStatus?.twilio?.configured ? 'OK' : 'NOT SET' }}
                </UBadge>
              </div>
            </template>
            <div class="space-y-2 text-xs text-gray-500">
              <p>Chiamate programmabili via API REST.</p>
              <code class="block bg-gray-950 p-2 rounded text-emerald-300 text-[10px] whitespace-pre">echo 'TWILIO_SID=ACxxxx' >> ~/.strikecore/twilio.env
echo 'TWILIO_TOKEN=xxxx' >> ~/.strikecore/twilio.env
echo 'TWILIO_FROM=+39xxx' >> ~/.strikecore/twilio.env</code>
            </div>
          </UCard>

          <UCard class="bg-gray-900/50">
            <template #header>
              <div class="flex items-center justify-between">
                <span class="text-sm font-semibold text-emerald-400">Call Sniffer</span>
                <UBadge color="emerald" variant="subtle" size="xs">READY</UBadge>
              </div>
            </template>
            <div class="space-y-2 text-xs text-gray-500">
              <p>Cattura passiva P2P durante chiamate WhatsApp/Telegram.</p>
              <code class="block bg-gray-950 p-2 rounded text-emerald-300 text-[10px]">sudo call-sniffer -i wlp0s20f3 -t TARGET -d 90</code>
              <code class="block bg-gray-950 p-2 rounded text-emerald-300 text-[10px]">sudo call-sniffer -i wlp0s20f3 -t TARGET --continuous</code>
            </div>
          </UCard>
        </div>

      </template>
    </UTabs>
  </div>
</template>
