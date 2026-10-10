() => {
  // Pulls the real design tokens out of a rendered page.
  // Pass this whole file as the `function` argument of the Playwright MCP
  // browser_evaluate tool. Returns ranked frequency tables, not raw dumps.
  const MAX_ELEMENTS = 4000;

  const toHex = (c) => {
    const m = c && c.match(/rgba?\(([^)]+)\)/);
    if (!m) return c;
    const [r, g, b, a = '1'] = m[1].split(/[ ,/]+/).filter(Boolean);
    if (parseFloat(a) === 0) return null;
    const hex = '#' + [r, g, b].map((v) => (+v).toString(16).padStart(2, '0')).join('');
    return parseFloat(a) < 1 ? `${hex} @${(+a).toFixed(2)}` : hex;
  };
  const tally = () => new Map();
  const add = (map, key, weight = 1) => {
    if (key == null || key === '' || key === 'none' || key === 'normal' || key === '0px') return;
    map.set(key, (map.get(key) || 0) + weight);
  };
  const top = (map, n = 12) =>
    [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, n).map(([value, weight]) => ({ value, weight: Math.round(weight) }));

  const t = {
    background: tally(), text: tally(), border: tally(), fontFamily: tally(), fontSize: tally(),
    fontWeight: tally(), lineHeight: tally(), letterSpacing: tally(), radius: tally(),
    spacing: tally(), shadow: tally(),
  };
  const headings = [];
  const ctas = [];
  const vw = window.innerWidth;

  const els = [...document.querySelectorAll('body *')].slice(0, MAX_ELEMENTS);
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || +s.opacity === 0) continue;

    const area = Math.min(r.width * r.height, vw * 1200) / 1000;
    add(t.background, toHex(s.backgroundColor), area);
    if (parseFloat(s.borderTopWidth) > 0 || parseFloat(s.borderBottomWidth) > 0) add(t.border, toHex(s.borderTopColor || s.borderBottomColor));
    add(t.radius, s.borderTopLeftRadius);
    add(t.shadow, s.boxShadow);
    for (const p of ['paddingTop', 'paddingLeft', 'rowGap', 'columnGap', 'marginBottom']) add(t.spacing, s[p]);

    const ownText = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join(' ').trim();
    if (ownText) {
      const w = Math.min(ownText.length, 400);
      add(t.text, toHex(s.color), w);
      add(t.fontFamily, s.fontFamily.split(',')[0].replace(/["']/g, '').trim(), w);
      add(t.fontSize, s.fontSize, w);
      add(t.fontWeight, s.fontWeight, w);
      add(t.lineHeight, s.lineHeight === 'normal' ? null : (parseFloat(s.lineHeight) / parseFloat(s.fontSize)).toFixed(2), w);
      add(t.letterSpacing, s.letterSpacing, w);

      const tag = el.tagName.toLowerCase();
      const fontPx = parseFloat(s.fontSize);
      if (/^h[1-4]$/.test(tag) || fontPx >= 28) {
        if (headings.length < 15) headings.push({ tag, text: ownText.slice(0, 50), fontSize: s.fontSize, fontFamily: s.fontFamily.split(',')[0], fontWeight: s.fontWeight, letterSpacing: s.letterSpacing, color: toHex(s.color) });
      }
      if ((tag === 'button' || tag === 'a') && toHex(s.backgroundColor) && ctas.length < 8) {
        ctas.push({ text: ownText.slice(0, 30), background: toHex(s.backgroundColor), color: toHex(s.color), radius: s.borderTopLeftRadius, padding: `${s.paddingTop} ${s.paddingLeft}`, height: `${Math.round(r.height)}px`, fontSize: s.fontSize, fontWeight: s.fontWeight });
      }
    }
  }

  // Many sites already define their tokens as CSS custom properties.
  const cssVars = {};
  for (const sheet of [...document.styleSheets]) {
    let rules;
    try { rules = sheet.cssRules; } catch { continue; } // cross-origin sheet
    for (const rule of [...(rules || [])]) {
      if (!rule.style || !/^(:root|html|body|\[data-theme[^\]]*\]|\.dark)$/.test((rule.selectorText || '').trim())) continue;
      for (const prop of [...rule.style]) {
        if (prop.startsWith('--') && Object.keys(cssVars).length < 150) cssVars[prop] = rule.style.getPropertyValue(prop).trim();
      }
    }
  }

  const pageBg = toHex(getComputedStyle(document.body).backgroundColor) || toHex(getComputedStyle(document.documentElement).backgroundColor);
  return {
    url: location.href,
    viewport: `${vw}x${window.innerHeight}`,
    pageBackground: pageBg,
    fontsLoaded: [...new Set([...document.fonts].filter((f) => f.status === 'loaded').map((f) => `${f.family.replace(/["']/g, '')} ${f.weight}`))].slice(0, 20),
    headings,
    ctas,
    cssVariables: cssVars,
    ranked: Object.fromEntries(Object.entries(t).map(([k, v]) => [k, top(v)])),
  };
}
