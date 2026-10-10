---
name: design-from-ref
description: Build or rebuild the project's DESIGN.md from a reference website URL or a reference image (Pinterest, Dribbble, screenshot), then wire the tokens into the codebase (Tailwind, CSS, or Streamlit's .streamlit/config.toml). Use when the user says "make a DESIGN.md", "use this site/image as reference", "match this style", or runs /design-from-ref.
---

# design-from-ref

Turn a reference (URL, image, or both) into a lint-clean `DESIGN.md` plus
working tokens in code. The goal is to take the reference's **system**
(palette structure, type scale, spacing rhythm, shapes), not its identity.

Input from the user: $ARGUMENTS
If that is empty, ask for a reference URL or image and a one-line
description of the product. If `PRODUCT.md` exists, read it for the product
description instead of asking.

Work in a `.design/` folder for screenshots and raw data.

## 1. Capture the reference

**URL, with Playwright MCP available** (tools named `browser_navigate`,
`browser_resize`, `browser_take_screenshot`, `browser_evaluate`):

1. Navigate to the URL. Resize to 1440x900. Dismiss cookie banners if they
   cover content.
2. Take a full-page screenshot, save as `.design/ref-desktop.png`.
3. Read `${CLAUDE_SKILL_DIR}/extract-styles.js` and pass its entire
   contents as the `function` argument of `browser_evaluate`. Save the JSON
   result to `.design/ref-desktop.json`.
4. Resize to 390x844, screenshot (`.design/ref-mobile.png`) and evaluate
   again (`.design/ref-mobile.json`) to get the mobile type scale.

If the Playwright tools are not available, tell the user once:
`claude mcp add playwright npx @playwright/mcp@latest`, then restart Claude
Code. Meanwhile ask them for a full-page screenshot and continue with the
image path below.

**Image**: Read the image and look at it carefully. Then get exact colors
instead of guessing:

```bash
python3 ${CLAUDE_SKILL_DIR}/palette.py <image> 10
```

It needs Pillow. If `python3` can't import it and the project uses uv, run
`uv run --with pillow python ${CLAUDE_SKILL_DIR}/palette.py <image> 10`
instead; otherwise `pip install pillow`. If neither works, estimate the hex
values by eye and say so. For sizes, assume a desktop screenshot is 1440px wide
unless told otherwise, and scale what you measure in the image to that.

## 2. Map raw data to tokens

Prefer the reference's own CSS variables (`cssVariables` in the JSON) when
they exist; they are its real tokens. Otherwise use the ranked tables.

Colors (keep it to 7 to 10):
- `background` = `pageBackground`. `surface` = the most common background
  that is close to it but different (cards, inputs).
- `on-surface` = the dominant text color. `muted` = the second text color.
- `line` = the most common border color.
- `primary` = the CTA background, or the most used saturated color.
  `on-primary` = the CTA text color. Add `primary-hover` (about 10 to 15%
  darker).
- `error` = a red that passes 4.5:1 on `background`, unless the reference
  has one.
- Every text pair must pass WCAG AA (4.5:1). If `muted` fails, darken it.
  Never use opacity to make muted text.
- `chart-1` to `chart-5`: series colors for data charts. Keep the existing
  ones unless they clash with the new palette; never reuse `primary` or
  `error` as a series color. If you change them, keep them distinct for
  color-blind readers (no red/green or blue/violet neighbors) and say in
  the Colors prose which ones need direct labels because they are under
  3:1 on `background`.

Typography (6 to 9 tokens: `display`, `h1`, `h2`, `h3`, `body-lg`, `body`,
`small`, `button`, `label`):
- Families from `fontsLoaded` and `headings`. If a font is proprietary or
  not on Google Fonts, pick the closest free font with the same character
  (serif vs sans, geometric vs humanist, width) and note the swap in
  prose. Never substitute Inter, Roboto, Arial or system-ui.
- Sizes: snap the ranked sizes and the headings list into the scale. Take
  `display` and `h1` from the largest headings, `body` from the most common
  size. Record the mobile sizes from the mobile JSON in the Typography
  prose.
- Line height as a unitless multiplier; letter spacing in em.

Spacing: snap the ranked spacing values to a 7-step 4px-based scale
(`xs` to `3xl`). Rounded: 2 or 3 values. Shadows: describe in
**Elevation & Depth**; note "flat" if the reference has none.

## 3. Take the system, not the identity

Never copy the logo, illustrations, photos, product names or copy text.
If the reference is a recognizable brand or someone's personal site, shift
the `primary` hue by at least 20 degrees or change the display font, so the
result is clearly inspired by it rather than a clone. Say which you did.

## 4. Write DESIGN.md

If a `DESIGN.md` already exists, use its structure as the template and
replace its contents. Rules from the spec:
- YAML front matter between `---` lines: `version: alpha`, `name`,
  `description`, `colors`, `typography`, `rounded`, `spacing`, `components`.
- `primary` color is required. Quote hex values: `"#C2410C"`.
- Dimensions need `px`, `em` or `rem`.
- Component properties are only `backgroundColor`, `textColor`,
  `typography`, `rounded`, `padding`, `size`, `height`, `width`, and should
  reference tokens like `"{colors.primary}"`.
- Sections, in this order: Overview, Colors, Typography, Layout,
  Elevation & Depth, Shapes, Components, Do's and Don'ts.

The prose is what makes the agent's later choices good, so be concrete:
- **Overview:** three character words and **one bold move** (the single
  distinctive thing everything else stays quiet around).
- **Colors / Components:** usage rules, e.g. "primary appears once per
  screen", "cards have a 1px line border, no shadow".
- **Do's and Don'ts:** keep the anti-slop list (no gradients or gradient
  text, no Inter/Roboto, no raw Tailwind palette classes or arbitrary
  values, no nested cards, no gray text on color, no hype copy, no emoji in
  headings), plus anything specific the reference teaches.

## 5. Validate

```bash
npx -y @google/design.md lint DESIGN.md
```

Fix every error and every contrast warning, then lint again until clean.

## 6. Wire the tokens into code

Check `package.json`, `pyproject.toml` / `requirements.txt` and the styles
setup first.

**Streamlit** (`streamlit` is a dependency or a `.py` file imports it):
write `.streamlit/config.toml` in the folder Streamlit is run from.
Streamlit reads the project config from `$CWD/.streamlit/config.toml`, not
from next to the script, so if the team runs `streamlit run day1/app.py`
from the repo root, the file goes in the repo root. Ask if unsure. Map:

```toml
[theme]
base = "light"                        # or "dark" if background is dark
primaryColor = "<colors.primary>"
backgroundColor = "<colors.background>"
secondaryBackgroundColor = "<colors.surface>"
textColor = "<colors.on-surface>"
borderColor = "<colors.line>"
redColor = "<colors.error>"
font = "'<Body Family>':https://fonts.googleapis.com/css2?family=<Body+Family>:wght@400;600&display=swap"
headingFont = "'<Heading Family>':https://fonts.googleapis.com/css2?family=<Heading+Family>:wght@500&display=swap"
baseRadius = "<rounded.sm>"
chartCategoricalColors = ["<chart-1>", "<chart-2>", "<chart-3>", "<chart-4>", "<chart-5>"]
```

- Use the same hex strings as DESIGN.md (the drift check compares them).
- Leave `chartSequentialColors` unset unless DESIGN.md defines 10 sequential
  steps.
- If `.claude/skills` has Streamlit's bundled theming skill (installed with
  `streamlit skills`), follow it for any key not listed here.
- Spacing, components and layout can't be set in config.toml. Add or update
  the "In Streamlit" subsection under Components in DESIGN.md (cards are
  `st.container(border=True)`, stat tiles are `st.metric`, splits are
  `st.columns`) instead of writing CSS. Never inject CSS through
  `st.markdown(..., unsafe_allow_html=True)`.
- Tell the user that theme changes show after saving and rerunning the app;
  font changes may need a server restart.

Everything below is for web frontends:
- **Tailwind v3** (`tailwind.config.*` exists):
  `npx -y @google/design.md export --format tailwind DESIGN.md > tailwind.theme.json`
  and merge it into `theme.extend` in the config.
- **Tailwind v4** (`@import "tailwindcss"` in CSS, no config): write the
  tokens as an `@theme { --color-primary: ...; }` block in the main CSS
  file.
- **No Tailwind:** write them as CSS custom properties on `:root` in the
  global stylesheet.
- Load the fonts (Google Fonts link or `next/font/google`).
- Search for existing hardcoded colors and fonts and swap them for tokens
  where it is a quick change.

## 7. Report back

Five lines max: palette (with hex), fonts, the one bold move, what you
changed to avoid cloning, and the files touched. Suggest building the next
section, then running the `design-reviewer` agent on it.
