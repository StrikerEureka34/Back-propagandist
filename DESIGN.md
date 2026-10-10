---
version: alpha
name: Paper & Signal
description: >-
  Warm paper background, near-black ink, one vermilion signal color.
  Editorial serif headlines over a plain sans body. Flat surfaces separated
  by hairlines instead of shadows. STARTER THEME: replace it by running
  /design-from-ref with your reference site or image.
colors:
  primary: "#C2410C"
  primary-hover: "#9A3412"
  on-primary: "#FFFFFF"
  background: "#F5F2EA"
  surface: "#FBFAF6"
  on-surface: "#17150F"
  muted: "#5C574C"
  line: "#DDD6C7"
  error: "#B42318"
  chart-1: "#1C5CAB"
  chart-2: "#199E70"
  chart-3: "#C98500"
  chart-4: "#D55181"
  chart-5: "#4A3AA7"
typography:
  display:
    fontFamily: Fraunces
    fontSize: 64px
    fontWeight: 500
    lineHeight: 1.0
    letterSpacing: -0.03em
  h1:
    fontFamily: Fraunces
    fontSize: 44px
    fontWeight: 500
    lineHeight: 1.05
    letterSpacing: -0.02em
  h2:
    fontFamily: Fraunces
    fontSize: 32px
    fontWeight: 500
    lineHeight: 1.15
    letterSpacing: -0.01em
  h3:
    fontFamily: IBM Plex Sans
    fontSize: 21px
    fontWeight: 600
    lineHeight: 1.3
  body-lg:
    fontFamily: IBM Plex Sans
    fontSize: 19px
    fontWeight: 400
    lineHeight: 1.55
  body:
    fontFamily: IBM Plex Sans
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.6
  small:
    fontFamily: IBM Plex Sans
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5
  button:
    fontFamily: IBM Plex Sans
    fontSize: 15px
    fontWeight: 600
    lineHeight: 1.0
  label:
    fontFamily: IBM Plex Mono
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: 0.08em
rounded:
  sm: 4px
  md: 8px
  full: 999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
  2xl: 64px
  3xl: 104px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.sm}"
    padding: 14px
    height: 44px
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    typography: "{typography.button}"
    rounded: "{rounded.sm}"
    padding: 14px
    height: 44px
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.md}"
    padding: 24px
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: 12px
    height: 44px
  nav:
    backgroundColor: "{colors.background}"
    textColor: "{colors.on-surface}"
    typography: "{typography.small}"
    height: 64px
  tag:
    backgroundColor: "{colors.background}"
    textColor: "{colors.muted}"
    typography: "{typography.label}"
    rounded: "{rounded.full}"
    padding: 6px
---

# Paper & Signal

<!--
Starter theme so your agent has something concrete on minute one.
Replace it: run /design-from-ref <url or image> in Claude Code.
Keep the section order below; the DESIGN.md spec expects it.
-->

## Overview

Three words: **calm, editorial, precise.** It should feel like a well-set
printed page that happens to be interactive, not like a SaaS template.

**The one bold move:** vermilion (`primary`) is the only saturated color on
the page. It marks the single most important action or number per screen.
Everything else is ink, muted ink, paper and hairlines. If two things on one
screen are vermilion, one of them is wrong.

## Colors

- `background` is the page. `surface` is for anything raised from it
  (cards, inputs, menus). Never put `surface` on `surface`.
- `on-surface` is the text color for headings and body copy.
- `muted` is for secondary text, captions and metadata. It passes AA on both
  backgrounds, so use it instead of lowering opacity.
- `line` is the only border color, always 1px. It separates; it does not
  decorate.
- `primary` is for the primary button, the active nav item, focus rings and
  at most one highlighted figure per screen. Not for icons, not for
  section backgrounds, never in a gradient.
- `error` is only for validation and destructive states.
- `chart-1` to `chart-5` are for data series only, assigned in that fixed
  order and never cycled; a 6th series folds into "Other". A series keeps
  its color when filters change. Validated for color-blind separation
  (worst adjacent pair ΔE 8.4). `chart-3` is under 3:1 on the background,
  so charts that use it need direct labels or a table view next to them.
  Highlight one series by keeping it in its color and graying the rest
  with `line`, not by switching it to `primary`.
- Checked contrast (WCAG): on-surface/background 16.3, muted/background 6.4,
  on-primary/primary 5.2, primary/background 4.6.

## Typography

- Headlines (`display`, `h1`, `h2`) use Fraunces. Everything else uses
  IBM Plex Sans; `label` uses IBM Plex Mono for small caps-style metadata,
  stats and tags (uppercase).
- Load from Google Fonts: Fraunces (400, 500), IBM Plex Sans (400, 600),
  IBM Plex Mono (500).
- Only use sizes from the scale. Hierarchy comes from size and font family,
  not from bold everywhere: body text is 400, only `h3` and `button` are 600.
- Mobile (under 640px): `display` 40px, `h1` 32px, `h2` 26px; everything else
  unchanged.
- Body line length: 60 to 72 characters (`max-width: 65ch`).

## Layout

- Spacing uses only the `spacing` scale (4px base).
- Content max width 1200px; text columns max 65ch. Side gutters `lg` on
  mobile, `xl` on desktop.
- Vertical rhythm between page sections: `3xl` desktop, `2xl` mobile.
  Inside a section: `xl` between heading and content, `lg` between items.
- Prefer left-aligned layouts and asymmetric 7/5 or 8/4 column splits over
  centered stacks. Center only the final CTA.
- One focal point per viewport.

## Elevation & Depth

Flat by default. Separate with `line` hairlines and the
`background`/`surface` step, not shadows. The only shadow is for floating
layers (dropdowns, dialogs, toasts): `0 8px 24px rgba(23, 21, 15, 0.12)`.

## Shapes

Mostly square: `sm` (4px) for buttons and inputs, `md` (8px) for cards and
images, `full` only for tags and avatars. No blobs, no organic shapes.

## Components

- **Buttons:** one `button-primary` per view. Secondary actions use
  `button-secondary` with a 1px `line` border, or a plain text link.
  Visible focus ring: 2px `primary`, 2px offset.
- **Cards:** `surface` with a 1px `line` border. No shadow, no hover lift.
  Never nest a card inside a card.
- **Inputs:** 44px tall, 1px `line` border, border turns `primary` on focus.
  Labels always visible above the field, in `small`.
- **Nav:** text links in `small`, active item in `on-surface` with a 2px
  `primary` underline; inactive in `muted`.
- **Tags:** `label` text in `muted` with a 1px `line` border.
- **Icons:** one outline icon set (Lucide), 1.5px stroke, 20px, color
  `muted` or `on-surface`. No icon in a colored rounded square.
- **Motion:** 150 to 200ms, `ease-out`, opacity and transform only.
  Respect `prefers-reduced-motion`. No bounce, no parallax, no animated
  gradients.

### In Streamlit

Tokens live in `.streamlit/config.toml` `[theme]`; layout comes from
Streamlit primitives, not CSS:
- Card: `st.container(border=True)`. Stat tile: `st.metric`, in a row of
  `st.columns`. Tag: `st.badge` or a `label`-styled caption.
- 7/5 split: `st.columns([7, 5])`. Dashboards use
  `st.set_page_config(layout="wide")`.
- Charts: series colors come from `chartCategoricalColors`. Leave
  Plotly/Altair charts on their default `theme="streamlit"` and don't
  hardcode hex in Python.
- No CSS injected through `st.markdown(..., unsafe_allow_html=True)`.

## Do's and Don'ts

- Do write copy that is specific to the product: say what it does, with
  real numbers. No "supercharge", "seamless", "unlock", "effortless", no
  emoji in headings.
- Do use real or realistic content in demos, never lorem ipsum.
- Don't use Inter, Roboto, Arial or system-ui for anything visible.
- Don't use gradients: no purple-to-blue, no gradient text, no glow.
- Don't use glassmorphism, blurred blobs or grain overlays.
- Don't use raw Tailwind palette classes (`bg-blue-500`, `text-gray-600`)
  or arbitrary values (`text-[13px]`, `bg-[#123456]`). Use the tokens.
- Don't build the hero, three feature cards, testimonials, pricing template.
  Every section must earn its place in this product's story.
- Don't put gray text on a colored background.
- Don't center everything.
