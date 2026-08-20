# patches/

> **Reviewing this patch for a server, or deciding whether to trust it?**
> Read [ADDON-REVIEW.md](ADDON-REVIEW.md). It covers what the addon does, where
> its data comes from, exactly what the three changes affect, and why the
> patched addon can only ever display a subset of what the unpatched one does.
> This file is the implementation-level companion to it.

## dynamic_entity_renamer.lua

**Upstream:** shipped in the [HorizonXI addon bundle](https://horizonxi.com/addons).
The Ashita-v4 port is multi-platform (Windower v4 + Ashita v4) and shares lineage with
[TeoTwawki/renamer](https://github.com/TeoTwawki/renamer).

**Authors of the upstream addon:** `zach2good, TeoTwawki, atom0s` (per `addon.author`).

**Baseline this patch targets:** the addon as shipped with the **HorizonXI 2.0**
bundle (`addon.version = 1.0.0.0`, md5 `bf206fab99105bfe9fee16b6fe74f25f`).
Patched result: md5 `3101e66d03125471cec55ad451e65f8e`.

> **Do not blind-copy `dynamic_entity_renamer.lua` over a newer upstream file.**
> Upstream rewrote this addon in the 2.0 bundle. Overwriting it with a
> pre-2.0 patched copy silently reverts upstream's own zone handling.
> Use `scripts/patch-renamer.py`, which applies each fix only if missing.

### Apply

```bash
python3 scripts/patch-renamer.py "<GAME>/addons/dynamic_entity_renamer/dynamic_entity_renamer.lua"
python3 scripts/patch-renamer.py --check  "<GAME>/..."   # report state, change nothing
python3 scripts/patch-renamer.py --revert "<GAME>/..."   # restore .bak_upstream
```

The script is idempotent, preserves the file's CRLF line endings, backs up the
untouched upstream file to `.bak_upstream`, and byte-compiles the result with
`luajit`/`luac` (reverting automatically if the patched file does not compile).

`dynamic_entity_renamer.lua.diff` is the same change set in readable form, and
`dynamic_entity_renamer.lua` is the fully-patched file — both are provided for
reference and for the case where you want to inspect or hand-apply the changes.

## The three fixes

### 1. Truthy-check bug

```lua
-- upstream
if bit.band(flags, nameflag) and targid >= 0x700 then
-- patched
if bit.band(flags, nameflag) ~= 0 and targid >= 0x700 then
```

`bit.band` returns a number, and in Lua `0` is truthy. The upstream condition
therefore matched **every** entity in the dynamic range, not just the ones
flagged for renaming, polluting the registry with entities that should never
have been touched. This is a genuine bug on Windows too; it just doesn't crash
there.

### 2. Defensive guards in `setMobName`

Upstream calls `GetEntity():SetName(targid, new_name)` unconditionally for every
registered entity, every frame. On Wine this faults whenever the entity slot is
mid-init or has been reused after a despawn — Windows tolerates the same reads
silently via Low Fragmentation Heap behavior. Added, in order:

- skip when `entity:GetActorPointer(targid) == 0` (slot empty / despawned)
- skip when `entity:GetSpawnFlags(targid) == 0` (slot not fully spawned)
- skip when `entity:GetName(targid) == new_name` (avoid redundant writes)
- wrap the `SetName` call in `pcall` as a last-resort guard

### 3. Render throttle to ~10 Hz

Upstream drives `render()` from `d3d_beginscene`, i.e. every frame. Names do not
need a 60+ Hz refresh; throttling to 10 Hz cuts the per-frame iteration cost and
the residual fault exposure proportionally, with no visible difference.

## Fixes that are no longer applied (upstream absorbed them)

The May 2026 version of this patch also added a zone-leave registry cleanup and
a 1-second post-zoning settle window. **Both are obsolete.** The 2.0 bundle's
addon has its own `zoneState` table that queues `packet_in 0x0E` until the zone
is stable and clears `name_list` on `packet_out 0x0A`. Re-adding the old
versions would duplicate — and in the settle-window case, fight — upstream's
handling.

## When upstream changes again

`patch-renamer.py` anchors on small, specific code fragments rather than line
numbers, so it usually survives unrelated upstream edits. If an anchor stops
matching, the script says which fix it could not apply and changes nothing else.
In that case, re-apply that one fix by hand using the snippets above — the
changes are small and localized, and none of them remove upstream logic.

Re-run `--check` after every HorizonXI update; the launcher rewrites bundled
addons. See [UPDATING.md](../UPDATING.md).

## Redistribution

`dynamic_entity_renamer.lua` here is a derived copy of a HorizonXI-distributed
file, included so the change can be reviewed and reproduced. If HorizonXI staff
would prefer it not be redistributed, both the `.lua` and the `.diff` can be
removed — `scripts/patch-renamer.py` ships none of upstream's code and patches
whatever copy the player already installed from the official bundle. See
[ADDON-REVIEW.md](ADDON-REVIEW.md) §7.
