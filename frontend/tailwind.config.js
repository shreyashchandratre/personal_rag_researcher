/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["Fraunces", "Georgia", "serif"],
        sans: ["DM Sans", "system-ui", "sans-serif"],
      },
      colors: {
        ink: {
          950: "#0c0f14",
          900: "#121820",
          800: "#1a2230",
          700: "#243047",
        },
        ember: {
          400: "#e8a05c",
          500: "#d4853b",
          600: "#b86a28",
        },
        mist: "#8b9cb3",
      },
      boxShadow: {
        glow: "0 0 40px -10px rgba(212, 133, 59, 0.35)",
      },
    },
  },
  plugins: [],
};
