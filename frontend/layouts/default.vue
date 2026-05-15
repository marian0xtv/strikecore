<script setup lang="ts">
const route = useRoute()

const mainNav = [
  { label: 'Dashboard', icon: 'i-heroicons-squares-2x2', to: '/' },
  { label: 'Investigations', icon: 'i-heroicons-magnifying-glass', to: '/investigations' },
  { label: 'Agents', icon: 'i-heroicons-cpu-chip', to: '/agents' },
  { label: 'GEOINT', icon: 'i-heroicons-globe-alt', to: '/geoint' },
]

const gatewayNav = [
  { label: 'Gateway', icon: 'i-heroicons-phone', to: '/gateway' },
  { label: 'IP Tracker', icon: 'i-heroicons-map-pin', to: '/tracking' },
  { label: 'Email Tracker', icon: 'i-heroicons-envelope', to: '/email-tracker' },
  { label: 'Tunnel', icon: 'i-heroicons-cloud', to: '/tunnel' },
]

const platformNav = [
  { label: 'Infrastructure', icon: 'i-heroicons-server', to: '/infrastructure' },
  { label: 'Tasks', icon: 'i-heroicons-play', to: '/tasks' },
  { label: 'Database', icon: 'i-heroicons-circle-stack', to: '/db' },
]

const sidebarOpen = ref(true)

const { data: gwStatus } = useGatewayStatus()
const { data: tunnel } = useTunnelStatus()
</script>

<template>
  <div class="flex h-screen bg-gray-950">
    <!-- Sidebar -->
    <aside
      class="flex flex-col border-r border-gray-800 bg-gray-950 transition-all duration-200"
      :class="sidebarOpen ? 'w-60' : 'w-16'"
    >
      <!-- Logo -->
      <div class="flex items-center gap-2 px-4 h-16 border-b border-gray-800 shrink-0">
        <span class="text-red-500 text-xl">&#9760;</span>
        <span v-if="sidebarOpen" class="text-white font-bold text-sm tracking-wider">STRIKECORE</span>
      </div>

      <!-- Navigation -->
      <nav class="flex-1 overflow-y-auto py-3 px-2 space-y-6">
        <!-- Main -->
        <div>
          <p v-if="sidebarOpen" class="px-3 mb-2 text-[10px] font-semibold text-gray-500 uppercase tracking-wider">Main</p>
          <ul class="space-y-0.5">
            <li v-for="item in mainNav" :key="item.to">
              <NuxtLink
                :to="item.to"
                class="flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors"
                :class="route.path === item.to || route.path.startsWith(item.to + '/')
                  ? 'bg-gray-800 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800/50'"
              >
                <UIcon :name="item.icon" class="w-5 h-5 shrink-0" />
                <span v-if="sidebarOpen">{{ item.label }}</span>
              </NuxtLink>
            </li>
          </ul>
        </div>

        <!-- Gateway Telefonico -->
        <div>
          <p v-if="sidebarOpen" class="px-3 mb-2 text-[10px] font-semibold text-red-500/60 uppercase tracking-wider">Gateway Telefonico</p>
          <ul class="space-y-0.5">
            <li v-for="item in gatewayNav" :key="item.to">
              <NuxtLink
                :to="item.to"
                class="flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors"
                :class="route.path === item.to || route.path.startsWith(item.to + '/')
                  ? 'bg-gray-800 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800/50'"
              >
                <UIcon :name="item.icon" class="w-5 h-5 shrink-0" />
                <span v-if="sidebarOpen">{{ item.label }}</span>
              </NuxtLink>
            </li>
          </ul>
        </div>

        <!-- Platform -->
        <div>
          <p v-if="sidebarOpen" class="px-3 mb-2 text-[10px] font-semibold text-gray-600 uppercase tracking-wider">Platform</p>
          <ul class="space-y-0.5">
            <li v-for="item in platformNav" :key="item.to">
              <NuxtLink
                :to="item.to"
                class="flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors"
                :class="route.path === item.to || route.path.startsWith(item.to + '/')
                  ? 'bg-gray-800 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800/50'"
              >
                <UIcon :name="item.icon" class="w-5 h-5 shrink-0" />
                <span v-if="sidebarOpen">{{ item.label }}</span>
              </NuxtLink>
            </li>
          </ul>
        </div>
      </nav>

      <!-- System Status Footer -->
      <div v-if="sidebarOpen" class="px-3 py-3 border-t border-gray-800 space-y-1 text-[10px] shrink-0">
        <div class="flex items-center gap-2">
          <span class="w-1.5 h-1.5 rounded-full" :class="tunnel?.running ? 'bg-emerald-400' : 'bg-red-400'" />
          <span class="text-gray-500">Tunnel: {{ tunnel?.running ? 'Active' : 'Off' }}</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="w-1.5 h-1.5 rounded-full" :class="gwStatus?.asterisk?.running ? 'bg-emerald-400' : 'bg-red-400'" />
          <span class="text-gray-500">PBX: {{ gwStatus?.asterisk?.running ? 'Online' : 'Offline' }}</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="w-1.5 h-1.5 rounded-full" :class="gwStatus?.twilio?.configured ? 'bg-emerald-400' : 'bg-yellow-400'" />
          <span class="text-gray-500">Twilio: {{ gwStatus?.twilio?.configured ? 'OK' : 'Not set' }}</span>
        </div>
      </div>

      <!-- Collapse toggle -->
      <button
        class="flex items-center justify-center h-10 border-t border-gray-800 text-gray-500 hover:text-white transition-colors"
        @click="sidebarOpen = !sidebarOpen"
      >
        <UIcon :name="sidebarOpen ? 'i-heroicons-chevron-left' : 'i-heroicons-chevron-right'" class="w-4 h-4" />
      </button>
    </aside>

    <!-- Main content -->
    <main class="flex-1 overflow-y-auto bg-gray-950">
      <!-- Top bar -->
      <header class="sticky top-0 z-30 flex items-center justify-between h-14 px-6 border-b border-gray-800 bg-gray-950/80 backdrop-blur-sm">
        <div class="text-sm font-medium text-white">
          {{ route.meta.title || 'StrikeCore C2' }}
        </div>
        <div class="flex items-center gap-3">
          <UBadge v-if="gwStatus?.phonebook_count" color="emerald" variant="subtle" size="xs">
            {{ gwStatus.phonebook_count }} contacts
          </UBadge>
          <UBadge v-if="gwStatus?.call_results_count" color="sky" variant="subtle" size="xs">
            {{ gwStatus.call_results_count }} calls
          </UBadge>
        </div>
      </header>

      <!-- Page content -->
      <div class="p-6">
        <slot />
      </div>
    </main>
  </div>
</template>
