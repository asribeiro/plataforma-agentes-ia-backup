const brand = {
  ink: '#111111',
  accent: '#E11D24',
  gray: '#E5E7EB',
  canvas: '#f7f7f7',
  white: '#ffffff',
};

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: [
    "./src/**/*.{js,jsx,ts,tsx}", // Legacy paths
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue', 'sans-serif'],
      },
      colors: {
        // Default brand palette
        brand: {
          DEFAULT: brand.ink,
          ink: brand.ink,
          accent: brand.accent,
          gray: brand.gray,
          canvas: brand.canvas,
          white: brand.white,
          50: brand.canvas,
          100: brand.gray,
          200: '#d1d5db',
          300: '#9ca3af',
          400: '#6b7280',
          500: '#4b5563',
          600: '#374151',
          700: '#1f2937',
          800: '#1a1a1a',
          900: '#161616',
          950: brand.ink,
          foreground: brand.white,
        },
        'brand-foreground': brand.white,

        // Primary now maps to the official brand ink.
        primary: {
          DEFAULT: brand.ink,
          50: brand.canvas,
          100: brand.gray,
          200: '#d1d5db',
          300: '#9ca3af',
          400: '#6b7280',
          500: '#4b5563',
          600: brand.ink,
          700: brand.ink,
          800: brand.ink,
          900: brand.ink,
          950: brand.ink,
          foreground: brand.white,
        },
        'primary-foreground': brand.white,

        // Secondary is a quiet light surface for neutral actions.
        secondary: {
          DEFAULT: brand.canvas,
          50: brand.white,
          100: brand.canvas,
          200: brand.gray,
          300: '#d1d5db',
          400: '#9ca3af',
          500: brand.canvas,
          600: '#d1d5db',
          700: '#6b7280',
          800: '#4b5563',
          900: brand.ink,
          foreground: brand.ink,
        },
        'secondary-foreground': brand.ink,

        // Destructive - Vermelho para ações perigosas
        destructive: {
          DEFAULT: 'var(--error)',
          foreground: brand.white,
        },
        'destructive-foreground': brand.white,

        // Accent is the subtle brand hover/focus surface.
        accent: {
          DEFAULT: brand.canvas,
          50: brand.white,
          100: brand.canvas,
          200: brand.gray,
          300: '#d1d5db',
          400: '#9ca3af',
          500: brand.canvas,
          600: brand.ink,
          700: brand.ink,
          800: brand.ink,
          900: brand.ink,
          foreground: brand.ink,
        },
        'accent-foreground': brand.ink,

        // Background e foreground gerais
        background: 'var(--surface-secondary)',
        foreground: 'var(--text-primary)',
        card: 'var(--surface-primary)',
        'card-foreground': 'var(--text-primary)',
        muted: 'var(--surface-secondary)',
        'muted-foreground': 'var(--text-secondary)',

        // Input e ring para focus states
        input: 'var(--border-default)',
        ring: 'var(--border-focus)',

        // Mist - official light background
        mist: brand.canvas,
        'card-border': 'var(--card-border)',
      },
      boxShadow: {
        flat: '0 1px 2px rgba(17, 17, 17, 0.06)',
        'flat-md': '0 8px 24px rgba(17, 17, 17, 0.08)',
        'flat-lg': '0 16px 40px rgba(17, 17, 17, 0.1)',
      },
    },
  },
  plugins: [],
};
