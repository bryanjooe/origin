import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        paper: '#f1f0e9',
        forest: '#183a30',
        green: '#17684f',
        cyan: '#168c98',
        amber: '#a9622f',
        critical: '#a9433d',
      },
      fontFamily: {
        sans: ['Avenir Next', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['SFMono-Regular', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config
