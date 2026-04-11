# Astra-Claw

An AI agent with tool calling capabilities. Talk to it in the terminal - it can read files, answer questions, and take actions using tools.

## What It Does

- Conversational AI agent with a tool-calling loop
- Reads and writes files via `read_file` and `write_file`
- Runs shell commands via `shell` with dangerous-command approval
- Searches files via `search_files` for content or filenames
- Persists interactive sessions as JSONL transcripts
- Streams responses as tokens arrive
- Supports OpenAI and OpenRouter
- Groups tools by `toolset` and filters unavailable tools before exposing schemas to the model

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

Interactive mode starts a new session and saves every turn:

```text
$ python -m astra_claw
Astra-Claw agent. Session: 2026-04-10_a1b2c3d4
Type 'exit' to quit.

> hey
Hello! How can I help you?
```

Resume a session:

```text
$ python -m astra_claw --session 2026-04-10_a1b2c3d4
Resumed session: 2026-04-10_a1b2c3d4
Loaded 4 messages.
```

List recent sessions:

```text
$ python -m astra_claw --sessions
```

One-shot mode does not save a session:

```text
$ python -m astra_claw "read README.md and summarize it"
```

## Project Structure

```text
astra-claw/
|-- astra_claw/
|   |-- __main__.py           # entry point (interactive, one-shot, --session, --sessions)
|   |-- constants.py          # get_astraclaw_home()
|   |-- config.py             # config loading + defaults
|   |-- session.py            # JSONL session persistence
|   |-- agent/
|   |   |-- loop.py           # AstraAgent - core conversation loop
|   |   `-- prompt_builder.py # system prompt assembly
|   `-- tools/
|       |-- registry.py       # tool registry with toolsets and availability filtering
|       |-- file_tools.py     # read_file, write_file tools
|       |-- shell_tool.py     # shell command execution
|       `-- search_tool.py    # file search (content + filename)
|-- tests/
|   `-- test_features.py      # unit tests for core features
`-- pyproject.toml
```

## Configuration

User data lives in `~/.astraclaw/` by default:

```text
~/.astraclaw/
|-- config.yaml
|-- sessions/
|-- memory/
|-- skills/
`-- logs/
```

Override defaults by creating `~/.astraclaw/config.yaml`:

```yaml
model:
  default: gpt-5.4-mini
  provider: openai
agent:
  max_turns: 30
tools:
  enabled_toolsets:
    - filesystem
    - terminal
```

If `tools.enabled_toolsets` is omitted, all registered and available tools are exposed.

## Testing

The current regression suite for the core agent lives in `tests/test_features.py`.

```bash
.\venv\Scripts\Activate.ps1
python -m pytest tests/test_features.py -v
```

## License

MIT
