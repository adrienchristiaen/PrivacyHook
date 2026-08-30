# holdthedoor marketing website — design spec

Date: 2026-08-30
Status: approved, ready for implementation plan

## Purpose

A public-facing marketing/landing site for holdthedoor, modeled on
[caveman.so](https://caveman.so/)'s style and structure, so people can discover
and evaluate the product without cloning the repo and reading the README.
Target audience: developers and companies evaluating AI-CLI security tooling.

## Non-goals

- Not a docs-hosting replacement for the README — `/docs` reorganizes existing
  README content, it doesn't introduce new technical content.
- No invented social proof, stats, case studies, "trusted by" logos, or a
  savings calculator. caveman.so has these; holdthedoor has no real content
  for them yet, so they're omitted rather than faked. Add them later, once
  they're real.
- No backend, no database, no user accounts. Fully static/SSG.
- No pricing numbers — holdthedoor's core is free/MIT; the only "pricing"
  content is an honest statement of today's licensing (MIT) and tomorrow's
  planned BSL-1.1 engine component (see `LICENSING.md` in the product repo),
  with a contact/GitHub CTA for enterprise interest. No invented tiers or
  dollar amounts.

## Repo & stack

- **New, separate repo**: `holdthedoor-site` (kept apart from the product repo
  — marketing content and product code have different contributors/release
  cadences).
- **Framework**: Next.js, App Router.
- **Styling**: Tailwind CSS.
- **Fonts**: Geist / Geist Mono via `next/font` (same family caveman.so uses;
  SIL Open Font License, freely usable).
- **Deployment**: Vercel. Domain choice deferred (candidate:
  `holdthedoor.dev`) — not a blocker for building the site.
- **i18n**: `next-intl`, locale-prefixed routing (`en` default with no
  prefix, `fr` at `/fr/...`), messages in `messages/en.json` /
  `messages/fr.json`. Translations written by hand (no embedded
  auto-translation), covering the landing page and `/pricing` only.

## Pages

### `/` — landing page

Single scrollable page, sections in order:

1. **Hero** — product name, one-line pitch, primary CTA (GitHub / install
   command copy button).
2. **Install** — tabbed code snippets per supported CLI: Claude Code, Codex,
   Gemini, OpenCode (mirrors the README's per-CLI install instructions).
3. **Features** — 4 numbered blocks: block sensitive paths/patterns, redact
   secrets in tool output, policy engine (custom block rules), HMAC-chained
   audit log. Content sourced from the product README's "What it does" table.
4. **Supported CLIs** — the CLI adapter table from the README (Claude Code,
   Codex, Gemini, OpenCode; hook mechanism per CLI).
5. **Live demo** — the existing `docs/img/monitor-screenshot.png` and the
   verified terminal transcript block from the README, styled as a
   terminal-look component (dark background, monospace, no invented content).
6. **Licensing teaser** — short honest paragraph: MIT today, planned BSL-1.1
   engine component later (per `LICENSING.md`), link to `/pricing` for
   detail.
7. **Final CTA** — repeat of hero CTA.
8. **Footer** — tagline, links (GitHub, docs, pricing), locale switcher.

### `/docs`

Reorganizes existing README sections (Installation, Architecture, Threat
model, CLI adapter mapping) into navigable subpages. **English only at
launch** — translating fast-changing technical docs line-by-line isn't worth
the maintenance cost yet. If a user visits `/fr/docs`, content renders in
English with a small "docs available in English only" banner; the language
switcher stays visible and functional for the rest of the site.

### `/pricing`

Explains: MIT core is free forever; a future, more detailed dashboard/engine
component is planned under BSL-1.1 (same free-for-self-host /
restricted-for-hosted-resale model already documented in the product repo's
`LICENSING.md`); no price list since nothing paid exists yet. CTA: GitHub
link / contact for enterprise interest.

## Visual identity / logo

- **Concept**: shield/wall direction (chosen over a door icon or abstract
  wordmark-only option) — a simple geometric shield containing a stylized
  door/bar shape, keeping the "hold the door" reference while reading as a
  generic security tool at a glance.
- **Format**: single SVG source, two renders:
  - Icon-only (favicon, GitHub avatar, mobile nav) — monochrome, legible at
    16×16.
  - Icon + wordmark (`holdthedoor` set in Geist Mono) — desktop nav, OG
    image, README.
- **Palette**: dark/terminal theme (near-black background, single accent
  color — green or amber, terminal-style). Exact accent color to be decided
  during implementation by comparing options side by side; not blocking the
  rest of the design.
- No complex figurative illustration — matches caveman.so's sober dev-tool
  tone.

## Content sourcing (no invented content)

| Site content | Source |
|---|---|
| Supported CLIs table, features list | Product repo `README.md` |
| Monitor screenshot, terminal transcript | Product repo `docs/img/monitor-screenshot.png` + README's verified demo transcript, reused as-is |
| `/docs` content | Reorganized from README (Installation, Architecture, Threat model, CLI adapter mapping) |
| `/pricing` / licensing teaser | Product repo `LICENSING.md` |
| French landing/pricing copy | Hand-translated for this site; existing `README.fr.md` in the product repo can inform tone/terminology but isn't copied verbatim (README structure differs from landing-page copy) |

## Testing

- `next build` must pass (type-check + static generation) as the baseline
  gate.
- No Playwright/e2e suite for v1 — static content, low behavioral surface
  (locale switch, tab component, copy-to-clipboard button are the only
  interactive bits, verified manually).

## Explicitly deferred (not this spec)

- Proxy-network fallback mode for CLIs without hook/plugin APIs (potential
  future BSL "engine" component) — unrelated to the website, tracked
  separately, not part of this site's scope.
- Domain purchase/DNS configuration.
- `/docs` French translation.
- Any social-proof, research/labs, news, or interactive-calculator sections
  — add only once real content (users, research, announcements) exists.
