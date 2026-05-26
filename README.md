# HorizonXI Wine Stability Fixes

A set of fixes that takes HorizonXI on Linux (Faugus/Proton) from **crashing every 30–60 minutes** to **multi-hour stable sessions including meriting parties** — without changing your client install or addon loadout.

This bundle is the result of a focused debugging effort in May 2026. All fixes are minimal, reversible, and target the actual root causes (not workarounds).

## The problem

If you play HorizonXI on Linux via Wine/Proton, you've probably seen this:

```
Unhandled exception: page fault on write access to 0x00000000 in wow64 32-bit code (0x79800097)
winedbg: Internal crash at 7845AF12
```

Sessions die at 30–60 minutes. Often during a BC fight or busy zone. The same client+addons run cleanly on native Windows. The crash address is always the same.

## Why it happens (two independent bug classes)

### Class 1 — Addon-induced access-violation storms

Per-frame addon code (notably `dynamic_entity_renamer` shipped with HorizonXI) reads FFXI's entity table without sufficient validation. When an entity slot is in transient state (mid-init, just-despawned, post-zone settle), Wine faults on the read; Windows tolerates it silently via Low Fragmentation Heap behavior. Each fault grows `RtlGrowFunctionTable` by an entry, slowly leaking 32-bit virtual address space.

### Class 2 — Wine builtin d3d8 state-block leak

`d3d8_device_CreateStateBlock` in Wine's builtin `d3d8.dll` leaks ~4 MB virtual address per allocation under sustained FFXI use. After ~2.5h on 4 GB VA (with LAA) or ~1h on 2 GB (without), the next `CreateStateBlock` fails with `E_OUTOFMEMORY`. The caller (DSOUND-area code) writes through the returned NULL → fatal crash at `0x79800097`.

Both classes only manifest on Wine. Both compound to drain the 32-bit address space until allocations fail and the game crashes.

## What this bundle fixes

Six layers, all required together:

| # | Layer | What it does |
|---|---|---|
| 1 | **LAA patch on `Ashita-cli.exe`** | Flips one bit in PE header so Wine gives the 32-bit process 4 GB of VA instead of 2 GB |
| 2 | **Minimal WINEDEBUG** | Stops Proton's default verbose `+seh,+unwind` logging from amplifying the leak (each caught exception was generating ~100 stderr lines) |
| 3 | **Patched `dynamic_entity_renamer.lua`** | Adds entity validation, fixes a truthy-check bug, adds registry cleanup on zone change, throttles render to 10 Hz, adds 1s post-zoning settle |
| 4 | **d3d8to9 wrapper** | Translates d3d8 calls to d3d9 so DXVK's d3d9 backend handles them (no leak) instead of Wine's builtin d3d8 |
| 5 | **Bat launch wrapper** | Required because Proton overwrites `syswow64/d3d8.dll` with Wine builtin on every launch. The wrapper copies d3d8to9 back in after Proton's setup. |
| 6 | **DLL override** | `WINEDLLOVERRIDES=d3d8=n,b` as belt-and-suspenders |

## Real-world results

From a typical user's debugging session:

| Metric | Before | After |
|---|---|---|
| Longest stable session | 58 min (crashed) | **2.30 hours of meriting** (clean shutdown) |
| Crashes per 2-hour window | ~2 | **0** |
| `out of memory for allocation` warnings | 270+ before fatal | **0** |
| `err:d3d8:` Wine builtin errors | dozens | **0** |
| AV storm volume absorbed | 74k AVs → fatal | 138k AVs → no crash |

## What's in this bundle

```
horizonxi-wine-fixes/
├── README.md                      ← this file
├── INSTALL.md                     ← step-by-step apply instructions
├── scripts/
│   ├── apply-laa.py               ← one-shot LAA patcher (idempotent)
│   └── faugus-horizonxi.bat       ← launch wrapper for Faugus addapp_bat
├── patches/
│   ├── dynamic_entity_renamer.lua          ← patched version (drop in)
│   └── dynamic_entity_renamer.lua.diff     ← readable diff vs HorizonXI-shipped original
├── bin/
│   ├── d3d8.dll                   ← d3d8to9 v1.15.1 (from crosire's release)
│   └── SOURCE.txt                 ← download URL + md5 to verify if you don't trust the bundled binary
└── monitor/
    ├── horizonxi-monitor.py       ← optional curses TUI for live monitoring
    └── README.md                  ← monitor instructions
```

## Caveats

- Tested on **CachyOS + Proton-11.0-1-beta2 (and earlier GE-Proton10-34) + Faugus**. Other Linux distros / Mesa drivers / Wine forks may behave differently but the underlying bug classes apply broadly.
- VmSize can still peak around 3.5 GB during shader-compile-heavy moments (zone change into a new area). Restart between very long (5h+) sessions remains advisable.
- The `dynamic_entity_renamer` patch is one specific addon. Other Lua addons may have similar fault paths; the same `pcall` + `GetSpawnFlags` pattern can be applied to them.
- HorizonXI may update `dynamic_entity_renamer.lua` in a future patch, overwriting your patched copy. Keep the diff file handy to re-apply.

## Next steps

Read [INSTALL.md](INSTALL.md) for the step-by-step recipe.

If you hit problems, the [horizonxi-monitor.py](monitor/horizonxi-monitor.py) TUI surfaces all the relevant metrics in real time — VmSize trend, OOM count, d3d8 errors, AV bursts, sparkline. It's standalone (stdlib Python only); just run it in a terminal next to the game.

## Credits

This bundle is unaffiliated with any of the projects below — but none of it would exist without them.

**Game and client:**
- **[HorizonXI](https://horizonxi.com/)** — the FFXI private server we play on
- **[HorizonXI Addons](https://horizonxi.com/addons)** — curated addon set shipped by HorizonXI
- **[Ashita v4](https://www.ashitaxi.com/)** ([source](https://github.com/AshitaXI/Ashita)) by the Ashita Development Team — the FFXI client framework that hosts the Lua addons; we used the `IEntity` API (`GetActorPointer`, `GetSpawnFlags`, `GetName`) in the addon patch

**The addon we patched** (in `patches/`):
- `dynamic_entity_renamer.lua` — authored by **zach2good, TeoTwawki, atom0s**, distributed as part of the HorizonXI addon bundle. The Ashita-v4 port shares lineage with TeoTwawki's [`renamer`](https://github.com/TeoTwawki/renamer) addon family (`renamer` / `renamer-windower`). Our patch is purely defensive — see `patches/dynamic_entity_renamer.lua.diff` for the exact changes.

**The d3d8 wrapper** (in `bin/`):
- **[d3d8to9](https://github.com/crosire/d3d8to9)** by **crosire** — translates D3D8 calls to D3D9. We bundle the official v1.15.1 release unmodified; see `bin/SOURCE.txt` for upstream URL and checksum.

**Linux runtime stack:**
- **[Faugus Launcher](https://github.com/Faugus/faugus-launcher)** — the Linux game launcher used for the install paths in this guide
- **[UMU Launcher](https://github.com/Open-Wine-Components/umu-launcher)** — Proton runtime invocation layer used under Faugus
- **[GE-Proton](https://github.com/GloriousEggroll/proton-ge-custom)** by GloriousEggroll / Proton by Valve — the Wine fork used during debugging (Proton-11.0-1-beta2 and GE-Proton10-34 both tested)
- **[DXVK](https://github.com/doitsujin/dxvk)** by Philip Rebohle (doitsujin) and contributors — Vulkan-based D3D9/10/11 translator that handles d3d8to9's output
- **[Wine Project](https://www.winehq.org/)** — for the underlying win32 emulation and debug channels used for diagnosis
