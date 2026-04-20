/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#f4f7fb",
          100: "#e6eef7",
          200: "#c5d6ea",
          300: "#9bb7d8",
          400: "#6c92c2",
          500: "#4673ad",
          600: "#365b91",
          700: "#2b4876",
          800: "#243c61",
          900: "#1f3251",
        },
      },
      fontFamily: {
        sans: ['"Inter"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: [
          '"JetBrains Mono"',
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      transitionDuration: {
        DEFAULT: "180ms",
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};
