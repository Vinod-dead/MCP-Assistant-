/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0a0c12", panel: "#10131c", panel2: "#151a26", line: "#232a3b", ink: "#e7eaf3", mute: "#8a93a8",
        accent: { DEFAULT: "#5b8cff", soft: "#5b8cff22" }, violet: { DEFAULT: "#8b7bff" },
        ok: "#34d399", warn: "#fbbf24", bad: "#f87171",
      },
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"], mono: ["JetBrains Mono", "ui-monospace", "Cascadia Code", "Consolas", "monospace"] },
      boxShadow: { glow: "0 0 0 1px #5b8cff33, 0 8px 30px -12px #5b8cff55" },
    },
  },
  plugins: [],
};
