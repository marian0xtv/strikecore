export default defineNuxtConfig({
  modules: ['@nuxt/ui', '@pinia/nuxt', '@vueuse/nuxt'],

  ssr: false,

  app: {
    baseURL: '/ui/',
    head: {
      title: 'StrikeCore C2',
      meta: [
        { name: 'robots', content: 'noindex,nofollow' },
      ],
    },
  },

  colorMode: {
    preference: 'dark',
    fallback: 'dark',
  },

  ui: {
    icons: ['heroicons'],
  },

  runtimeConfig: {
    public: {
      apiBase: '/api',
    },
  },

  devtools: { enabled: false },

  compatibilityDate: '2025-01-01',
})
