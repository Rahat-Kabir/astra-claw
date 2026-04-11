# Astra-Claw

An AI agent with tool calling capabilities. Talk to it in the terminal — it can read files, answer questions, and take actions using tools.

## What It Does

- Conversational AI agent with a tool-calling loop
- Reads and writes files via `read_file` and `write_file` tools
- Runs shell commands via `shell` tool (with dangerous command approval)
- Multi-turn conversations with session persistence (JSONL)
- Streaming responses — tokens print live as they arrive
- Supports OpenAI and OpenRouter as LLM providers

## Quick Start

```bash
git clone https://github.com/YOUR_USERNAME/astra-claw.git
cd astra-claw
python -m venv venv
.\venv\Scripts\Activate.ps1    # Windows PowerShell
# source venv/bin/activate     # Linux / macOS / Git Bash
pip install -e .
```

Set your API key:

```bash
# PowerShell
$env:OPENAI_API_KEY = "sk-..."

# Bash
export OPENAI_API_KEY="sk-..."
```

Run:

```bash
python -m astra_claw
```

## Usage

**Interactive mode** — starts a new session, saves every turn:

```
$ python -m astra_claw
Astra-Claw agent. Session: 2026-04-10_a1b2c3d4
Type 'exit' to quit.

> hey
Hello! How can I help you?
```

**Resume a session:**

```
$ python -m astra_claw --session 2026-04-10_a1b2c3d4
Resumed session: 2026-04-10_a1b2c3d4
Loaded 4 messages.
```

**List recent sessions:**

```
$ python -m astra_claw --sessions
```

**Shell commands** — the agent can run terminal commands (asks approval for dangerous ones):

```
> list all python files in this directory
[calls shell: find . -name "*.py"]

> delete the temp folder
⚠ Dangerous: recursive delete
Allow? (y/n): y
```

**One-shot mode** — no session saved:

```
$ python -m astra_claw "read README.md and summarize it"
```

## Project Structure

```
astra-claw/
├── astra_claw/
│   ├── __main__.py           # entry point (interactive, one-shot, --session, --sessions)
│   ├── constants.py          # get_astraclaw_home()
│   ├── config.py             # config loading + defaults
│   ├── session.py            # JSONL session persistence
│   ├── agent/
│   │   ├── loop.py           # AstraAgent — core conversation loop
│   │   └── prompt_builder.py # system prompt assembly
│   └── tools/
│       ├── registry.py       # tool registry
│       ├── file_tools.py     # read_file, write_file tools
│       └── shell_tool.py     # shell command execution
├── tests/
│   └── test_features.py      # unit tests for all features
└── pyproject.toml
```

## Configuration

User data lives in `~/.astraclaw/` (auto-created on first run):

```
~/.astraclaw/
├── config.yaml    # override default settings
├── sessions/      # conversation history (JSONL, one file per session)
├── memory/        # persistent memory (coming soon)
├── skills/        # custom skills (coming soon)
└── logs/
```

Override defaults by creating `~/.astraclaw/config.yaml`:

```yaml
model:
  default: gpt-5.4-mini
  provider: openai
agent:
  max_turns: 30
```

## License

MIT
