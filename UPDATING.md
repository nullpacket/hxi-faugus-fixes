# After a HorizonXI Update

A HorizonXI game or launcher update rewrites **Horizon-bundled files only**.
Third-party addons and everything under `config/addons/**` (including
luashitacast profiles) survive untouched. But several things this bundle
depends on do get reverted — and one of them stops the game launching at all.

**Fastest path after any update:**

```bash
python3 scripts/verify-install.py        # what broke
python3 scripts/restore-config.py        # restore config (needs restore-config.json)
python3 scripts/apply-laa.py       "<GAME>/Ashita-cli.exe"
python3 scripts/patch-renamer.py   "<GAME>/addons/dynamic_entity_renamer/dynamic_entity_renamer.lua"
python3 scripts/verify-install.py        # confirm all green
```

Every one of those is idempotent, so running them when nothing broke is a no-op.

## What gets reverted, and why it matters

| Reverted | Symptom | Restored by |
|---|---|---|
| `config/pivot/pivot.ini` → `root_path=C:\Games\HorizonXI\polplugins\DATs` | **Game logs in then closes after ~5s.** Horizon's default install path, not a Faugus one. All overlays log `=> failed`, then a clean `UninstallAshita` — no crash, no dump | `restore-config.py` |
| `config/pivot/pivot.ini` `[overlays]` → full stock list | Not a crash. But a large texture overlay costs a lot of FPS in crowded areas, so a list you trimmed comes back | `restore-config.py` (`pivot_overlays`) |
| `config/boot/ashita.ini` → `command = --server play.horizonxi.com` | Autologin gone; stops at the login prompt | `restore-config.py` |
| `config/boot/ashita.ini` `[ffxi.registry]` | Resolution reset to 1920x1080 | `restore-config.py` |
| `scripts/default.txt` `HORIZON_*` blocks → stock minimal | luashitacast, addons and plugins stop loading. Your custom-user section outside the markers survives | `restore-config.py` |
| `config/sandbox/sandbox.ini` `use_interface_bypass` | A game-data update can break the PlayOnline version check; FFXI exits before creating a window | `restore-config.py` |
| `Ashita-cli.exe` | LAA lost (`0x0122` → `0x0102`); VA exhaustion crash returns ~1h sooner | `apply-laa.py` |
| `addons/dynamic_entity_renamer/` | The Wine AV storm returns | `patch-renamer.py` |

**Not touched by updates:** `Game/d3d8.dll`, `faugus-horizonxi.bat`, and your
Faugus `games.json` (runner pin, `WINEDLLOVERRIDES`, `addapp_bat`). Those only
change if you change them.

## Setting up restore-config.py

```bash
cp scripts/restore-config.example.json scripts/restore-config.json
chmod 600 scripts/restore-config.json
$EDITOR scripts/restore-config.json
```

Fill in your game directory, autologin credentials, display registry values, and
the plugin/addon load lists you actually want. Every section is optional —
delete what you don't want managed.

`restore-config.json` is gitignored. It holds your password in plaintext,
exactly as `ashita.ini` already does; keep it mode 600 and don't commit it.
(Ashita's own boot-config log dump redacts the `command` line, so the game's
logs are safe to share.)

Check before writing:

```bash
python3 scripts/restore-config.py --dry-run
```

## The addon patch: patch, don't overwrite

This is the one step where the obvious move is wrong.

HorizonXI 2.0 rewrote `dynamic_entity_renamer` and gave it its own `zoneState`
table — it now queues `packet_in 0x0E` until the zone is stable and clears
`name_list` on `packet_out 0x0A`. That supersedes the zone-leave cleanup and
post-zone settle window that the May 2026 version of this patch added.

**Copying an old patched `.lua` back in reverts upstream's new zone handling**
and reintroduces zone-change instability. `patch-renamer.py` applies only the
three fixes upstream still hasn't adopted (truthy check, entity guards, render
throttle), each only if missing.

If upstream changes shape enough that an anchor no longer matches, the script
reports which fix it couldn't apply and changes nothing else — re-apply that one
by hand from [patches/NOTE.md](patches/NOTE.md).

## Recovering a deleted plugin

Don't restore plugin binaries from an older prefix — pre-2.0 builds are missing
the `expDestroyPlugin` export and won't load under current Ashita. Pull the
matching build from the update package instead:

```bash
unzip -o -j "<HorizonXI>/Downloads/HorizonXI-2_0_1.zip" "plugins/<Name>.dll" -d <dest>
```

`config/<Plugin>/` settings are unaffected either way.

## Useful evidence when something breaks

- `<GAME>/logs/*.txt` — Ashita's own log. Compare a failing run against your
  last good one; first-vs-last timestamp shows session length, so a good session
  is hours and a failure is ~5 seconds.
- `~/.local/share/faugus-launcher/logs/horizonxi/` — the Wine log. **Faugus does not
  use a stable filename here**: it has written `proton.log` on one launch and
  `steam-default.log` on the next, in the same install. Take the newest file rather
  than hardcoding a name (`verify-install.py` and the monitor both probe by mtime).
  The `Proton:` line reveals the runner **actually** used, which can differ from what
  `games.json` says.
- `~/.local/share/faugus-launcher/games-backup/*.json` — timestamped runner
  history, good for distinguishing "an update changed this" from "I changed it
  while troubleshooting".

## GPU clock lock (not update-related, but it resets on every reboot)

NVIDIA's driver leaves the GPU in its P8 idle power state during FFXI — a 2002 game's
small, bursty submissions never look like enough load to trigger a clock ramp. The card
sits at ~300 MHz while you play, which cost ~35% of crowd framerate on the machine this
was measured on.

```bash
sudo nvidia-smi -lgc 1500,3135     # apply now (until reboot)
sudo nvidia-smi -rgc               # revert
```

`nvidia-settings -a '[gpu:0]/GPUPowerMizerMode=1'` is **not** a substitute — it reports
success, the clocks rise for about a second, then the driver silently resets the attribute
to 0.

To apply it automatically at boot:

```bash
sudo install -m644 scripts/nvidia-clock-lock.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nvidia-clock-lock.service
```

Check with `nvidia-smi --query-gpu=pstate,clocks.current.graphics --format=csv,noheader`
while the game runs — you want >=1500 MHz, not P8.
