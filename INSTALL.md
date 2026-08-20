# Install Guide

Step-by-step recipe. Apply in order. Each step has verification, and
`scripts/verify-install.py` checks all of them at once at the end.

## Prerequisites

- [HorizonXI](https://horizonxi.com/) installed via [Faugus Launcher](https://github.com/Faugus/faugus-launcher) (which uses [UMU Launcher](https://github.com/Open-Wine-Components/umu-launcher) + [Proton](https://github.com/GloriousEggroll/proton-ge-custom) under the hood). Validated against Proton-11.0-1-beta2; GE-Proton10-34 also worked.
- The HorizonXI addon bundle installed, including `dynamic_entity_renamer`
- Game and Faugus fully closed — Faugus rewrites `games.json` on exit and will
  overwrite edits you make while it is running:
  ```bash
  pgrep -af 'faugus|Ashita|wine|umu'
  ```
- Python 3 (all scripts are stdlib-only)

Throughout this guide, replace `<PREFIX>` with your Wine prefix and `<GAME>`
with your game directory inside it. Stock Faugus defaults:

| | |
|---|---|
| `<PREFIX>` | `~/Games/faugus/horizonxi` |
| `<GAME>` | `<PREFIX>/drive_c/Program Files/HorizonXI/Game` |
| Faugus game config | `~/.local/share/faugus-launcher/games.json` |
| Faugus app config | `~/.config/faugus-launcher/config.json` |
| Wine log | `~/.local/share/faugus-launcher/logs/horizonxi/proton.log` |

> **Note on paths.** Faugus moved its state from `~/.config/faugus-launcher/` to
> `~/.local/share/faugus-launcher/`, and the per-game Wine log is now
> `proton.log` rather than `steam-0.log`. Older guides (including earlier
> revisions of this one) point at the old locations. If both directories exist
> on your machine, the one holding `games.json` is the live one.

## Step 1 — Patch `Ashita-cli.exe` for LARGEADDRESSAWARE

Doubles the 32-bit VA cap from 2 GB to 4 GB. Single bit flip in the PE header.

```bash
python3 scripts/apply-laa.py "<GAME>/Ashita-cli.exe"
```

The script backs up to `<GAME>/Ashita-cli.exe.bak_no_laa` first, and is
idempotent.

**Verify:**
```bash
python3 scripts/apply-laa.py --check "<GAME>/Ashita-cli.exe"
# Expected: LAA=YES  (Characteristics=0x0122 at offset ...)
```

The script locates the Characteristics field by parsing the PE header. Do not
hardcode a file offset — it moved when HorizonXI 2.0 shipped a rebuilt
`Ashita-cli.exe`, and patching a fixed offset would corrupt the binary.

**Revert:** `mv "<GAME>/Ashita-cli.exe.bak_no_laa" "<GAME>/Ashita-cli.exe"`

## Step 2 — Install d3d8to9 and the bat wrapper

```bash
cp bin/d3d8.dll "<GAME>/d3d8.dll"
cp scripts/faugus-horizonxi.bat "<GAME>/faugus-horizonxi.bat"
```

**Verify:**
```bash
md5sum "<GAME>/d3d8.dll"
# Expected: f18148b1bc580a7b1f0df1f055782c31
```

If your game is installed somewhere other than
`C:\Program Files\HorizonXI\Game`, edit the two paths inside the `.bat` to match.

## Step 3 — Wire the bat wrapper into Faugus

Edit `~/.local/share/faugus-launcher/games.json` and find your HorizonXI entry.
**Close Faugus first** — it rewrites this file on exit.

Set these three fields:

```json
"addapp_enabled": "addapp_enabled",
"addapp_bat": "<GAME>/faugus-horizonxi.bat",
"launch_arguments": "WINEDEBUG=+timestamp,+pid,+tid,-all,err+all,warn+seh,+debugstr WINEDLLOVERRIDES=d3d8=n,b",
```

> The JSON key is **`addapp_enabled`**, not `addapp_checkbox`. Earlier revisions
> of this guide named the wrong key; setting `addapp_checkbox` does nothing and
> Faugus silently launches the exe directly, bypassing the wrapper.

Why each part of `launch_arguments` matters:
- The minimal `WINEDEBUG` prevents Proton's verbose default from amplifying
  caught exceptions into a synchronous-I/O storm. This is not just noise
  reduction — verbose logging measurably worsens the leak.
- `WINEDLLOVERRIDES=d3d8=n,b` tells Wine to prefer the native d3d8 that the
  wrapper copies into place.

While you're in the config, **pin your runner** — set `"runner"` to a specific
Proton version rather than a floating "Latest". A runner change has previously
reintroduced login connection failures.

To capture the Wine log (needed for the monitor and for any further debugging),
enable logging in Faugus: Settings → **Enable logging**, or set
`"logging-enabled": "True"` in `~/.config/faugus-launcher/config.json`.

## Step 4 — Patch `dynamic_entity_renamer`

```bash
python3 scripts/patch-renamer.py \
  "<GAME>/addons/dynamic_entity_renamer/dynamic_entity_renamer.lua"
```

This applies three fixes, each only if missing, so it is idempotent and safe to
re-run after any HorizonXI update. It backs up the untouched upstream file to
`.bak_upstream`, preserves the file's CRLF line endings, and byte-compiles the
result (reverting automatically if the patched file does not compile).

> **Do not copy `patches/dynamic_entity_renamer.lua` over a newer upstream
> file.** HorizonXI 2.0 rewrote this addon and added its own zone-state
> handling; overwriting it with a pre-2.0 patched copy silently reverts that.
> The full patched file is included for reference and hand-inspection only.

**Verify:**
```bash
python3 scripts/patch-renamer.py --check "<GAME>/addons/.../dynamic_entity_renamer.lua"
# Expected: truthy / guards / throttle all "present"
```

**Revert:** `python3 scripts/patch-renamer.py --revert "<GAME>/addons/.../dynamic_entity_renamer.lua"`

See [patches/NOTE.md](patches/NOTE.md) for what each fix does and why.

## Step 5 — Check the settings that updates revert

These are not Wine fixes, but a HorizonXI update resets them and one of them
stops the game launching at all. Confirm:

```bash
grep root_path "<GAME>/config/pivot/pivot.ini"
# Expected: root_path=C:\Program Files\HorizonXI\Game\polplugins\DATs
#   A wrong root makes every overlay fail and the game exits ~5s after login.

grep use_interface_bypass "<GAME>/config/sandbox/sandbox.ini"
# Expected: use_interface_bypass = 1
#   HorizonXI ships 0; with 0, a game-data update can break the PlayOnline
#   version check and FFXI exits before creating a window.
```

To automate this and the rest of the post-update restore, see
[UPDATING.md](UPDATING.md).

## Step 6 — Verify everything

```bash
python3 scripts/verify-install.py
```

This checks all six layers plus the config above, and reports the counters from
your last session's log. Two checks (`d3d8to9 active in syswow64`, the log
counters) only become meaningful after you have launched the game once — they
report `SKIP` until then.

Launch HorizonXI through Faugus normally, then re-run it. Everything should be
`PASS`. The single most important line is:

```
PASS  d3d8to9 active in syswow64  wrapper ran
```

If that says `FAIL`, the bat wrapper did not run and you still have the
Class 2 leak.

## Step 7 — (Optional) Run the monitor

```bash
python3 monitor/horizonxi-monitor.py
```

A TUI with session duration, AV count and 60-second sparkline, OOM warnings,
d3d8 status, game memory usage against the 4 GB cap, and a server-reachability
ping. Press `q` to quit. See [monitor/README.md](monitor/README.md).

## Troubleshooting

### Game logs in, then closes after ~5 seconds

**This is not a crash** — there is no dump, and the Ashita log ends in an
orderly `AshitaCore::Release` / `UninstallAshita` unwind. Check
`<GAME>/logs/<newest>.txt` for the `pivot | m_rootPath` line first: a wrong root
path makes every `addOverlay` log `=> failed` while the fopen hook stays
installed. Fix `root_path` in `config/pivot/pivot.ini` (Step 5).

If the root path is correct, check `use_interface_bypass = 1` in
`config/sandbox/sandbox.ini` — that's what broke launching on the 2.0.0 update.

### Game crashes immediately on launch

Most likely a bad path in `games.json`. Check that `addapp_bat` points at an
existing file, with the exact path.

### `err:d3d8:` still appears in the log

The `d3d8.dll` in syswow64 isn't d3d8to9. Causes, in order of likelihood:
- `addapp_enabled` isn't set to `addapp_enabled` (check the key spelling)
- the paths inside the `.bat` don't match your install
- Faugus's "Edit Game" dialog round-tripped the JSON and dropped the addapp
  config — edit `games.json` directly rather than using the GUI

Confirm with `md5sum <PREFIX>/drive_c/windows/syswow64/d3d8.dll` after a launch.

### Login fails / "failed connection"

Usually the Proton runner, not this bundle. Pin the runner to a known-good
version (`Proton-11.0-1-beta2` is the one validated here) rather than a floating
"Latest". `~/.local/share/faugus-launcher/games-backup/*.json` holds timestamped
runner history, which is useful for telling "I changed this while
troubleshooting" from "an update changed it".

Beware attributing a failure to a config change that came *after* the first
failure — check whether the symptom predates the change before blaming it.

### A plugin fails with "Plugin is missing required exports"

The DLL lacks one of Ashita v4's three entry points. Check with:

```bash
objdump -p plugins/X.dll | awk '/^\[Ordinal\/Name Pointer\] Table/,0' | grep -oE "exp[A-Za-z]+" | sort -u
# want: expCreatePlugin expDestroyPlugin expGetInterfaceVersion
```

Pre-2.0 plugin builds are missing `expDestroyPlugin` and will not load under
current Ashita. Pull the matching build out of the update package rather than
restoring an old binary from a pre-2.0 install:

```bash
unzip -o -j "<HorizonXI>/Downloads/HorizonXI-2_0_1.zip" "plugins/<Name>.dll" -d <dest>
```

### Visual regressions (missing textures, odd colors)

d3d8to9 is generally faithful but has occasional quirks versus native d3d8. To
back it out: `rm "<GAME>/d3d8.dll"` and set `"addapp_enabled": ""` in
`games.json`. You're back on Wine builtin d3d8 — rendering unchanged, and the
2.5h crash returns.

### Missing `api-ms-win-crt-*.dll` in the prefix

Normal. Wine provides these as builtins with no file on disk. Their absence is
not a dependency problem.

### `0xe24c4a02` exceptions all over the log

Normal, and not an error. That's LuaJIT's internal SEH exception code (low bytes
are ASCII `LJ`) — it's how LuaJIT implements `pcall`. Thousands per session is
expected. Real faults are `c0000005`.
