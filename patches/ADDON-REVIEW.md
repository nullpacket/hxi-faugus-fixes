# `dynamic_entity_renamer` patch — review notes

This document is written for HorizonXI staff reviewing the local modification in
this directory, and for any player who wants to know exactly what they are
running before they run it.

**Summary:** three defensive changes to the Ashita-v4 branch of the
HorizonXI-distributed `dynamic_entity_renamer` addon, to stop it crashing the
client under Wine/Proton. The changes only ever *skip or delay* work the addon
already does. They add no new data source, no new packet, and no new display.
The set of entities the patched addon renames is always a subset of the set the
unpatched addon renames.

---

## 1. What the upstream addon does

`dynamic_entity_renamer` gives dynamic-range entities (targid ≥ `0x700`) a
display name supplied by the server:

| Step | Code | Source of truth |
|---|---|---|
| Ask the server for the zone's name list | `askForList()` sends outgoing packet `0x01` with `{0x01, 0x04, 0x00, 0x00}` | client request |
| Receive the list | `handleList()` parses incoming packet `0x1FF` into `name_list[zoneId][original_name] = new_name` | **server** |
| Notice a renamable entity | `register_dynamic_entity()` reads incoming packet `0x0E`: name at `0x34`, targid at `0x08`, flags at `0x0A`, and tests the `0x08` "may be renamed" flag | **server** |
| Apply the name | `setMobName()` calls `GetEntity():SetName(targid, new_name)` — only if `name_list[zone][original_name]` exists | **server** |

The two things that decide *what gets renamed* and *what it is renamed to* are
both sent by the server. The addon is a display layer over server-provided data.
**The patch does not change either of them.**

## 2. The problem being fixed

Under Wine/Proton, `setMobName` is called for every registered entity on every
frame with no validation of the entity slot. When a slot is mid-initialisation,
just-despawned, or still streaming in after a zone change, the read faults.
Windows tolerates the same access silently (Low Fragmentation Heap keeps freed
memory mapped); Wine's stricter memory layout raises an access violation.

Each fault is caught, but each one also grows the process's unwind function
table, leaking 32-bit virtual address space until allocations fail and the
client dies. In a busy zone this reached tens of thousands of faults per minute.

This is a Wine-only *crash*, but the underlying code is doing an unguarded write
on both platforms — Windows just absorbs it.

## 3. The three changes

### 3.1 Honour the server's rename flag

```lua
-- upstream
if bit.band(flags, nameflag) and targid >= 0x700 then
-- patched
if bit.band(flags, nameflag) ~= 0 and targid >= 0x700 then
```

In Lua, `0` is truthy, and `bit.band` returns a number — so the upstream
condition is true whenever `targid >= 0x700`, regardless of the flag. Upstream
therefore registers **every** dynamic-range entity, including those the server
did *not* mark with the `0x08` flag.

**Effect:** the patched client registers a strict subset — only entities the
server flagged. This makes the client *more* compliant with the server's stated
intent, not less. It is the only change with a user-visible effect, and the
effect is that fewer names are replaced.

> If HorizonXI's intent is in fact that all dynamic-range entities be renamed
> regardless of the flag, then the flag test is dead code and upstream should
> drop it — but in that case this patch is still safe, because the name still
> only changes when the server sent a replacement for that exact original name.

### 3.2 Validate the entity slot before writing

```lua
local entity = AshitaCore:GetMemoryManager():GetEntity()
if entity:GetActorPointer(targid) == 0 then return end   -- slot empty / despawned
if entity:GetSpawnFlags(targid) == 0    then return end   -- slot not fully spawned
if entity:GetName(targid) == new_name    then return end   -- already correct
pcall(function() entity:SetName(targid, new_name) end)     -- last-resort guard
```

Four early exits in front of the existing `SetName`. Each one can only cause a
rename to be **skipped**; none can cause a rename to happen that would not
otherwise have happened, and none can change *which* name is written — `new_name`
is unchanged and still comes from `name_list`.

`GetActorPointer`, `GetSpawnFlags` and `GetName` are read-only Ashita v4
`IEntity` accessors for the same entity the addon is already about to write to.
No additional entity, field, or memory region is read.

### 3.3 Throttle the render loop to ~10 Hz

```lua
local now = os.clock()
if now - last_render < render_interval then return end   -- render_interval = 0.1
last_render = now
```

Upstream drives `render()` from `d3d_beginscene`, i.e. once per frame (60+ Hz).
Names do not need that refresh rate. The same names are applied from the same
list; a newly-registered entity may take up to 100 ms longer to show its
replacement name.

**Effect:** timing only. A delay cannot reveal anything.

## 4. Fairness analysis

The property that matters for review is this, and it is checkable from the diff:

> At any instant, the set of entities showing a replacement name under the
> patched addon is a **subset** of the set showing one under the unpatched
> addon, with identical names.

Because:

- change 3.1 narrows the registration condition → fewer entities registered
- change 3.2 adds early-exits before the write → fewer writes, same `new_name`
- change 3.3 delays writes → same set, later

There is no code path in the patch that adds an entity, invents a name, or
displays anything the server did not send. The patch cannot surface information
that the unpatched, HorizonXI-distributed addon would not also surface.

Concretely, the patch does **not**:

- change `name_list`, or how packet `0x1FF` is parsed
- change how packet `0x0E` is parsed (name/targid/flags offsets are untouched)
- send, inject, modify, block, or delay any packet — `askForList()` is unmodified
- read any memory the addon was not already reading
- add commands, hotkeys, UI, overlays, logging, or files on disk
- touch targeting, movement, combat, timers, automation, or anything outside
  the entity display name
- persist anything between sessions

The only intended net effect is that the client stops leaking address space and
crashing.

## 5. Verifying this yourself

```bash
# the exact change set, against the HorizonXI 2.0 bundle's copy
cat patches/dynamic_entity_renamer.lua.diff

# reproduce the patched file from a pristine upstream copy
python3 scripts/patch-renamer.py --check <upstream-copy>.lua   # reports what's missing
python3 scripts/patch-renamer.py         <upstream-copy>.lua   # applies it
```

Checksums, so it is unambiguous which file this was derived from:

| File | md5 |
|---|---|
| Upstream, HorizonXI 2.0 addon bundle | `bf206fab99105bfe9fee16b6fe74f25f` |
| Patched | `3101e66d03125471cec55ad451e65f8e` |

`scripts/patch-renamer.py` applies each change only if it is missing and reverts
automatically if the result does not byte-compile, so it can be re-run after any
HorizonXI update without stacking edits.

## 6. What upstream already handles (and this patch deliberately leaves alone)

An earlier (May 2026) version of this patch also added a zone-leave registry
cleanup and a one-second post-zone settle window. The HorizonXI 2.0 rewrite
introduced its own `zoneState` table that queues `packet_in 0x0E` until the zone
is stable and clears `name_list` on `packet_out 0x0A`, which covers both cases
properly. Those two additions have been **removed** from the current patch so
they cannot conflict with upstream's handling.

## 7. Provenance and redistribution

`dynamic_entity_renamer` is authored by **zach2good, TeoTwawki, atom0s** and
distributed as part of the HorizonXI addon bundle; the Ashita-v4 port shares
lineage with [TeoTwawki/renamer](https://github.com/TeoTwawki/renamer). This
repository is not affiliated with HorizonXI, Ashita, or those authors.

This directory contains a derived copy of a HorizonXI-distributed file. It is
included so Linux players can see and reproduce the change, and so the diff can
be reviewed. **If HorizonXI staff would prefer it not be redistributed**, the
`.lua` and `.diff` can be dropped and `scripts/patch-renamer.py` alone is
sufficient — it patches whatever copy the player already installed from the
official bundle, and ships none of upstream's code.

The preferred outcome is that these fixes land upstream, at which point this
patch should be deleted rather than maintained. Changes 3.1 (the truthy bug) and
3.2 (the unguarded write) are real defects on Windows as well; they simply do
not crash there.
