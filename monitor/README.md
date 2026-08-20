# horizonxi-monitor.py

Curses TUI for live monitoring of HorizonXI/Faugus/Proton Wine log metrics
during a play session. Standalone — Python stdlib only, no dependencies.

## Usage

```bash
python3 horizonxi-monitor.py
```

Press `q` to quit.

Requires Faugus logging to be on (Settings → **Enable logging**, or
`"logging-enabled": "True"` in `~/.config/faugus-launcher/config.json`).

## Panels

- **Header** — session duration, log size, syswow64 `d3d8.dll` md5 verdict
  (green if d3d8to9, red if Wine builtin or missing)
- **Critical** — OOM count, d3d8 error count, crash dump count + latest file.
  Any non-zero OOM or d3d8 = pre-crash signal (red)
- **Access Violations** — total `c0000005` count, 60-sec rate
  (green/yellow/red), last burst (count + when), 60-second sparkline
- **Game memory** — VmSize / VmPeak / VmRSS with a bar against the 4 GB cap, and
  a 60s delta rate (yellow at >1 MB/min, red "active VA leak" at >8 MB/min)
- **Server** — ICMP ping latency to the game server, so a network blip is
  distinguishable from a client problem
- **LuaJIT baseline** — total `e24c4a02` (normal Lua control flow), rate per min

## Paths

Defaults are probed rather than hardcoded, so a stock Faugus install needs no
configuration. The log is looked for in this order:

1. `~/.local/share/faugus-launcher/logs/horizonxi/proton.log`  ← current Faugus
2. `~/.local/share/faugus-launcher/logs/horizonxi/steam-0.log`
3. the same two under `~/.config/faugus-launcher/`             ← pre-move Faugus

Override anything via env:

```bash
HXI_MONITOR_LOG=/path/to/proton.log \
HXI_MONITOR_CRASH_DIR=/tmp/umu_crashreports \
HXI_MONITOR_D3D8=/path/to/syswow64/d3d8.dll \
HXI_MONITOR_D3D8TO9_MD5=f18148b1bc580a7b1f0df1f055782c31 \
HXI_MONITOR_GAME_COMM=horizon-loader.,ashita-cli.exe \
HXI_MONITOR_SERVER_HOST=play.horizonxi.com \
    python3 horizonxi-monitor.py
```

Set `HXI_MONITOR_SERVER_HOST=""` to disable the ping probe entirely.

## What "good" looks like

- d3d8 verdict: **green / d3d8to9 ✓**
- OOM: **0** — any number here means a crash is imminent
- d3d8 errors: **0** — any number means the wrapper failed and Wine builtin is active
- AV 60s rate: low single digits in normal play, spikes during combat and zoning
- VmSize: stable in the 2–3 GB range, with peaks during DXVK shader compiles
- 60s trend: hovering near 0 KB/min, brief positive bumps are fine
- LuaJIT: thousands per session is **normal**, not a fault — that's how LuaJIT
  implements `pcall`

## What to watch for

- **VmSize peak climbing past 3.5 GB** — close to the 4 GB cap; consider restarting soon
- **60s trend sustained > 8 MB/min** — active leak; something new is consuming VA
- **OOM > 0 with no crash yet** — pre-crash; log out before it dies
- **d3d8 verdict flipping to red mid-session** — would mean the syswow64 file
  changed, which shouldn't be possible without a relaunch

## Notes

- Tracks the actual game process by comm field. The real process is
  `horizon-loader.exe` (truncated to `horizon-loader.` in `/proc`), **not**
  `Ashita-cli.exe` — that's just a bootstrap. Monitoring the wrong PID gets you
  nothing useful.
- Deliberately does **not** read `/proc/<pid>/cmdline`: HorizonXI's loader takes
  credentials as CLI arguments, and displaying them could surface them in a
  screenshot or recording.
- The server probe uses ICMP via `/usr/bin/ping`. It deliberately does not
  TCP-probe the game ports, which would show up as connection attempts in
  server-side logs and rate limiters.
- Tails the log incrementally (tracks byte position), so refresh cost stays low
  even on multi-MB logs, and handles rotation (counters reset if the file
  shrinks or its inode changes).
