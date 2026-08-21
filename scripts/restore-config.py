#!/usr/bin/env python3
"""restore-config.py - re-apply local HorizonXI config after an update reverts it.

The HorizonXI launcher rewrites its own managed blocks on every run, and a game
update rewrites more. This restores the parts that are yours:

  - config/pivot/pivot.ini      root_path (wrong root => "logs in then closes")
  - config/boot/ashita.ini      autologin credentials
  - config/boot/ashita.ini      [ffxi.registry] display settings
  - config/sandbox/sandbox.ini  use_interface_bypass (PlayOnline version check)
  - scripts/default.txt         HORIZON_PLUGINS / HORIZON_ADDONS blocks

Idempotent - safe to run any time, prints only what it changed. It deliberately
does NOT touch the LAA patch or the addon patches; use apply-laa.py and
patch-renamer.py for those (verify-install.sh checks all of them at once).

Configuration lives in a JSON file so no credentials are stored in this script.
Copy restore-config.example.json to restore-config.json and edit it; that
filename is gitignored.

Usage:
    restore-config.py                       # use ./restore-config.json
    restore-config.py --config PATH         # use a different config file
    restore-config.py --dry-run             # report what would change

Paths resolve as flag > env var > config file > $HOME-relative default:

    flag        env var             default
    --config    HXI_RESTORE_CONFIG  <this script's dir>/restore-config.json
    --game-dir  HXI_GAME_DIR        the config file's "game_dir", else
                                    $HOME/Games/faugus/horizonxi/drive_c/
                                        Program Files/HorizonXI/Game

"~" and environment variables inside config values are expanded, so a config
file is portable between machines.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.environ.get("HXI_RESTORE_CONFIG",
                                os.path.join(HERE, "restore-config.json"))
DEFAULT_GAME_DIR = os.path.join(
    os.path.expanduser("~"),
    "Games", "faugus", "horizonxi", "drive_c", "Program Files", "HorizonXI", "Game")


def expand(path):
    """Expand ~ and $VARS so config values are portable between machines."""
    return os.path.expanduser(os.path.expandvars(path))


def load_config(path, game_dir_override=None):
    if not os.path.isfile(path):
        sys.exit(
            f"error: no config file at {path}\n"
            f"       copy restore-config.example.json to restore-config.json "
            f"and edit it."
        )
    with open(path) as fh:
        cfg = json.load(fh)

    # Flag > env var > config file > $HOME-relative default.
    cfg["game_dir"] = expand(game_dir_override
                             or os.environ.get("HXI_GAME_DIR")
                             or cfg.get("game_dir")
                             or DEFAULT_GAME_DIR)
    if not os.path.isdir(cfg["game_dir"]):
        sys.exit(f"error: game_dir not found: {cfg['game_dir']}")
    return cfg


def read(path):
    with open(path, "r", newline="") as fh:
        return fh.read()


def write(path, text, dry_run):
    if not dry_run:
        with open(path, "w", newline="") as fh:
            fh.write(text)


def newline_of(text):
    """Dominant line ending. Counting rather than testing for any CRLF matters
    because a partly-rewritten file can be mixed, and picking the minority
    ending would rewrite every line we touch in the wrong style."""
    crlf = text.count("\r\n")
    return "\r\n" if crlf * 2 > text.count("\n") else "\n"


def restore_pivot(cfg, dry_run):
    """pivot.ini root_path and the [overlays] list.

    An update resets root_path to Horizon's default install path; every overlay
    then logs '=> failed' and the game exits ~5s after login.

    It also restores the full stock overlay list. That is not fatal, but heavy
    texture overlays cost a lot of FPS in crowded areas, so the desired list is
    managed here too."""
    path = os.path.join(cfg["game_dir"], "config", "pivot", "pivot.ini")
    if not os.path.isfile(path):
        return []
    text = read(path)
    changes = []

    want = cfg.get("pivot_root_path")
    if want:
        # lambda replacement: the value is a Windows path, and re.sub would treat
        # its backslashes as escape sequences in a plain replacement string.
        new = re.sub(r"^root_path=[^\r\n]*", lambda _: "root_path=" + want,
                     text, count=1, flags=re.M)
        if new != text:
            text = new
            changes.append("pivot_root")

    overlays = cfg.get("pivot_overlays")
    if overlays is not None:
        head, sep, tail = text.partition("[overlays]")
        if sep:
            newline = newline_of(text)
            # Renumber from 0 with no gaps. Whether pivot's parser stops at a
            # missing index is unconfirmed, so a gap could silently drop every
            # overlay after it.
            body = newline + newline.join("%d=%s" % (i, n)
                                          for i, n in enumerate(overlays)) + newline
            if tail != body:
                text = head + sep + body
                changes.append("pivot_overlays(%d)" % len(overlays))

    if changes:
        write(path, text, dry_run)
    return changes


def restore_sandbox(cfg, dry_run):
    """sandbox.ini use_interface_bypass. HorizonXI ships 0; Sandbox's own default
    is 1. With 0, a game-data update can make the PlayOnline version check fail
    and FFXI exits before creating a window."""
    if not cfg.get("sandbox_interface_bypass", True):
        return []
    path = os.path.join(cfg["game_dir"], "config", "sandbox", "sandbox.ini")
    if not os.path.isfile(path):
        return []
    text = read(path)
    if re.search(r"^use_interface_bypass\s*=\s*1", text, flags=re.M):
        return []
    if re.search(r"^use_interface_bypass\s*=", text, flags=re.M):
        new = re.sub(r"^use_interface_bypass\s*=[^\r\n]*", "use_interface_bypass = 1",
                     text, count=1, flags=re.M)
    else:
        newline = newline_of(text)
        new = text.replace("[sandbox.hooks]",
                           "[sandbox.hooks]" + newline + "use_interface_bypass = 1", 1)
        if new == text:
            return []
    write(path, new, dry_run)
    return ["interface_bypass"]


def restore_ashita_ini(cfg, dry_run):
    """Autologin credentials and [ffxi.registry] display settings."""
    path = os.path.join(cfg["game_dir"], "config", "boot", "ashita.ini")
    if not os.path.isfile(path):
        return []
    text = read(path)
    changes = []

    login = cfg.get("autologin") or {}
    if login.get("username") and "--username" not in text:
        cmd = "command = --server %s --username %s --password %s" % (
            login.get("server", "play.horizonxi.com"),
            login["username"], login["password"])
        if login.get("otp"):
            cmd += " --otp %s" % login["otp"]
        # lambda replacement: a password may contain backslashes.
        new = re.sub(r"^command = --server [^\r\n]*", lambda _: cmd,
                     text, count=1, flags=re.M)
        if new != text:
            text = new
            changes.append("autologin")

    registry = cfg.get("registry") or {}
    if registry:
        fixed = []

        def sub(match):
            key, value = match.group(1), match.group(2)
            if key in registry and value != str(registry[key]):
                fixed.append(key)
                return "%s = %s" % (key, registry[key])
            return match.group(0)

        # Match to end-of-line without $ so CRLF files work.
        text = re.sub(r"^(\d{4}) = ([^\r\n]+)", sub, text, flags=re.M)
        if fixed:
            changes.append("display(%s)" % ",".join(fixed))

    if changes:
        write(path, text, dry_run)
    return changes


def restore_default_txt(cfg, dry_run):
    """The HORIZON_PLUGINS / HORIZON_ADDONS managed blocks in the boot script.
    The custom-user section outside these markers is left alone."""
    path = os.path.join(cfg["game_dir"], "scripts", "default.txt")
    if not os.path.isfile(path):
        return []
    text = read(path)
    newline = newline_of(text)
    changes = []

    def fill(text, start, stop, lines):
        try:
            a = text.index(start) + len(start)
            b = text.index(stop)
        except ValueError:
            print("  ! marker not found: %s" % start, file=sys.stderr)
            return text, False
        wanted = newline + newline.join(lines) + newline
        if text[a:b] == wanted:
            return text, False
        return text[:a] + wanted + text[b:], True

    plugins = ["/load %s" % p for p in cfg.get("plugins", [])]
    addons = ["/addon load %s" % a for a in cfg.get("addons", [])]

    if plugins:
        text, hit = fill(text, "# --HORIZON_PLUGINS_START--",
                         "# --HORIZON_PLUGINS_STOP--", plugins)
        if hit:
            changes.append("plugins(%d)" % len(plugins))
    if addons:
        text, hit = fill(text, "# --HORIZON_ADDONS_START--",
                         "# --HORIZON_ADDONS_STOP--", addons)
        if hit:
            changes.append("addons(%d)" % len(addons))

    if changes:
        write(path, text, dry_run)
    return changes


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--config", default=DEFAULT_CONFIG,
                   help="path to restore-config.json (default: next to this script)")
    p.add_argument("--game-dir", default=None,
                   help="override the config file's game_dir")
    p.add_argument("--dry-run", action="store_true",
                   help="report what would change without writing")
    args = p.parse_args()

    cfg = load_config(expand(args.config), args.game_dir)

    changes = (restore_pivot(cfg, args.dry_run)
               + restore_sandbox(cfg, args.dry_run)
               + restore_ashita_ini(cfg, args.dry_run)
               + restore_default_txt(cfg, args.dry_run))

    prefix = "would restore" if args.dry_run else "restored"
    print("%s: %s" % (prefix, ", ".join(changes)) if changes
          else "already up to date - nothing to restore")
    return 0


if __name__ == "__main__":
    sys.exit(main())
