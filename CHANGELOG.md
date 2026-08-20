# Changelog

## 2026-08 — HorizonXI 2.0.x refresh

Brings the bundle current with the HorizonXI 2.0 client and the Faugus config
layout change. **If you installed this before August 2026, re-read
[INSTALL.md](INSTALL.md) — two of the old instructions are now actively wrong.**

### Breaking corrections

- **The addon patch must no longer be applied by copying the file in.**
  HorizonXI 2.0 rewrote `dynamic_entity_renamer` and added its own `zoneState`
  handling. Dropping the old patched `.lua` on top reverts that. The old
  `.diff` also no longer applies (all four hunks fail against the 2.0 upstream).
  Replaced by `scripts/patch-renamer.py`, which applies each fix only if
  missing. The bundled `.lua` and `.diff` are regenerated against the 2.0
  upstream and are now reference material, not the install path.
- **The Faugus `games.json` key is `addapp_enabled`, not `addapp_checkbox`.**
  The old name is not in Faugus's schema; setting it does nothing and the bat
  wrapper is silently bypassed, leaving the Class 2 d3d8 leak in place.
- **Faugus paths moved.** `games.json` is now at
  `~/.local/share/faugus-launcher/`, not `~/.config/faugus-launcher/`. The Wine
  log is `logs/horizonxi/proton.log`, not `steam-0.log`. App settings are
  `config.json` (`"logging-enabled": "True"`), not `config.ini`
  (`enable-logging=True`).
- **Don't hardcode the LAA file offset.** The PE Characteristics field moved
  from `0x11e` to `0x106` when 2.0 shipped a rebuilt `Ashita-cli.exe`, because
  `e_lfanew` changed. `apply-laa.py` always parsed the header rather than
  assuming an offset, so it was unaffected — but notes and one-liners floating
  around that patch `0x11e` directly will corrupt a 2.0 binary.

### Added

- `scripts/patch-renamer.py` — idempotent addon patcher. Anchors on code
  fragments rather than line numbers, applies only missing fixes, preserves
  CRLF, backs up to `.bak_upstream`, byte-compiles the result with
  `luajit`/`luac` and auto-reverts if it doesn't compile. `--check` / `--revert`.
- `scripts/verify-install.py` — one-shot health check of every layer (LAA,
  d3d8to9 in both locations, bat wrapper, addon patch, Faugus wiring, pivot and
  sandbox config, last session's log counters). Non-zero exit on any failure.
- `scripts/restore-config.py` + `restore-config.example.json` — re-applies the
  config a HorizonXI update reverts: pivot `root_path`, autologin,
  `[ffxi.registry]` display settings, `use_interface_bypass`, and the
  `HORIZON_PLUGINS` / `HORIZON_ADDONS` blocks in `default.txt`. Config-driven so
  no credentials live in the script; `restore-config.json` is gitignored.
- `UPDATING.md` — what a HorizonXI update reverts and how to restore it.
- Coverage of the 2.0-era launch failures that aren't Wine bugs at all: the
  `pivot.ini` `root_path` reset ("logs in then closes after ~5s") and
  `use_interface_bypass` (game-data update breaks the PlayOnline version check).
- Troubleshooting for the pre-2.0 plugin `expDestroyPlugin` export problem.

### Changed

- `monitor/horizonxi-monitor.py` — synced with the newer working copy, adding
  the server-reachability ping and configurable game process names. Default
  paths no longer hardcode a home directory, and the log path probes the new
  and old Faugus locations in turn.
- `patches/NOTE.md` — rewritten. Documents the three fixes still needed and
  explicitly records the two that upstream absorbed (zone-leave registry cleanup
  and the 1s post-zone settle window), so they don't get re-added.
- `bin/d3d8.dll` — unchanged. d3d8to9 v1.15.1 is still the current upstream
  release; re-verified against crosire's releases in August 2026.

## 2026-05 — Initial release

LAA patch, minimal WINEDEBUG, patched `dynamic_entity_renamer`, d3d8to9 via bat
wrapper, DLL override, and the monitor TUI. Took sessions from ~58 minutes
(crash) to 2.30 hours (clean shutdown) with zero OOM warnings and zero
`err:d3d8:` lines.
