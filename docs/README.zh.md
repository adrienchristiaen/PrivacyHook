# privacyhook

> AI 编程 CLI 的隐私安全层。LLM 无法绕过的确定性钩子——密钥被脱敏、敏感文件被屏蔽、提示词被扫描，每一次工具调用都可以由你定义的规则来治理。

[![tests](https://img.shields.io/badge/tests-96%20passed-brightgreen)](#测试)
[![python](https://img.shields.io/badge/python-3.11+-blue)](#要求)
[![license](https://img.shields.io/badge/license-MIT-green)](../LICENSE)

**其他语言：** [English](../README.md) · [Français](README.fr.md) · [日本語](README.ja.md)

---

## 目录

- [为什么](#为什么)
- [支持的 CLI](#支持的-cli)
- [工作原理](#工作原理)
- [Tool-call 策略引擎](#tool-call-策略引擎)
- [要求](#要求)
- [安装](#安装)
- [验证安装](#验证安装)
- [常用命令](#常用命令)
- [严格模式](#严格模式)
- [端到端演示](#端到端演示)
- [架构](#架构)
- [可检测的密钥类型](#可检测的密钥类型)
- [测试](#测试)
- [威胁模型](#威胁模型)
- [路线图](#路线图-v02)
- [许可证](#许可证)

---

## 为什么

AI 编程 agent 会读取你的文件系统、执行 shell 命令、抓取网页——然后把结果直接喂回 LLM 的上下文。密钥就是这样泄露的：agent 自己推理过程中的一次 `cat .env`、curl 响应里遗留的一个 API key、不小心粘贴进提示词的凭据。基于提示词的指令（"不要读取密钥"）并不是安全边界——LLM 可能被诱导绕过。privacyhook 运行在模型**之外**，作为纯 Python 的 CLI 钩子，在每次工具调用前后执行。LLM 无法看到、禁用或与钩子谈判——调用要么被放行，要么被拦截。

---

## 支持的 CLI

| CLI | 钩子支持 | 说明 |
|---|---|---|
| **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** | 完整（3 个钩子） | `PostToolUse`、`PreToolUse`、`UserPromptSubmit` |
| **[OpenAI Codex CLI](https://openai.com/codex)** | 完整（3 个钩子） | 与 Claude Code 格式相同 |
| **[Gemini CLI](https://gemini.google.com/cli)** | 部分（2 个钩子） | `BeforeTool`、`AfterTool` — 无提示词钩子 |

---

## 工作原理

| 钩子 | 触发时机 | 操作 |
|---|---|---|
| **PostToolUse / AfterTool** | `Bash` / `Read` / `WebFetch`（或对应 CLI 工具）调用返回后 | 将工具输出中检测到的密钥替换为可逆 session token（如 `[WALL:openai_key:1]`），在 LLM 读取前完成脱敏。 |
| **PreToolUse / BeforeTool** | 任何文件/Shell 工具调用之前 | 屏蔽指向敏感路径（`.env`、SSH 密钥、凭据、`*.pem`）的调用，**并**评估你自定义的[策略规则](#tool-call-策略引擎)。退出码 2 = CLI 中止操作。 |
| **UserPromptSubmit** | 每次用户输入（仅 Claude Code + Codex） | 扫描结构化密钥。默认警告，严格模式下阻止发送。 |

所有事件——脱敏、拦截、警告、策略匹配——都记录在 HMAC 链式审计日志（`~/.local/share/privacyhook/audit.jsonl`）中。任何篡改都会破坏链式结构，`privacyhook audit --verify` 可以证明这一点。

---

## Tool-call 策略引擎

敏感路径屏蔽（`.env`、SSH 密钥等）是内置的，始终生效。在此之上，你可以定义自己的 **allow / warn / block** 规则——无需改代码，无需重新部署：

```bash
# 屏蔽任意分支上的 force-push
privacyhook policy add --id no-force-push \
  --tool Bash --match 'push.*--force' --action block \
  --reason "force push 需要人工确认"

# 对 node_modules 类路径下的写入仅警告，不屏蔽
privacyhook policy add --id watch-writes \
  --tool Write --match-type path_glob --match '*/node_modules/*' \
  --action warn

# 列出当前生效的规则
privacyhook policy list

# 针对当前规则做干跑测试——无副作用
privacyhook policy test "git push --force origin main"
# → block  (matched rule 'no-force-push': force push 需要人工确认)

# 删除规则
privacyhook policy remove no-force-push
```

规则存储在 `~/.local/share/privacyhook/policy.json` 中，按添加顺序依次评估，第一条匹配的规则生效（无匹配 → allow）。每条规则限定作用于某个工具（`Bash`、`Read`、`Write`、`*` 表示全部，或 `Tool1|Tool2`），匹配方式为：

- `command_regex`（默认）— 针对 shell 命令的正则表达式（`Bash` 调用）
- `path_glob` — 针对文件路径的 glob 模式（`Read`/`Write`/`Edit` 调用）

每次匹配都会作为 `policy_block` 或 `policy_warn` 写入审计日志，与内置事件一起呈现——`privacyhook audit` 给出完整视图。

当内置检查对你的团队来说不够用时，就该用这个机制：锁定危险命令、限制特定路径的写入，或要求对涉及某个敏感目录的操作进行审查——全部以确定性方式执行，不受模型控制。

---

## 要求

- Python 3.11+
- 以下任一 CLI：Claude Code、OpenAI Codex CLI、Gemini CLI
- 零外部依赖——仅使用 Python 标准库（`sqlite3`、`hmac`、`re`、`json`）

---

## 安装

### macOS

```bash
# 安装 pipx（如未安装）
brew install pipx

# 安装 privacyhook
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# 注册钩子（自动检测已安装的 CLI）
privacyhook install
```

### Linux

```bash
# 安装 pipx
python3 -m pip install --user pipx
python3 -m pipx ensurepath

# 重启终端后执行：
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# 注册钩子
privacyhook install
```

### Windows（PowerShell）

```powershell
# 安装 pipx
pip install pipx
pipx ensurepath

# 重启终端后执行：
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# 注册钩子
privacyhook install
```

> **Windows 说明：** 配置文件分别写入 `%APPDATA%\Claude\settings.json`、
> `%APPDATA%\Codex\hooks.json` 和 `%APPDATA%\Gemini\settings.json`。

### 从源码安装（开发模式）

```bash
git clone https://github.com/adrienchristiaen/privacyhook.git
cd privacyhook
pipx install --editable .
privacyhook install
```

### 指定目标 CLI

默认情况下 `install` 自动检测已安装的 CLI。也可显式指定：

```bash
privacyhook install --cli claude   # 仅 Claude Code
privacyhook install --cli codex    # 仅 Codex CLI
privacyhook install --cli gemini   # 仅 Gemini CLI
privacyhook install --cli all      # 所有检测到的 CLI
```

`uninstall` 和 `status` 命令支持相同的 `--cli` 参数。

---

## 验证安装

```bash
privacyhook status
```

预期输出：

```
[Claude Code]  ✓ installed
  /Users/you/.claude/settings.json
  hooks: PostToolUse · PreToolUse · UserPromptSubmit

SESSION  /tmp/privacyhook/<session-id>/session.db
  0 values redacted this session

RECENT EVENTS
  (none)
```

重新打开 CLI 会话后，钩子将自动生效。

---

## 常用命令

| 命令 | 作用 |
|---|---|
| `privacyhook status [--cli auto\|claude\|codex\|gemini\|all]` | 每个 CLI 的钩子安装状态、session DB 路径、最近 5 条审计事件。 |
| `privacyhook reveal <token>` | 返回 session token 对应的原始值（作用域限定在当前 session，随会话结束而失效）。 |
| `privacyhook audit [--verify] [--last N] [--json] [--follow]` | 打印审计日志。`--verify` 校验 HMAC 链完整性。`--follow`（`-f`）实时追踪新事件，适合在第二个终端中监控。 |
| `privacyhook policy list \| add \| remove \| test` | 管理自定义规则——见 [策略引擎](#tool-call-策略引擎)。 |
| `privacyhook uninstall [--cli ...] [--yes]` | 仅移除 privacyhook 的条目，其他钩子不受影响。 |

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

### 紧急禁用

```bash
export PRIVACYHOOK_DISABLED=1
# ... 处理含示例密钥的文档等操作 ...
unset PRIVACYHOOK_DISABLED
```

---

## 严格模式

默认情况下，`UserPromptSubmit` 钩子仅发出警告，不阻止发送。如需阻止：

```bash
export PRIVACYHOOK_STRICT=1
```

---

## 端到端演示

```bash
bash scripts/demo.sh
```

在隔离的临时目录中运行——不会影响你真实的 CLI 配置。

---

## 架构

```
privacyhook/
├── patterns.py    # 正则分类 + 敏感文件名/目录/后缀集合
├── session.py     # 每会话的 SQLite WAL 存储
├── tokenizer.py   # 值 <-> [WALL:cat:N] 双向、幂等转换
├── audit.py       # HMAC 链式 JSONL 日志 + verify()
├── workspace.py   # 工作区扫描 + check_path / check_bash（内置规则）
├── policy.py      # 用户自定义 allow/warn/block 规则（策略引擎）
├── settings.py    # 多 CLI 安装/卸载（Claude/Codex/Gemini 适配器）
├── cli.py         # argparse 入口
└── hooks/
    ├── _common.py             # stdin/stdout JSON、session、工具名归一化
    ├── post_tool_use.py       # AfterTool / PostToolUse
    ├── pre_tool_use.py        # BeforeTool / PreToolUse
    └── user_prompt_submit.py  # UserPromptSubmit（Claude Code + Codex）
```

### CLI 对应关系

| 功能 | Claude Code | Codex CLI | Gemini CLI |
|---|---|---|---|
| Post-tool 事件 | `PostToolUse` | `PostToolUse` | `AfterTool` |
| Pre-tool 事件 | `PreToolUse` | `PreToolUse` | `BeforeTool` |
| Prompt 事件 | `UserPromptSubmit` | `UserPromptSubmit` | *(不支持)* |
| Shell 工具名 | `Bash` | `Bash` | `run_shell_command` |
| 文件读取工具 | `Read` | `Read` | `read_file` |
| 网页抓取工具 | `WebFetch` | `WebFetch` | `fetch_webpage` |
| 超时单位 | 秒 | 秒 | 毫秒 |

---

## 可检测的密钥类型

| 类别 | 模式示例 |
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
| `private_ip` | RFC 1918 地址段 |
| `internal_hostname` | `*.internal`、`*.corp`、`*.local` |

如需添加自定义类别，编辑 `privacyhook/patterns.py` 即可。若要屏蔽其他内容——某条命令、某个路径、整类写操作——改用[策略引擎](#tool-call-策略引擎)，无需改代码。

---

## 测试

```bash
pip install -e '.[dev]'
pytest -q   # 96 passed
```

---

## 威胁模型

**已覆盖：**
1. LLM 通过工具输出读取密钥 → PostToolUse/AfterTool 脱敏
2. LLM 读取 `.env` / SSH 密钥 → PreToolUse/BeforeTool 拦截（exit 2）
3. LLM 执行团队标记为危险的命令或触碰特定路径 → 策略引擎拦截/警告
4. 提示词中的密钥 → UserPromptSubmit 扫描
5. 事后篡改日志 → HMAC 链式校验

**未覆盖：**
- 复制粘贴式传播（LLM 把密钥抄到别的文件里）
- 完整的文件系统隔离（请使用容器）
- `patterns.py` 中未收录的新型密钥格式
- Gemini CLI 的提示词（没有 `UserPromptSubmit` 等价物）
- 拥有本地写权限的用户直接修改 `policy.json` 或钩子本身——这防的是 *LLM* 绕过控制，不是防恶意的本地操作者

---

## 路线图 (v0.2)

- [ ] Ollama 上下文改写（200ms 超时，回退到正则）
- [ ] `Stop` 钩子，输出会话级脱敏摘要
- [ ] 执行前占位符替换（密钥永不进入 LLM 上下文）
- [ ] Homebrew formula + PyPI 发布
- [ ] GitHub Actions CI（Python 3.11–3.14，macOS/Linux/Windows）
- [ ] 合规/审计导出（基于 HMAC 日志生成类 SOC2 报告）
- [ ] 已安装 skills/MCP 服务器的供应链审查

---

## 许可证

MIT — 详见 [LICENSE](../LICENSE)。
