#!/usr/bin/env python3
"""
HorizonXI Health Monitor — curses TUI that tails the Faugus/Proton Wine debug
log and surfaces the metrics we care about for long-session stability:

  - Total c0000005 access violations (addon entity-read faults caught by pcall)
  - Total OOM warnings (precursor to the d3d8 leak crash)
  - Total `err:d3d8:` lines (Wine builtin d3d8 active = wrapper broken)
  - Last AV burst window (timestamp + count)
  - 60s sliding-window AV rate + sparkline
  - LuaJIT baseline (0xe24c4a02) rate
  - syswow64 d3d8.dll md5 check (proves d3d8to9 wrapper actually copied)
  - Latest crash dump file

Colors: green=clean, yellow=AV burst active, red=critical (OOM/d3d8-error).
Quit: q or Ctrl-C.
"""

import curses
import hashlib
import os
import re
import sys
import time
from collections import deque
from pathlib import Path

# --- Defaults (overridable via env vars) ----------------------------------

LOG_PATH = Path(os.environ.get(
    "HXI_MONITOR_LOG",
    "/home/nullpacket/.config/faugus-launcher/logs/horizonxi/steam-0.log"))
CRASH_DIR = Path(os.environ.get(
    "HXI_MONITOR_CRASH_DIR",
    "/tmp/umu_crashreports"))
D3D8_PATH = Path(os.environ.get(
    "HXI_MONITOR_D3D8",
    "/home/nullpacket/Games/faugus/horizonxi/drive_c/windows/syswow64/d3d8.dll"))
D3D8TO9_MD5 = os.environ.get(
    "HXI_MONITOR_D3D8TO9_MD5",
    "f18148b1bc580a7b1f0df1f055782c31")

REFRESH_SECONDS = 1.0
SPARKLINE_WIDTH = 60
BLOCKS = " ▁▂▃▄▅▆▇█"


# --- Log parsing ----------------------------------------------------------

# Wine debug log line format: 12345.678:00aa:00bb:level:channel:rest
LINE_RE = re.compile(r"^(\d+\.\d+):[0-9a-f]+:[0-9a-f]+:(\w+):(\w+):")

class Metrics:
    def __init__(self):
        self.file_pos = 0
        self.file_inode = None
        self.session_first_ts = None
        self.session_last_ts = None

        self.av_total = 0
        self.luajit_total = 0
        self.oom_total = 0
        self.d3d8_err_total = 0
        self.wine_cxx_total = 0

        # AVs per timestamp-second, kept for sparkline + rate window
        self.av_per_sec = {}   # int second -> count
        self.last_burst_ts = None
        self.last_burst_count = 0

        # Crash dumps
        self.crash_count = 0
        self.latest_crash_path = None
        self.latest_crash_mtime = 0

        # d3d8 verification (md5 of syswow64 file)
        self.d3d8_md5 = None
        self.d3d8_md5_check_time = 0

        # Game process memory
        self.game_pid = None
        self.game_comm = None
        self.vm_size_kb = 0   # current virtual memory
        self.vm_peak_kb = 0   # high water mark
        self.vm_rss_kb = 0    # resident set size
        self.vm_data_kb = 0   # data + stack
        self.vm_size_history = deque(maxlen=120)  # 2 min of samples for delta

    # ----- log ingestion -----

    def ingest(self):
        if not LOG_PATH.exists():
            return
        try:
            st = LOG_PATH.stat()
        except OSError:
            return

        # Reset on rotation / shrink
        if self.file_inode is None or st.st_ino != self.file_inode or st.st_size < self.file_pos:
            self.file_inode = st.st_ino
            self.file_pos = 0
            self.session_first_ts = None
            self.av_total = 0
            self.luajit_total = 0
            self.oom_total = 0
            self.d3d8_err_total = 0
            self.wine_cxx_total = 0
            self.av_per_sec.clear()
            self.last_burst_ts = None
            self.last_burst_count = 0

        try:
            with open(LOG_PATH, "rb") as f:
                f.seek(self.file_pos)
                data = f.read()
                self.file_pos = f.tell()
        except OSError:
            return

        text = data.decode("utf-8", errors="replace")
        for line in text.splitlines():
            self._parse_line(line)

    def _parse_line(self, line):
        m = LINE_RE.match(line)
        if not m:
            return
        ts = float(m.group(1))
        if self.session_first_ts is None:
            self.session_first_ts = ts
        self.session_last_ts = ts

        # Cheap substring checks — avoid full regex on every line
        if "code=c0000005" in line:
            self.av_total += 1
            sec = int(ts)
            self.av_per_sec[sec] = self.av_per_sec.get(sec, 0) + 1
        elif "code=e24c4a02" in line:
            self.luajit_total += 1
        elif "code=e06d7363" in line:
            self.wine_cxx_total += 1
        if "out of memory for allocation" in line:
            self.oom_total += 1
        if "err:d3d8:" in line:
            self.d3d8_err_total += 1

    # ----- derived metrics -----

    def session_duration(self):
        if self.session_first_ts is None or self.session_last_ts is None:
            return 0
        return self.session_last_ts - self.session_first_ts

    def av_rate_60s(self):
        if not self.av_per_sec or self.session_last_ts is None:
            return 0.0
        cutoff = int(self.session_last_ts) - 60
        recent = sum(c for sec, c in self.av_per_sec.items() if sec > cutoff)
        return recent / 60.0

    def luajit_rate_per_min(self):
        # Coarse: total / session minutes
        dur = self.session_duration()
        if dur < 1:
            return 0
        return self.luajit_total / (dur / 60.0)

    def update_last_burst(self):
        """A 'burst' = one or more consecutive seconds with > 12 AVs, allowing
        up to 5-second gaps within one logical burst. Track the LATEST burst."""
        if not self.av_per_sec:
            self.last_burst_ts = None
            self.last_burst_count = 0
            return
        first = min(self.av_per_sec)
        last = max(self.av_per_sec)
        latest_ts = None
        latest_count = 0
        cur_start = None
        cur_count = 0
        gap = 0
        for sec in range(first, last + 1):
            count = self.av_per_sec.get(sec, 0)
            if count > 12:
                if cur_start is None:
                    cur_start = sec
                cur_count += count
                gap = 0
            else:
                if cur_count > 0:
                    gap += 1
                    if gap > 5:
                        latest_ts = cur_start
                        latest_count = cur_count
                        cur_start = None
                        cur_count = 0
                        gap = 0
        if cur_count > 0:  # trailing burst
            latest_ts = cur_start
            latest_count = cur_count
        self.last_burst_ts = latest_ts
        self.last_burst_count = latest_count

    def sparkline(self, width=SPARKLINE_WIDTH):
        """Return a sparkline string showing AV count per second for the last
        `width` seconds of session time."""
        if self.session_last_ts is None:
            return " " * width
        end = int(self.session_last_ts)
        start = end - width + 1
        bucket = [self.av_per_sec.get(s, 0) for s in range(start, end + 1)]
        peak = max(bucket) if bucket else 0
        if peak == 0:
            return " " * width
        scale = peak / (len(BLOCKS) - 1)
        return "".join(BLOCKS[min(len(BLOCKS) - 1, int(c / scale))] if scale else BLOCKS[0] for c in bucket)

    # ----- crash reports -----

    def scan_crashes(self):
        if not CRASH_DIR.exists():
            self.crash_count = 0
            self.latest_crash_path = None
            return
        try:
            files = list(CRASH_DIR.glob("*_crash.log"))
        except OSError:
            return
        self.crash_count = len(files)
        if files:
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            self.latest_crash_path = files[0]
            self.latest_crash_mtime = files[0].stat().st_mtime

    # ----- game process memory -----

    def update_game_memory(self):
        """Find Ashita-cli.exe (or fallback to the largest WoW64 wine process)
        and read its memory stats from /proc."""
        # Validate cached PID
        if self.game_pid is not None:
            if not Path(f"/proc/{self.game_pid}").exists():
                self.game_pid = None
                self.game_comm = None
                self.vm_size_kb = 0
                self.vm_peak_kb = 0
                self.vm_rss_kb = 0
                self.vm_data_kb = 0

        if self.game_pid is None:
            self.game_pid, self.game_comm = self._find_game_pid()

        if self.game_pid is None:
            return

        try:
            with open(f"/proc/{self.game_pid}/status") as f:
                for line in f:
                    if line.startswith("VmSize:"):
                        self.vm_size_kb = int(line.split()[1])
                    elif line.startswith("VmPeak:"):
                        self.vm_peak_kb = int(line.split()[1])
                    elif line.startswith("VmRSS:"):
                        self.vm_rss_kb = int(line.split()[1])
                    elif line.startswith("VmData:"):
                        self.vm_data_kb = int(line.split()[1])
        except (OSError, ValueError, IndexError):
            self.game_pid = None
            return

        # Track history (current time + vm_size) for delta calculation
        self.vm_size_history.append((time.time(), self.vm_size_kb))

    @staticmethod
    def _find_game_pid():
        """Find the actual FFXI render process by comm match.

        HorizonXI's launch chain is:
            faugus → Ashita-cli.exe (bootstrap) → horizon-loader.exe (game)
        We want the game itself (where memory pressure shows up). Try
        horizon-loader.exe first, then fall back to Ashita-cli.exe.

        NOTE: we DELIBERATELY do not read /proc/PID/cmdline for matching —
        HorizonXI's loader has the user's password as a CLI arg, and reading
        it here would risk surfacing it in logs/errors.
        """
        # comm field is truncated to 15 chars by the kernel ("horizon-loader.exe" → "horizon-loader.")
        candidates = ("horizon-loader.", "ashita-cli.exe")
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                comm = (proc / "comm").read_text().strip()
            except OSError:
                continue
            for c in candidates:
                if comm.lower() == c:
                    return int(proc.name), comm
        return None, None

    def vm_size_delta_kb_per_min(self):
        """Returns rate of VM size change in KB/min over the last ~60s of history.
        Positive = growing (leak); negative = freed; ~0 = stable."""
        if len(self.vm_size_history) < 2:
            return 0
        now_t, now_v = self.vm_size_history[-1]
        # Find earliest sample within the last 60s
        for t, v in self.vm_size_history:
            if now_t - t <= 60:
                if now_t == t:
                    return 0
                return (now_v - v) / ((now_t - t) / 60.0)
        return 0

    # ----- d3d8 md5 check (cheap, every ~30s) -----

    def check_d3d8(self):
        now = time.time()
        if now - self.d3d8_md5_check_time < 30:
            return
        self.d3d8_md5_check_time = now
        if not D3D8_PATH.exists():
            self.d3d8_md5 = None
            return
        try:
            h = hashlib.md5()
            with open(D3D8_PATH, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            self.d3d8_md5 = h.hexdigest()
        except OSError:
            self.d3d8_md5 = None


# --- TUI ------------------------------------------------------------------

def fmt_duration(secs):
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60}s"
    return f"{secs // 3600}h {(secs % 3600) // 60}m"


def fmt_filesize(p):
    try:
        n = p.stat().st_size
    except OSError:
        return "—"
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def fmt_kb(kb):
    """Format a KB count into a human-friendly string (KB / MB / GB)."""
    if kb < 0:
        return "-" + fmt_kb(-kb)
    if kb < 1024:
        return f"{kb} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    gb = mb / 1024
    return f"{gb:.2f} GB"


def draw(stdscr, m):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    if h < 18 or w < 70:
        stdscr.addstr(0, 0, f"Terminal too small ({w}x{h}); need 70x18+")
        stdscr.refresh()
        return

    # Color setup (lazy)
    if not hasattr(draw, "_colors_init"):
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
        curses.init_pair(4, curses.COLOR_CYAN, -1)
        curses.init_pair(5, curses.COLOR_MAGENTA, -1)
        draw._colors_init = True
    GREEN = curses.color_pair(1)
    YELLOW = curses.color_pair(2)
    RED = curses.color_pair(3)
    CYAN = curses.color_pair(4)
    DIM = curses.A_DIM
    BOLD = curses.A_BOLD

    row = 0
    title = " HorizonXI Health Monitor "
    stdscr.addstr(row, 0, "=" * w, DIM)
    stdscr.addstr(row, (w - len(title)) // 2, title, CYAN | BOLD)
    row += 1

    # Header line: session, log size, d3d8 verdict
    d3d8_ok = (m.d3d8_md5 == D3D8TO9_MD5)
    d3d8_str = ("d3d8to9 ✓" if d3d8_ok else
                ("Wine builtin ✗" if m.d3d8_md5 else "missing ?"))
    d3d8_attr = GREEN if d3d8_ok else RED
    row += 1
    stdscr.addstr(row, 2, f"Session: ")
    stdscr.addstr(fmt_duration(m.session_duration()), BOLD)
    stdscr.addstr(f"   Log: {fmt_filesize(LOG_PATH)}   syswow64 d3d8: ")
    stdscr.addstr(d3d8_str, d3d8_attr | BOLD)
    row += 2

    # Section: Critical
    stdscr.addstr(row, 0, "- Critical ".ljust(w, "-"), CYAN)
    row += 1
    crit_attr = RED | BOLD if m.oom_total > 0 else GREEN
    stdscr.addstr(row, 2, f"OOM warnings:    ")
    stdscr.addstr(f"{m.oom_total:>6}", crit_attr)
    if m.oom_total > 0:
        stdscr.addstr("   ⚠ pre-crash signal — VA space exhausting", RED)
    row += 1
    d3derr_attr = RED | BOLD if m.d3d8_err_total > 0 else GREEN
    stdscr.addstr(row, 2, f"d3d8 errors:     ")
    stdscr.addstr(f"{m.d3d8_err_total:>6}", d3derr_attr)
    if m.d3d8_err_total > 0:
        stdscr.addstr("   ⚠ Wine builtin d3d8 is active — wrapper failed", RED)
    row += 1
    crash_attr = YELLOW if m.crash_count > 0 else DIM
    stdscr.addstr(row, 2, f"Crash dumps:     ")
    stdscr.addstr(f"{m.crash_count:>6}", crash_attr)
    if m.latest_crash_path:
        when = time.strftime("%H:%M:%S", time.localtime(m.latest_crash_mtime))
        stdscr.addstr(f"   latest: {m.latest_crash_path.name}  ({when})", DIM)
    row += 2

    # Section: Access Violations
    stdscr.addstr(row, 0, "- Access Violations (c0000005) ".ljust(w, "-"), CYAN)
    row += 1
    rate = m.av_rate_60s()
    rate_attr = (RED if rate > 100 else
                 YELLOW if rate > 5 else GREEN)
    stdscr.addstr(row, 2, f"Total: ")
    stdscr.addstr(f"{m.av_total:>8}", BOLD)
    stdscr.addstr(f"   60s rate: ")
    stdscr.addstr(f"{rate:>6.1f}/sec", rate_attr | BOLD)
    row += 1
    if m.last_burst_ts is not None:
        burst_age = m.session_last_ts - m.last_burst_ts
        stdscr.addstr(row, 2,
                      f"Last burst: {m.last_burst_count} AVs at ts={m.last_burst_ts} "
                      f"({fmt_duration(burst_age)} ago)")
    else:
        stdscr.addstr(row, 2, "Last burst: none in session", DIM)
    row += 1
    sparkline = m.sparkline(min(SPARKLINE_WIDTH, w - 4))
    stdscr.addstr(row, 2, sparkline, YELLOW)
    row += 1
    stdscr.addstr(row, 2, f"  ↑ {len(sparkline)}s window  (each cell = 1 sec; height ∝ AVs that second)", DIM)
    row += 2

    # Section: Memory (game process)
    stdscr.addstr(row, 0, "- Game memory ".ljust(w, "-"), CYAN)
    row += 1
    if m.game_pid is None:
        stdscr.addstr(row, 2, "Ashita-cli.exe not found — game not running?", DIM)
        row += 2
    else:
        # Show pid + comm
        stdscr.addstr(row, 2, f"PID {m.game_pid} ({m.game_comm})")
        row += 1
        # VmSize bar against 4 GB 32-bit cap (~4194304 KB) — the LAA limit
        cap_kb = 4 * 1024 * 1024
        pct = min(100, m.vm_size_kb * 100 // cap_kb) if cap_kb else 0
        bar_width = max(20, min(40, w - 40))
        filled = pct * bar_width // 100
        bar = "█" * filled + "░" * (bar_width - filled)
        vm_attr = (RED | BOLD if pct >= 80 else
                   YELLOW if pct >= 60 else GREEN)
        stdscr.addstr(row, 2, "VmSize:  ")
        stdscr.addstr(f"{fmt_kb(m.vm_size_kb)}", BOLD)
        stdscr.addstr(f" / 4.0 GB (32-bit cap)  [")
        stdscr.addstr(bar, vm_attr)
        stdscr.addstr(f"] {pct}%")
        row += 1
        stdscr.addstr(row, 2, "Peak:    ")
        stdscr.addstr(f"{fmt_kb(m.vm_peak_kb)}", DIM | BOLD)
        stdscr.addstr(f"          ")
        stdscr.addstr("RSS: ", DIM)
        stdscr.addstr(f"{fmt_kb(m.vm_rss_kb)}", DIM | BOLD)
        stdscr.addstr("   ")
        stdscr.addstr("Data: ", DIM)
        stdscr.addstr(f"{fmt_kb(m.vm_data_kb)}", DIM | BOLD)
        row += 1
        delta = m.vm_size_delta_kb_per_min()
        delta_attr = (RED | BOLD if delta > 8192 else  # > 8 MB/min = active leak
                      YELLOW if delta > 1024 else
                      GREEN if delta >= 0 else DIM)
        sign = "+" if delta >= 0 else ""
        stdscr.addstr(row, 2, "60s trend: ")
        stdscr.addstr(f"{sign}{fmt_kb(int(delta))}/min", delta_attr | BOLD)
        if delta > 8192:
            stdscr.addstr(" ⚠ active VA leak", RED)
        elif delta > 1024:
            stdscr.addstr(" growing slowly", YELLOW)
        row += 2

    # Section: LuaJIT baseline
    stdscr.addstr(row, 0, "- LuaJIT baseline (e24c4a02) ".ljust(w, "-"), CYAN)
    row += 1
    lj_rate = m.luajit_rate_per_min()
    stdscr.addstr(row, 2, f"Total: ")
    stdscr.addstr(f"{m.luajit_total:>8}", BOLD)
    stdscr.addstr(f"   rate: {lj_rate:>5.1f}/min   ")
    stdscr.addstr(f"(normal idle: 5-20/min, busy: 30-60/min)", DIM)
    row += 1
    stdscr.addstr(row, 2, f"C++ exc paired (e06d7363): ")
    stdscr.addstr(f"{m.wine_cxx_total:>8}", DIM)
    row += 2

    # Footer
    stdscr.addstr(h - 1, 0, " q: quit | refresh: 1s ".ljust(w), DIM | curses.A_REVERSE)

    stdscr.refresh()


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(int(REFRESH_SECONDS * 1000))

    m = Metrics()

    while True:
        m.ingest()
        m.update_last_burst()
        m.scan_crashes()
        m.check_d3d8()
        m.update_game_memory()
        try:
            draw(stdscr, m)
        except curses.error:
            pass  # terminal resize race

        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q"), 27):
            break


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
