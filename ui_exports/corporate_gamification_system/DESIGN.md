---
name: Corporate Gamification System
colors:
  surface: '#f6fafd'
  surface-dim: '#d6dbdd'
  surface-bright: '#f6fafd'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f0f4f7'
  surface-container: '#eaeef1'
  surface-container-high: '#e5e9ec'
  surface-container-highest: '#dfe3e6'
  on-surface: '#171c1f'
  on-surface-variant: '#404750'
  inverse-surface: '#2c3134'
  inverse-on-surface: '#edf1f4'
  outline: '#707881'
  outline-variant: '#c0c7d1'
  surface-tint: '#00639a'
  primary: '#005787'
  on-primary: '#ffffff'
  primary-container: '#0070ad'
  on-primary-container: '#e0eeff'
  inverse-primary: '#95ccff'
  secondary: '#00658c'
  on-secondary: '#ffffff'
  secondary-container: '#2abcfd'
  on-secondary-container: '#004966'
  tertiary: '#255f00'
  on-tertiary: '#ffffff'
  tertiary-container: '#327a00'
  on-tertiary-container: '#bbff92'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#cde5ff'
  primary-fixed-dim: '#95ccff'
  on-primary-fixed: '#001d32'
  on-primary-fixed-variant: '#004a75'
  secondary-fixed: '#c5e7ff'
  secondary-fixed-dim: '#80d0ff'
  on-secondary-fixed: '#001e2d'
  on-secondary-fixed-variant: '#004c6a'
  tertiary-fixed: '#87fe45'
  tertiary-fixed-dim: '#6be026'
  on-tertiary-fixed: '#082100'
  on-tertiary-fixed-variant: '#1f5100'
  background: '#f6fafd'
  on-background: '#171c1f'
  surface-variant: '#dfe3e6'
typography:
  display-lg:
    fontFamily: Hanken Grotesk
    fontSize: 48px
    fontWeight: '800'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Hanken Grotesk
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
  headline-lg-mobile:
    fontFamily: Hanken Grotesk
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
  headline-md:
    fontFamily: Hanken Grotesk
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
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
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: 0.05em
  stats-number:
    fontFamily: Hanken Grotesk
    fontSize: 24px
    fontWeight: '800'
    lineHeight: 24px
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
  margin-mobile: 16px
  margin-desktop: 40px
  card-gap: 20px
---

## Brand & Style

This design system establishes a "Corporate Gamification" aesthetic: a hybrid that balances the high-stakes reliability of enterprise SaaS with the dopamine-driven engagement of language learning apps. It is designed for professionals who value efficiency but are motivated by social proof, streaks, and visible progression.

The visual style is **Corporate Modern with Tactile Accents**. It utilizes the clean, high-white-space layout of modern learning management systems but injects personality through "squishy" buttons, vibrant reward states, and a layered card architecture. The goal is to make professional upskilling feel less like a chore and more like a rewarding daily ritual.

## Colors

The palette is rooted in professional blues to maintain institutional trust, while secondary and accent colors are reserved for gamified interactions.

- **Primary Blue (#0070ad):** Used for navigation, headers, and primary actions. It represents the "Corporate" foundation.
- **Secondary Cyan (#00b0f0):** Used for progress bars and active states. It provides a more energetic, digital-first feel.
- **Success Green (#58cc02):** Borrowed from high-engagement paradigms, this is used exclusively for "Lesson Complete" states and correct answers.
- **Gamification Accents:** XP (Gold), Streaks (Orange), and Badges (Purple) use high-vibrancy hues to differentiate reward feedback from functional UI.
- **Neutral Palette:** High-lightness grays with a slight blue tint ensure the interface feels airy and clean, similar to the Google Skills reference.

## Typography

The typographic hierarchy distinguishes between *Content* and *Data*.

- **Headlines (Hanken Grotesk):** A sharp, contemporary sans-serif that feels both professional and modern. Bold weights are used for achievement titles and module headers.
- **Body (Inter):** The industry standard for readability in SaaS. Used for course descriptions and instructional text.
- **Labels & Data (JetBrains Mono):** A monospaced font used for "Technical XP" values, time-to-complete, and metadata labels, reinforcing a sense of precision and skill-building.
- **Scaling:** On mobile, display sizes are capped to ensure progress dashboards remain glanceable without excessive scrolling.

## Layout & Spacing

The layout utilizes a **Fixed Grid** on desktop (1200px max-width) and a **Fluid Single Column** on mobile. 

- **The Dashboard Grid:** Uses a 12-column system. Primary learning content (The "Path") spans 8 columns, while gamification sidebars (Streaks, XP Leaderboards) span 4 columns.
- **Rhythm:** An 8px base unit drives all spacing. 24px gutters provide enough "breath" to prevent the dense card-based UI from feeling cluttered.
- **Mobile Reflow:** On mobile, the gamification sidebar transforms into a "Top Stats Bar" that sticks to the header, keeping motivational triggers visible during active learning.

## Elevation & Depth

Hierarchy is achieved through **Tonal Layers** and **Tactile Shadows**.

- **Level 0 (Background):** The neutral background (#f0f4f7) acts as the canvas.
- **Level 1 (Cards):** White surfaces with a soft, 1px border (#e0e6ed) and no shadow. This mimics the clean Google Skills layout.
- **Level 2 (Interactive/Gamified):** Elements like "Current Lesson" or "Claim Reward" use a "thick-border" bottom shadow (2px or 4px) in a darker shade of the element's color. This creates the "squishy" physical feel characteristic of gamified interfaces, making buttons feel satisfying to click.
- **Overlays:** Modals for badge reveals use a high-blur ambient shadow (24px blur, 10% opacity) to focus the user's attention on the achievement.

## Shapes

The design system uses **Rounded (0.5rem base)** geometry. 

- **Standard Cards:** 1rem (`rounded-lg`) corner radius to soften the corporate data and make it feel approachable.
- **Progress Paths:** Circular nodes (pill-shaped) for lesson icons, following the Duolingo "stepping stone" metaphor.
- **Buttons:** 0.5rem radius for standard actions, but "XP Boost" or "Start Lesson" buttons may use a full pill-shape to signal a higher priority, more "fun" interaction.

## Components

### Buttons
- **Primary:** Solid #0070ad with a 2px darker bottom-border. Text is white Hanken Grotesk.
- **Gamified:** Solid #58cc02 (Success Green) for "Finish" or "Continue" actions to reinforce positive completion.

### Learning Cards
- Cards feature a top-heavy layout. A small "Label-md" category tag at the top-left, a "Headline-md" title, and a "Secondary Cyan" horizontal progress bar at the very bottom edge of the card.

### Gamification Indicators
- **Streak Flame:** An icon-text pair using `accent_streak_hex`. In the header, it should have a subtle "pulse" animation if the user has not yet completed their daily goal.
- **XP Chips:** Small, pill-shaped containers with a gold background (#ffc800) and black JetBrains Mono text for numerical values.

### Progress Paths
- A vertical or serpentine arrangement of circular lesson nodes. Completed nodes are solid Primary Blue; the current node is Secondary Cyan with a white concentric ring; locked nodes are light gray.

### Input Fields
- Clean, white backgrounds with 1px neutral borders. On focus, the border transitions to Primary Blue with a 2px thickness to emphasize the "active task" state.