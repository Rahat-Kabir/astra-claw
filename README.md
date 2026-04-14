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
- Retries once on a fallback provider/model for transient LLM failures
- Groups tools by `toolset` and filters unavailable tools before exposing schemas to the model
- Persistent memory across sessions via `MEMORY.md` (agent notes) and `USER.md` (user profile), injected into the system prompt as a frozen snapshot
- Global `SOUL.md` persona file loaded from `~/.astraclaw/SOUL.md` as the primary identity layer
- Workspace fence: `--workspace <path>` locks `write_file` to a single directory tree for safe sandbox testing

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

Lock the agent to a sandbox directory for safe testing:

```text
$ python -m astra_claw --workspace d:/PROJECT/sandbox
Astra-Claw agent. Session: 2026-04-14_abcd1234
Workspace: d:\PROJECT\sandbox
```

`write_file` rejects any resolved path outside the workspace (relative escapes, absolute paths, or `~`). `read_file` and `shell` are not fenced and still run relative to the chdir'd cwd.

## Project Structure

```text
astra-claw/
|-- astra_claw/
|   |-- __main__.py           # entry point (interactive, one-shot, --session, --sessions)
|   |-- constants.py          # get_astraclaw_home()
|   |-- config.py             # config loading + defaults
|   |-- llm.py                # provider routing, client creation, fallback policy
|   |-- session.py            # JSONL session persistence
|   |-- memory.py             # MemoryStore - persistent memory (MEMORY.md + USER.md)
|   |-- soul.py               # SOUL.md loader + first-run seeding
|   |-- agent/
|   |   |-- loop.py           # AstraAgent - core conversation loop
|   |   `-- prompt_builder.py # system prompt assembly (SOUL.md + memory snapshot)
|   `-- tools/
|       |-- registry.py       # tool registry with toolsets and availability filtering
|       |-- file_tools.py     # read_file, write_file tools
|       |-- shell_tool.py     # shell command execution
|       |-- search_tool.py    # file search (content + filename)
|       `-- memory_tool.py    # memory tool (add/replace/remove)
|-- tests/
|   |-- agent/               # mocked agent loop tests
|   |-- tools/               # tool-level tests
|   |-- test_features.py     # core regression tests
|   |-- test_soul.py         # SOUL.md seeding and loading tests
|   `-- test_session.py      # session persistence tests
|-- docs/
|   |-- tech_spec.md         # technical design notes
|   |-- progress.md          # implementation progress log
|   `-- testing.md          # test commands and suite layout
`-- pyproject.toml
```

## Configuration

User data lives in `~/.astraclaw/` by default:

```text
~/.astraclaw/
|-- config.yaml
|-- SOUL.md
|-- sessions/
|-- memory/
|-- skills/
`-- logs/
```

`SOUL.md` is seeded automatically on first run if it does not already exist. Edit it to change Astra-Claw's default identity and tone globally.

Override defaults by creating `~/.astraclaw/config.yaml`:

```yaml
model:
  default: gpt-5.4-mini
  provider: openai
  fallback_provider: openrouter
  fallback_model: gpt-5.4-mini
agent:
  max_turns: 30
tools:
  enabled_toolsets:
    - filesystem
    - terminal
    - memory
memory:
  enabled: true
  user_profile_enabled: true
  memory_char_limit: 2200
  user_char_limit: 1375
```

If `tools.enabled_toolsets` is omitted, all registered and available tools are exposed.

Fallback retries only apply to transient/runtime failures such as timeouts, connection errors, rate limits, and 5xx responses. Auth and bad-request errors do not fail over.

## Testing

Run the full suite:

```bash
python -m pytest tests -v
```

For focused test commands and suite layout, see `docs/testing.md`.

## License

MIT
