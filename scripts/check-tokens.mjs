#!/usr/bin/env node
// Token drift check: finds UI code that ignores DESIGN.md.
// Zero dependencies. Run from the folder that holds DESIGN.md:
//   node scripts/check-tokens.mjs            # scans the whole project (skips .venv, node_modules...)
//   node scripts/check-tokens.mjs day1 ui    # scan specific paths
//   node scripts/check-tokens.mjs --warn-only
// Exit 1 when anything is found or when no files were scanned (0 with --warn-only).
// Silence one line on purpose with a `check-tokens-ignore` comment on it.

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { extname, join, relative } from 'node:path';

const args = process.argv.slice(2);
const warnOnly = args.includes('--warn-only');
const roots = args.filter((a) => !a.startsWith('--'));
if (!roots.length) roots.push('.');
const EXT = new Set(['.tsx', '.jsx', '.ts', '.js', '.mjs', '.vue', '.svelte', '.astro', '.html', '.css', '.scss', '.py', '.toml']);
const HASH_COMMENT_EXT = new Set(['.py', '.toml']);
const SKIP_DIRS = new Set([
  'node_modules', '.next', 'dist', 'build', '.git', '.claude', '.design', '.impeccable', 'coverage', 'scripts',
  '.venv', 'venv', 'env', '__pycache__', 'site-packages', '.pytest_cache', '.ruff_cache', '.mypy_cache',
  '.ipynb_checkpoints', '.tox', '.uv-cache',
]);
const MAX_PER_RULE = 15;
const done = (code) => process.exit(warnOnly ? 0 : code);

// Palette = every hex value in DESIGN.md front matter.
const normalize = (hex) => {
  let h = hex.slice(1).toLowerCase();
  if (h.length === 3 || h.length === 4) h = [...h].map((c) => c + c).join('');
  return '#' + h.slice(0, 6);
};
if (!existsSync('DESIGN.md')) {
  console.error('No DESIGN.md in the current folder. Run this from the project root.');
  done(1);
}
const frontMatter = (readFileSync('DESIGN.md', 'utf8').match(/^---\r?\n([\s\S]*?)\r?\n---/) || [, ''])[1];
const palette = new Set((frontMatter.match(/#[0-9a-fA-F]{3,8}\b/g) || []).map(normalize));

const TW_PALETTE = 'slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose';
const rules = [
  {
    id: 'off-palette-color',
    why: 'hex color not in DESIGN.md; use a token (Streamlit: config.toml [theme], charts: chartCategoricalColors)',
    test: (line) => {
      if (/href=|url\(|src=/.test(line)) return null;
      const bad = (line.match(/(?<![\w&/-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/g) || []).filter(
        (h) => !palette.has(normalize(h)),
      );
      return bad.length ? bad.join(' ') : null;
    },
  },
  {
    id: 'css-injection',
    why: 'CSS injected into Streamlit breaks on upgrades; use config.toml [theme] or layout primitives',
    only: '.py',
    re: /<style\b|\bstyle\s*=\s*\\?["'][^"']*:/g,
  },
  {
    id: 'raw-tailwind-palette',
    why: 'default Tailwind color; map it to a token (bg-primary, text-muted...)',
    re: new RegExp(`\\b(?:bg|text|border|from|via|to|ring|fill|stroke|outline|divide|shadow|accent|decoration|placeholder)-(?:${TW_PALETTE})-\\d{2,3}\\b`, 'g'),
  },
  {
    id: 'arbitrary-value',
    why: 'one-off value; use the type, spacing or radius scale',
    re: /\b(?:text|bg|p[xytrbl]?|m[xytrbl]?|gap|space-[xy]|rounded(?:-[a-z]+)?|leading|tracking|border|shadow)-\[[^\]\s]+\]/g,
  },
  {
    id: 'gradient',
    why: 'DESIGN.md bans gradients and gradient text',
    re: /\bbg-(?:gradient|linear|radial|conic)-[\w-]+|(?:linear|radial|conic)-gradient\(|\bbg-clip-text\b/g,
  },
  {
    id: 'banned-font',
    why: 'default AI font; use the DESIGN.md families',
    test: (line) =>
      /font-?family|fontFamily|next\/font|fonts\.googleapis|@fontsource|\b(?:font|headingFont|codeFont|family)\s*=/i.test(line) &&
      (line.match(/\b(?:Inter|Roboto|Arial|Open[ +]Sans|Poppins|system-ui)\b/) || [])[0],
  },
  {
    id: 'slop-copy',
    why: 'hype copy; say what the product actually does',
    re: /\b(?:supercharge[sd]?|seamless(?:ly)?|unlock (?:your|the power|new)|effortless(?:ly)?|revolutioni[sz]e[sd]?|game[- ]chang(?:er|ing)|cutting[- ]edge|next[- ]gen(?:eration)?|unleash(?:es)?|elevate your|empower(?:s|ing)?|lorem ipsum)\b/gi, // check-tokens-ignore
  },
];

const files = [];
const walk = (p) => {
  if (!existsSync(p)) return console.error(`skipping ${p}: not found`);
  const st = statSync(p);
  if (st.isDirectory()) {
    for (const name of readdirSync(p)) if (!SKIP_DIRS.has(name)) walk(join(p, name));
  } else if (EXT.has(extname(p))) files.push(p);
};
roots.forEach(walk);

if (!files.length) {
  console.log(`No UI files found under ${roots.map((r) => `'${r}'`).join(', ')}, so nothing was checked. Pass the folder your app lives in.`);
  done(1);
}

const findings = Object.fromEntries(rules.map((r) => [r.id, []]));
for (const file of files) {
  const ext = extname(file);
  const hashComments = HASH_COMMENT_EXT.has(ext);
  readFileSync(file, 'utf8').split('\n').forEach((line, i) => {
    if (line.includes('check-tokens-ignore')) return;
    if (hashComments && /^\s*#/.test(line)) return; // whole-line Python/TOML comment
    for (const rule of rules) {
      if (rule.only && rule.only !== ext) continue;
      const hit = rule.test ? rule.test(line) : [...new Set(line.match(rule.re) || [])].join(' ');
      if (hit) findings[rule.id].push(`${relative('.', file)}:${i + 1}  ${hit.length > 80 ? hit.slice(0, 77) + '...' : hit}`);
    }
  });
}

let total = 0;
for (const rule of rules) {
  const list = findings[rule.id];
  if (!list.length) continue;
  total += list.length;
  console.log(`\n${rule.id} (${list.length}): ${rule.why}`);
  list.slice(0, MAX_PER_RULE).forEach((f) => console.log('  ' + f));
  if (list.length > MAX_PER_RULE) console.log(`  ...and ${list.length - MAX_PER_RULE} more`);
}
console.log(
  total
    ? `\n${total} finding(s) in ${files.length} files. Palette: ${palette.size} colors from DESIGN.md.`
    : `Clean: ${files.length} files match DESIGN.md (${palette.size} palette colors).`,
);
done(total ? 1 : 0);
