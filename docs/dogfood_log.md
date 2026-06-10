# Dogfood Log

One line per friction point. Don't fix mid-week - log and move on.

## 2026-06-10

1. **No image support** - `@file:page-1.png` rejected (binary). All message content assumes string; vision needs multimodal parts.
2. **Emergent OCR workaround** - agent built its own pipeline (`uv run --with pillow/rapidocr`) to read a PNG. Worked, but ~14 shell calls + package downloads vs 1 native vision call.
3. **Approval gap** - `uv run --with <pkg>` installs arbitrary PyPI packages mid-conversation; dangerous-command approval never fired.
4. **No learning reflex** - fresh session re-solved the same image problem from scratch, same mistakes in same order (`<<PY` heredoc, bare `python -c`). Never used `memory` to save the workaround, never used `session_search` to find the prior fix.
5. **Win: preview-approve + xlsx pivot** - asked to run csv script on xlsx; agent extended script, installed openpyxl, ran it, even flagged mixed raw/summary data in sheet. 4 clean diff approvals.
6. **Install hit wrong env** - `uv pip install openpyxl` permanently mutated the hermes python 3.11 env (first thing on PATH), not the sandbox. Command approval silent again - #3 is a pattern.
7. **Memory fired, but on trivia** - agent saved a memory in the csv session ("file named test may be xlsx, check extensions") yet never saved the hard-won ocr workaround. Memory judgment is inconsistent, not absent - refines #4.
8. **Approval fatigue** - multi-file MVP build triggered 10+ individual `y` prompts. `a` (always approve) exists but agent never hints at it; most users will keep pressing `y` until they give up.
9. **Delegation didn't fire unprompted** - "build full MVP end to end" is a multi-file, self-contained task — a natural delegate candidate. Agent built inline instead, hit the turn limit. Delegation needs an explicit ask.
10. **Win: explicit delegation worked cleanly** - "add a pin feature, use delegate agent" → child read 9 files, patched models/routes/templates/CSS/tests, fixed its own `pytest` env failure (`uv run pytest`), added DB auto-migration. Visual confirmed in browser. Parent context untouched. 27 turns, 115s.
11. **Win: memory recall shortened OCR path** - fresh session took ~6 shells vs ~14 first time. Saved context reduced trial-and-error. Core limitation (no native vision) unchanged.
12. **Win: session resume recalled full schema** - `--session` loaded 120 messages, answered full DB schema including delegate-added `is_pinned` field across session boundary. No file reads needed.

## To Test

- [x] Delegation on a real repo task (explicit works; unprompted still doesn't fire)
- [x] Memory recall - shorter OCR path (~6 shells vs ~14), saved context reduced trial-and-error
- [x] Session resume (`--session`) + cross-session recall via session_search
- [ ] Long session (20+ turns) - does compaction keep early decisions? todo re-injection?
- [x] Quick checks: /usage, /retry, @diff, /skills — all pass. @diff graceful on non-git dir (suggested git init). /skills correct empty-state message.
