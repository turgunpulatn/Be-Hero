/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "system-ui", "sans-serif"] },
      colors: {
        bg: "#F8F8F4",
        panel: "#EEF0FA",
        "panel-strong": "#E2E6F8",
        ink: "#2F3D4C",
        muted: "#6B7280",
        line: "#D9DDEB",
        primary: { DEFAULT: "#5568C9", dark: "#4456B5" },
        danger: { DEFAULT: "#B42318", bg: "#FDECEA", line: "#E5806F" },
        warn: "#A15C07",
        ok: "#2F7D4F",
      },
    },
  },
  plugins: [],
};
