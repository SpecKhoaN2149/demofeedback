# Implementation Plan: Spectrum UI Redesign

## Overview

This plan implements a comprehensive UI redesign of the Spectrum customer feedback application using a three-layer architecture: Design System (tokens, reset, animations) → Component Library (Button, Input, Card, ProgressBar, Alert, Badge) → Page Composition (Landing, Sentiment, Status, Admin). All work is additive to the existing React 18 + TypeScript + Vite stack, using CSS custom properties for design tokens and CSS Modules for component scoping.

## Tasks

- [x] 1. Set up design system foundation
  - [x] 1.1 Create design tokens CSS file
    - Create `frontend/src/styles/tokens.css` defining all CSS custom properties on `:root`
    - Include color tokens (primary, secondary, accent, neutrals, semantic colors, text colors)
    - Include typography tokens (font-family, font-sizes xs–3xl, weights, line-heights)
    - Include spacing scale tokens (space-1 through space-16)
    - Include border-radius tokens (sm, md, lg, full)
    - Include shadow tokens (sm, md, lg)
    - Include transition-duration tokens (fast: 150ms, normal: 250ms, slow: 400ms)
    - _Requirements: 1.1, 1.2, 1.3, 15.1_

  - [x] 1.2 Create CSS reset and global typography
    - Create `frontend/src/styles/reset.css` with a modern CSS reset
    - Set `font-family: var(--spectrum-font-family)` on `html` and `body`
    - Set `font-size: 16px` on body with line-height 1.5 for body text
    - Apply `overflow-wrap: break-word` and `max-width: 100%` on images
    - Set heading line-heights to 1.2
    - _Requirements: 12.1, 12.2, 12.3_

  - [x] 1.3 Create animations and transitions CSS
    - Create `frontend/src/styles/animations.css` with keyframe definitions
    - Define `@keyframes pulse` for ProgressBar pulsing effect (opacity 0.6 → 1.0)
    - Define `@keyframes fadeIn` for page transition (opacity 0 → 1)
    - Add `@media (prefers-reduced-motion: reduce)` query that disables all transitions and animations globally
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

  - [x] 1.4 Create global styles barrel import
    - Create `frontend/src/styles/index.css` that imports tokens.css, reset.css, and animations.css in order
    - Import this barrel file in `frontend/src/main.tsx` (or existing entry point)
    - _Requirements: 1.4, 12.1_

- [x] 2. Implement core UI components
  - [x] 2.1 Implement Button component
    - Create `frontend/src/components/ui/Button/Button.tsx` with ButtonProps interface
    - Accept `variant` (primary/secondary/outline/ghost), `size` (small/medium/large), `fullWidth`, `disabled` props
    - Create `frontend/src/components/ui/Button/Button.module.css` with variant and size styles
    - Implement hover darkening via `filter: brightness(0.9)` with fast transition
    - Implement 2px focus ring with 2px offset using `--spectrum-color-primary`
    - Implement disabled state: opacity 0.5, cursor not-allowed, pointer-events none
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

  - [x]* 2.2 Write property tests for Button variant+size rendering
    - **Property 1: Button variant and size produce correct styles**
    - Generate random (variant, size) pairs via fast-check, verify CSS class and dimensions
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

  - [x]* 2.3 Write property test for disabled Button behavior
    - **Property 2: Disabled Button behavior**
    - Generate random button configs with `disabled=true`, verify opacity + no click handler fires
    - **Validates: Requirements 3.9**

  - [x] 2.4 Implement Input component
    - Create `frontend/src/components/ui/Input/Input.tsx` with InputProps interface
    - Render `<label>` above input with font-weight 500 and 4px margin-bottom
    - Create `frontend/src/components/ui/Input/Input.module.css` with border, padding, focus, error styles
    - Implement focus state: border to `--spectrum-color-primary`, 3px box-shadow glow
    - Implement error state: red border, error message below, `aria-invalid="true"`, `aria-describedby`
    - _Requirements: 4.1, 4.2, 4.3, 4.6_

  - [x]* 2.5 Write property test for Input error state accessibility
    - **Property 3: Input error state accessibility**
    - Generate random non-empty error strings, verify aria-invalid + aria-describedby linkage
    - **Validates: Requirements 4.3**

  - [x] 2.6 Implement Textarea component
    - Create `frontend/src/components/ui/Textarea/Textarea.tsx` with TextareaProps interface
    - Create `frontend/src/components/ui/Textarea/Textarea.module.css` with identical styling to Input
    - Accept `rows` prop for height configuration
    - Implement same focus and error behavior as Input
    - _Requirements: 4.4_

  - [x] 2.7 Implement Select component
    - Create `frontend/src/components/ui/Select/Select.tsx` with SelectProps interface
    - Create `frontend/src/components/ui/Select/Select.module.css` with identical border, focus, error styling
    - Accept `options` array prop and `error` prop
    - Implement same focus and error accessibility behavior as Input
    - _Requirements: 4.5_

  - [x] 2.8 Implement Card component
    - Create `frontend/src/components/ui/Card/Card.tsx` with CardProps interface
    - Create `frontend/src/components/ui/Card/Card.module.css`
    - Base: white background, `--spectrum-radius-md`, `--spectrum-shadow-md`, 24px padding
    - Interactive mode: hover lifts shadow to lg + scale(1.02), keyboard focus ring
    - Bordered mode: 1px solid neutral-200 border, no shadow
    - Set `tabIndex`, `role`, `onClick`, `onKeyDown` for interactive cards
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x]* 2.9 Write property test for Card bordered mode
    - **Property 4: Card bordered mode removes shadow**
    - Generate Card with `bordered=true`, verify border presence + shadow absence
    - **Validates: Requirements 5.4**

  - [x] 2.10 Implement ProgressBar component
    - Create `frontend/src/components/ui/ProgressBar/ProgressBar.tsx` with ProgressBarProps interface
    - Create `frontend/src/components/ui/ProgressBar/ProgressBar.module.css`
    - Track: neutral-200, fill: primary color with animated width transition
    - Clamp value to [0, 100] range
    - Implement size variants: small (4px), default (8px), large (12px)
    - Implement pulsing animation (opacity 0.6→1.0 loop)
    - At 100%: fill color changes to success color
    - Set `role="progressbar"`, `aria-valuenow`, `aria-valuemin=0`, `aria-valuemax=100`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x]* 2.11 Write property test for ProgressBar size mapping
    - **Property 5: ProgressBar size maps to height**
    - Generate random sizes, verify track height matches spec (small: 4px, default: 8px, large: 12px)
    - **Validates: Requirements 6.5**

  - [x]* 2.12 Write property test for ProgressBar ARIA attributes
    - **Property 6: ProgressBar ARIA attributes reflect value**
    - Generate random values [0, 100], verify aria-valuenow matches value
    - **Validates: Requirements 6.6**

  - [x] 2.13 Implement Alert component
    - Create `frontend/src/components/ui/Alert/Alert.tsx` with AlertProps interface
    - Create `frontend/src/components/ui/Alert/Alert.module.css`
    - 4px left border + background tint based on severity (success/warning/error/info)
    - Set `role="alert"` for error/warning, `role="status"` for success/info
    - Optional close button with `aria-label="Close alert"`
    - _Requirements: 7.1, 7.2, 7.3_

  - [x]* 2.14 Write property test for Alert severity rendering
    - **Property 7: Alert severity determines colors and ARIA role**
    - Generate random severities, verify color + role mapping
    - **Validates: Requirements 7.1, 7.2, 7.3**

  - [x] 2.15 Implement Badge component
    - Create `frontend/src/components/ui/Badge/Badge.tsx` with BadgeProps interface
    - Create `frontend/src/components/ui/Badge/Badge.module.css`
    - Pill shape (radius-full), 4px/8px padding, xs font-size, weight 600
    - Color maps to semantic design tokens
    - _Requirements: 7.4, 7.5_

  - [x]* 2.16 Write property test for Badge color mapping
    - **Property 8: Badge color maps to semantic token**
    - Generate random colors, verify semantic token application
    - **Validates: Requirements 7.4**

- [x] 3. Checkpoint - Core components complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement layout components
  - [x] 4.1 Create SpectrumLogo component
    - Create `frontend/src/components/brand/SpectrumLogo/SpectrumLogo.tsx`
    - Render inline SVG wordmark with `aria-label="Spectrum"`
    - Accept `variant` prop: 'light' (white) or 'dark' (Spectrum Blue)
    - Enforce min-width 120px, max-width 160px, maintain aspect ratio
    - Add clear space padding equal to the height of the "S" glyph
    - Create or place `frontend/src/assets/spectrum-wordmark.svg`
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_

  - [x] 4.2 Implement Header component
    - Create `frontend/src/components/layout/Header/Header.tsx`
    - Create `frontend/src/components/layout/Header/Header.module.css`
    - Fixed position, Dark Navy background, box-shadow for separation
    - Logo aligned left, navigation links centered (visible ≥768px)
    - Mobile menu toggle button (visible <768px)
    - Implement mobile slide-out navigation panel with translateX transition
    - ESC key and overlay click close mobile menu, return focus to toggle
    - _Requirements: 2.1, 2.4, 2.5, 2.6_

  - [x] 4.3 Implement Footer component
    - Create `frontend/src/components/layout/Footer/Footer.tsx`
    - Create `frontend/src/components/layout/Footer/Footer.module.css`
    - Render copyright text "© {current year} Charter Communications, Inc."
    - Render Terms of Service and Privacy Policy links
    - _Requirements: 2.3_

  - [x] 4.4 Implement NavigationShell component
    - Create `frontend/src/components/layout/NavigationShell/NavigationShell.tsx`
    - Create `frontend/src/components/layout/NavigationShell/NavigationShell.module.css`
    - CSS Grid layout: `grid-template-rows: auto 1fr auto` for header/main/footer
    - Main content: max-width 1200px, centered, 16px mobile / 32px desktop padding
    - Padding-top offset for fixed header (~64px)
    - Compose Header and Footer within the shell
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 4.5 Implement AdminSidebar component
    - Create `frontend/src/components/layout/AdminSidebar/AdminSidebar.tsx`
    - Create `frontend/src/components/layout/AdminSidebar/AdminSidebar.module.css`
    - Navigation links: Dashboard, Review Queue, Tickets, Marketing Log, Trend Analysis
    - Active link: Spectrum Blue background, white text
    - 240px width on desktop
    - _Requirements: 11.1_

  - [x] 4.6 Implement AdminLayout component
    - Create `frontend/src/components/layout/AdminLayout/AdminLayout.tsx`
    - Create `frontend/src/components/layout/AdminLayout/AdminLayout.module.css`
    - Desktop (≥1024px): sidebar + content grid layout
    - Tablet (<1024px): horizontal tab bar below header
    - _Requirements: 11.1, 11.2_

- [x] 5. Checkpoint - Layout components complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement page compositions
  - [x] 6.1 Redesign Landing Page
    - Update the existing landing page to use NavigationShell wrapper
    - Replace form fields with Input, Textarea components from Component_Library
    - Add page title "Tell us about your experience" in Card, using 2xl font-size, weight 700
    - Add instructional subtitle in text-secondary color
    - Use Button component (variant primary, size large) for submit, full-width on mobile
    - Apply 16px spacing between form fields
    - Limit form content width to ~600px (65 characters)
    - Apply fade-in animation on page entry
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 12.4, 12.5_

  - [x] 6.2 Redesign Sentiment Selection Page
    - Update existing sentiment page to use NavigationShell wrapper
    - Render three sentiment options as interactive Card components
    - Horizontal row on ≥768px, vertical stack on mobile
    - Each Card: icon, title, description, colored left border (red/green/blue)
    - Apply Card interactive hover effect
    - Navigate to corresponding form page on click/keyboard activation
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 6.3 Redesign Status Tracker Page
    - Update existing status page to use NavigationShell wrapper
    - Render ProgressBar inside a Card, centered with max-width 600px
    - Display percentage text above progress bar
    - Display status message below using lg font-size
    - Show success Alert at 100% completion
    - Show error Alert + retry Button (variant outline) on connection failure
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 6.4 Redesign Admin Panel
    - Wrap admin routes with AdminLayout component
    - Implement dashboard with stat Cards (3xl value, sm label, colored top border)
    - Style data tables with alternating row colors, 1px borders, semibold headers
    - Use Button (variant outline, size small) for table action buttons
    - Apply fade-in transition on admin page changes
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 6.5 Wire NavigationShell into App.tsx
    - Update `frontend/src/App.tsx` to wrap all routes with NavigationShell
    - Ensure page transitions use fade-in animation with normal transition duration
    - Verify no horizontal overflow at any viewport width
    - _Requirements: 2.1, 14.5, 15.3_

- [x] 7. Implement responsive behavior and accessibility
  - [x] 7.1 Add responsive breakpoint styles
    - Add media queries for mobile (<768px), tablet (768px–1023px), desktop (≥1024px)
    - Mobile: stack forms vertically, full-width buttons, vertical card stacks, hide nav
    - Tablet: single-column centered, 32px padding, horizontal nav visible
    - Desktop: sidebar layout for admin, horizontal cards, full max-width 1200px
    - Ensure no horizontal scrolling at any width 320px–1440px
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

  - [x] 7.2 Implement accessibility enhancements
    - Verify all interactive elements have visible focus indicators
    - Set `aria-invalid`, `aria-describedby` on error-state inputs
    - Set `role="alert"` on dynamic error messages
    - Add `aria-label` on icon-only buttons (mobile toggle, close buttons)
    - Add `alt=""` or `aria-hidden="true"` on decorative icons
    - _Requirements: 13.3, 13.4, 13.5, 13.6_

- [x] 8. Implement property-based tests for accessibility and layout
  - [x]* 8.1 Write property test for color contrast compliance
    - **Property 9: Color contrast compliance**
    - Generate all defined foreground-background color pairings from design tokens
    - Compute contrast ratio and verify ≥ 4.5:1 for normal text, ≥ 3:1 for large text
    - **Validates: Requirements 13.1, 13.2**

  - [x]* 8.2 Write property test for interactive element focus indicators
    - **Property 10: Interactive elements have visible focus indicator**
    - Generate each interactive component type, verify focus-visible styles present
    - **Validates: Requirements 13.3**

  - [x]* 8.3 Write property test for error dual-channel signaling
    - **Property 11: Error states use dual-channel signaling**
    - Generate error-capable components with error state, verify both color change and text/icon present
    - **Validates: Requirements 13.4**

  - [x]* 8.4 Write property test for no horizontal overflow
    - **Property 12: No horizontal overflow across viewport widths**
    - Generate random viewport widths [320, 1440], verify no horizontal scrollbar
    - **Validates: Requirements 14.5**

  - [x]* 8.5 Write property test for reduced motion
    - **Property 13: Reduced motion disables animations**
    - Generate animated component types, verify transitions disabled under prefers-reduced-motion
    - **Validates: Requirements 15.4**

- [x] 9. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The design uses TypeScript with CSS Modules — all implementations follow this pattern
- fast-check and Vitest + @testing-library/react are already installed
- Existing page logic and routing remain intact; redesign is additive (wrapping/replacing visual elements)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4"] },
    { "id": 2, "tasks": ["2.1", "2.4", "2.6", "2.7", "2.8", "2.10", "2.13", "2.15"] },
    { "id": 3, "tasks": ["2.2", "2.3", "2.5", "2.9", "2.11", "2.12", "2.14", "2.16"] },
    { "id": 4, "tasks": ["4.1", "4.3", "4.5"] },
    { "id": 5, "tasks": ["4.2", "4.4", "4.6"] },
    { "id": 6, "tasks": ["6.1", "6.2", "6.3", "6.5"] },
    { "id": 7, "tasks": ["6.4"] },
    { "id": 8, "tasks": ["7.1", "7.2"] },
    { "id": 9, "tasks": ["8.1", "8.2", "8.3", "8.4", "8.5"] }
  ]
}
```
