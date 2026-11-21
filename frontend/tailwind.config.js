/** @type {import('tailwindcss').Config} */
// Tokens shared with the silue-dev portfolio: blue-tinted near-black, one amber accent.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Geist", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        canvas: "#0d1117",
        surface: "#151b23",
        raised: "#1c2430",
        line: "#262f3b",
        "line-strong": "#3a4554",
        ink: "#e6edf3",
        "ink-soft": "#9aa6b6",
        "ink-faint": "#7a8698",
        accent: "#F59E0B",
        "accent-hover": "#D97706",
        "on-accent": "#0d1117",
        ok: "#3fb950",
        bad: "#f85149",
      },
    },
  },
  plugins: [],
};
