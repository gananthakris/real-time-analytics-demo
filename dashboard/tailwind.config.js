/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        void:    '#080c10',
        surface: '#0d1420',
        panel:   '#111827',
        border:  '#1e2d3d',
        muted:   '#374151',
        dim:     '#6b7280',
        ghost:   '#9ca3af',
        text:    '#e2e8f0',
        amber:   { DEFAULT: '#f59e0b', light: '#fbbf24', dim: '#78350f' },
        cyan:    { DEFAULT: '#22d3ee', dim: '#164e63' },
        green:   { DEFAULT: '#10b981', dim: '#064e3b' },
        red:     { DEFAULT: '#f87171', dim: '#7f1d1d' },
      },
      fontFamily: {
        display: ['Syne', 'sans-serif'],
        mono:    ['JetBrains Mono', 'monospace'],
        sans:    ['DM Sans', 'sans-serif'],
      },
      animation: {
        'pulse-dot': 'pulse-dot 2s ease-in-out infinite',
        'fade-up':   'fade-up 0.4s ease both',
        'slide-in':  'slide-in 0.35s ease both',
        'glow':      'glow 3s ease-in-out infinite',
      },
      keyframes: {
        'pulse-dot': {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%':      { opacity: '0.4', transform: 'scale(0.85)' },
        },
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(12px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-in': {
          from: { opacity: '0', transform: 'translateX(-8px)' },
          to:   { opacity: '1', transform: 'translateX(0)' },
        },
        'glow': {
          '0%, 100%': { boxShadow: '0 0 12px 0 rgba(245,158,11,0.15)' },
          '50%':      { boxShadow: '0 0 24px 4px rgba(245,158,11,0.3)' },
        },
      },
    },
  },
  plugins: [],
}
