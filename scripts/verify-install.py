#!/usr/bin/env python3
"""verify-install.py - check that every layer of the fix stack is in place.

Run it any time, but especially after a HorizonXI update or launcher run. Checks
that need a launch to be meaningful (the syswow64 d3d8 swap, the log counters)
are reported as SKIP when there is no evidence yet rather than as failures.

Usage:
    verify-install.py
    verify-install.py --game-dir "<path>" --prefix "<path>"

Paths resolve in this order: command-line flag, then environment variable, then
the stock Faugus default (relative to $HOME - nothing is hardcoded to a
particular user or install location).

    flag           env var          default
    --prefix       HXI_PREFIX       $HOME/Games/faugus/horizonxi
    --game-dir     HXI_GAME_DIR     <prefix>/drive_c/Program Files/HorizonXI/Game
    --games-json   HXI_GAMES_JSON   $HOME/.local/share/faugus-launcher/games.json
    --log          HXI_LOG          $HOME/.local/share/faugus-launcher/logs/horizonxi/proton.log

So a non-standard install needs no edits, e.g.:

    HXI_PREFIX=/games/prefixes/hxi python3 verify-install.py

Exit status is 1 if any check FAILs, 0 otherwise.
"""

import argparse
import hashlib
import json
import os
import re
import struct
import sys
from pathlib import Path

D3D8TO9_MD5 = "f18148b1bc580a7b1f0df1f055782c31"

GREEN, YELLOW, RED, GREY, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[90m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    GREEN = YELLOW = RED = GREY = RESET = ""

results = []


def report(status, name, detail=""):
    colour = {"PASS": GREEN, "WARN": YELLOW, "FAIL": RED, "SKIP": GREY}[status]
    print(f"  {colour}{status:4s}{RESET}  {name}" + (f"  {GREY}{detail}{RESET}" if detail else ""))
    results.append(status)


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_laa(game):
    exe = game / "Ashita-cli.exe"
    if not exe.is_file():
        return report("FAIL", "LAA on Ashita-cli.exe", "exe not found")
    with open(exe, "rb") as f:
        f.seek(0x3C)
        pe = struct.unpack("<I", f.read(4))[0]
        f.seek(pe + 4 + 18)
        chars = struct.unpack("<H", f.read(2))[0]
    if chars & 0x0020:
        report("PASS", "LAA on Ashita-cli.exe", f"Characteristics=0x{chars:04X}")
    else:
        report("FAIL", "LAA on Ashita-cli.exe",
               f"0x{chars:04X} - run scripts/apply-laa.py")


def check_d3d8(game, prefix):
    src = game / "d3d8.dll"
    if not src.is_file():
        report("FAIL", "d3d8to9 in game dir", "missing - copy bin/d3d8.dll")
    elif md5(src) == D3D8TO9_MD5:
        report("PASS", "d3d8to9 in game dir", "v1.15.1")
    else:
        report("WARN", "d3d8to9 in game dir", f"unexpected md5 {md5(src)}")

    live = prefix / "drive_c/windows/syswow64/d3d8.dll"
    if not live.is_file():
        report("SKIP", "d3d8to9 active in syswow64", "no file yet - launch once")
    elif md5(live) == D3D8TO9_MD5:
        report("PASS", "d3d8to9 active in syswow64", "wrapper ran")
    else:
        report("FAIL", "d3d8to9 active in syswow64",
               "Wine builtin is loaded - bat wrapper did not run")

    bat = game / "faugus-horizonxi.bat"
    report("PASS" if bat.is_file() else "FAIL", "bat wrapper present", str(bat.name))


def check_games_json(path):
    if not path.is_file():
        return report("FAIL", "Faugus games.json", f"not found at {path}")
    try:
        data = json.loads(path.read_text())
    except Exception as e:
        return report("FAIL", "Faugus games.json", f"unreadable: {e}")

    entries = data if isinstance(data, list) else data.get("games", [])
    entry = next((g for g in entries
                  if "horizon" in json.dumps(g).lower()), None)
    if entry is None:
        return report("FAIL", "Faugus games.json", "no HorizonXI entry")

    if entry.get("addapp_enabled") == "addapp_enabled":
        report("PASS", "games.json addapp_enabled", "wrapper wired in")
    else:
        report("FAIL", "games.json addapp_enabled",
               "empty - Faugus will bypass the bat wrapper")

    bat = entry.get("addapp_bat", "")
    if bat and Path(bat).is_file():
        report("PASS", "games.json addapp_bat", "points at an existing file")
    else:
        report("FAIL", "games.json addapp_bat", f"bad path: {bat!r}")

    args = entry.get("launch_arguments", "")
    if "WINEDEBUG=" in args and "-all" in args:
        report("PASS", "quiet WINEDEBUG", "minimal channels set")
    else:
        report("FAIL", "quiet WINEDEBUG",
               "verbose default amplifies the leak - see INSTALL.md step 3")
    report("PASS" if "d3d8=n" in args else "WARN", "WINEDLLOVERRIDES d3d8=n,b",
           "" if "d3d8=n" in args else "not set (belt-and-suspenders only)")

    runner = entry.get("runner", "")
    report("PASS" if runner else "WARN", "runner pinned",
           runner or "empty - a floating 'Latest' can regress the connection")


def check_renamer(game):
    lua = game / "addons/dynamic_entity_renamer/dynamic_entity_renamer.lua"
    if not lua.is_file():
        return report("SKIP", "dynamic_entity_renamer patch", "addon not installed")
    text = lua.read_bytes().replace(b"\r\n", b"\n").decode("utf-8", "replace")
    have = {
        "truthy": "bit.band(flags, nameflag) ~= 0" in text,
        "guards": "entity:GetSpawnFlags(targid) == 0" in text,
        "throttle": "local render_interval" in text,
    }
    missing = [k for k, v in have.items() if not v]
    if not missing:
        report("PASS", "dynamic_entity_renamer patch", "truthy, guards, throttle")
    else:
        report("FAIL", "dynamic_entity_renamer patch",
               f"missing {', '.join(missing)} - run scripts/patch-renamer.py")


def check_ini(game):
    pivot = game / "config/pivot/pivot.ini"
    if not pivot.is_file():
        report("SKIP", "pivot root_path", "pivot.ini not found")
    else:
        m = re.search(r"^root_path=(.*)$", pivot.read_text(errors="replace"), re.M)
        root = (m.group(1).strip() if m else "")
        if root.lower().rstrip("\\").endswith("horizonxi\\game\\polplugins\\dats"):
            report("PASS", "pivot root_path", root)
        else:
            report("FAIL", "pivot root_path",
                   f"{root!r} - wrong root makes the game exit ~5s after login")

    sandbox = game / "config/sandbox/sandbox.ini"
    if not sandbox.is_file():
        report("SKIP", "sandbox use_interface_bypass", "sandbox.ini not found")
    elif re.search(r"^use_interface_bypass\s*=\s*1", sandbox.read_text(errors="replace"), re.M):
        report("PASS", "sandbox use_interface_bypass", "1")
    else:
        report("WARN", "sandbox use_interface_bypass",
               "not 1 - a game-data update can then break launching")


def check_log(log):
    if not log.is_file():
        return report("SKIP", "Wine log counters", f"no log at {log}")
    text = log.read_text(errors="replace")
    size_mb = log.stat().st_size / (1 << 20)
    for label, needle, bad in (
        ("no d3d8 builtin errors", "err:d3d8:", True),
        ("no OOM warnings", "out of memory for allocation", True),
        ("no access violations", "code=c0000005", False),
    ):
        n = text.count(needle)
        if n == 0:
            report("PASS", label, f"0 in {size_mb:.1f} MB")
        elif bad:
            report("FAIL", label, f"{n} found - the wrapper is not active")
        else:
            report("WARN", label, f"{n} found - bounded bursts are expected")
    lj = text.count("code=e24c4a02")
    report("PASS", "LuaJIT exceptions (informational)",
           f"{lj} - normal Lua control flow, not a fault")


def main():
    home = Path.home()
    # Flag > env var > $HOME-relative default. Nothing is tied to a specific
    # user or install path.
    faugus = home / ".local/share/faugus-launcher"
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--prefix", default=os.environ.get(
        "HXI_PREFIX", str(home / "Games/faugus/horizonxi")))
    p.add_argument("--game-dir", default=os.environ.get("HXI_GAME_DIR"))
    p.add_argument("--games-json", default=os.environ.get(
        "HXI_GAMES_JSON", str(faugus / "games.json")))
    p.add_argument("--log", default=os.environ.get(
        "HXI_LOG", str(faugus / "logs/horizonxi/proton.log")))
    args = p.parse_args()

    prefix = Path(os.path.expanduser(args.prefix))
    game = Path(os.path.expanduser(args.game_dir)) if args.game_dir else \
        prefix / "drive_c/Program Files/HorizonXI/Game"

    print(f"\nprefix   {prefix}\ngame dir {game}\n")
    if not game.is_dir():
        print(f"{RED}error: game dir not found{RESET}\n")
        return 2

    print("Fix stack")
    check_laa(game)
    check_d3d8(game, prefix)
    check_renamer(game)
    print("\nFaugus wiring")
    check_games_json(Path(os.path.expanduser(args.games_json)))
    print("\nConfig that updates revert")
    check_ini(game)
    print("\nLast session's log")
    check_log(Path(os.path.expanduser(args.log)))

    fails = results.count("FAIL")
    warns = results.count("WARN")
    print(f"\n{results.count('PASS')} pass, {warns} warn, {fails} fail, "
          f"{results.count('SKIP')} skip\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
