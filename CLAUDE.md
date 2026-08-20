See [AGENTS.md](AGENTS.md) — the instructions for AI assistants working with
this repository are kept there so they apply to any tool, not just Claude Code.

Two things worth loading before you touch anything:

- Run `python3 scripts/verify-install.py` before forming a hypothesis. It checks
  every layer and most questions are answered by its output alone.
- Never copy `patches/dynamic_entity_renamer.lua` over a newer upstream file —
  use `scripts/patch-renamer.py`. AGENTS.md explains why, along with the other
  hard rules and the credential-handling requirements.
