# privacyhook

> Couche de sécurité privacy-first pour les CLI de coding IA. Des hooks déterministes que le LLM ne peut pas contourner — les secrets sont masqués, les fichiers sensibles bloqués, les prompts analysés, et chaque appel d'outil peut être gouverné par des règles que vous définissez.

[![tests](https://img.shields.io/badge/tests-96%20passed-brightgreen)](#tests)
[![python](https://img.shields.io/badge/python-3.11+-blue)](#prérequis)
[![license](https://img.shields.io/badge/license-MIT-green)](../LICENSE)

**Lire en :** [English](../README.md) · [中文](README.zh.md) · [日本語](README.ja.md)

---

## Sommaire

- [Pourquoi](#pourquoi)
- [CLI supportés](#cli-supportés)
- [Ce que ça fait](#ce-que-ça-fait)
- [Moteur de policy tool-call](#moteur-de-policy-tool-call)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Vérifier l'installation](#vérifier-linstallation)
- [Commandes](#commandes)
- [Mode strict](#mode-strict)
- [Démo de bout en bout](#démo-de-bout-en-bout)
- [Architecture](#architecture)
- [Catégories de secrets détectées](#catégories-de-secrets-détectées)
- [Tests](#tests)
- [Modèle de menace](#modèle-de-menace)
- [Roadmap](#roadmap-v02)
- [Licence](#licence)

---

## Pourquoi

Les agents de coding IA lisent votre filesystem, exécutent des commandes shell, récupèrent des pages web — puis renvoient tout ça directement dans le contexte du LLM. C'est comme ça que les secrets fuient : un `cat .env` dans le raisonnement de l'agent, une clé API qui traîne dans une réponse curl, un credential collé par erreur dans un prompt. Des instructions au niveau du prompt ("ne lis pas les secrets") ne sont pas une barrière de sécurité — le LLM peut en être détourné. privacyhook se place **en dehors** du modèle, sous forme de hooks CLI qui tournent en Python pur avant/après chaque appel d'outil. Le LLM ne peut ni voir, ni désactiver, ni négocier avec un hook — soit l'appel passe, soit il ne passe pas.

---

## CLI supportés

| CLI | Support hooks | Notes |
|---|---|---|
| **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** | Complet (3 hooks) | `PostToolUse`, `PreToolUse`, `UserPromptSubmit` |
| **[OpenAI Codex CLI](https://openai.com/codex)** | Complet (3 hooks) | Même format que Claude Code |
| **[Gemini CLI](https://gemini.google.com/cli)** | Partiel (2 hooks) | `BeforeTool`, `AfterTool` — pas de hook prompt |

---

## Ce que ça fait

| Hook | Déclencheur | Action |
|---|---|---|
| **PostToolUse / AfterTool** | Après `Bash` / `Read` / `WebFetch` (ou équivalents CLI) | Remplace les secrets détectés dans la sortie d'un outil par des tokens de session réversibles type `[WALL:openai_key:1]`, avant que le LLM ne les voie. |
| **PreToolUse / BeforeTool** | Avant tout appel fichier/shell | Bloque les appels ciblant des chemins sensibles (`.env`, clés SSH, credentials, `*.pem`) **et** évalue vos [règles de policy](#moteur-de-policy-tool-call) personnalisées. Code de sortie 2 = le CLI annule l'appel. |
| **UserPromptSubmit** | Chaque prompt utilisateur (Claude Code + Codex uniquement) | Analyse le prompt à la recherche de secrets structurés. Avertit par défaut, bloque en mode strict. |

Chaque événement — redaction, blocage, avertissement, match de policy — est enregistré dans un log d'audit chaîné par HMAC (`~/.local/share/privacyhook/audit.jsonl`). Toute modification d'une entrée casse la chaîne, et `privacyhook audit --verify` le prouve.

---

## Moteur de policy tool-call

Le blocage des chemins sensibles (`.env`, clés SSH, …) est intégré et toujours actif. En plus de ça, vous pouvez définir vos propres règles **allow / warn / block** — sans toucher au code, sans redéploiement :

```bash
# Bloquer les force-push sur n'importe quelle branche
privacyhook policy add --id no-force-push \
  --tool Bash --match 'push.*--force' --action block \
  --reason "force push nécessite une validation humaine"

# Avertir (sans bloquer) sur les écritures sous un chemin type node_modules
privacyhook policy add --id watch-writes \
  --tool Write --match-type path_glob --match '*/node_modules/*' \
  --action warn

# Lister les règles actives
privacyhook policy list

# Tester une commande contre les règles actuelles — aucun effet de bord
privacyhook policy test "git push --force origin main"
# → block  (matched rule 'no-force-push': force push nécessite une validation humaine)

# Supprimer une règle
privacyhook policy remove no-force-push
```

Les règles sont stockées dans `~/.local/share/privacyhook/policy.json`, évaluées dans l'ordre d'ajout, et la première qui matche l'emporte (aucun match → allow). Chaque règle est scopée à un outil (`Bash`, `Read`, `Write`, `*` pour tous, ou `Tool1|Tool2`) et matche soit :

- `command_regex` (défaut) — une regex testée sur la commande shell (appels `Bash`)
- `path_glob` — un glob testé sur le chemin de fichier (appels `Read`/`Write`/`Edit`)

Chaque match est écrit dans le log d'audit comme `policy_block` ou `policy_warn`, aux côtés des événements intégrés — `privacyhook audit` donne une vue complète.

C'est le mécanisme à utiliser quand les checks intégrés ne suffisent pas pour votre équipe : épingler des commandes dangereuses, restreindre les écritures à certains chemins, ou exiger une revue pour tout ce qui touche un répertoire sensible — le tout appliqué de façon déterministe, en dehors du contrôle du modèle.

---

## Prérequis

- Python 3.11+
- Un de : Claude Code CLI, OpenAI Codex CLI, Gemini CLI
- Zéro dépendance externe — stdlib Python uniquement (`sqlite3`, `hmac`, `re`, `json`)

---

## Installation

### macOS

```bash
# Installer pipx si absent
brew install pipx

# Installer privacyhook
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# Enregistrer les hooks (détection auto des CLI installés)
privacyhook install
```

### Linux

```bash
# Installer pipx
python3 -m pip install --user pipx
python3 -m pipx ensurepath

# Redémarrer le terminal, puis :
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# Enregistrer les hooks
privacyhook install
```

### Windows (PowerShell)

```powershell
# Installer pipx
pip install pipx
pipx ensurepath

# Redémarrer le terminal, puis :
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# Enregistrer les hooks
privacyhook install
```

> **Note Windows :** Les settings sont écrits dans `%APPDATA%\Claude\settings.json`,
> `%APPDATA%\Codex\hooks.json` et `%APPDATA%\Gemini\settings.json` selon le CLI.

### Depuis les sources (développement)

```bash
git clone https://github.com/adrienchristiaen/privacyhook.git
cd privacyhook
pipx install --editable .
privacyhook install
```

### Cibler un CLI spécifique

Par défaut, `install` détecte automatiquement les CLI installés. Pour cibler explicitement :

```bash
privacyhook install --cli claude   # Claude Code uniquement
privacyhook install --cli codex    # Codex CLI uniquement
privacyhook install --cli gemini   # Gemini CLI uniquement
privacyhook install --cli all      # Tous les CLI détectés
```

Le même flag fonctionne pour `uninstall` et `status`.

---

## Vérifier l'installation

```bash
privacyhook status
```

Sortie attendue :

```
[Claude Code]  ✓ installed
  /Users/vous/.claude/settings.json
  hooks: PostToolUse · PreToolUse · UserPromptSubmit

SESSION  /tmp/privacyhook/<session-id>/session.db
  0 values redacted this session

RECENT EVENTS
  (none)
```

Ouvrez une nouvelle session CLI — les hooks s'activent automatiquement.

---

## Commandes

| Commande | Ce qu'elle fait |
|---|---|
| `privacyhook status [--cli auto\|claude\|codex\|gemini\|all]` | Hooks installés par CLI, chemin de la session DB, 5 derniers événements d'audit. |
| `privacyhook reveal <token>` | Affiche la valeur originale derrière un token de session (scopé à la session — meurt avec elle). |
| `privacyhook audit [--verify] [--last N] [--json] [--follow]` | Affiche le log d'audit. `--verify` parcourt la chaîne HMAC. `--follow` (`-f`) suit les nouveaux événements en direct, pour un monitoring dans un second terminal. |
| `privacyhook policy list \| add \| remove \| test` | Gère les règles personnalisées — voir [moteur de policy](#moteur-de-policy-tool-call). |
| `privacyhook uninstall [--cli ...] [--yes]` | Retire uniquement les entrées privacyhook. Les autres hooks sont préservés. |

```
$ privacyhook reveal '[WALL:openai_key:1]'
sk-proj-••••••••••••••••••••••••••••••••••••••

$ privacyhook audit --verify
  ✓ chain intact

$ privacyhook audit --follow
SESSION AUDIT  —  live (Ctrl-C to stop)
────────────────────────────────────────────────────────────────
  16:11:02  ✗ block  pre-tool  Read  /vous/projet/.env  →  filename '.env' is sensitive
```

### Désactivation d'urgence

```bash
export PRIVACYHOOK_DISABLED=1
# ... opérations avec exemples de patterns de secrets ...
unset PRIVACYHOOK_DISABLED
```

---

## Mode strict

Par défaut, le hook `UserPromptSubmit` avertit sans bloquer. Pour bloquer :

```bash
export PRIVACYHOOK_STRICT=1
```

---

## Démo de bout en bout

```bash
bash scripts/demo.sh
```

Tourne dans un tmpdir isolé — ne touche pas à votre config CLI réelle.

---

## Architecture

```
privacyhook/
├── patterns.py    # catégories regex + sets filename/dir/suffix sensibles
├── session.py     # store SQLite WAL par session
├── tokenizer.py   # valeur <-> [WALL:cat:N] bidirectionnel, idempotent
├── audit.py       # log JSONL chaîné par HMAC + verify()
├── workspace.py   # scan workspace + check_path / check_bash (règles intégrées)
├── policy.py      # règles allow/warn/block définies par l'utilisateur (policy engine)
├── settings.py     # install/uninstall multi-CLI (adaptateurs Claude/Codex/Gemini)
├── cli.py         # point d'entrée argparse
└── hooks/
    ├── _common.py             # stdin/stdout JSON, session, normalisation nom d'outil
    ├── post_tool_use.py       # AfterTool / PostToolUse
    ├── pre_tool_use.py        # BeforeTool / PreToolUse
    └── user_prompt_submit.py  # UserPromptSubmit (Claude Code + Codex)
```

### Correspondance des CLI

| Fonctionnalité | Claude Code | Codex CLI | Gemini CLI |
|---|---|---|---|
| Event post-tool | `PostToolUse` | `PostToolUse` | `AfterTool` |
| Event pre-tool | `PreToolUse` | `PreToolUse` | `BeforeTool` |
| Event prompt | `UserPromptSubmit` | `UserPromptSubmit` | *(indisponible)* |
| Outil shell | `Bash` | `Bash` | `run_shell_command` |
| Outil lecture fichier | `Read` | `Read` | `read_file` |
| Outil fetch web | `WebFetch` | `WebFetch` | `fetch_webpage` |
| Unité de timeout | secondes | secondes | millisecondes |

---

## Catégories de secrets détectées

| Catégorie | Pattern |
|---|---|
| `anthropic_key` | `sk-ant-api03-…` |
| `openai_key` | `sk-proj-…` |
| `github_token` | `ghp_…`, `gho_…`, `ghs_…` |
| `aws_access_key` | `AKIA…` |
| `google_api_key` | `AIza…` |
| `jwt` | `eyJ….eyJ….` |
| `private_key_block` | `-----BEGIN … KEY-----` |
| `slack_token` | `xoxb-…` |
| `email` | `utilisateur@domaine.tld` |
| `private_ip` | Plages RFC 1918 |
| `internal_hostname` | `*.internal`, `*.corp`, `*.local` |

Étendre en ajoutant des entrées dans `privacyhook/patterns.py`. Pour bloquer autre chose — une commande, un chemin, toute une catégorie d'écritures — utilisez plutôt le [moteur de policy](#moteur-de-policy-tool-call), sans toucher au code.

---

## Tests

```bash
pip install -e '.[dev]'
pytest -q   # 96 passed
```

---

## Modèle de menace

**Couvert :**
1. Le LLM lit des secrets via une sortie d'outil → redaction PostToolUse/AfterTool
2. Le LLM lit `.env` / clés SSH → blocage PreToolUse/BeforeTool (exit 2)
3. Le LLM exécute une commande ou touche un chemin flaggé par l'équipe → blocage/warn du policy engine
4. Secrets dans les prompts → scan UserPromptSubmit
5. Falsification a posteriori du log → chaîne HMAC

**Non couvert :**
- Propagation par copier-coller (le LLM recopie un secret ailleurs)
- Isolation complète du filesystem (utilisez un conteneur)
- Formats de secrets inédits, absents de `patterns.py`
- Prompts Gemini CLI (pas d'équivalent `UserPromptSubmit`)
- Un utilisateur avec accès en écriture local qui modifie `policy.json` ou les hooks eux-mêmes — ça protège contre le *LLM* qui contourne les contrôles, pas contre un opérateur local malveillant

---

## Roadmap (v0.2)

- [ ] Réécriture contextuelle via Ollama (timeout 200 ms, fallback regex)
- [ ] Hook `Stop` avec résumé des redactions de la session
- [ ] Placeholder avant exécution (le secret n'entre jamais dans le contexte du LLM)
- [ ] Formule Homebrew + release PyPI
- [ ] CI GitHub Actions (Python 3.11–3.14, macOS/Linux/Windows)
- [ ] Export compliance/audit (rapport type SOC2 depuis le log HMAC)
- [ ] Vetting supply-chain des skills/serveurs MCP installés

---

## Licence

MIT — voir [LICENSE](../LICENSE).
