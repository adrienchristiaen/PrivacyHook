# holdthedoor marketing website — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and ship a static Next.js marketing site for holdthedoor (new repo `holdthedoor-site`), styled like caveman.so, with an `en`/`fr` landing + pricing, English-only docs, and a shield/wall logo — all content sourced from the existing product repo's README/LICENSING.md, no invented stats or pricing.

**Architecture:** Next.js App Router site with a `[locale]` segment (via `next-intl`) wrapping three routes — `/` (landing, all sections), `/docs` (English-only, static content reorganized from the product README), `/pricing` (from `LICENSING.md`). Content lives in small typed TS data modules under `src/content/`, consumed by presentational components under `src/components/`. No backend, no database — fully statically generated, deployed to Vercel.

**Tech Stack:** Next.js 14 (App Router) · TypeScript · Tailwind CSS v3 · `next-intl` v3 · Geist / Geist Mono via `next/font/google` · Vitest + React Testing Library (smoke tests only, per spec) · npm

**Spec:** `docs/superpowers/specs/2026-08-30-holdthedoor-website-design.md` (in the `holdthedoor` product repo — this plan builds a *separate* repo, `holdthedoor-site`; read the spec for the full rationale before starting)

## Global Constraints

- New repo: `holdthedoor-site`, separate from the product repo. All paths in this plan are relative to that new repo's root unless stated otherwise.
- No invented content: no social-proof/logos, no research/news sections, no calculator, no pricing numbers. Only reuse content sourced from the product repo (`README.md`, `LICENSING.md`, `docs/img/monitor-screenshot.png`) — copy exact text/values, don't paraphrase facts.
- i18n (`en` default unprefixed, `fr` at `/fr/...`) applies to `/` and `/pricing` only. `/docs` is English-only; visiting `/fr/docs` renders English content with a small "docs available in English only" banner.
- Fonts: Geist + Geist Mono via `next/font/google` (available there since Next.js 14.2+; if unavailable in the installed Next version, fall back to `next/font/local` with self-hosted Geist `.woff2` files — do not substitute a different font family).
- Testing gate: `npm run build` must succeed (type-check + static generation). Component smoke tests use Vitest + React Testing Library only for interactive components (tabs, copy button, locale switcher) and for the assembled landing page (renders all section headings). No e2e suite.
- Deployment target: Vercel. No domain purchase in this plan (deferred per spec).
- Product repo path referenced throughout this plan: `/Users/admin/Desktop/Dossier Perso/Projets/SKILLS/claude-wall` — read-only source of content, never written to by this plan.

---

### Task 1: Repo scaffold — Next.js + TypeScript + Tailwind + base layout

**Files:**
- Create: `holdthedoor-site/package.json`
- Create: `holdthedoor-site/tsconfig.json`
- Create: `holdthedoor-site/next.config.ts`
- Create: `holdthedoor-site/tailwind.config.ts`
- Create: `holdthedoor-site/postcss.config.mjs`
- Create: `holdthedoor-site/vitest.config.ts`
- Create: `holdthedoor-site/src/app/layout.tsx`
- Create: `holdthedoor-site/src/app/globals.css`
- Create: `holdthedoor-site/src/app/page.tsx` (temporary root redirect placeholder, replaced in Task 2)
- Create: `holdthedoor-site/.gitignore`

**Interfaces:**
- Produces: project builds with `npm run build`; Tailwind classes available in any `.tsx` under `src/`; Vitest runnable via `npm run test`.

- [ ] **Step 1: Initialize the repo and Next.js project**

```bash
mkdir -p "holdthedoor-site"
cd "holdthedoor-site"
git init
npx create-next-app@14 . --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --use-npm --no-turbopack
```

When prompted, accept defaults. This scaffolds `package.json`, `tsconfig.json`, `next.config.ts`, `tailwind.config.ts`, `postcss.config.mjs`, `src/app/layout.tsx`, `src/app/page.tsx`, `src/app/globals.css`, `.gitignore` already wired together — the remaining steps only adjust generated content, not re-create it from scratch.

- [ ] **Step 2: Add Vitest + React Testing Library**

```bash
npm install -D vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/jest-dom
```

Create `vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
```

Create `vitest.setup.ts`:

```typescript
import "@testing-library/jest-dom/vitest";
```

Add to `package.json` `"scripts"`:

```json
"test": "vitest run"
```

- [ ] **Step 3: Write a trivial smoke test to prove the toolchain works**

Create `src/app/page.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";

describe("toolchain smoke test", () => {
  it("runs", () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 4: Run the smoke test**

Run: `npm run test`
Expected: PASS (1 test)

- [ ] **Step 5: Verify the production build works**

Run: `npm run build`
Expected: build succeeds, no type errors.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: scaffold Next.js + TypeScript + Tailwind + Vitest"
```

---

### Task 2: next-intl locale routing

**Files:**
- Create: `holdthedoor-site/src/i18n/routing.ts`
- Create: `holdthedoor-site/src/i18n/request.ts`
- Create: `holdthedoor-site/src/i18n/navigation.ts`
- Create: `holdthedoor-site/src/middleware.ts`
- Create: `holdthedoor-site/messages/en.json`
- Create: `holdthedoor-site/messages/fr.json`
- Modify: `holdthedoor-site/next.config.ts`
- Modify: `holdthedoor-site/src/app/layout.tsx` → replaced by `holdthedoor-site/src/app/[locale]/layout.tsx`
- Delete: `holdthedoor-site/src/app/page.tsx`, `holdthedoor-site/src/app/page.test.tsx` (superseded by `[locale]` versions)
- Create: `holdthedoor-site/src/app/[locale]/page.tsx`
- Create: `holdthedoor-site/src/app/[locale]/page.test.tsx`

**Interfaces:**
- Consumes: Tailwind/globals setup from Task 1 (`src/app/globals.css`).
- Produces: `routing.locales = ["en", "fr"] as const`, `routing.defaultLocale = "en"`; `Link`, `redirect`, `usePathname`, `useRouter` re-exported from `src/i18n/navigation.ts` (locale-aware wrappers other tasks import instead of `next/link`/`next/navigation`); translation keys read via `useTranslations(namespace)` from `next-intl` in client components and `getTranslations(namespace)` in server components.

- [ ] **Step 1: Install next-intl**

```bash
npm install next-intl
```

- [ ] **Step 2: Define routing config**

Create `src/i18n/routing.ts`:

```typescript
import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: ["en", "fr"] as const,
  defaultLocale: "en",
});

export type Locale = (typeof routing.locales)[number];
```

- [ ] **Step 3: Define request config**

Create `src/i18n/request.ts`:

```typescript
import { getRequestConfig } from "next-intl/server";
import { hasLocale } from "next-intl";
import { routing } from "./routing";

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested)
    ? requested
    : routing.defaultLocale;

  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
  };
});
```

- [ ] **Step 4: Define locale-aware navigation wrappers**

Create `src/i18n/navigation.ts`:

```typescript
import { createNavigation } from "next-intl/navigation";
import { routing } from "./routing";

export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
```

- [ ] **Step 5: Wire the middleware**

Create `src/middleware.ts`:

```typescript
import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  matcher: ["/((?!api|trpc|_next|_vercel|.*\\..*).*)"],
};
```

- [ ] **Step 6: Wire the Next config plugin**

Modify `next.config.ts` — wrap the existing exported config:

```typescript
import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {};

export default withNextIntl(nextConfig);
```

- [ ] **Step 7: Seed messages files**

Create `messages/en.json`:

```json
{
  "Landing": {
    "heroPlaceholder": "holdthedoor — coming together"
  }
}
```

Create `messages/fr.json`:

```json
{
  "Landing": {
    "heroPlaceholder": "holdthedoor — en construction"
  }
}
```

- [ ] **Step 8: Move root files into the `[locale]` segment**

```bash
rm src/app/page.tsx src/app/page.test.tsx
mkdir -p "src/app/[locale]"
mv src/app/layout.tsx "src/app/[locale]/layout.tsx"
```

Replace `src/app/[locale]/layout.tsx` with:

```typescript
import type { Metadata } from "next";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { notFound } from "next/navigation";
import { routing } from "@/i18n/routing";
import "../globals.css";

export const metadata: Metadata = {
  title: "holdthedoor",
  description:
    "Privacy-first security layer for AI coding CLIs — deterministic hooks the LLM cannot bypass.",
};

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) {
    notFound();
  }

  return (
    <html lang={locale}>
      <body>
        <NextIntlClientProvider>{children}</NextIntlClientProvider>
      </body>
    </html>
  );
}
```

Create a minimal root layout Next.js still requires at `src/app/layout.tsx` (delegates entirely to the `[locale]` segment, renders nothing of its own):

```typescript
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
```

Create `src/app/[locale]/page.tsx`:

```typescript
import { useTranslations } from "next-intl";

export default function LandingPage() {
  const t = useTranslations("Landing");
  return <main>{t("heroPlaceholder")}</main>;
}
```

- [ ] **Step 9: Write a locale routing smoke test**

Create `src/app/[locale]/page.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "../../../messages/en.json";
import LandingPage from "./page";

describe("LandingPage", () => {
  it("renders the English placeholder via next-intl", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <LandingPage />
      </NextIntlClientProvider>,
    );
    expect(
      screen.getByText("holdthedoor — coming together"),
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 10: Run tests and build**

Run: `npm run test`
Expected: PASS (2 tests total: toolchain smoke test replaced by this one, plus this new one — confirm only this file's test remains since `page.test.tsx` at the old path was deleted in Step 8)

Run: `npm run build`
Expected: succeeds, generates `/`, `/fr` (and other locale-prefixed routes as `[locale]` static params).

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat: add next-intl locale routing (en default, fr)"
```

---

### Task 3: Logo assets + Nav shell

**Files:**
- Create: `holdthedoor-site/public/logo-icon.svg`
- Create: `holdthedoor-site/public/logo-wordmark.svg`
- Create: `holdthedoor-site/public/favicon.ico`
- Create: `holdthedoor-site/src/components/Nav.tsx`
- Create: `holdthedoor-site/src/components/Nav.test.tsx`
- Modify: `holdthedoor-site/src/app/[locale]/layout.tsx` (render `<Nav />` above `{children}`)
- Modify: `holdthedoor-site/messages/en.json`, `holdthedoor-site/messages/fr.json` (add `"Nav"` namespace)

**Interfaces:**
- Produces: `Nav` component (no props — reads locale/pathname internally via `src/i18n/navigation.ts`), rendered once in the locale layout so every page gets it.

- [ ] **Step 1: Create the shield/wall icon SVG**

Create `public/logo-icon.svg` — a simple geometric shield containing a stylized door/bar, single-color (`currentColor`) so it inherits text color, legible at 16×16:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none">
  <path
    d="M16 2 L28 7 V15 C28 22 23 27 16 30 C9 27 4 22 4 15 V7 Z"
    stroke="currentColor"
    stroke-width="2"
    stroke-linejoin="round"
  />
  <rect x="13" y="12" width="6" height="12" rx="1" stroke="currentColor" stroke-width="2" />
  <line x1="16" y1="15" x2="16" y2="17" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
</svg>
```

- [ ] **Step 2: Create the icon + wordmark SVG**

Create `public/logo-wordmark.svg` — icon on the left, `holdthedoor` set in monospace on the right, single color:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 220 32" fill="none">
  <g>
    <path
      d="M16 2 L28 7 V15 C28 22 23 27 16 30 C9 27 4 22 4 15 V7 Z"
      stroke="currentColor"
      stroke-width="2"
      stroke-linejoin="round"
    />
    <rect x="13" y="12" width="6" height="12" rx="1" stroke="currentColor" stroke-width="2" />
    <line x1="16" y1="15" x2="16" y2="17" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
  </g>
  <text
    x="40"
    y="22"
    font-family="ui-monospace, SFMono-Regular, monospace"
    font-size="18"
    fill="currentColor"
  >holdthedoor</text>
</svg>
```

- [ ] **Step 3: Generate a favicon from the icon SVG**

```bash
npx -y sharp-cli -i public/logo-icon.svg -o public/favicon-32.png resize 32 32
```

If `sharp-cli` is unavailable in the environment, use any installed image tool to rasterize `public/logo-icon.svg` to a 32×32 PNG, then convert that PNG to `public/favicon.ico` (e.g. `npx -y png-to-ico public/favicon-32.png > public/favicon.ico`). Either path must end with a working `public/favicon.ico`.

- [ ] **Step 4: Add Nav translation keys**

Modify `messages/en.json`, add:

```json
"Nav": {
  "docs": "Docs",
  "pricing": "Pricing",
  "github": "GitHub"
}
```

Modify `messages/fr.json`, add:

```json
"Nav": {
  "docs": "Docs",
  "pricing": "Tarifs",
  "github": "GitHub"
}
```

- [ ] **Step 5: Build the Nav component**

Create `src/components/Nav.tsx`:

```typescript
import { useTranslations } from "next-intl";
import Image from "next/image";
import { Link } from "@/i18n/navigation";

export function Nav() {
  const t = useTranslations("Nav");

  return (
    <nav className="flex items-center justify-between px-6 py-4 border-b border-neutral-800">
      <Link href="/" className="flex items-center gap-2">
        <Image src="/logo-wordmark.svg" alt="holdthedoor" width={160} height={24} />
      </Link>
      <div className="flex items-center gap-6 text-sm">
        <Link href="/docs">{t("docs")}</Link>
        <Link href="/pricing">{t("pricing")}</Link>
        <a href="https://github.com/adrienchristiaen/holdthedoor" target="_blank" rel="noreferrer">
          {t("github")}
        </a>
      </div>
    </nav>
  );
}
```

- [ ] **Step 6: Render Nav in the locale layout**

Modify `src/app/[locale]/layout.tsx` — import `Nav` and render it as the first child inside `<NextIntlClientProvider>`, before `{children}`:

```typescript
import { Nav } from "@/components/Nav";
// ...
return (
  <html lang={locale}>
    <body>
      <NextIntlClientProvider>
        <Nav />
        {children}
      </NextIntlClientProvider>
    </body>
  </html>
);
```

- [ ] **Step 7: Write a Nav smoke test**

Create `src/components/Nav.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "../../messages/en.json";
import { Nav } from "./Nav";

describe("Nav", () => {
  it("renders Docs and Pricing links", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <Nav />
      </NextIntlClientProvider>,
    );
    expect(screen.getByText("Docs")).toBeInTheDocument();
    expect(screen.getByText("Pricing")).toBeInTheDocument();
  });
});
```

- [ ] **Step 8: Run tests and build**

Run: `npm run test`
Expected: PASS (all tests, including new Nav test)

Run: `npm run build`
Expected: succeeds

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: add shield/wall logo assets and site nav"
```

---

### Task 4: Content data modules (sourced from product README)

**Files:**
- Create: `holdthedoor-site/src/content/clis.ts`
- Create: `holdthedoor-site/src/content/features.ts`
- Create: `holdthedoor-site/src/content/install-snippets.ts`
- Create: `holdthedoor-site/src/content/demo-transcript.ts`
- Create: `holdthedoor-site/src/content/clis.test.ts`

**Interfaces:**
- Produces:
  - `CLI_SUPPORT: { id: "claude" | "codex" | "gemini" | "opencode"; name: string; hookSupport: string; notes: string }[]` from `clis.ts`
  - `FEATURES: { title: string; description: string }[]` (4 items) from `features.ts`
  - `INSTALL_SNIPPETS: Record<"claude" | "codex" | "gemini" | "opencode", { label: string; command: string }>` from `install-snippets.ts`
  - `DEMO_TRANSCRIPT: string` (the literal abridged transcript block) from `demo-transcript.ts`
  - These are consumed by Tasks 6–9's components.

- [ ] **Step 1: Write the CLI support data, sourced verbatim from README's "Supported CLIs" table**

Create `src/content/clis.ts`:

```typescript
export type CliId = "claude" | "codex" | "gemini" | "opencode";

export interface CliSupport {
  id: CliId;
  name: string;
  hookSupport: string;
  notes: string;
}

export const CLI_SUPPORT: CliSupport[] = [
  {
    id: "claude",
    name: "Claude Code",
    hookSupport: "Full (3 hooks)",
    notes: "PostToolUse, PreToolUse, UserPromptSubmit",
  },
  {
    id: "codex",
    name: "OpenAI Codex CLI",
    hookSupport: "Full (3 hooks)",
    notes: "Same hook format as Claude Code",
  },
  {
    id: "gemini",
    name: "Gemini CLI",
    hookSupport: "Partial (2 hooks)",
    notes: "BeforeTool, AfterTool — no prompt hook",
  },
  {
    id: "opencode",
    name: "OpenCode",
    hookSupport: "Partial (2 hooks)",
    notes:
      "JS plugin bridging tool.execute.before / tool.execute.after to the same Python hooks — no prompt hook",
  },
];
```

- [ ] **Step 2: Write the features data, sourced from README's "What it does" table**

Create `src/content/features.ts`:

```typescript
export interface Feature {
  title: string;
  description: string;
}

export const FEATURES: Feature[] = [
  {
    title: "Block sensitive paths",
    description:
      "Blocks tool calls targeting .env files, SSH keys, credentials, and *.pem files before they run — exit code 2 aborts the call.",
  },
  {
    title: "Redact secrets in output",
    description:
      "Replaces detected secrets in tool output with reversible session tokens like [WALL:openai_key:1] before the LLM ever sees them.",
  },
  {
    title: "Custom policy engine",
    description:
      "Define your own allow/warn/block rules by command regex or path glob — no code changes, no redeploy.",
  },
  {
    title: "HMAC-chained audit log",
    description:
      "Every redaction, block, warning, and policy match is recorded in a tamper-evident log. holdthedoor audit --verify proves the chain is intact.",
  },
];
```

- [ ] **Step 3: Write the install snippets, sourced from README's "Installation" section**

Create `src/content/install-snippets.ts`:

```typescript
import type { CliId } from "./clis";

export interface InstallSnippet {
  label: string;
  command: string;
}

export const INSTALL_SNIPPETS: Record<CliId, InstallSnippet> = {
  claude: {
    label: "Claude Code",
    command:
      "pipx install git+https://github.com/adrienchristiaen/holdthedoor.git\nholdthedoor install --cli claude",
  },
  codex: {
    label: "Codex CLI",
    command:
      "pipx install git+https://github.com/adrienchristiaen/holdthedoor.git\nholdthedoor install --cli codex",
  },
  gemini: {
    label: "Gemini CLI",
    command:
      "pipx install git+https://github.com/adrienchristiaen/holdthedoor.git\nholdthedoor install --cli gemini",
  },
  opencode: {
    label: "OpenCode",
    command:
      "pipx install git+https://github.com/adrienchristiaen/holdthedoor.git\nholdthedoor install --cli opencode",
  },
};
```

- [ ] **Step 4: Write the demo transcript, copied verbatim from README's "End-to-end demo" section**

Create `src/content/demo-transcript.ts`:

```typescript
export const DEMO_TRANSCRIPT = `=== 1. PostToolUse redact ===
{"hookSpecificOutput": {"hookEventName": "PostToolUse",
  "updatedToolOutput": "OPENAI_API_KEY=[WALL:openai_key:1]\\nemail=[WALL:email:1]"}}

=== 2. PreToolUse block .env ===
{"decision": "block", "reason": "path '.env' blocked: filename '.env' is sensitive"}
blocked as expected (exit 2)

=== 3. UserPromptSubmit warn ===
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
  "additionalContext": "⚠ holdthedoor: 1 sensitive value(s) detected in your prompt
  (categories: email). The prompt was sent unchanged, but tokens have been recorded
  for \`holdthedoor reveal\`."}}

=== 8. CLI: audit --verify ===
SESSION AUDIT  —  2 events
────────────────────────────────────────────────────────────────
  1 blocked · 1 warned · 1 values replaced with [WALL:*] tokens
  ✓ chain intact`;
```

- [ ] **Step 5: Write a data-shape smoke test**

Create `src/content/clis.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { CLI_SUPPORT } from "./clis";
import { FEATURES } from "./features";
import { INSTALL_SNIPPETS } from "./install-snippets";

describe("content data modules", () => {
  it("has exactly 4 supported CLIs", () => {
    expect(CLI_SUPPORT).toHaveLength(4);
    expect(CLI_SUPPORT.map((c) => c.id)).toEqual([
      "claude",
      "codex",
      "gemini",
      "opencode",
    ]);
  });

  it("has exactly 4 features", () => {
    expect(FEATURES).toHaveLength(4);
  });

  it("has an install snippet for every supported CLI", () => {
    for (const cli of CLI_SUPPORT) {
      expect(INSTALL_SNIPPETS[cli.id]).toBeDefined();
      expect(INSTALL_SNIPPETS[cli.id].command).toContain("holdthedoor install");
    }
  });
});
```

- [ ] **Step 6: Run tests and build**

Run: `npm run test`
Expected: PASS

Run: `npm run build`
Expected: succeeds

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add content data modules sourced from product README"
```

---

### Task 5: Hero section

**Files:**
- Create: `holdthedoor-site/src/components/Hero.tsx`
- Create: `holdthedoor-site/src/components/Hero.test.tsx`
- Modify: `holdthedoor-site/messages/en.json`, `holdthedoor-site/messages/fr.json` (add `"Hero"` namespace)

**Interfaces:**
- Produces: `Hero` component (no props), rendered by `page.tsx` in Task 11.

- [ ] **Step 1: Add Hero translation keys**

Modify `messages/en.json`, add:

```json
"Hero": {
  "tagline": "Privacy-first security layer for AI coding CLIs",
  "subline": "Deterministic hooks the LLM cannot bypass — secrets get redacted, sensitive files get blocked, prompts get scanned, and every tool call can be governed by rules you define.",
  "cta": "View on GitHub"
}
```

Modify `messages/fr.json`, add (hand-translated, not machine-translated):

```json
"Hero": {
  "tagline": "Couche de sécurité orientée confidentialité pour les CLI de code IA",
  "subline": "Des hooks déterministes que le LLM ne peut pas contourner — les secrets sont masqués, les fichiers sensibles bloqués, les prompts scannés, et chaque appel d'outil peut être gouverné par vos propres règles.",
  "cta": "Voir sur GitHub"
}
```

- [ ] **Step 2: Build the Hero component**

Create `src/components/Hero.tsx`:

```typescript
import { useTranslations } from "next-intl";

export function Hero() {
  const t = useTranslations("Hero");

  return (
    <section className="px-6 py-24 text-center max-w-3xl mx-auto">
      <h1 className="text-4xl font-mono font-semibold mb-6">
        {t("tagline")}
      </h1>
      <p className="text-lg text-neutral-400 mb-8">{t("subline")}</p>
      <a
        href="https://github.com/adrienchristiaen/holdthedoor"
        target="_blank"
        rel="noreferrer"
        className="inline-block px-6 py-3 rounded-md bg-neutral-100 text-neutral-900 font-medium"
      >
        {t("cta")}
      </a>
    </section>
  );
}
```

- [ ] **Step 3: Write a Hero smoke test**

Create `src/components/Hero.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "../../messages/en.json";
import { Hero } from "./Hero";

describe("Hero", () => {
  it("renders the tagline and GitHub CTA", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <Hero />
      </NextIntlClientProvider>,
    );
    expect(
      screen.getByText("Privacy-first security layer for AI coding CLIs"),
    ).toBeInTheDocument();
    expect(screen.getByText("View on GitHub")).toHaveAttribute(
      "href",
      "https://github.com/adrienchristiaen/holdthedoor",
    );
  });
});
```

- [ ] **Step 4: Run tests and build**

Run: `npm run test`
Expected: PASS

Run: `npm run build`
Expected: succeeds

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add Hero section"
```

---

### Task 6: Install tabs (interactive — tab switch + copy button)

**Files:**
- Create: `holdthedoor-site/src/components/CopyButton.tsx`
- Create: `holdthedoor-site/src/components/CopyButton.test.tsx`
- Create: `holdthedoor-site/src/components/InstallTabs.tsx`
- Create: `holdthedoor-site/src/components/InstallTabs.test.tsx`
- Modify: `holdthedoor-site/messages/en.json`, `holdthedoor-site/messages/fr.json` (add `"Install"` namespace)

**Interfaces:**
- Consumes: `INSTALL_SNIPPETS`, `CliId` from `src/content/install-snippets.ts` and `src/content/clis.ts` (Task 4).
- Produces: `CopyButton` component (`props: { text: string }`), `InstallTabs` component (no props), both rendered by `page.tsx` in Task 11.

- [ ] **Step 1: Add Install translation keys**

Modify `messages/en.json`, add:

```json
"Install": {
  "heading": "Install",
  "copy": "Copy",
  "copied": "Copied"
}
```

Modify `messages/fr.json`, add:

```json
"Install": {
  "heading": "Installation",
  "copy": "Copier",
  "copied": "Copié"
}
```

- [ ] **Step 2: Write the failing CopyButton test**

Create `src/components/CopyButton.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "../../messages/en.json";
import { CopyButton } from "./CopyButton";

describe("CopyButton", () => {
  beforeEach(() => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("copies the given text and shows a confirmation", async () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <CopyButton text="holdthedoor install" />
      </NextIntlClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "holdthedoor install",
    );
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm run test -- CopyButton`
Expected: FAIL — `Cannot find module './CopyButton'`

- [ ] **Step 4: Implement CopyButton**

Create `src/components/CopyButton.tsx`:

```typescript
"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

export function CopyButton({ text }: { text: string }) {
  const t = useTranslations("Install");
  const [copied, setCopied] = useState(false);

  async function handleClick() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <button
      onClick={handleClick}
      className="text-xs px-2 py-1 rounded border border-neutral-700"
    >
      {copied ? t("copied") : t("copy")}
    </button>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm run test -- CopyButton`
Expected: PASS

- [ ] **Step 6: Write the failing InstallTabs test**

Create `src/components/InstallTabs.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "../../messages/en.json";
import { InstallTabs } from "./InstallTabs";

describe("InstallTabs", () => {
  it("shows Claude Code's command by default and switches to Codex's on click", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <InstallTabs />
      </NextIntlClientProvider>,
    );
    expect(screen.getByText(/holdthedoor install --cli claude/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Codex CLI" }));
    expect(screen.getByText(/holdthedoor install --cli codex/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 7: Run test to verify it fails**

Run: `npm run test -- InstallTabs`
Expected: FAIL — `Cannot find module './InstallTabs'`

- [ ] **Step 8: Implement InstallTabs**

Create `src/components/InstallTabs.tsx`:

```typescript
"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { CLI_SUPPORT, type CliId } from "@/content/clis";
import { INSTALL_SNIPPETS } from "@/content/install-snippets";
import { CopyButton } from "./CopyButton";

export function InstallTabs() {
  const t = useTranslations("Install");
  const [active, setActive] = useState<CliId>("claude");
  const snippet = INSTALL_SNIPPETS[active];

  return (
    <section className="px-6 py-16 max-w-3xl mx-auto">
      <h2 className="text-2xl font-mono mb-6">{t("heading")}</h2>
      <div role="tablist" className="flex gap-2 mb-4">
        {CLI_SUPPORT.map((cli) => (
          <button
            key={cli.id}
            role="tab"
            aria-selected={active === cli.id}
            onClick={() => setActive(cli.id)}
            className={`px-3 py-1.5 text-sm rounded ${
              active === cli.id
                ? "bg-neutral-100 text-neutral-900"
                : "bg-neutral-800 text-neutral-300"
            }`}
          >
            {cli.name}
          </button>
        ))}
      </div>
      <div className="bg-neutral-900 rounded-md p-4 flex items-start justify-between gap-4">
        <pre className="text-sm font-mono whitespace-pre-wrap">
          {snippet.command}
        </pre>
        <CopyButton text={snippet.command} />
      </div>
    </section>
  );
}
```

- [ ] **Step 9: Run test to verify it passes**

Run: `npm run test -- InstallTabs`
Expected: PASS

- [ ] **Step 10: Run full test suite and build**

Run: `npm run test`
Expected: PASS (all tests)

Run: `npm run build`
Expected: succeeds

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat: add install tabs with per-CLI snippets and copy button"
```

---

### Task 7: Features + Supported CLIs sections

**Files:**
- Create: `holdthedoor-site/src/components/Features.tsx`
- Create: `holdthedoor-site/src/components/Features.test.tsx`
- Create: `holdthedoor-site/src/components/CliTable.tsx`
- Create: `holdthedoor-site/src/components/CliTable.test.tsx`
- Modify: `holdthedoor-site/messages/en.json`, `holdthedoor-site/messages/fr.json` (add `"Features"` and `"CliTable"` namespaces)

**Interfaces:**
- Consumes: `FEATURES` from `src/content/features.ts`, `CLI_SUPPORT` from `src/content/clis.ts` (Task 4).
- Produces: `Features`, `CliTable` components (no props), rendered by `page.tsx` in Task 11.

- [ ] **Step 1: Add translation keys**

Modify `messages/en.json`, add:

```json
"Features": { "heading": "What it does" },
"CliTable": {
  "heading": "Supported CLIs",
  "cliColumn": "CLI",
  "hookColumn": "Hook support",
  "notesColumn": "Notes"
}
```

Modify `messages/fr.json`, add:

```json
"Features": { "heading": "Ce qu'il fait" },
"CliTable": {
  "heading": "CLI supportés",
  "cliColumn": "CLI",
  "hookColumn": "Support des hooks",
  "notesColumn": "Notes"
}
```

- [ ] **Step 2: Build Features component**

Create `src/components/Features.tsx`:

```typescript
import { useTranslations } from "next-intl";
import { FEATURES } from "@/content/features";

export function Features() {
  const t = useTranslations("Features");

  return (
    <section className="px-6 py-16 max-w-4xl mx-auto">
      <h2 className="text-2xl font-mono mb-8">{t("heading")}</h2>
      <ol className="grid gap-6 sm:grid-cols-2">
        {FEATURES.map((feature, i) => (
          <li key={feature.title} className="border border-neutral-800 rounded-md p-4">
            <span className="text-neutral-500 font-mono text-sm">
              {String(i + 1).padStart(2, "0")}
            </span>
            <h3 className="font-medium mt-1">{feature.title}</h3>
            <p className="text-sm text-neutral-400 mt-1">{feature.description}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
```

- [ ] **Step 3: Write Features smoke test**

Create `src/components/Features.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "../../messages/en.json";
import { Features } from "./Features";
import { FEATURES } from "@/content/features";

describe("Features", () => {
  it("renders all 4 feature titles", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <Features />
      </NextIntlClientProvider>,
    );
    for (const feature of FEATURES) {
      expect(screen.getByText(feature.title)).toBeInTheDocument();
    }
  });
});
```

- [ ] **Step 4: Build CliTable component**

Create `src/components/CliTable.tsx`:

```typescript
import { useTranslations } from "next-intl";
import { CLI_SUPPORT } from "@/content/clis";

export function CliTable() {
  const t = useTranslations("CliTable");

  return (
    <section className="px-6 py-16 max-w-4xl mx-auto">
      <h2 className="text-2xl font-mono mb-8">{t("heading")}</h2>
      <table className="w-full text-sm text-left border-collapse">
        <thead>
          <tr className="border-b border-neutral-800 text-neutral-500">
            <th className="py-2 pr-4">{t("cliColumn")}</th>
            <th className="py-2 pr-4">{t("hookColumn")}</th>
            <th className="py-2">{t("notesColumn")}</th>
          </tr>
        </thead>
        <tbody>
          {CLI_SUPPORT.map((cli) => (
            <tr key={cli.id} className="border-b border-neutral-900">
              <td className="py-2 pr-4 font-medium">{cli.name}</td>
              <td className="py-2 pr-4">{cli.hookSupport}</td>
              <td className="py-2 text-neutral-400">{cli.notes}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
```

- [ ] **Step 5: Write CliTable smoke test**

Create `src/components/CliTable.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "../../messages/en.json";
import { CliTable } from "./CliTable";
import { CLI_SUPPORT } from "@/content/clis";

describe("CliTable", () => {
  it("renders a row for every supported CLI", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <CliTable />
      </NextIntlClientProvider>,
    );
    for (const cli of CLI_SUPPORT) {
      expect(screen.getByText(cli.name)).toBeInTheDocument();
    }
  });
});
```

- [ ] **Step 6: Run full test suite and build**

Run: `npm run test`
Expected: PASS

Run: `npm run build`
Expected: succeeds

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add Features and Supported CLIs sections"
```

---

### Task 8: Live demo section (screenshot + transcript)

**Files:**
- Create: `holdthedoor-site/public/monitor-screenshot.png` (binary copy — see Step 1)
- Create: `holdthedoor-site/src/components/LiveDemo.tsx`
- Create: `holdthedoor-site/src/components/LiveDemo.test.tsx`
- Modify: `holdthedoor-site/messages/en.json`, `holdthedoor-site/messages/fr.json` (add `"LiveDemo"` namespace)

**Interfaces:**
- Consumes: `DEMO_TRANSCRIPT` from `src/content/demo-transcript.ts` (Task 4).
- Produces: `LiveDemo` component (no props), rendered by `page.tsx` in Task 11.

- [ ] **Step 1: Copy the monitor screenshot from the product repo**

```bash
cp "/Users/admin/Desktop/Dossier Perso/Projets/SKILLS/claude-wall/docs/img/monitor-screenshot.png" public/monitor-screenshot.png
```

- [ ] **Step 2: Add LiveDemo translation keys**

Modify `messages/en.json`, add:

```json
"LiveDemo": {
  "heading": "Live monitor",
  "screenshotAlt": "holdthedoor monitor dashboard showing an intact HMAC chain and recent audit events"
}
```

Modify `messages/fr.json`, add:

```json
"LiveDemo": {
  "heading": "Monitoring en direct",
  "screenshotAlt": "Tableau de bord holdthedoor montrant une chaîne HMAC intacte et les événements d'audit récents"
}
```

- [ ] **Step 3: Build the LiveDemo component**

Create `src/components/LiveDemo.tsx`:

```typescript
import { useTranslations } from "next-intl";
import Image from "next/image";
import { DEMO_TRANSCRIPT } from "@/content/demo-transcript";

export function LiveDemo() {
  const t = useTranslations("LiveDemo");

  return (
    <section className="px-6 py-16 max-w-4xl mx-auto">
      <h2 className="text-2xl font-mono mb-8">{t("heading")}</h2>
      <Image
        src="/monitor-screenshot.png"
        alt={t("screenshotAlt")}
        width={1280}
        height={720}
        className="rounded-md border border-neutral-800 mb-6"
      />
      <pre className="bg-neutral-900 rounded-md p-4 text-xs font-mono overflow-x-auto whitespace-pre">
        {DEMO_TRANSCRIPT}
      </pre>
    </section>
  );
}
```

- [ ] **Step 4: Write LiveDemo smoke test**

Create `src/components/LiveDemo.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "../../messages/en.json";
import { LiveDemo } from "./LiveDemo";

describe("LiveDemo", () => {
  it("renders the screenshot and the verified transcript", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <LiveDemo />
      </NextIntlClientProvider>,
    );
    expect(
      screen.getByAltText(
        "holdthedoor monitor dashboard showing an intact HMAC chain and recent audit events",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/chain intact/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Run full test suite and build**

Run: `npm run test`
Expected: PASS

Run: `npm run build`
Expected: succeeds

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add live monitor demo section with screenshot and transcript"
```

---

### Task 9: Licensing teaser, final CTA, Footer with locale switcher

**Files:**
- Create: `holdthedoor-site/src/components/LicensingTeaser.tsx`
- Create: `holdthedoor-site/src/components/LicensingTeaser.test.tsx`
- Create: `holdthedoor-site/src/components/LocaleSwitcher.tsx`
- Create: `holdthedoor-site/src/components/LocaleSwitcher.test.tsx`
- Create: `holdthedoor-site/src/components/Footer.tsx`
- Create: `holdthedoor-site/src/components/Footer.test.tsx`
- Modify: `holdthedoor-site/src/app/[locale]/layout.tsx` (render `<Footer />` after `{children}`)
- Modify: `holdthedoor-site/messages/en.json`, `holdthedoor-site/messages/fr.json` (add `"Licensing"` and `"Footer"` namespaces)

**Interfaces:**
- Consumes: `Link`, `usePathname` from `@/i18n/navigation` (Task 2); `routing.locales` from `@/i18n/routing` (Task 2).
- Produces: `LicensingTeaser`, `Footer` (no props, `Footer` renders `LocaleSwitcher` and links to `/pricing`), rendered by `page.tsx` (LicensingTeaser) in Task 11 and by the layout (Footer) in this task.

- [ ] **Step 1: Add translation keys**

Modify `messages/en.json`, add:

```json
"Licensing": {
  "heading": "Licensing",
  "body": "MIT today, everywhere. A future, more detailed dashboard/engine component is planned under BSL-1.1 — free for internal use and self-hosting, restricted only for reselling it as a hosted service.",
  "link": "Read the full strategy"
},
"Footer": {
  "tagline": "the fire stays in your cave.",
  "docs": "Docs",
  "pricing": "Pricing",
  "github": "GitHub"
}
```

Modify `messages/fr.json`, add:

```json
"Licensing": {
  "heading": "Licence",
  "body": "MIT aujourd'hui, partout. Un futur composant de dashboard/moteur plus détaillé est prévu sous BSL-1.1 — gratuit en usage interne et auto-hébergé, restreint uniquement pour la revente en service hébergé.",
  "link": "Lire la stratégie complète"
},
"Footer": {
  "tagline": "le feu reste dans votre grotte.",
  "docs": "Docs",
  "pricing": "Tarifs",
  "github": "GitHub"
}
```

- [ ] **Step 2: Build LicensingTeaser component**

Create `src/components/LicensingTeaser.tsx`:

```typescript
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";

export function LicensingTeaser() {
  const t = useTranslations("Licensing");

  return (
    <section className="px-6 py-16 max-w-3xl mx-auto text-center">
      <h2 className="text-2xl font-mono mb-4">{t("heading")}</h2>
      <p className="text-neutral-400 mb-4">{t("body")}</p>
      <Link href="/pricing" className="underline">
        {t("link")}
      </Link>
    </section>
  );
}
```

- [ ] **Step 3: Write LicensingTeaser smoke test**

Create `src/components/LicensingTeaser.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "../../messages/en.json";
import { LicensingTeaser } from "./LicensingTeaser";

describe("LicensingTeaser", () => {
  it("links to the pricing page", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <LicensingTeaser />
      </NextIntlClientProvider>,
    );
    expect(screen.getByText("Read the full strategy").closest("a")).toHaveAttribute(
      "href",
      "/pricing",
    );
  });
});
```

- [ ] **Step 4: Build LocaleSwitcher component**

Create `src/components/LocaleSwitcher.tsx`:

```typescript
"use client";

import { usePathname, useRouter } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import { useLocale } from "next-intl";

export function LocaleSwitcher() {
  const pathname = usePathname();
  const router = useRouter();
  const activeLocale = useLocale();

  return (
    <div className="flex gap-2 text-xs">
      {routing.locales.map((locale) => (
        <button
          key={locale}
          onClick={() => router.replace(pathname, { locale })}
          aria-current={locale === activeLocale}
          className={
            locale === activeLocale ? "underline" : "text-neutral-500"
          }
        >
          {locale.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Write LocaleSwitcher smoke test**

Create `src/components/LocaleSwitcher.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LocaleSwitcher } from "./LocaleSwitcher";

describe("LocaleSwitcher", () => {
  it("renders a button for EN and FR", () => {
    render(<LocaleSwitcher />);
    expect(screen.getByText("EN")).toBeInTheDocument();
    expect(screen.getByText("FR")).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Build Footer component**

Create `src/components/Footer.tsx`:

```typescript
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { LocaleSwitcher } from "./LocaleSwitcher";

export function Footer() {
  const t = useTranslations("Footer");

  return (
    <footer className="px-6 py-12 border-t border-neutral-800 flex items-center justify-between text-sm text-neutral-500">
      <p className="italic">{t("tagline")}</p>
      <div className="flex items-center gap-6">
        <Link href="/docs">{t("docs")}</Link>
        <Link href="/pricing">{t("pricing")}</Link>
        <a href="https://github.com/adrienchristiaen/holdthedoor" target="_blank" rel="noreferrer">
          {t("github")}
        </a>
        <LocaleSwitcher />
      </div>
    </footer>
  );
}
```

- [ ] **Step 7: Write Footer smoke test**

Create `src/components/Footer.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "../../messages/en.json";
import { Footer } from "./Footer";

describe("Footer", () => {
  it("renders the tagline", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <Footer />
      </NextIntlClientProvider>,
    );
    expect(screen.getByText("the fire stays in your cave.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 8: Render Footer in the locale layout**

Modify `src/app/[locale]/layout.tsx` — import `Footer` and render after `{children}`:

```typescript
import { Footer } from "@/components/Footer";
// ...
<NextIntlClientProvider>
  <Nav />
  {children}
  <Footer />
</NextIntlClientProvider>
```

- [ ] **Step 9: Run full test suite and build**

Run: `npm run test`
Expected: PASS

Run: `npm run build`
Expected: succeeds

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: add licensing teaser, footer, and locale switcher"
```

---

### Task 10: Assemble the landing page

**Files:**
- Modify: `holdthedoor-site/src/app/[locale]/page.tsx`
- Modify: `holdthedoor-site/src/app/[locale]/page.test.tsx`
- Modify: `holdthedoor-site/messages/en.json`, `holdthedoor-site/messages/fr.json` (remove now-unused `"Landing.heroPlaceholder"` key)

**Interfaces:**
- Consumes: `Hero` (Task 5), `InstallTabs` (Task 6), `Features`, `CliTable` (Task 7), `LiveDemo` (Task 8), `LicensingTeaser` (Task 9).
- Produces: fully assembled `/` landing page.

- [ ] **Step 1: Replace the placeholder landing page with the assembled sections**

Modify `src/app/[locale]/page.tsx`:

```typescript
import { Hero } from "@/components/Hero";
import { InstallTabs } from "@/components/InstallTabs";
import { Features } from "@/components/Features";
import { CliTable } from "@/components/CliTable";
import { LiveDemo } from "@/components/LiveDemo";
import { LicensingTeaser } from "@/components/LicensingTeaser";

export default function LandingPage() {
  return (
    <main>
      <Hero />
      <InstallTabs />
      <Features />
      <CliTable />
      <LiveDemo />
      <LicensingTeaser />
    </main>
  );
}
```

- [ ] **Step 2: Remove the now-unused placeholder message key**

Modify `messages/en.json` and `messages/fr.json` — delete the `"Landing"` namespace entirely (its only key, `heroPlaceholder`, is no longer referenced anywhere).

- [ ] **Step 3: Rewrite the landing page test as a full assembly smoke test**

Replace `src/app/[locale]/page.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "../../../messages/en.json";
import LandingPage from "./page";

describe("LandingPage", () => {
  it("renders every section's heading", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <LandingPage />
      </NextIntlClientProvider>,
    );
    expect(
      screen.getByText("Privacy-first security layer for AI coding CLIs"),
    ).toBeInTheDocument();
    expect(screen.getByText("Install")).toBeInTheDocument();
    expect(screen.getByText("What it does")).toBeInTheDocument();
    expect(screen.getByText("Supported CLIs")).toBeInTheDocument();
    expect(screen.getByText("Live monitor")).toBeInTheDocument();
    expect(screen.getByText("Licensing")).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run full test suite and build**

Run: `npm run test`
Expected: PASS

Run: `npm run build`
Expected: succeeds, `/` and `/fr` both statically generated

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: assemble full landing page from all sections"
```

---

### Task 11: `/pricing` page

**Files:**
- Create: `holdthedoor-site/src/app/[locale]/pricing/page.tsx`
- Create: `holdthedoor-site/src/app/[locale]/pricing/page.test.tsx`
- Modify: `holdthedoor-site/messages/en.json`, `holdthedoor-site/messages/fr.json` (add `"Pricing"` namespace)

**Interfaces:**
- Produces: `/pricing` and `/fr/pricing` routes.

- [ ] **Step 1: Add Pricing translation keys, content drawn from the product repo's LICENSING.md**

Modify `messages/en.json`, add:

```json
"Pricing": {
  "heading": "Pricing",
  "todayHeading": "Today",
  "todayBody": "The entire holdthedoor repository — hooks, CLI, policy engine, audit log, and the current monitor dashboard — is MIT licensed. Nothing you can install and run today requires anything other than MIT.",
  "plannedHeading": "Planned",
  "plannedBody": "A future, substantially more detailed dashboard/engine component is planned. When it ships, it will be licensed under the Business Source License 1.1 (BSL-1.1): free for internal evaluation, local development, CI/CD, and self-hosted use, including inside a company for your own team's traffic. Offering it to third parties as a hosted service requires a commercial agreement. Four years after that component's first release, it automatically relicenses to Apache License 2.0.",
  "cta": "Questions about enterprise use? Open an issue on GitHub."
}
```

Modify `messages/fr.json`, add:

```json
"Pricing": {
  "heading": "Tarifs",
  "todayHeading": "Aujourd'hui",
  "todayBody": "L'ensemble du dépôt holdthedoor — hooks, CLI, moteur de règles, journal d'audit, et le dashboard monitor actuel — est sous licence MIT. Rien de ce que vous pouvez installer et exécuter aujourd'hui ne nécessite autre chose que MIT.",
  "plannedHeading": "Prévu",
  "plannedBody": "Un futur composant de dashboard/moteur bien plus détaillé est prévu. À sa sortie, il sera sous licence Business Source License 1.1 (BSL-1.1) : gratuit pour l'évaluation interne, le développement local, la CI/CD, et l'auto-hébergement, y compris en entreprise pour le trafic de votre propre équipe. Le proposer à des tiers en tant que service hébergé nécessite un accord commercial. Quatre ans après la première sortie de ce composant, il repasse automatiquement sous licence Apache 2.0.",
  "cta": "Des questions sur l'usage en entreprise ? Ouvrez une issue sur GitHub."
}
```

- [ ] **Step 2: Build the pricing page**

Create `src/app/[locale]/pricing/page.tsx`:

```typescript
import { useTranslations } from "next-intl";

export default function PricingPage() {
  const t = useTranslations("Pricing");

  return (
    <main className="px-6 py-16 max-w-3xl mx-auto">
      <h1 className="text-3xl font-mono mb-8">{t("heading")}</h1>
      <section className="mb-8">
        <h2 className="text-xl font-medium mb-2">{t("todayHeading")}</h2>
        <p className="text-neutral-400">{t("todayBody")}</p>
      </section>
      <section className="mb-8">
        <h2 className="text-xl font-medium mb-2">{t("plannedHeading")}</h2>
        <p className="text-neutral-400">{t("plannedBody")}</p>
      </section>
      <a
        href="https://github.com/adrienchristiaen/holdthedoor/issues"
        target="_blank"
        rel="noreferrer"
        className="underline"
      >
        {t("cta")}
      </a>
    </main>
  );
}
```

- [ ] **Step 3: Write a pricing page smoke test**

Create `src/app/[locale]/pricing/page.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "../../../../messages/en.json";
import PricingPage from "./page";

describe("PricingPage", () => {
  it("renders Today and Planned sections with no invented price", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <PricingPage />
      </NextIntlClientProvider>,
    );
    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText("Planned")).toBeInTheDocument();
    expect(screen.getByText(/BSL-1.1/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run full test suite and build**

Run: `npm run test`
Expected: PASS

Run: `npm run build`
Expected: succeeds, `/pricing` and `/fr/pricing` both statically generated

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add pricing page sourced from LICENSING.md"
```

---

### Task 12: `/docs` pages (English-only, reorganized from product README)

**Files:**
- Create: `holdthedoor-site/src/app/[locale]/docs/page.tsx`
- Create: `holdthedoor-site/src/app/[locale]/docs/page.test.tsx`
- Create: `holdthedoor-site/src/app/[locale]/docs/installation/page.tsx`
- Create: `holdthedoor-site/src/app/[locale]/docs/architecture/page.tsx`
- Create: `holdthedoor-site/src/app/[locale]/docs/threat-model/page.tsx`
- Create: `holdthedoor-site/src/components/EnglishOnlyBanner.tsx`
- Create: `holdthedoor-site/src/components/EnglishOnlyBanner.test.tsx`

**Interfaces:**
- Consumes: `useLocale` from `next-intl`.
- Produces: `EnglishOnlyBanner` component (no props — shows itself only when `useLocale() !== "en"`), rendered at the top of every `/docs/*` page.

- [ ] **Step 1: Write the failing EnglishOnlyBanner test**

Create `src/components/EnglishOnlyBanner.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { EnglishOnlyBanner } from "./EnglishOnlyBanner";

describe("EnglishOnlyBanner", () => {
  it("shows nothing when locale is en", () => {
    render(
      <NextIntlClientProvider locale="en" messages={{}}>
        <EnglishOnlyBanner />
      </NextIntlClientProvider>,
    );
    expect(
      screen.queryByText(/available in English only/),
    ).not.toBeInTheDocument();
  });

  it("shows a banner when locale is fr", () => {
    render(
      <NextIntlClientProvider locale="fr" messages={{}}>
        <EnglishOnlyBanner />
      </NextIntlClientProvider>,
    );
    expect(screen.getByText(/available in English only/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- EnglishOnlyBanner`
Expected: FAIL — `Cannot find module './EnglishOnlyBanner'`

- [ ] **Step 3: Implement EnglishOnlyBanner**

Create `src/components/EnglishOnlyBanner.tsx`:

```typescript
"use client";

import { useLocale } from "next-intl";

export function EnglishOnlyBanner() {
  const locale = useLocale();
  if (locale === "en") return null;

  return (
    <p className="bg-neutral-900 text-neutral-400 text-xs px-4 py-2 rounded-md mb-6">
      Docs available in English only.
    </p>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- EnglishOnlyBanner`
Expected: PASS

- [ ] **Step 5: Build the docs index page, content from README's "Why" + "Requirements" sections**

Create `src/app/[locale]/docs/page.tsx`:

```typescript
import { EnglishOnlyBanner } from "@/components/EnglishOnlyBanner";
import { Link } from "@/i18n/navigation";

export default function DocsIndexPage() {
  return (
    <main className="px-6 py-16 max-w-3xl mx-auto">
      <EnglishOnlyBanner />
      <h1 className="text-3xl font-mono mb-6">Docs</h1>
      <p className="text-neutral-400 mb-8">
        AI coding agents read your filesystem, run shell commands, and fetch
        web pages — then feed the results straight back into an LLM context.
        That&apos;s how secrets leak: a <code>cat .env</code> in an
        agent&apos;s own reasoning, a stray API key in a curl response, a
        credential pasted by mistake into a prompt. Prompt-based instructions
        (&quot;don&apos;t read secrets&quot;) are not a security boundary —
        the LLM can be talked out of them. holdthedoor sits outside the
        model, as CLI hooks that run in plain Python before/after every tool
        call. The LLM cannot see, disable, or negotiate with a hook — it
        either lets the call through or it doesn&apos;t.
      </p>
      <p className="text-neutral-400 mb-8">
        Requirements: Python 3.11+, one of Claude Code CLI / OpenAI Codex CLI
        / Gemini CLI / OpenCode, and zero external Python dependencies
        (stdlib only).
      </p>
      <ul className="space-y-2">
        <li>
          <Link href="/docs/installation" className="underline">
            Installation
          </Link>
        </li>
        <li>
          <Link href="/docs/architecture" className="underline">
            Architecture
          </Link>
        </li>
        <li>
          <Link href="/docs/threat-model" className="underline">
            Threat model
          </Link>
        </li>
      </ul>
    </main>
  );
}
```

- [ ] **Step 6: Write docs index smoke test**

Create `src/app/[locale]/docs/page.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import DocsIndexPage from "./page";

describe("DocsIndexPage", () => {
  it("links to installation, architecture, and threat model", () => {
    render(
      <NextIntlClientProvider locale="en" messages={{}}>
        <DocsIndexPage />
      </NextIntlClientProvider>,
    );
    expect(screen.getByText("Installation").closest("a")).toHaveAttribute(
      "href",
      "/docs/installation",
    );
    expect(screen.getByText("Architecture").closest("a")).toHaveAttribute(
      "href",
      "/docs/architecture",
    );
    expect(screen.getByText("Threat model").closest("a")).toHaveAttribute(
      "href",
      "/docs/threat-model",
    );
  });
});
```

- [ ] **Step 7: Build the installation subpage, content from README's "Installation" section (macOS/Linux/Windows)**

Create `src/app/[locale]/docs/installation/page.tsx`:

```typescript
import { EnglishOnlyBanner } from "@/components/EnglishOnlyBanner";

export default function InstallationDocsPage() {
  return (
    <main className="px-6 py-16 max-w-3xl mx-auto">
      <EnglishOnlyBanner />
      <h1 className="text-3xl font-mono mb-6">Installation</h1>

      <h2 className="text-xl font-medium mb-2">macOS</h2>
      <pre className="bg-neutral-900 rounded-md p-4 text-sm font-mono mb-6 overflow-x-auto">
{`brew install pipx
pipx install git+https://github.com/adrienchristiaen/holdthedoor.git
holdthedoor install`}
      </pre>

      <h2 className="text-xl font-medium mb-2">Linux</h2>
      <pre className="bg-neutral-900 rounded-md p-4 text-sm font-mono mb-6 overflow-x-auto">
{`python3 -m pip install --user pipx
python3 -m pipx ensurepath
pipx install git+https://github.com/adrienchristiaen/holdthedoor.git
holdthedoor install`}
      </pre>

      <h2 className="text-xl font-medium mb-2">Windows (PowerShell)</h2>
      <pre className="bg-neutral-900 rounded-md p-4 text-sm font-mono mb-6 overflow-x-auto">
{`pip install pipx
pipx ensurepath
pipx install git+https://github.com/adrienchristiaen/holdthedoor.git
holdthedoor install`}
      </pre>

      <p className="text-neutral-400 mb-2">
        By default <code>install</code> auto-detects which CLIs are
        installed. To target explicitly:
      </p>
      <pre className="bg-neutral-900 rounded-md p-4 text-sm font-mono overflow-x-auto">
{`holdthedoor install --cli claude
holdthedoor install --cli codex
holdthedoor install --cli gemini
holdthedoor install --cli opencode
holdthedoor install --cli all`}
      </pre>
    </main>
  );
}
```

- [ ] **Step 8: Build the architecture subpage, content from README's "Architecture" section**

Create `src/app/[locale]/docs/architecture/page.tsx`:

```typescript
import { EnglishOnlyBanner } from "@/components/EnglishOnlyBanner";

export default function ArchitectureDocsPage() {
  return (
    <main className="px-6 py-16 max-w-3xl mx-auto">
      <EnglishOnlyBanner />
      <h1 className="text-3xl font-mono mb-6">Architecture</h1>
      <pre className="bg-neutral-900 rounded-md p-4 text-sm font-mono mb-6 overflow-x-auto">
{`holdthedoor/
├── patterns.py    # regex categories + sensitive filename/dir/suffix sets
├── session.py     # SQLite WAL per-session store
├── tokenizer.py   # value <-> [WALL:cat:N] bidirectional, idempotent
├── audit.py       # HMAC-chained JSONL log + verify() + export_csv()
├── workspace.py   # workspace scan + check_path / check_bash (built-in rules)
├── policy.py      # user-defined allow/warn/block rules (policy engine)
├── settings.py    # multi-CLI install / uninstall (Claude/Codex/Gemini/OpenCode adapters)
├── cli.py         # argparse entry point
└── hooks/
    ├── _common.py             # stdin/stdout JSON, session, tool name normalization
    ├── post_tool_use.py       # AfterTool / PostToolUse / tool.execute.after
    ├── pre_tool_use.py        # BeforeTool / PreToolUse / tool.execute.before
    └── user_prompt_submit.py  # UserPromptSubmit (Claude Code + Codex)`}
      </pre>
      <p className="text-neutral-400">
        For every JSON-hooks-array CLI (Claude/Codex/Gemini), install writes
        a hook entry that spawns <code>python -m holdthedoor.hooks.&lt;name&gt;
        --cli &lt;cli&gt;</code> per event. OpenCode is the one exception: it
        loads a JS plugin directly into its own process, so{" "}
        <code>install --cli opencode</code> instead generates a thin JS shim
        that shells out to the same Python hook modules — no logic
        duplicated in JS.
      </p>
    </main>
  );
}
```

- [ ] **Step 9: Build the threat model subpage, content from README's "Threat model" section**

Create `src/app/[locale]/docs/threat-model/page.tsx`:

```typescript
import { EnglishOnlyBanner } from "@/components/EnglishOnlyBanner";

export default function ThreatModelDocsPage() {
  return (
    <main className="px-6 py-16 max-w-3xl mx-auto">
      <EnglishOnlyBanner />
      <h1 className="text-3xl font-mono mb-6">Threat model</h1>

      <h2 className="text-xl font-medium mb-2">Mitigated</h2>
      <ol className="list-decimal list-inside text-neutral-400 mb-6 space-y-1">
        <li>LLM reads secrets via tool output → PostToolUse/AfterTool/tool.execute.after redaction</li>
        <li>LLM reads .env / SSH keys → PreToolUse/BeforeTool/tool.execute.before block</li>
        <li>LLM runs a command or touches a path your team has flagged → policy engine block/warn</li>
        <li>Secrets in prompts → UserPromptSubmit scan (Claude Code + Codex)</li>
        <li>Post-hoc log tampering → HMAC-chained audit</li>
      </ol>

      <h2 className="text-xl font-medium mb-2">Not mitigated</h2>
      <ul className="list-disc list-inside text-neutral-400 space-y-1">
        <li>Copy-paste propagation (LLM copies secret to another file)</li>
        <li>Full filesystem isolation (use a container)</li>
        <li>Novel secret formats not in patterns.py</li>
        <li>Gemini CLI / OpenCode prompts (no UserPromptSubmit equivalent)</li>
        <li>
          A user with local write access editing policy.json or the hooks
          themselves — this protects against the LLM bypassing controls, not
          against a malicious local operator
        </li>
      </ul>
    </main>
  );
}
```

- [ ] **Step 10: Run full test suite and build**

Run: `npm run test`
Expected: PASS

Run: `npm run build`
Expected: succeeds, all `/docs/*` routes statically generated for both locales (fr renders English content + banner)

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat: add English-only docs pages reorganized from product README"
```

---

### Task 13: Deployment config + site README

**Files:**
- Create: `holdthedoor-site/vercel.json`
- Create: `holdthedoor-site/README.md`

**Interfaces:**
- Produces: a deployable repo — no code interfaces (this is the final packaging task).

- [ ] **Step 1: Add a minimal Vercel config**

Create `vercel.json`:

```json
{
  "framework": "nextjs"
}
```

- [ ] **Step 2: Write the site repo's own README**

Create `README.md`:

```markdown
# holdthedoor-site

Marketing site for [holdthedoor](https://github.com/adrienchristiaen/holdthedoor)
— a privacy-first security layer for AI coding CLIs.

## Stack

Next.js (App Router) · TypeScript · Tailwind CSS · next-intl (en/fr) · Vitest

## Develop

\`\`\`bash
npm install
npm run dev
\`\`\`

## Test

\`\`\`bash
npm run test
\`\`\`

## Build

\`\`\`bash
npm run build
\`\`\`

## Content policy

All product claims, CLI support info, and licensing terms in this site are
sourced verbatim from the product repo (`README.md`, `LICENSING.md`,
`docs/img/monitor-screenshot.png`). No invented stats, social proof, or
pricing numbers — see
`docs/superpowers/specs/2026-08-30-holdthedoor-website-design.md` in the
product repo for the full design rationale.

## Deploy

Deployed to Vercel. No custom domain configured yet.
```

- [ ] **Step 3: Final full verification**

Run: `npm run test`
Expected: PASS (full suite)

Run: `npm run build`
Expected: succeeds — this is the plan's final acceptance gate.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: add deployment config and site README"
```

- [ ] **Step 5: Report next manual step to the user (not automated by this plan)**

Print a note for the human operator: create a new GitHub repo `holdthedoor-site` under the same account as the product repo, push this local repo to it (`git remote add origin <url> && git push -u origin main`), then connect it on vercel.com as a new project (Vercel auto-detects Next.js from `vercel.json` + `package.json`). Domain choice and purchase remain deferred, per the spec.
