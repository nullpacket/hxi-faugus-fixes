# HorizonXI Wine Stability Fixes

## Read this first

**Nothing here has been reviewed, endorsed, or sanctioned by the HorizonXI team.** This is an unaffiliated, community-made collection of changes by one player who wanted their client to stop crashing on Linux. It is not official, not supported by HorizonXI, and not supported by the Ashita, Faugus, Proton, DXVK, or d3d8to9 projects either.

**Use it at your own risk.**

- **Results will vary with your setup.** This was developed and tested on one machine — CachyOS, NVIDIA, Faugus, Proton-11.0-1-beta2. Different distros, GPUs, drivers, Wine forks, launchers, or HorizonXI versions may behave differently, or may not need these fixes at all.
- **It modifies your game install.** The steps patch a client executable, replace a system DLL inside your Wine prefix, and edit a HorizonXI-distributed addon. Every step is reversible and documented, but you are changing files the launcher expects to own.
- **I am not responsible for the outcome.** If your game stops launching, your install breaks, your prefix needs rebuilding, you lose progress, or your account is actioned or banned — that is on you, not on me. Back up anything you care about before you start.
- **Read `patches/ADDON-REVIEW.md` before you run the addon patch.** It documents exactly what that change does and does not affect. It is written so that you — or a server admin — can judge it for yourself rather than take my word for it. Whether running a modified copy of a server-distributed addon is acceptable is **HorizonXI's call, not mine**, and they have not made one.
- **If in doubt, ask HorizonXI staff first.** If they say don't, then don't — and please [open an issue](../../issues) so this repository can be corrected or taken down.

No warranty of any kind is offered; see [LICENSE](LICENSE).

---

A set of fixes that takes HorizonXI on Linux (Faugus/Proton) from **crashing every 30–60 minutes** to **multi-hour stable sessions including meriting parties** — without changing your client install or addon loadout.

All fixes are minimal, reversible, and target the actual root causes rather than working around them.

**Current for:** HorizonXI **2.0.1** (August 2026) · Ashita v4 · Proton 11.x / GE-Proton 10.x · d3d8to9 v1.15.1
If you set this up before August 2026, see [CHANGELOG.md](CHANGELOG.md) — the addon patch changed and the Faugus config paths moved.

## The problem

If you play HorizonXI on Linux via Wine/Proton, you've probably seen this:

```
Unhandled exception: page fault on write access to 0x00000000 in wow64 32-bit code (0x79800097)
winedbg: Internal crash at 7845AF12
```

Sessions die at 30–60 minutes, often during a BC fight or in a busy zone. The same client and addons run cleanly on native Windows. The crash address is always the same.

## Why it happens (two independent bug classes)

### Class 1 — Addon-induced access-violation storms

Per-frame addon code (notably `dynamic_entity_renamer`, shipped with HorizonXI) reads FFXI's entity table without sufficient validation. When an entity slot is in a transient state — mid-init, just-despawned, still streaming in after a zone — Wine faults on the read; Windows tolerates it silently via Low Fragmentation Heap behavior. Each fault grows `RtlGrowFunctionTable` by an entry, slowly leaking 32-bit virtual address space.

### Class 2 — Wine builtin d3d8 state-block leak

`d3d8_device_CreateStateBlock` in Wine's builtin `d3d8.dll` leaks ~4 MB of virtual address per allocation under sustained FFXI use. After ~2.5h on 4 GB of VA (with LAA) or ~1h on 2 GB (without), the next `CreateStateBlock` fails with `E_OUTOFMEMORY`. The caller writes through the returned NULL → fatal crash at `0x79800097`.

Both classes reproduce only on Wine, and both drain the same 32-bit address space until allocations fail.

## What this bundle fixes

| # | Layer | What it does |
|---|---|---|
| 1 | **LAA patch on `Ashita-cli.exe`** | Flips one bit in the PE header so Wine gives the 32-bit process 4 GB of VA instead of 2 GB |
| 2 | **Minimal WINEDEBUG** | Stops Proton's default verbose `+seh,+unwind` logging from amplifying the leak (each caught exception generated ~100 stderr lines) |
| 3 | **Patched `dynamic_entity_renamer`** | Fixes a truthy-check bug, validates entity slots before writing names, throttles rendering to 10 Hz |
| 4 | **d3d8to9 wrapper** | Translates d3d8 calls to d3d9 so DXVK's d3d9 backend handles them (no leak) instead of Wine's builtin d3d8 |
| 5 | **Bat launch wrapper** | Required because Proton overwrites `syswow64/d3d8.dll` with the Wine builtin on every launch. The wrapper copies d3d8to9 back in after Proton's setup. |
| 6 | **DLL override** | `WINEDLLOVERRIDES=d3d8=n,b`, belt-and-suspenders |

Since HorizonXI 2.0 there is also a **third category** that isn't a Wine bug at all: settings that a game update silently reverts, one of which stops the game launching entirely. Those are covered in [UPDATING.md](UPDATING.md) and automated by `scripts/restore-config.py`.

## Real-world results

| Metric | Before | After |
|---|---|---|
| Longest stable session | 58 min (crashed) | **2.30 hours of meriting** (clean shutdown) |
| Crashes per 2-hour window | ~2 | **0** |
| `out of memory for allocation` warnings | 270+ before fatal | **0** |
| `err:d3d8:` Wine builtin errors | dozens | **0** |
| AV storm volume absorbed | 74k AVs → fatal | 138k AVs → no crash |

## What's in this bundle

```
hxi-faugus-fixes/
├── README.md                       ← this file
├── INSTALL.md                      ← step-by-step apply instructions
├── UPDATING.md                     ← what a HorizonXI update breaks, and how to restore it
├── CHANGELOG.md                    ← what changed between bundle revisions
├── AGENTS.md                       ← instructions for AI assistants (any vendor)
├── CLAUDE.md                       ← pointer to AGENTS.md for Claude Code
├── scripts/
│   ├── apply-laa.py                ← LAA patcher (idempotent, --check / --revert)
│   ├── patch-renamer.py            ← addon patcher (idempotent, survives upstream rewrites)
│   ├── restore-config.py           ← re-apply config an update reverted
│   ├── restore-config.example.json ← copy to restore-config.json and edit
│   ├── verify-install.py           ← one-shot health check of every layer
│   └── faugus-horizonxi.bat        ← launch wrapper for Faugus addapp_bat
├── patches/
│   ├── dynamic_entity_renamer.lua        ← patched file, for reference
│   ├── dynamic_entity_renamer.lua.diff   ← readable diff vs the 2.0 upstream
│   ├── ADDON-REVIEW.md                   ← review notes: scope, behaviour, fairness
│   └── NOTE.md                           ← what each change does and why
├── bin/
│   ├── d3d8.dll                    ← d3d8to9 v1.15.1 (crosire's release, unmodified)
│   └── SOURCE.txt                  ← download URL + checksum to verify it yourself
└── monitor/
    ├── horizonxi-monitor.py        ← optional curses TUI for live monitoring
    └── README.md                   ← monitor instructions
```

## Quick start

```bash
python3 scripts/verify-install.py     # see which layers are missing
```

Then follow [INSTALL.md](INSTALL.md), and re-run `verify-install.py` when you're done. It exits non-zero if any layer is broken, so it also works as a pre-launch check after a HorizonXI update.

## Caveats

- Tested on **CachyOS + Proton-11.0-1-beta2 (and earlier GE-Proton10-34) + Faugus**. Other distros, Mesa drivers, or Wine forks may behave differently, but the underlying bug classes apply broadly.
- VmSize can still peak around 3.5 GB during shader-compile-heavy moments (zoning into a new area). Restarting between very long (5h+) sessions remains advisable.
- The addon patch covers one specific addon. Other Lua addons may have similar fault paths; the same `pcall` + `GetSpawnFlags` pattern applies to them.
- HorizonXI updates overwrite bundled addons and reset several config files. See [UPDATING.md](UPDATING.md).
- Pin your Proton runner. A floating "Latest" has regressed the login connection before; the version this was validated against is `Proton-11.0-1-beta2`.

## Credits

This bundle is unaffiliated with any of the projects below — but none of it would exist without them.

**Game and client:**
- **[HorizonXI](https://horizonxi.com/)** — the FFXI private server we play on
- **[HorizonXI Addons](https://horizonxi.com/addons)** — curated addon set shipped by HorizonXI
- **[Ashita v4](https://www.ashitaxi.com/)** ([source](https://github.com/AshitaXI/Ashita)) by the Ashita Development Team — the FFXI client framework that hosts the Lua addons; the addon patch uses its `IEntity` API (`GetActorPointer`, `GetSpawnFlags`, `GetName`)

**The addon we patched** (in `patches/`):
- `dynamic_entity_renamer.lua` — authored by **zach2good, TeoTwawki, atom0s**, distributed as part of the HorizonXI addon bundle. The Ashita-v4 port shares lineage with TeoTwawki's [`renamer`](https://github.com/TeoTwawki/renamer) addon family. Our patch is purely defensive — see [`patches/ADDON-REVIEW.md`](patches/ADDON-REVIEW.md) for a full account of what it changes, and `patches/dynamic_entity_renamer.lua.diff` for the exact lines.

**The d3d8 wrapper** (in `bin/`):
- **[d3d8to9](https://github.com/crosire/d3d8to9)** by **crosire** — translates D3D8 calls to D3D9. We bundle the official v1.15.1 release unmodified; see `bin/SOURCE.txt` for the upstream URL and checksum.

**Linux runtime stack:**
- **[Faugus Launcher](https://github.com/Faugus/faugus-launcher)** — the Linux game launcher used for the install paths in this guide
- **[UMU Launcher](https://github.com/Open-Wine-Components/umu-launcher)** — Proton runtime invocation layer used under Faugus
- **[GE-Proton](https://github.com/GloriousEggroll/proton-ge-custom)** by GloriousEggroll / Proton by Valve — the Wine fork used during debugging
- **[DXVK](https://github.com/doitsujin/dxvk)** by Philip Rebohle (doitsujin) and contributors — Vulkan-based D3D9/10/11 translator that handles d3d8to9's output
- **[Wine Project](https://www.winehq.org/)** — for the underlying win32 emulation and the debug channels used for diagnosis
