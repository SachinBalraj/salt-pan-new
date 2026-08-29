import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brine: {
          50: "#eefafc",
          100: "#d5f2f7",
          200: "#a9e4ef",
          300: "#7cd5e7",
          400: "#4cc4dc",
          500: "#24aecd",
          600: "#198ca8",
          700: "#146c84",
          800: "#11505f",
          900: "#0e3a45",
        },
        sun: {
          500: "#f59e0b",
          600: "#d97706",
        },
      },
    },
  },
  plugins: [],
};

export default config;