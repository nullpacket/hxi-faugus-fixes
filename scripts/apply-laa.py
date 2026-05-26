#!/usr/bin/env python3
"""
apply-laa.py — toggle the LARGEADDRESSAWARE flag on a 32-bit Windows PE file.

For HorizonXI / Ashita on Wine: setting this flag on Ashita-cli.exe doubles
the available virtual address space from 2 GB to 4 GB, which is the single
highest-leverage change to keep long sessions from hitting the d3d8 OOM crash.

Usage:
    apply-laa.py <path/to/Ashita-cli.exe>           # patch (idempotent)
    apply-laa.py --check <path/to/Ashita-cli.exe>   # report current state
    apply-laa.py --revert <path/to/Ashita-cli.exe>  # clear LAA bit

Backup is written to <exe>.bak_no_laa before any modification.
"""

import argparse
import shutil
import struct
import sys
from pathlib import Path

LAA_BIT = 0x0020  # IMAGE_FILE_LARGE_ADDRESS_AWARE


def read_characteristics(path: Path):
    with open(path, "rb") as f:
        f.seek(0x3C)
        pe_off = struct.unpack("<I", f.read(4))[0]
        f.seek(pe_off)
        sig = f.read(4)
        if sig != b"PE\x00\x00":
            raise ValueError(f"{path}: not a PE file (sig={sig!r})")
        f.read(2)  # Machine
        f.read(2)  # NumberOfSections
        f.read(4)  # TimeDateStamp
        f.read(4)  # PointerToSymbolTable
        f.read(4)  # NumberOfSymbols
        f.read(2)  # SizeOfOptionalHeader
        chars_off = f.tell()
        chars = struct.unpack("<H", f.read(2))[0]
        return chars_off, chars


def write_characteristics(path: Path, chars_off: int, chars: int):
    with open(path, "r+b") as f:
        f.seek(chars_off)
        f.write(struct.pack("<H", chars))


def cmd_check(path: Path):
    off, chars = read_characteristics(path)
    state = "YES" if chars & LAA_BIT else "NO"
    print(f"{path}: LAA={state}  (Characteristics=0x{chars:04X} at offset 0x{off:X})")


def cmd_apply(path: Path):
    off, chars = read_characteristics(path)
    if chars & LAA_BIT:
        print(f"{path}: LAA already set (0x{chars:04X}); no-op")
        return
    backup = path.with_suffix(path.suffix + ".bak_no_laa")
    if not backup.exists():
        shutil.copy2(path, backup)
        print(f"  backup written: {backup}")
    new_chars = chars | LAA_BIT
    write_characteristics(path, off, new_chars)
    print(f"  Characteristics: 0x{chars:04X} -> 0x{new_chars:04X}  (LAA set)")


def cmd_revert(path: Path):
    off, chars = read_characteristics(path)
    if not (chars & LAA_BIT):
        print(f"{path}: LAA already clear (0x{chars:04X}); no-op")
        return
    new_chars = chars & ~LAA_BIT
    write_characteristics(path, off, new_chars)
    print(f"  Characteristics: 0x{chars:04X} -> 0x{new_chars:04X}  (LAA cleared)")


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("path", help="path to the .exe file")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="report current LAA state, no changes")
    g.add_argument("--revert", action="store_true", help="clear LAA bit (restore default)")
    args = p.parse_args()

    path = Path(args.path)
    if not path.is_file():
        print(f"error: {path} is not a file", file=sys.stderr)
        sys.exit(2)

    try:
        if args.check:
            cmd_check(path)
        elif args.revert:
            cmd_revert(path)
        else:
            cmd_apply(path)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
