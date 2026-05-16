/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg:    "#0a0d12",
        panel: "#11151c",
        line:  "#1d2330",
        text:  "#e6e9ef",
        muted: "#8a93a6",
        accent: "#7ab7ff",   // Hermes-ish blue
        good:  "#5ad19c",
        warn:  "#f0b440",
        bad:   "#f06973",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
