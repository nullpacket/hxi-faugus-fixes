# horizonxi-monitor.py

Curses TUI for live monitoring of HorizonXI/Faugus/Proton Wine log metrics
during a play session. Standalone (Python stdlib only, no dependencies).

## Usage

```bash
python3 horizonxi-monitor.py
```

Press `q` to quit.

## Panels

- **Header** — session duration, log size, syswow64 d3d8.dll md5 verdict
  (green if d3d8to9, red if Wine builtin or missing)
- **Critical** — OOM count, d3d8 error count, crash dump count + latest file.
  Any non-zero OOM or d3d8 = pre-crash signal (red)
- **Access Violations** — total c0000005 count, 60-sec rate (green/yellow/red),
  last burst (count + when), 60-second sparkline (height per cell = AVs that second)
- **Game memory** — VmSize / VmPeak / VmRSS with bar against 4 GB cap, 60s delta
  rate (yellow at >1 MB/min, red "active VA leak" at >8 MB/min)
- **LuaJIT baseline** — total e24c4a02 (normal Lua flow), rate per min

## Environment variable overrides

If your install paths differ from the defaults (one user's CachyOS+Faugus
setup), override via env:

```bash
HXI_MONITOR_LOG=/path/to/steam-0.log \
HXI_MONITOR_CRASH_DIR=/tmp/umu_crashreports \
HXI_MONITOR_D3D8=/path/to/syswow64/d3d8.dll \
HXI_MONITOR_D3D8TO9_MD5=f18148b1bc580a7b1f0df1f055782c31 \
    python3 horizonxi-monitor.py
```

The defaults assume:
- log:        `~/.config/faugus-launcher/logs/horizonxi/steam-0.log`
- crash dir:  `/tmp/umu_crashreports`
- d3d8 file:  `~/Games/faugus/horizonxi/drive_c/windows/syswow64/d3d8.dll`

## What "good" looks like

- d3d8 verdict: **green / d3d8to9 ✓**
- OOM: **0** (any number here means crash imminent)
- d3d8 errors: **0** (any number means wrapper failed and Wine builtin is active)
- AV 60s rate: low single digits in normal play, spikes during combat/zone changes
- VmSize: stable in 2–3 GB range; peaks during DXVK shader compile bursts
- 60s trend: hovering around 0 KB/min, brief positive bumps OK

## What to watch for

- **VmSize peak climbing past 3.5 GB** — getting close to the 4 GB cap; consider restarting soon
- **60s trend sustained > 8 MB/min** — active leak; something new is consuming VA
- **OOM > 0 with no crash yet** — pre-crash; save and log out before it dies
- **d3d8 verdict flipping to red mid-session** — extremely unusual; would mean the syswow64 file changed (shouldn't be possible without a relaunch)

## Notes

- Tracks the actual game process by comm field (`horizon-loader.exe`, truncated to
  `horizon-loader.` in /proc). Falls back to `ashita-cli.exe` if not found.
- Deliberately does NOT read /proc/<pid>/cmdline — HorizonXI passes credentials
  as CLI args. Reading them could risk surfacing them in logs.
- Tails the log incrementally (tracks byte position), so refresh cost stays
  low even on multi-MB logs.
- Handles log rotation: if the file shrinks or inode changes, all counters reset.
