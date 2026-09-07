# privacyhook

> AI コーディング CLI 向けプライバシーファーストなセキュリティレイヤー。LLM が回避できない決定的フックで、シークレットを難読化し、機密ファイルをブロックし、プロンプトをスキャンし、さらにすべてのツール呼び出しを自分で定義したルールで統制できます。

[![tests](https://img.shields.io/badge/tests-96%20passed-brightgreen)](#テスト)
[![python](https://img.shields.io/badge/python-3.11+-blue)](#要件)
[![license](https://img.shields.io/badge/license-MIT-green)](../LICENSE)

**他の言語：** [English](../README.md) · [Français](README.fr.md) · [中文](README.zh.md)

---

## 目次

- [なぜ必要か](#なぜ必要か)
- [対応 CLI](#対応-cli)
- [動作概要](#動作概要)
- [ツール呼び出しポリシーエンジン](#ツール呼び出しポリシーエンジン)
- [要件](#要件)
- [インストール](#インストール)
- [インストールの確認](#インストールの確認)
- [コマンド一覧](#コマンド一覧)
- [厳格モード](#厳格モード)
- [エンドツーエンドデモ](#エンドツーエンドデモ)
- [アーキテクチャ](#アーキテクチャ)
- [検出されるシークレットカテゴリ](#検出されるシークレットカテゴリ)
- [テスト](#テスト)
- [脅威モデル](#脅威モデル)
- [ロードマップ](#ロードマップ-v02)
- [ライセンス](#ライセンス)

---

## なぜ必要か

AI コーディング agent はファイルシステムを読み、シェルコマンドを実行し、Web ページを取得し——その結果をそのまま LLM のコンテキストに流し込みます。シークレットはこうして漏れます。agent 自身の推論過程での `cat .env`、curl のレスポンスに紛れ込んだ API キー、誤ってプロンプトに貼り付けられた認証情報。プロンプトレベルの指示（「シークレットを読むな」）はセキュリティ境界にはなりません——LLM は説得されて回避してしまう可能性があります。privacyhook はモデルの**外側**に位置し、各ツール呼び出しの前後で動く素の Python の CLI フックとして動作します。LLM はフックを見ることも、無効化することも、交渉することもできません——呼び出しを通すか通さないかのどちらかです。

---

## 対応 CLI

| CLI | フックサポート | 備考 |
|---|---|---|
| **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** | 完全（3フック） | `PostToolUse`、`PreToolUse`、`UserPromptSubmit` |
| **[OpenAI Codex CLI](https://openai.com/codex)** | 完全（3フック） | Claude Code と同一フォーマット |
| **[Gemini CLI](https://gemini.google.com/cli)** | 部分（2フック） | `BeforeTool`、`AfterTool` — プロンプトフックなし |

---

## 動作概要

| フック | トリガー | アクション |
|---|---|---|
| **PostToolUse / AfterTool** | `Bash` / `Read` / `WebFetch`（または対応 CLI ツール）実行後 | ツール出力に含まれるシークレットを可逆セッショントークン（例: `[WALL:openai_key:1]`）に置換し、LLM に渡る前に難読化します。 |
| **PreToolUse / BeforeTool** | ファイル/シェルツール呼び出し前 | 機密パス（`.env`、SSH キー、認証情報、`*.pem`）へのアクセスをブロックし、**さらに**独自の[ポリシールール](#ツール呼び出しポリシーエンジン)を評価します。終了コード 2 = CLI がキャンセル。 |
| **UserPromptSubmit** | ユーザー入力ごと（Claude Code + Codex のみ） | 構造化シークレットをスキャン。デフォルトは警告のみ、厳格モードではブロック。 |

すべてのイベント——難読化、ブロック、警告、ポリシーマッチ——は HMAC チェーン型の監査ログ（`~/.local/share/privacyhook/audit.jsonl`）に記録されます。改ざんするとチェーンが壊れ、`privacyhook audit --verify` でそれを証明できます。

---

## ツール呼び出しポリシーエンジン

機密パスのブロック（`.env`、SSH キーなど）は組み込みで常時有効です。それに加えて、コードを変更せず、再デプロイもせずに、独自の **allow / warn / block** ルールを定義できます。

```bash
# 任意のブランチへの force-push をブロック
privacyhook policy add --id no-force-push \
  --tool Bash --match 'push.*--force' --action block \
  --reason "force push には人によるレビューが必要"

# node_modules 的なパスへの書き込みは警告のみ（ブロックしない）
privacyhook policy add --id watch-writes \
  --tool Write --match-type path_glob --match '*/node_modules/*' \
  --action warn

# 有効なルールを一覧表示
privacyhook policy list

# 現在のルールに対してコマンドをドライラン——副作用なし
privacyhook policy test "git push --force origin main"
# → block  (matched rule 'no-force-push': force push には人によるレビューが必要)

# ルールを削除
privacyhook policy remove no-force-push
```

ルールは `~/.local/share/privacyhook/policy.json` に保存され、追加された順に評価され、最初にマッチしたものが適用されます（マッチなし → allow）。各ルールは対象ツール（`Bash`、`Read`、`Write`、全ツール対象の `*`、または `Tool1|Tool2`）にスコープされ、以下いずれかの方式でマッチします：

- `command_regex`（デフォルト）— シェルコマンドに対する正規表現（`Bash` 呼び出し）
- `path_glob` — ファイルパスに対する glob パターン（`Read`/`Write`/`Edit` 呼び出し）

マッチはすべて `policy_block` または `policy_warn` として監査ログに記録され、組み込みイベントと並んで表示されます——`privacyhook audit` で全体像を把握できます。

組み込みのチェックだけではチームにとって不十分な場合に使う仕組みです。危険なコマンドを封じる、特定パスへの書き込みを制限する、注意すべきディレクトリに触れる操作にレビューを義務付ける——すべてモデルの制御が及ばないところで、決定的に強制されます。

---

## 要件

- Python 3.11+
- 以下のいずれか：Claude Code CLI、OpenAI Codex CLI、Gemini CLI
- 外部依存ゼロ — Python 標準ライブラリのみ（`sqlite3`、`hmac`、`re`、`json`）

---

## インストール

### macOS

```bash
# pipx のインストール（未インストールの場合）
brew install pipx

# privacyhook のインストール
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# フックの登録（インストール済み CLI を自動検出）
privacyhook install
```

### Linux

```bash
# pipx のインストール
python3 -m pip install --user pipx
python3 -m pipx ensurepath

# ターミナルを再起動してから：
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# フックの登録
privacyhook install
```

### Windows（PowerShell）

```powershell
# pipx のインストール
pip install pipx
pipx ensurepath

# ターミナルを再起動してから：
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# フックの登録
privacyhook install
```

> **Windows の注意：** 設定ファイルはそれぞれ `%APPDATA%\Claude\settings.json`、
> `%APPDATA%\Codex\hooks.json`、`%APPDATA%\Gemini\settings.json` に書き込まれます。

### ソースからインストール（開発用）

```bash
git clone https://github.com/adrienchristiaen/privacyhook.git
cd privacyhook
pipx install --editable .
privacyhook install
```

### 対象 CLI の指定

デフォルトでは `install` がインストール済みの CLI を自動検出します。明示的に指定する場合：

```bash
privacyhook install --cli claude   # Claude Code のみ
privacyhook install --cli codex    # Codex CLI のみ
privacyhook install --cli gemini   # Gemini CLI のみ
privacyhook install --cli all      # 検出された全 CLI
```

`uninstall` と `status` も同じ `--cli` フラグに対応しています。

---

## インストールの確認

```bash
privacyhook status
```

期待される出力：

```
[Claude Code]  ✓ installed
  /Users/you/.claude/settings.json
  hooks: PostToolUse · PreToolUse · UserPromptSubmit

SESSION  /tmp/privacyhook/<session-id>/session.db
  0 values redacted this session

RECENT EVENTS
  (none)
```

新しい CLI セッションを開くと、フックが自動的に有効になります。

---

## コマンド一覧

| コマンド | 内容 |
|---|---|
| `privacyhook status [--cli auto\|claude\|codex\|gemini\|all]` | 各 CLI のフック状態、セッション DB パス、直近5件の監査イベント。 |
| `privacyhook reveal <token>` | セッショントークンの元の値を返します（セッション内限定——セッション終了とともに消えます）。 |
| `privacyhook audit [--verify] [--last N] [--json] [--follow]` | 監査ログを表示します。`--verify` で HMAC チェーンの整合性を検証。`--follow`（`-f`）で新しいイベントをリアルタイムに追跡し、別ターミナルでの監視に使えます。 |
| `privacyhook policy list \| add \| remove \| test` | カスタムルールを管理——[ポリシーエンジン](#ツール呼び出しポリシーエンジン)参照。 |
| `privacyhook uninstall [--cli ...] [--yes]` | privacyhook のエントリのみ削除します。他のフックはそのまま保持されます。 |

```
$ privacyhook reveal '[WALL:openai_key:1]'
sk-proj-••••••••••••••••••••••••••••••••••••••

$ privacyhook audit --verify
  ✓ chain intact

$ privacyhook audit --follow
SESSION AUDIT  —  live (Ctrl-C to stop)
────────────────────────────────────────────────────────────────
  16:11:02  ✗ block  pre-tool  Read  /you/project/.env  →  filename '.env' is sensitive
```

### 緊急無効化

```bash
export PRIVACYHOOK_DISABLED=1
# ... シークレットパターン例を含むドキュメント編集などの操作 ...
unset PRIVACYHOOK_DISABLED
```

---

## 厳格モード

デフォルトでは `UserPromptSubmit` フックは警告のみでプロンプトを通過させます。ブロックするには：

```bash
export PRIVACYHOOK_STRICT=1
```

---

## エンドツーエンドデモ

```bash
bash scripts/demo.sh
```

隔離された一時ディレクトリ内で実行されるため、実際の CLI 設定には影響しません。

---

## アーキテクチャ

```
privacyhook/
├── patterns.py    # 正規表現カテゴリ + 機密ファイル名/ディレクトリ/拡張子セット
├── session.py     # セッションごとの SQLite WAL ストア
├── tokenizer.py   # 値 <-> [WALL:cat:N] の双方向・冪等変換
├── audit.py       # HMAC チェーン型 JSONL ログ + verify()
├── workspace.py   # ワークスペーススキャン + check_path / check_bash（組み込みルール）
├── policy.py      # ユーザー定義の allow/warn/block ルール（ポリシーエンジン）
├── settings.py    # 複数 CLI のインストール/アンインストール（Claude/Codex/Gemini アダプター）
├── cli.py         # argparse エントリーポイント
└── hooks/
    ├── _common.py             # stdin/stdout JSON、セッション、ツール名の正規化
    ├── post_tool_use.py       # AfterTool / PostToolUse
    ├── pre_tool_use.py        # BeforeTool / PreToolUse
    └── user_prompt_submit.py  # UserPromptSubmit（Claude Code + Codex）
```

### CLI 対応表

| 機能 | Claude Code | Codex CLI | Gemini CLI |
|---|---|---|---|
| Post-tool イベント | `PostToolUse` | `PostToolUse` | `AfterTool` |
| Pre-tool イベント | `PreToolUse` | `PreToolUse` | `BeforeTool` |
| Prompt イベント | `UserPromptSubmit` | `UserPromptSubmit` | *（利用不可）* |
| シェルツール名 | `Bash` | `Bash` | `run_shell_command` |
| ファイル読み取りツール | `Read` | `Read` | `read_file` |
| Web 取得ツール | `WebFetch` | `WebFetch` | `fetch_webpage` |
| タイムアウト単位 | 秒 | 秒 | ミリ秒 |

---

## 検出されるシークレットカテゴリ

| カテゴリ | パターン例 |
|---|---|
| `anthropic_key` | `sk-ant-api03-…` |
| `openai_key` | `sk-proj-…` |
| `github_token` | `ghp_…`、`gho_…`、`ghs_…` |
| `aws_access_key` | `AKIA…` |
| `google_api_key` | `AIza…` |
| `jwt` | `eyJ….eyJ….` |
| `private_key_block` | `-----BEGIN … KEY-----` |
| `slack_token` | `xoxb-…` |
| `email` | `user@domain.tld` |
| `private_ip` | RFC 1918 アドレス範囲 |
| `internal_hostname` | `*.internal`、`*.corp`、`*.local` |

`privacyhook/patterns.py` にエントリを追加することでカスタムカテゴリを追加できます。それ以外——特定のコマンド、パス、書き込み操作全体——をブロックしたい場合は、コードを変更せずに[ポリシーエンジン](#ツール呼び出しポリシーエンジン)を使ってください。

---

## テスト

```bash
pip install -e '.[dev]'
pytest -q   # 96 passed
```

---

## 脅威モデル

**対応済み：**
1. LLM がツール出力経由でシークレットを読む → PostToolUse/AfterTool による難読化
2. LLM が `.env` / SSH キーを読む → PreToolUse/BeforeTool によるブロック（exit 2）
3. LLM がチームが危険とマークしたコマンドを実行、または特定パスに触れる → ポリシーエンジンによるブロック/警告
4. プロンプト内のシークレット → UserPromptSubmit スキャン
5. 事後的なログ改ざん → HMAC チェーン検証

**対応していないもの：**
- コピー&ペーストによる伝播（LLM がシークレットを別ファイルにコピーする）
- 完全なファイルシステム隔離（コンテナを使用してください）
- `patterns.py` に未収録の新しいシークレット形式
- Gemini CLI のプロンプト（`UserPromptSubmit` に相当するものがない）
- ローカルの書き込み権限を持つユーザーが `policy.json` やフック自体を編集する場合——これは *LLM* が制御を回避することへの対策であり、悪意あるローカル操作者への対策ではありません

---

## ロードマップ (v0.2)

- [ ] Ollama によるコンテキスト考慮の書き換え（200ms タイムアウト、正規表現へのフォールバック）
- [ ] セッション単位の難読化サマリーを出す `Stop` フック
- [ ] 実行前プレースホルダー置換（シークレットが LLM のコンテキストに一切入らない）
- [ ] Homebrew formula + PyPI リリース
- [ ] GitHub Actions CI（Python 3.11–3.14、macOS/Linux/Windows）
- [ ] コンプライアンス/監査エクスポート（HMAC ログからの SOC2 相当レポート）
- [ ] インストール済み skills/MCP サーバーのサプライチェーン検証

---

## ライセンス

MIT — [LICENSE](../LICENSE) 参照。
