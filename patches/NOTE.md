# patches/

## dynamic_entity_renamer.lua

**Upstream:** distributed as part of the [HorizonXI addons bundle](https://horizonxi.com/addons).
The Ashita-v4 port is multi-platform (Windower v4 + Ashita v4) and shares lineage with
[TeoTwawki/renamer](https://github.com/TeoTwawki/renamer).

**Authors of the upstream addon:** `zach2good, TeoTwawki, atom0s` (per `addon.author` field).

**Our changes** (see `dynamic_entity_renamer.lua.diff`):

1. **Truthy-check fix on line 314.** Original: `if bit.band(flags, nameflag) and ...`.
   In Lua, `bit.band` returns a number, and `0` is truthy — so this condition
   matched ALL entities in the dynamic-range, polluting the registry with
   entities that should never be renamed. Fixed to `~= 0`.

2. **Defensive guards in `setMobName`.** Original code called
   `AshitaCore:GetMemoryManager():GetEntity():SetName(targid, new_name)`
   unconditionally for every registered entity, every frame. On Wine this
   faults whenever the entity slot is mid-init or has been reused after
   despawn (Windows tolerates this silently via LFH heap behavior). Added:
   - `GetActorPointer(targid) == 0` skip
   - `GetSpawnFlags(targid) == 0` skip
   - `GetName(targid) == new_name` skip (avoid redundant writes)
   - Wrap final `SetName` in `pcall` as a last-resort guard

3. **Zone-leave registry cleanup.** On `packet_in 0x0B` (zone leave), clear
   `registry[zoneId]` to prevent transient BC/event entity entries from
   accumulating across zone changes.

4. **Render throttle to ~10 Hz.** Renaming doesn't need to run every frame;
   reducing the call frequency proportionally reduces any residual fault
   exposure.

5. **1-second post-zoning settle window.** After `GetIsZoning()` returns to 0,
   skip render for another second — the new zone's entities are still
   streaming in and reading their fields can fault during that transient
   window.

Each change is a localized addition; none of the original logic was removed.

## Reapplying after a HorizonXI launcher update

If the HorizonXI launcher rewrites `dynamic_entity_renamer.lua` (e.g., because
the upstream addon was updated), drop the patched file back in OR re-apply
the diff:

```bash
cd /path/to/addons/dynamic_entity_renamer
patch -b dynamic_entity_renamer.lua < /path/to/dynamic_entity_renamer.lua.diff
```

If upstream has changed enough that the diff doesn't apply cleanly, the
individual changes above are small enough to re-apply by hand using the
inline `+`/`-` markers in the .diff file as a guide.
