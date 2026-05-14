/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "sans-serif"],
      },
      colors: {
        navy: "#0a0f1e",
        panel: "#0f172a",
        borderline: "#1e293b",
        accent: "#6366f1",
      },
    },
  },
  plugins: [],
};
