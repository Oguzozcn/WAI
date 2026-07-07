---
name: Corporate Gamification System (Dark Mode)
colors:
  surface: '#0b1326'
  surface-dim: '#0b1326'
  surface-bright: '#31394d'
  surface-container-lowest: '#060e20'
  surface-container-low: '#131b2e'
  surface-container: '#171f33'
  surface-container-high: '#222a3d'
  surface-container-highest: '#2d3449'
  on-surface: '#dae2fd'
  on-surface-variant: '#bdc8d1'
  inverse-surface: '#dae2fd'
  inverse-on-surface: '#283044'
  outline: '#87929a'
  outline-variant: '#3e484f'
  surface-tint: '#7bd0ff'
  primary: '#8ed5ff'
  on-primary: '#00354a'
  primary-container: '#38bdf8'
  on-primary-container: '#004965'
  inverse-primary: '#00668a'
  secondary: '#bcc7de'
  on-secondary: '#263143'
  secondary-container: '#3e495d'
  on-secondary-container: '#aeb9d0'
  tertiary: '#98d3ff'
  on-tertiary: '#00344d'
  tertiary-container: '#43bbff'
  on-tertiary-container: '#00486a'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#c4e7ff'
  primary-fixed-dim: '#7bd0ff'
  on-primary-fixed: '#001e2c'
  on-primary-fixed-variant: '#004c69'
  secondary-fixed: '#d8e3fb'
  secondary-fixed-dim: '#bcc7de'
  on-secondary-fixed: '#111c2d'
  on-secondary-fixed-variant: '#3c475a'
  tertiary-fixed: '#c9e6ff'
  tertiary-fixed-dim: '#89ceff'
  on-tertiary-fixed: '#001e2f'
  on-tertiary-fixed-variant: '#004c6e'
  background: '#0b1326'
  on-background: '#dae2fd'
  surface-variant: '#2d3449'
typography:
  headline-xl:
    fontFamily: Hanken Grotesk
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Hanken Grotesk
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Hanken Grotesk
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  gutter: 24px
  margin-desktop: 48px
  margin-mobile: 16px
  container-max: 1440px
---

## Brand & Style
The design system focuses on a professional, high-performance environment where gamification is an additive layer rather than a distraction. The aesthetic is **Corporate Modern** with a lean toward **Minimalism**, utilizing dark surfaces to reduce eye strain and emphasize critical progress indicators. 

The target audience consists of enterprise employees and managers. The UI evokes a sense of focus, achievement, and technological sophistication. It balances "serious work" with "rewarding play" through high-contrast typography and subtle glassmorphism to signify depth and priority.

## Colors
The palette is built on a foundation of deep navy and charcoal. 
- **Primary Surface (#0f172a):** Used for the main application background.
- **Surface-1 (#1e293b):** Used for primary containers, sidebars, and cards.
- **Surface-2 (#334155):** Used for elevated elements like tooltips and active states.
- **Primary Accent (#38bdf8):** A slightly desaturated and brightened version of the corporate blue, optimized for legibility and vibrance against dark backgrounds.
- **Text:** Headings utilize near-white for maximum impact, while body text uses a softer slate to maintain readability over long periods.

## Typography
The typography system uses **Hanken Grotesk** for headings to provide a sharp, contemporary professional feel. **Inter** serves as the body typeface for its exceptional legibility in data-heavy environments. **JetBrains Mono** is utilized for labels, badges, and "gamified" metrics (like XP counts or rankings) to provide a technical, precise character.

Large display headings should use tighter letter spacing for a more intentional, editorial look. Mobile headings are scaled down to ensure content density remains high without sacrificing hierarchy.

## Layout & Spacing
The design system employs a **Fluid Grid** model based on an 8px spacing rhythm. 
- **Desktop:** 12-column grid with 24px gutters. Use wide 48px margins to provide "breathing room" in a dark environment, preventing the UI from feeling claustrophobic.
- **Tablet:** 8-column grid with 16px gutters.
- **Mobile:** 4-column grid with 16px margins.

Spacing should prioritize vertical rhythm, using larger gaps (32px-48px) between distinct sections and tighter gaps (8px-16px) between related components like form inputs or list items.

## Elevation & Depth
In this dark mode system, depth is communicated through **Tonal Layers** and **Subtle Outlines** rather than heavy shadows.
- **Level 0 (Base):** The #0f172a background.
- **Level 1 (Cards):** #1e293b with a 1px solid border of #334155.
- **Level 2 (Popovers/Modals):** #334155 with a soft 10% black ambient shadow and a light top-edge highlight to simulate a light source.
- **Interactive States:** Use a primary-colored glow (inner shadow or drop shadow) to indicate "active" or "achievement" states, reflecting the gamification narrative.

## Shapes
The design system uses a **Rounded** shape language to soften the industrial nature of the corporate theme. 
- Standard components (buttons, inputs) use a **0.5rem (8px)** radius.
- Large containers and cards use a **1rem (16px)** radius.
- Progress bars and status badges should use **Full (Pill)** rounding to distinguish them as dynamic, gamified elements within the more rigid corporate structure.

## Components
- **Buttons:** Primary buttons use the accent blue (#38bdf8) with white text. Secondary buttons are outlined with a subtle slate-700 border and no fill.
- **Chips & Badges:** Use "JetBrains Mono" for badge text. Achievement badges should feature a subtle gradient background using the primary accent.
- **Input Fields:** Dark background (#0f172a) with a slate-700 border. On focus, the border transitions to the primary blue with a soft outer glow.
- **Cards:** Utilize the "Surface-1" color. Headers within cards should have a subtle bottom divider (#334155).
- **Progress Bars:** Use a high-contrast background (#1e293b) with the primary blue for the progress indicator. For "Epic" goals, use a gradient transition from primary blue to tertiary light blue.
- **Lists:** Use hover states that subtly lighten the background of the row to #334155 to provide immediate feedback.