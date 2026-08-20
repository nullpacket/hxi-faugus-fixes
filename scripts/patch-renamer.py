#!/usr/bin/env python3
"""patch-renamer.py - apply the Wine-stability fixes to dynamic_entity_renamer.lua.

Three independent fixes, each applied only if missing, so the script is
idempotent and survives upstream rewrites of the surrounding code:

  1. truthy   - `bit.band(flags, nameflag)` compared as a boolean. In Lua 0 is
                truthy, so the guard matched every entity in the dynamic range.
  2. guards   - validate the entity slot before SetName (ActorPointer,
                SpawnFlags, name-equality) and pcall the write.
  3. throttle - run render() at ~10 Hz instead of once per frame.

Upstream (as of the HorizonXI 2.0 addon bundle) handles zone state itself via
its `zoneState` table, so the old zone-leave cleanup and post-zone settle
window from the May 2026 version of this patch are NOT re-applied here.

The file is CRLF; line endings are preserved.

Usage:
    patch-renamer.py <path/to/dynamic_entity_renamer.lua>
    patch-renamer.py --check <path>     # report which fixes are present
    patch-renamer.py --revert <path>    # restore from .bak_upstream

A backup of the untouched upstream file is written to <file>.bak_upstream
the first time the script modifies anything.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

BACKUP_SUFFIX = ".bak_upstream"

# --- Fix 1: truthy check -------------------------------------------------

TRUTHY_OLD = "if bit.band(flags, nameflag) and targid >= 0x700 then"
TRUTHY_NEW = "if bit.band(flags, nameflag) ~= 0 and targid >= 0x700 then"

# --- Fix 2: entity guards + pcall ----------------------------------------

GUARDS_OLD = """                local targid = bit.band(id, 0x0FFF)
                AshitaCore:GetMemoryManager():GetEntity():SetName(targid, new_name)
"""

GUARDS_NEW = """                local targid = bit.band(id, 0x0FFF)
                local entity = AshitaCore:GetMemoryManager():GetEntity()
                -- Defense in depth against Wine-side AV storm (Windows tolerates the
                -- same accesses via LFH; Wine's strict memory layout faults). Each
                -- caught AV grows the unwind function table, slowly leaking 32-bit VA.
                -- Skip if entity slot is empty/despawned.
                if entity:GetActorPointer(targid) == 0 then
                    return
                end
                -- Skip if entity isn't fully spawned. Catches mid-initialization
                -- states (BC mob spawn, busy-zone NPC stream-in) that pass the
                -- ActorPointer check but have inconsistent inner state.
                if entity:GetSpawnFlags(targid) == 0 then
                    return
                end
                -- Skip if current name already matches; avoids redundant writes.
                if entity:GetName(targid) == new_name then
                    return
                end
                -- Wrap in pcall as last-resort guard. Any error becomes a swallowed
                -- Lua error instead of a caught C++ exception that retries every frame.
                pcall(function() entity:SetName(targid, new_name) end)
"""

GUARDS_MARKER = "entity:GetSpawnFlags(targid) == 0"

# --- Fix 3: render throttle ----------------------------------------------

THROTTLE_OLD = """local function render()
"""

THROTTLE_NEW = """-- Throttle render() to ~10 Hz instead of 60+. Names do not need 60 Hz refresh;
-- this cuts per-frame iteration cost (and residual AV exposure) with no visible
-- difference. Upstream calls render() from d3d_beginscene every frame.
local last_render = 0
local render_interval = 0.1  -- seconds

local function render()
    local now = os.clock()
    if now - last_render < render_interval then
        return
    end
    last_render = now

"""

THROTTLE_MARKER = "local render_interval"

FIXES = [
    ("truthy", TRUTHY_NEW, TRUTHY_OLD, TRUTHY_NEW),
    ("guards", GUARDS_MARKER, GUARDS_OLD, GUARDS_NEW),
    ("throttle", THROTTLE_MARKER, THROTTLE_OLD, THROTTLE_NEW),
]


def read_lf(path):
    """Read the file, remembering whether it was CRLF, and return LF text."""
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    return raw.replace(b"\r\n", b"\n").decode("utf-8"), crlf


def write_lf(path, text, crlf):
    data = text.encode("utf-8")
    if crlf:
        data = data.replace(b"\n", b"\r\n")
    path.write_bytes(data)


def status(text):
    """Return {fix_name: bool present} for the given source text."""
    return {name: marker in text for name, marker, _, _ in FIXES}


def cmd_check(path):
    text, crlf = read_lf(path)
    st = status(text)
    print(f"{path}  ({'CRLF' if crlf else 'LF'})")
    for name, present in st.items():
        print(f"  {name:9s} {'present' if present else 'MISSING'}")
    return 0 if all(st.values()) else 1


def syntax_check(path):
    """Byte-compile with luajit/luac if available. Returns (ok, message)."""
    for tool, args in (("luajit", ["-bl"]), ("luac", ["-p"])):
        if shutil.which(tool):
            r = subprocess.run([tool] + args + [str(path)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                return False, f"{tool}: {r.stderr.strip()}"
            return True, f"{tool}: ok"
    return True, "no luajit/luac found, skipped"


def cmd_apply(path):
    text, crlf = read_lf(path)
    before = status(text)

    if all(before.values()):
        print(f"{path}: all fixes already present; no-op")
        return 0

    applied, failed = [], []
    for name, marker, old, new in FIXES:
        if marker in text:
            continue
        if old not in text:
            failed.append(name)
            continue
        text = text.replace(old, new, 1)
        applied.append(name)

    if not applied:
        print("error: no fixes could be applied - upstream code has changed shape.",
              file=sys.stderr)
        print(f"       missing and unanchored: {', '.join(failed)}", file=sys.stderr)
        print("       See patches/NOTE.md and apply by hand.", file=sys.stderr)
        return 1

    backup = path.with_name(path.name + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(path, backup)
        print(f"  backup written: {backup.name}")

    write_lf(path, text, crlf)
    print(f"  applied: {', '.join(applied)}")
    if failed:
        print(f"  COULD NOT ANCHOR: {', '.join(failed)} - apply by hand, "
              f"see patches/NOTE.md", file=sys.stderr)

    ok, msg = syntax_check(path)
    print(f"  syntax check: {msg}")
    if not ok:
        print(f"  restoring backup - patched file does not compile", file=sys.stderr)
        shutil.copy2(backup, path)
        return 1

    return 1 if failed else 0


def cmd_revert(path):
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    if not backup.exists():
        print(f"error: no backup at {backup}", file=sys.stderr)
        return 1
    shutil.copy2(backup, path)
    print(f"restored {path.name} from {backup.name}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("path", help="path to dynamic_entity_renamer.lua")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true",
                   help="report which fixes are present, change nothing")
    g.add_argument("--revert", action="store_true",
                   help="restore the upstream file from .bak_upstream")
    args = p.parse_args()

    path = Path(args.path)
    if not path.is_file():
        print(f"error: {path} is not a file", file=sys.stderr)
        return 2

    if args.check:
        return cmd_check(path)
    if args.revert:
        return cmd_revert(path)
    return cmd_apply(path)


if __name__ == "__main__":
    sys.exit(main())
