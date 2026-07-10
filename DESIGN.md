---
name: Pixel Pet
description: A quiet native controller for a playful desktop companion.
colors:
  accent-apricot: "#D47A47"
  accent-ink: "#9A4B27"
typography:
  title:
    fontFamily: "system-ui, sans-serif"
    fontWeight: 700
    lineHeight: 1.2
  body:
    fontFamily: "system-ui, sans-serif"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "system-ui, sans-serif"
    fontWeight: 500
    lineHeight: 1.3
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "24px"
  xl: "28px"
components:
  status-active:
    textColor: "{colors.accent-ink}"
    typography: "{typography.label}"
  button-destructive:
    textColor: "{colors.accent-ink}"
    typography: "{typography.label}"
---

# Design System: Pixel Pet

## 1. Overview

**Creative North Star: "The Quiet Companion Desk"**

Pixel Pet is a small, orderly place where the user checks on a companion and makes a few understandable choices. Structure follows GNOME Settings, control density borrows from Raycast Preferences, and the Pet Preview treats pixel art with Aseprite-like crispness.

The interface is playful through Catbone, not decorative chrome. Libadwaita supplies platform typography, system light and dark themes, focus behavior, controls, and tonal surfaces. The custom layer is deliberately narrow: restrained apricot state color, a softly tinted preview pane, and precise spacing.

It rejects Razer Synapse-style hardware density, neon gamer styling, childish toy-store styling, and generic nested card grids.

**Key Characteristics:**
- Native Libadwaita settings structure
- One persistent crisp Pet Preview
- Restrained apricot state color
- System humanist typography
- Live Setting feedback without choreography
- Split layout that stacks below 650sp

## 2. Colors

Libadwaita owns neutral surfaces, text, borders, semantic errors, and light/dark adaptation. Pixel Pet adds only Apricot Signal and Apricot Ink from the frontmatter.

### Primary
- **Apricot Signal**: active switches, focus, slider fill, and selected states.
- **Apricot Ink**: active status text and high-contrast warm emphasis.

### Neutral
- **System Window Surface**: inherited from Libadwaita for controller background.
- **System Tonal Surface**: inherited for preference groups and preview separation.
- **System Border**: inherited for fine dividers and window structure.

**The Quiet Accent Rule.** Apricot remains under 10% of the surface. It indicates action or state and never decorates empty space.

**The System Theme Rule.** Light and dark appearances come from the user's system. Dark mode is never forced for category flavor.

## 3. Typography

**Display Font:** System UI humanist sans
**Body Font:** System UI humanist sans

**Character:** Friendly, compact, and native. Libadwaita's title and body classes provide platform-correct metrics without custom font loading or layout shift.

### Hierarchy
- **Title** (700, system title-1, 1.2): Catbone identity and primary preview label.
- **Body** (400, system body, 1.5): descriptions and permission guidance.
- **Label** (500, system control label, 1.3): actions, values, and status.

**The One-Family Rule.** Use one system family across headings, labels, controls, and supporting text. Novelty display faces are forbidden.

## 4. Elevation

Flat by default. Preview, grouped settings, and footer are separated through system tonal layering and fine dividers. Pixel Pet defines no custom shadows. Transient dialogs use Libadwaita's platform elevation.

**The Still Surface Rule.** Motion communicates native control state only. No entrance choreography, bounce, or decorative loops appear outside the Pet Preview.

## 5. Components

### Pet Preview
- **Structure:** flexible drawing area, Catbone identity, text-plus-dot status, one-line description, pause action.
- **Rendering:** nearest-neighbor sprite sampling centered from the active frame's opaque bounds.
- **Motion:** mirrors current pet behavior; freezes when paused or system animations are disabled.

### Preference Groups
- **Structure:** Companion and System groups containing standard Libadwaita rows.
- **Separation:** native group surfaces and fine row dividers, never nested cards.
- **Spacing:** 24px group rhythm with 28px horizontal content inset.

### Switch Rows
- **Style:** native Libadwaita title, subtitle, switch, hover, focus, active, and disabled states.
- **Disabled:** affected input controls remain visible but disabled when evdev access is unavailable.

### Range Controls
- **Style:** native GTK scale with persistent visible value label.
- **Size:** 75% to 200% in 25% steps.
- **Typing Hold:** 0 to 5 seconds in 0.5-second steps.

### Footer Actions
- **Status:** icon plus text communicates first run, saved, copied, and error states.
- **Actions:** Restore defaults is secondary; Quit Pixel Pet uses destructive text styling.

### Permission Guidance
- **Structure:** visible explanation with Copy setup command and Recheck actions.
- **Tone:** direct and non-blaming. Pixel Pet never runs sudo.

## 6. Do's and Don'ts

### Do:
- **Do** follow native GTK focus order, keyboard behavior, and system theming.
- **Do** use the 4px spacing family and vary rhythm deliberately.
- **Do** keep pixel art nearest-neighbor sampled and optically centered.
- **Do** make safe settings apply and save together.
- **Do** preserve text labels alongside color and icons.
- **Do** freeze preview motion when system animations are disabled.

### Don't:
- **Don't** create a dense developer-control dashboard.
- **Don't** use childish toy-store styling.
- **Don't** use neon gamer aesthetics or Razer Synapse-style hardware chrome.
- **Don't** compose the window from generic nested card grids.
- **Don't** let decorative animation compete with the Pet Preview.
- **Don't** rasterize interface text or imitate generated window chrome.
