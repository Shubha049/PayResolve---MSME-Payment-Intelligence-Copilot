/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Manrope', 'ui-sans-serif', 'sans-serif'],
      },
      colors: {
        brand: {
          50:  '#eef5ff',
          100: '#dceaff',
          200: '#b9d4ff',
          300: '#82b4ff',
          400: '#4e8cf5',
          500: '#2563d8',
          600: '#1d4fb3',
          700: '#193f8f',
          800: '#183674',
          900: '#162f60',
        },
        coral: {
          50: '#fff2ef',
          100: '#ffe1db',
          700: '#c2412d',
        },
        surface: {
          900: '#f6f9fd',
          800: '#ffffff',
          700: '#e4ebf4',
          600: '#cfd9e7',
          500: '#a7b5c8',
          400: '#6c7d93',
          300: '#52647b',
          200: '#34465d',
          100: '#1e304a',
          50:  '#10233f',
        },
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
