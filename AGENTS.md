# AGENTS.md — instructions for AI assistants working with this repository

For any LLM-based assistant (Claude, ChatGPT/Codex, Gemini, Copilot, Cursor, or
other) helping a user apply, debug, or extend the fixes in this repository.
Human readers want [README.md](README.md) and [INSTALL.md](INSTALL.md) instead.

## What this repository is

A bundle of fixes that stop the HorizonXI FFXI client (Ashita v4) from crashing
and leaking 32-bit address space when run on Linux under Wine/Proton. It is
**not** a mod, trainer, or gameplay tool. It targets two Wine-specific bug
classes plus a set of settings that HorizonXI updates revert.

You will normally be helping a user with a **live game install**. Treat their
Wine prefix as production: every change here is reversible and documented, but
confirm before you modify anything, and prefer the repo's scripts over ad-hoc
shell commands.

## Rule 0 — run the verifier before you theorise

```bash
python3 scripts/verify-install.py
```

It checks every layer and exits non-zero if any fail. **Do this before forming a
hypothesis, and again after any change.** Most questions ("is d3d8to9 actually
loaded?", "did the update break my LAA patch?") are answered by its output
directly, without reading a single log.

Add `--prefix` / `--game-dir` for non-default installs, or set the environment
variables in the table below.

## The scripts, and when to reach for each

| Script | Use when | Notes |
|---|---|---|
| `scripts/verify-install.py` | Always first, and after every change | Read-only. `--prefix`, `--game-dir`, `--games-json`, `--log` |
| `scripts/patch-renamer.py` | The addon patch is missing or was reverted by an update | `--check` first (read-only), then apply. `--revert` restores `.bak_upstream` |
| `scripts/apply-laa.py` | LAA lost after a client update | `--check` / `--revert`. Idempotent |
| `scripts/restore-config.py` | After a HorizonXI update reverted config | **`--dry-run` first.** Needs `scripts/restore-config.json` |
| `monitor/horizonxi-monitor.py` | User wants live in-session monitoring | Interactive curses TUI — do **not** launch it from a non-interactive tool call |

All are Python stdlib only, idempotent, and safe to re-run when nothing is
broken. Paths resolve **flag > environment variable > `$HOME`-relative
default**:

| Variable | Default |
|---|---|
| `HXI_PREFIX` | `$HOME/Games/faugus/horizonxi` |
| `HXI_GAME_DIR` | `<prefix>/drive_c/Program Files/HorizonXI/Game` |
| `HXI_GAMES_JSON` | `$HOME/.local/share/faugus-launcher/games.json` |
| `HXI_LOG` | `$HOME/.local/share/faugus-launcher/logs/horizonxi/proton.log` |
| `HXI_RESTORE_CONFIG` | `scripts/restore-config.json` |

Never hardcode a home directory or username into anything you write here.

## Hard rules — these cause real damage if you get them wrong

1. **Never copy `patches/dynamic_entity_renamer.lua` over a newer upstream
   file.** HorizonXI 2.0 rewrote that addon and added its own `zoneState`
   handling; overwriting reverts it and reintroduces zone-change instability.
   Use `scripts/patch-renamer.py`, which applies only missing fixes. The bundled
   `.lua` and `.diff` are reference material, not an install path.
2. **Never hardcode a PE file offset for the LAA patch.** The Characteristics
   field moved (`0x11e` → `0x106`) when HorizonXI 2.0 shipped a rebuilt
   `Ashita-cli.exe`, because `e_lfanew` changed. Patching a fixed offset
   corrupts the binary. `apply-laa.py` parses the header; use it.
3. **The Faugus JSON key is `addapp_enabled`, not `addapp_checkbox`.** The wrong
   name is silently ignored, Faugus launches the exe directly, the bat wrapper
   never runs, and the d3d8 leak stays. Older guides on the web have this wrong.
4. **Faugus config lives in `~/.local/share/faugus-launcher/`**, not
   `~/.config/faugus-launcher/`. The Wine log is `logs/horizonxi/proton.log`,
   not `steam-0.log`. App settings are `config.json`, not `config.ini`.
5. **Faugus must be fully closed before editing `games.json`** — it rewrites the
   file on exit and will discard your edit. Check with
   `pgrep -af 'faugus|Ashita|wine|umu'`.
6. **Never recommend `PROTON_DXVK_D3D8=1`.** It removes the d3d8 leak but causes
   a privileged-instruction crash at `0x7a2c3ffc` within ~30 min for
   FFXI/Ashita. Tested and confirmed bad.

## Credentials — do not leak these

- `scripts/restore-config.json` contains the user's HorizonXI password in
  plaintext (as `config/boot/ashita.ini` already does). It is **gitignored** and
  mode 600. Only `restore-config.example.json` is tracked.
- **Never print, echo, log, or commit its contents.** If you generate or edit
  it, report field *presence* ("password: set"), never the value.
- **Never read `/proc/<pid>/cmdline` for the game process.** HorizonXI's loader
  takes credentials as CLI arguments. The monitor deliberately avoids this.
- Before any commit touching this repo, confirm no credential reached a
  trackable file:
  ```bash
  git ls-files -co --exclude-standard | xargs grep -l "<the password>" || echo clean
  ```
- Ashita redacts the `command` line in its own boot-config log dump, so
  `Game/logs/*.txt` are safe to share. Faugus/Wine logs are also safe.

## Reading logs without raising false alarms

The Wine log is `$HOME/.local/share/faugus-launcher/logs/horizonxi/proton.log`.

| Signal | Meaning | Action |
|---|---|---|
| `code=e24c4a02`, thousands per session | **Normal.** LuaJIT's internal SEH code (low bytes are ASCII `LJ`) — this is how it implements `pcall` | None. Do not report as a fault |
| `code=c0000005` | Real access violations. Bounded bursts during combat/zoning are expected | Investigate only if sustained or huge |
| `out of memory for allocation` | Pre-crash. VA is exhausting | Tell the user to log out; the wrapper is likely not active |
| `err:d3d8:` | Wine builtin d3d8 is loaded — the bat wrapper did not run | Recheck `addapp_enabled` and the syswow64 md5 |

Crash address legend:

| Address | Cause |
|---|---|
| `0x79800097` page fault write to NULL | Wine builtin d3d8 OOM cascade (Class 2) |
| `0x7a2c3ffc` privileged instruction | DXVK d3d8 — do not use it for FFXI |
| `0x78xxxxxx` range | Inside Ashita's `Addons.dll` dispatcher — addon-driven (Class 1) |

The real game process is **`horizon-loader.exe`** (comm truncates to
`horizon-loader.`), *not* `Ashita-cli.exe`, which is only a bootstrap.
Monitoring the wrong PID yields nothing.

## Diagnosing "the game won't start"

Check in this order — the first two are far more common than any Wine issue:

1. **Logs in, then closes after ~5s, no crash dump.** Not a crash. Check
   `pivot | m_rootPath` in `<GAME>/logs/<newest>.txt`. A wrong `root_path` in
   `config/pivot/pivot.ini` makes every overlay log `=> failed`. Fix with
   `restore-config.py`.
2. **Exits before a window appears, after a game-data update.** Check
   `use_interface_bypass = 1` in `config/sandbox/sandbox.ini` (HorizonXI ships
   `0`). This broke launching on the 2.0.0 update.
3. **"Failed connection" at login.** Usually the Proton runner, not this repo.
   The user should pin a known-good runner rather than a floating "Latest".
   `~/.local/share/faugus-launcher/games-backup/*.json` holds runner history.
4. **Plugin fails with "missing required exports."** Pre-2.0 plugin builds lack
   `expDestroyPlugin`. Extract the matching build from the update `.zip` — do
   not restore a binary from an older prefix.

Before blaming a config change for a failure, check whether the symptom
**predates** the change. This has produced wrong conclusions before.

## Do not re-litigate settled negative results

These were tested and rejected. Don't propose them as new ideas:

DXVK d3d8 (`PROTON_DXVK_D3D8=1`) · placing d3d8to9 only in the exe dir (Proton's
per-launch syswow64 copy wins) · placing it only in syswow64 (overwritten next
launch) · reverting to verbose `WINEDEBUG` (measurably worsens the leak) ·
disabling `DXVK_ASYNC` · `PROTON_NO_NTSYNC=1` · swapping gdiplus versions ·
installing DXVK via winetricks.

`CHANGELOG.md` and `README.md` record the reasoning.

## Extending or editing this repo

- Match the existing style: stdlib-only Python, `--check` / `--dry-run` /
  `--revert` where meaningful, idempotent, backups before mutation.
- Anchor text edits on **code fragments, not line numbers** — upstream files get
  rewritten by updates. `patch-renamer.py` is the model.
- Preserve line endings. `dynamic_entity_renamer.lua` is CRLF;
  `scripts/default.txt` is LF. Detect the *dominant* ending rather than testing
  for any CRLF; partially-rewritten files are mixed.
- Verify Lua edits compile (`luajit -bl <file>` or `luac -p`).
- Update `CHANGELOG.md` for anything user-visible, and re-run
  `verify-install.py` before declaring done.
- Test destructive logic against a **copy** of the game config, never the live
  prefix.

## If asked to share, publish, or package this

Read [`patches/ADDON-REVIEW.md`](patches/ADDON-REVIEW.md) first.

The addon patch modifies a **HorizonXI-distributed** file. As of the last
update, HorizonXI staff had **not** reviewed or sanctioned this repository, and
the README says so. Do not describe it as approved, endorsed, or officially
supported. If redistributing upstream's file is unwelcome, the repo can ship
`scripts/patch-renamer.py` alone — it contains none of upstream's code.

Do not weaken or remove the README's "Read this first" disclaimer.

## Tone when reporting to the user

Say what you verified and what you only inferred. `verify-install.py` output is
evidence; a guess about their GPU driver is not. If a check reports `SKIP`
because the game hasn't been launched yet, say that rather than implying it
passed.
