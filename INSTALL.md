# Install Guide

Step-by-step recipe. Apply in order. Each step has verification.

## Prerequisites

- [HorizonXI](https://horizonxi.com/) installed via [Faugus Launcher](https://github.com/Faugus/faugus-launcher) (which uses [UMU Launcher](https://github.com/Open-Wine-Components/umu-launcher) + [Proton](https://github.com/GloriousEggroll/proton-ge-custom) under the hood). Tested with Proton-11.0-1-beta2 and GE-Proton10-34.
- The HorizonXI launcher's [addon bundle](https://horizonxi.com/addons) installed, including `dynamic_entity_renamer`
- Game and Faugus fully closed (`pgrep -af 'faugus|Ashita|wine|umu'` returns nothing relevant)
- Know your Wine prefix path (default Faugus: `~/Games/faugus/horizonxi/`)
- Know the path to your HorizonXI install inside the prefix (default: `<prefix>/drive_c/Program Files/HorizonXI/Game/`)

Throughout this guide, replace `<PREFIX>` with your prefix path and `<GAME>` with your game install path.

## Step 1 — Patch `Ashita-cli.exe` for LARGEADDRESSAWARE

Doubles your 32-bit VA cap from 2 GB to 4 GB. Single byte flip in the PE header.

```bash
python3 scripts/apply-laa.py "<GAME>/Ashita-cli.exe"
```

The script makes a backup at `<GAME>/Ashita-cli.exe.bak_no_laa` first. It's idempotent (safe to run twice).

**Verify:**
```bash
python3 scripts/apply-laa.py --check "<GAME>/Ashita-cli.exe"
# Expected: "LAA=YES (chars=0x0122)"
```

**Revert:**
```bash
mv "<GAME>/Ashita-cli.exe.bak_no_laa" "<GAME>/Ashita-cli.exe"
```

## Step 2 — Install d3d8to9 + bat wrapper in the game directory

```bash
cp bin/d3d8.dll "<GAME>/d3d8.dll"
cp scripts/faugus-horizonxi.bat "<GAME>/faugus-horizonxi.bat"
```

**Verify:**
```bash
md5sum "<GAME>/d3d8.dll"
# Expected: f18148b1bc580a7b1f0df1f055782c31
```

## Step 3 — Wire the bat wrapper into Faugus

Edit `~/.config/faugus-launcher/games.json` for your HorizonXI entry. Make sure Faugus is fully closed before editing (it overwrites the file on game exit).

Change:
```json
"addapp_checkbox": "",
"addapp_bat": "",
"launch_arguments": "...whatever you had...",
```
To:
```json
"addapp_checkbox": "addapp_enabled",
"addapp_bat": "<GAME>/faugus-horizonxi.bat",
"launch_arguments": "WINEDEBUG=+timestamp,+pid,+tid,-all,err+all,warn+seh,+debugstr WINEDLLOVERRIDES=d3d8=n,b",
```

Why each part of launch_arguments matters:
- The minimal `WINEDEBUG` prevents Proton's verbose default from amplifying any caught exceptions into a synchronous-I/O storm.
- The `WINEDLLOVERRIDES=d3d8=n,b` tells Wine to prefer native d3d8 (our file copied by the wrapper).

Also set `enable-logging=True` in `~/.config/faugus-launcher/config.ini` so Wine output gets captured to the log file (only needed if you want to use the monitor or do further debugging).

## Step 4 — Patch `dynamic_entity_renamer`

```bash
# Backup the HorizonXI-shipped version
cp "<GAME>/addons/dynamic_entity_renamer/dynamic_entity_renamer.lua" \
   "<GAME>/addons/dynamic_entity_renamer/dynamic_entity_renamer.lua.bak_original"

# Replace with patched
cp patches/dynamic_entity_renamer.lua \
   "<GAME>/addons/dynamic_entity_renamer/dynamic_entity_renamer.lua"
```

Or apply the diff directly:
```bash
cd "<GAME>/addons/dynamic_entity_renamer"
patch -b dynamic_entity_renamer.lua < /path/to/patches/dynamic_entity_renamer.lua.diff
```

**Verify:** load the game and check that NPC/BC names are still rendering correctly. The fix only adds defensive guards; behavior should be identical when entities are valid.

## Step 5 — Verify everything on first launch

Launch HorizonXI through Faugus normally. After login, run from another terminal:

```bash
# 1. The bat wrapper ran and overwrote Proton's d3d8 with d3d8to9:
md5sum <PREFIX>/drive_c/windows/syswow64/d3d8.dll
# Expected: f18148b1bc580a7b1f0df1f055782c31

# 2. Zero d3d8 errors in the log (if you enabled logging):
grep -c 'err:d3d8:' ~/.config/faugus-launcher/logs/horizonxi/steam-0.log
# Expected: 0

# 3. The game process is running:
pgrep -af horizon-loader.exe
# Should show one PID
```

## Step 6 — (Optional) Run the monitor

In a separate terminal:
```bash
python3 monitor/horizonxi-monitor.py
```

You'll see a TUI with session duration, AV count, OOM warnings, d3d8 status, game memory usage, and a 60-second sparkline of access-violation rate. Press `q` to quit.

If you see:
- **OOM > 0**: the d3d8to9 wrapper isn't loading correctly. Recheck steps 2-3.
- **d3d8 errors > 0**: Wine builtin d3d8 is active. Recheck syswow64 md5; the bat wrapper isn't running.
- **VmSize climbing >8 MB/min sustained**: active VA leak. Restart the game, file an issue with the log.

## Troubleshooting

### Game crashes immediately on launch

Most likely cause: a path in `games.json` is wrong. Check the `addapp_bat` field points to an existing file with the exact path. Verify by manually running the bat file as a sanity check (it should fail visibly).

### Game launches but immediately exits

The bat wrapper might be syntactically wrong. Open `<GAME>/faugus-horizonxi.bat` and verify it has no Windows line ending issues — should look like:
```batch
@echo off
copy /Y "C:\Program Files\HorizonXI\Game\d3d8.dll" "C:\windows\syswow64\d3d8.dll" >nul
"C:\Program Files\HorizonXI\Game\Ashita-cli.exe" %*
```

### `err:d3d8:` still appearing in log after launch

The d3d8.dll in syswow64 isn't d3d8to9. Causes:
- The bat wrapper isn't running (check `addapp_checkbox` is `addapp_enabled`, not just empty)
- The path inside the bat is wrong for your install
- Faugus's "Edit Game" dialog round-tripped the JSON and stripped the addapp config (don't use the GUI; edit games.json directly)

### Visual regressions (missing textures, weird colors)

d3d8to9 is generally very faithful but has occasional quirks vs. native d3d8. If something looks wrong, you can:
1. Remove just the d3d8to9 wrapper (`rm <GAME>/d3d8.dll`) and disable `addapp_checkbox` — back to Wine builtin (will crash again after 2.5h but rendering will be unchanged)
2. Report which visual is broken; d3d8to9 is actively maintained

### Future HorizonXI update overwrites the patched addon

If you run the Horizon launcher GUI, it may rewrite the addon. Either:
- Don't run the Horizon launcher GUI (launch HorizonXI directly via Faugus per these instructions)
- Re-apply the patch after each launcher run (the `.diff` file is small enough to script)
