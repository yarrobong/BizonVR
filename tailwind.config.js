/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',
    './catalog/templates/**/*.html',
    './accounts/templates/**/*.html',
    './orders/templates/**/*.html',
    './payments/templates/**/*.html',
  ],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'sans-serif'] },
      colors: {
        accent: '#00d4ff',
        'accent-hover': '#00b4e6',
        dark: { 900: '#111111', 800: '#1a1a1a', 700: '#252525', 600: '#333333' },
      },
    },
  },
  blocklist: ['pt-[var(--header-height)]'],
  safelist: ['md:flex'],
  plugins: [],
};
