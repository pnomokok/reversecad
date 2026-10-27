---
name: Precision CAD Drafting
colors:
  surface: '#131313'
  surface-dim: '#131313'
  surface-bright: '#393939'
  surface-container-lowest: '#0e0e0e'
  surface-container-low: '#1b1b1c'
  surface-container: '#202020'
  surface-container-high: '#2a2a2a'
  surface-container-highest: '#353535'
  on-surface: '#e5e2e1'
  on-surface-variant: '#e1bfb6'
  inverse-surface: '#e5e2e1'
  inverse-on-surface: '#303030'
  outline: '#a98a81'
  outline-variant: '#59413a'
  surface-tint: '#ffb59f'
  primary: '#ffb59f'
  on-primary: '#5f1500'
  primary-container: '#ff6a3d'
  on-primary-container: '#611600'
  inverse-primary: '#ae3104'
  secondary: '#bdf4ff'
  on-secondary: '#00363d'
  secondary-container: '#00e3fd'
  on-secondary-container: '#00616d'
  tertiary: '#58d7eb'
  on-tertiary: '#00363d'
  tertiary-container: '#00a9bc'
  on-tertiary-container: '#00373f'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#ffdbd1'
  primary-fixed-dim: '#ffb59f'
  on-primary-fixed: '#3b0a00'
  on-primary-fixed-variant: '#862200'
  secondary-fixed: '#9cf0ff'
  secondary-fixed-dim: '#00daf3'
  on-secondary-fixed: '#001f24'
  on-secondary-fixed-variant: '#004f58'
  tertiary-fixed: '#9af0ff'
  tertiary-fixed-dim: '#58d7eb'
  on-tertiary-fixed: '#001f24'
  on-tertiary-fixed-variant: '#004f58'
  background: '#131313'
  on-background: '#e5e2e1'
  surface-variant: '#353535'
typography:
  headline-xl:
    fontFamily: Space Grotesk
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Space Grotesk
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.015em
  headline-md:
    fontFamily: Space Grotesk
    fontSize: 18px
    fontWeight: '500'
    lineHeight: 24px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 22px
  body-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  body-sm:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '400'
    lineHeight: 16px
  label-lg:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.03em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 9px
    fontWeight: '600'
    lineHeight: 12px
    letterSpacing: 0.05em
  dimension-callout:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '700'
    lineHeight: 12px
    letterSpacing: 0.04em
spacing:
  gutter: 0.5rem
  margin: 0.75rem
  space-xs: 0.25rem
  space-sm: 0.375rem
  space-md: 0.5rem
  space-lg: 0.75rem
  space-xl: 1rem
---

## Brand & Style

This design system is engineered for industrial precision, computer vision drafting, and metrological inspection. It bridges raw photographic capture with exact technical schematics, delivering an experience calibrated for mechanical engineers, industrial designers, and fabrication specialists.

The aesthetic fuses **Technical Utilitarianism** and **Modern Drafting Minimal**:
- **Controlled, Purposeful Density:** Every pixel serves operational clarity. The canvas remains the hero, framed by slim, tactile tooling.
- **Instrument-Grade Feedback:** High contrast, zero-latency aesthetic cues reassure users that line extractions, vector snapping, and tolerance bounds are exact.
- **No Decorative Overhead:** Skew, ornamental gradients, and gratuitous blur effects are banned. Precision is established through crisp geometric delineation, meticulous 1px structural framing, and high-visibility measurement callouts.

## Colors

The palette reproduces the focused, glare-free environment of precision instrumentation and high-spec CAD monitors:

- **Primary (`#FF6A3D` - Vivid Cadmium Orange):** Dedicated to active drafting vectors, detected high-confidence contours, selection reticles, and primary actions. It commands immediate optical priority against dark substrates.
- **Secondary (`#00E5FF` - Electric Cyan):** Dedicated to inspection delta states, calibration references, snapped vertices, and secondary data feeds.
- **Canvas Base (`#141414`):** Deep charcoal substrate providing infinite optical depth for viewport inspection and reducing ocular fatigue during extended sessions.
- **Surface Elevation 1 (`#1E1E1E`):** Resting state for side panels, inspector toolbars, and contextual docks.
- **Surface Elevation 2 (`#282828`):** Hover states, nested tool compartments, and active input backgrounds.
- **Structural Boundary (`#383838`):** Razor-thin 1px architectural divider lines.
- **Inspection White (`#FFFFFF`):** Reserved strictly for dimension strings, tick lines, unit indicators, and dynamic arrowheads to maintain ISO/ANSI drafting readability.

## Typography

The typographic hierarchy separates narrative navigation from numerical data:

- **Space Grotesk (Headings):** Brings technical character and architectural structure to panel titles, modal caps, and file metadata.
- **Inter (Body UI):** Delivers neutral, highly legible copy for tooltips, layer descriptions, settings descriptions, and system notifications.
- **JetBrains Mono (Metrics & Controls):** Used for all numerical values, dimensional tolerance outputs (`±0.025 mm`), coordinates (`X, Y, Z`), scale calibrations, and parameter scrubbers.
- Numerical fields must always employ tabular figures (`tnum`) to eliminate layout jitter during active measurement recalculations and real-time cursor dragging.

## Layout & Spacing

The workspace uses a full-bleed workstation layout engineered for continuous viewport interaction:

- **Workspace Division:** 
  - **Left Rail (Fixed 48px):** Primary viewport tools (Select, Calibrate, Trace, Dimension, Section).
  - **Main Canvas (Fluid):** Photographic backdrop, vector line overlay, and interactive dimension rendering engine.
  - **Right Inspector Panel (Fixed 280px / 320px):** Layer hierarchy, edge detection thresholds, tolerance parameters, and batch export definitions.
- **Rhythm & Grid:** Built on an exacting 4px incremental scale. Margins and gutters within control decks are intentionally compact (`0.25rem` to `0.75rem`) to maximize high-density metric monitoring without requiring scroll overflow.
- **Responsive Adaptations:**
  - **Desktop (1280px+):** Pinned persistent side panels, dual viewport comparison mode.
  - **Tablet (768px - 1279px):** Inspector transitions into an off-canvas drawer with edge-swipe invocation; quick-tool shelf docks to the bottom edge.
  - **Mobile (<768px):** Strict inspection review mode; toolbars compress into bottom bottom-sheets, vector drawing locks to single-point tap selection.

## Elevation & Depth

Visual hierarchy is communicated through **structural borders and tonal stratification**, eliminating blur-based shadows that compromise technical acuity:

- **Level 0 (Base Canvas - `#141414`):** The image rendering plane and drafting grid.
- **Level 1 (Docked Surfaces - `#1E1E1E`):** Side panels and HUD ribbons framed by a continuous `1px solid #282828` contour.
- **Level 2 (Active Sub-modules & Inputs - `#282828`):** Parameter sliders, dropdown inputs, and segment selectors recessed or resting with an interior `1px solid #383838` stroke.
- **Level 3 (Floating HUDs & Flyouts - `#1E1E1E`):** Calibration loupes, contextual coordinate callouts, and cursor-adjacent tooltips use an absolute `1px solid #FF6A3D` stroke or crisp `0 2px 8px rgba(0, 0, 0, 0.8)` ambient cutoff to lift clean off visual data without softness.

## Shapes

The design system enforces a sharp geometry (`roundedness: 0`):

- **Zero Radius:** Buttons, inputs, panel edges, tabs, and modals use square `0px` corners. This mirrors precision CNC-machined metal blocks and structural drafting interfaces.
- **Micro-chamfers:** Specific high-level indicator tags or selected tool chips may use diagonal corner cuts (chamfers) at a strict 45-degree angle (2px to 4px) to emphasize technical drafting heritage.
- **Reticles and Line Geometry:** All overlay markers, dimension extension limits, and crosshairs utilize exact 1px or 2px stroke profiles.

## Components

### Buttons & Tool Selectors
- **Primary Action (Commit / Export):** Solid `#FF6A3D` background, `#141414` text, bold `JetBrains Mono`, 0px border radius. Hover: `#FF825C`. Active: `#E05328`.
- **Tool Shelf Buttons:** 36x36px squares, transparent background with 1px `#282828` border. Active tool state fills `#282828` with a persistent 2px left border in `#FF6A3D` and active icon tinting.

### Precision Sliders & Steppers (Edge Detection & Tolerance)
- Sliders consist of a 2px track in `#282828` with an active fill in `#FF6A3D`.
- Thumb: 8x14px sharp rectangular block in `#FFFFFF` with numeric label directly adjacent in `label-sm`.
- Number steppers include micro `+` and `-` click-targets combined with inline direct-entry text fields using monospace alignment.

### Dimension Line Callouts
- Drawn natively over canvas vectors.
- Dimension line: 1px `#FFFFFF` with 45-degree slash or filled arrowhead terminal endpoints.
- Value Badge: Centered on dimension line; `#141414` background pill (square-edged) with 1px `#FFFFFF` border, displaying measurement and active deviation in `dimension-callout` (`24.085mm ±0.005`).

### Layer & Vector Toggles
- Row items with 28px height, containing layer visibility (eye icon), lock state, vector fill color indicator, and confidence score (`JetBrains Mono`).
- Checkboxes are 12x12px square outlines (`#383838`). When checked, they fill `#FF6A3D` with a crisp black square inset rather than a rounded checkmark.

### Input Fields & Calibration Pickers
- High-density containers with top-aligned micro-labels in uppercase `label-sm` (`#888888`).
- Input body: `#141414` background, `1px solid #383838`, text in `#FFFFFF`. On focus: border shifts instantly to `1px solid #FF6A3D` without glowing outer rings.