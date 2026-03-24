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
      screens: { '2xl': '1440px' },
      fontFamily: {
        sans: [
          'Onest',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
      },
      colors: {
        accent: {
          DEFAULT: '#00D4FF',
          hover: '#00B8E6',
          purple: '#9D00FF',
        },
        dark: {
          900: '#0B0D14',
          800: '#151923',
          700: '#1F2532',
          600: '#2A3042',
        },
      },
      boxShadow: {
        neon: '0 0 10px rgba(0, 212, 255, 0.5), 0 0 20px rgba(0, 212, 255, 0.3)',
        'neon-purple':
          '0 0 10px rgba(157, 0, 255, 0.5), 0 0 20px rgba(157, 0, 255, 0.3)',
        glass: '0 8px 32px 0 rgba(0, 0, 0, 0.37)',
      },
    },
  },
  blocklist: ['pt-[var(--header-height)]'],
  safelist: ['md:flex', 'lg:grid-cols-[minmax(500px,600px)_1fr]', '2xl:grid-cols-[620px_1fr]', 'top-[5rem]', 'top-[12rem]', 'h-[calc(100vh-5rem)]', 'h-[calc(100vh-12rem)]', 'hidden', 'lg:block', 'lg:hidden', '2xl:block', '2xl:hidden'],
  plugins: [],
};
