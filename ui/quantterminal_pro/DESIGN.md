---
name: QuantTerminal Pro
colors:
  surface: '#f8f9ff'
  surface-dim: '#d8dae1'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f3fa'
  surface-container: '#eceef4'
  surface-container-high: '#e6e8ef'
  surface-container-highest: '#e0e2e9'
  on-surface: '#181c21'
  on-surface-variant: '#414751'
  inverse-surface: '#2d3136'
  inverse-on-surface: '#eff0f7'
  outline: '#717782'
  outline-variant: '#c0c7d3'
  surface-tint: '#0061a5'
  primary: '#005ea1'
  on-primary: '#ffffff'
  primary-container: '#2178c3'
  on-primary-container: '#fdfcff'
  inverse-primary: '#9fcaff'
  secondary: '#585e6c'
  on-secondary: '#ffffff'
  secondary-container: '#dde2f3'
  on-secondary-container: '#5e6473'
  tertiary: '#864f00'
  on-tertiary: '#ffffff'
  tertiary-container: '#a96400'
  on-tertiary-container: '#fffbff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d2e4ff'
  primary-fixed-dim: '#9fcaff'
  on-primary-fixed: '#001d37'
  on-primary-fixed-variant: '#00497e'
  secondary-fixed: '#dde2f3'
  secondary-fixed-dim: '#c1c6d7'
  on-secondary-fixed: '#161c27'
  on-secondary-fixed-variant: '#414754'
  tertiary-fixed: '#ffdcbd'
  tertiary-fixed-dim: '#ffb86e'
  on-tertiary-fixed: '#2c1600'
  on-tertiary-fixed-variant: '#693c00'
  background: '#f8f9ff'
  on-background: '#181c21'
  surface-variant: '#e0e2e9'
typography:
  display-lg:
    fontFamily: Work Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Work Sans
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
  body-md:
    fontFamily: Work Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Work Sans
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  data-tabular:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 16px
  label-caps:
    fontFamily: Work Sans
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  container-padding: 16px
  gutter: 12px
  sidebar-width: 240px
  header-height: 48px
  row-height-dense: 32px
  row-height-standard: 40px
---

## Brand & Style

The design system is engineered for high-density financial analysis, prioritizing data integrity, speed of comprehension, and authoritative presence. It targets institutional analysts and professional traders who require a tool that feels like a precision instrument rather than a consumer application.

The aesthetic follows a **Minimalist Business** direction. It utilizes a sophisticated, low-saturation grayscale palette to reduce visual fatigue during long sessions. The interface relies on structural hierarchy and purposeful alignment rather than decorative elements. Every pixel is dedicated to surfacing insights, creating a "financial texture" that is stable, reliable, and strictly professional.

## Colors

This design system employs a utility-first color logic. The primary background (#F5F7FA) provides a soft, non-reflective base that allows white panels to "pop" subtly, defining workspace boundaries without heavy shadows.

- **Primary Action/Opportunity:** Opportunity Blue (#3182CE) is used for interactive elements and signaling undervalued assets.
- **Financial Status:** Standardized Red (#E53E3E) and Green (#38A169) are used strictly for directional price movement and performance. 
- **Systemic Neutral:** Neutral Gray (#666666) is reserved for flat or unchanged data points to prevent visual noise.
- **Surface Logic:** Use the Sidebar/Header color (#EBF0F5) to denote persistent navigational structures, creating a clear "frame" for the dynamic data panels.

## Typography

Typography in this design system is optimized for legibility and vertical alignment. **Work Sans** provides a professional and neutral tone for all UI labels and prose. 

A critical departure is made for financial figures: **JetBrains Mono** (or a system monospaced equivalent) must be used for all price data, percentages, and tickers. This ensures that decimals align perfectly in high-density tables, allowing the eye to scan vertical columns of numbers without jumping. 

For internationalization (specifically Chinese markets), fall back to **PingFang SC** or **Microsoft YaHei**, maintaining the same weight and scale ratios defined in the tokens.

## Layout & Spacing

The design system utilizes a **3-column classic terminal layout**. 
1. **Top Bar:** A slim 48px global header for system status and search.
2. **Left Nav:** A fixed 240px sidebar for portfolio switching and main modules.
3. **Main Content:** A fluid, multi-panel grid area that hosts the data dashboards.

Spacing follows a strict 4px grid. To achieve "high-density," internal padding in tables and cards is compressed. Use a 12px gutter between panels to maintain a clean separation of concerns while maximizing the information-to-screen ratio. The layout should be "Locked" (Fixed) for professional desktop use, with overflow handled within individual panels rather than the global page.

## Elevation & Depth

This design system avoids traditional shadows to maintain a flat, "printed" financial report feel. Depth is achieved through **Tonal Layering**:
- **Level 0 (Base):** #F5F7FA (Main Background)
- **Level 1 (Panels):** #FFFFFF (Cards/Charts/Tables)
- **Level 2 (Active/Hover):** #E2E8F0 (Subtle borders or hover states)

Borders are the primary tool for separation. Use a 1px solid border (#E2E8F0) around all panels. When an element requires focus, use a 1px solid Opportunity Blue border rather than a shadow. This keeps the interface crisp and prevents the "blurry" look often associated with consumer software.

## Shapes

The shape language is disciplined and geometric. A standard **8px (0.5rem)** radius is applied to all main panels and cards to provide a hint of modern refinement without appearing "bubbly." 

Smaller UI components like buttons, input fields, and tags should use a reduced **4px** radius to maintain precision at small scales. Progress bars and valuation tracks should remain slightly rounded to distinguish them from structural layout containers.

## Components

- **High-Density Tables:** The core of the design system. Use 32px row heights for dense data. Header cells should use `label-caps` typography with a subtle background fill (#EBF0F5). Numeric columns must be right-aligned.
- **Valuation Progress Bars:** Linear tracks using a 4px height. The "current value" is represented by a 2px vertical needle or a high-contrast segment. Use Risk Orange for overvalued and Opportunity Blue for undervalued.
- **Compact Cards:** Every card must have a header section with a 1px bottom divider. Action icons in headers should be 16x16px to conserve space.
- **Mini Charts (Sparklines):** Simplified, no-axis line charts. Use a 1.5px stroke width. The color of the sparkline should match the directional status (Red/Green).
- **Inputs & Controls:** Search bars and dropdowns should use #FFFFFF background with #E2E8F0 borders. The focus state is a 1px Opportunity Blue outline. No inner shadows or gradients.
- **Status Chips:** Small, rectangular tags with 2px border-radius. Use low-opacity tints of the status colors (e.g., 10% opacity Red) with full-opacity text for maximum readability without visual heaviness.