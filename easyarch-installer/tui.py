#!/usr/bin/env python3
"""EasyArch TUI: preview by default; real full-disk erase only with --install."""
from __future__ import annotations

import argparse
import curses
import locale
import os
import sys
import textwrap
from typing import Any

from core import DESKTOPS, enumerate_disks, export_plan, preflight, system_timezone, validate_plan
from installer import Installer, InstallError, preinstall_checks

VERSION = "0.3.0-alpha"
STEPS = ("Welcome", "System checks", "Select disk", "Desktop", "Account", "Passwords", "Review")
DESCRIPTIONS = (
    "A familiar, customizable desktop - great for most users.",
    "A focused, streamlined desktop experience.",
    "A classic, lightweight desktop for older hardware.",
    "No graphical environment. Recommended for experienced users.",
)
FIELDS = (
    ("hostname", "Computer name", "arch-pc", 63),
    ("username", "Username", "alex", 32),
    ("timezone", "Timezone", "Europe/Berlin", 100),
)


def example_disks() -> list[dict[str, Any]]:
    """Virtual inventory used only in --demo (never exported as a real plan)."""
    return enumerate_disks({"blockdevices": [
        {"name": "vda", "path": "/dev/vda", "type": "disk", "size": 128 * 1024**3,
         "rm": 0, "ro": 0, "tran": "virtio", "model": "Demo Virtual Drive", "mountpoints": [None]},
        {"name": "sda", "path": "/dev/sda", "type": "disk", "size": 64 * 1024**3,
         "rm": 1, "ro": 0, "tran": "usb", "model": "Demo Installer USB", "mountpoints": [None]},
        {"name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk", "size": 500 * 1024**3,
         "rm": 0, "ro": 0, "tran": "nvme", "model": "Demo Mounted Drive",
         "mountpoints": [None], "children": [{"type": "part", "mountpoints": ["/"]}]},
    ]})


class Wizard:
    def __init__(self, screen: Any, demo: bool = False, install_enabled: bool = False, dry_run: bool = False):
        self.screen = screen
        self.demo = demo
        self.install_enabled = install_enabled
        self.dry_run = dry_run
        self.passwords: dict[str, str] = {}
        self.password_cursor = 0
        self.selected_bytes = None
        self.selected_identity = None
        self.step = 0
        self.hw = preflight()
        self.disks = example_disks() if demo else enumerate_disks()
        self.disk_cursor = 0
        self.desktop_cursor = 0
        self.account_cursor = 0
        self.check_cursor = 0
        self.plan = {
            "disk": "", "desktop": DESKTOPS[0], "hostname": "arch-pc",
            "username": "user", "timezone": system_timezone(),
        }
        self.message = ""
        self.message_is_error = False
        self.saved_plan = ""
        self.color = False
        self.result = ""

    def init_screen(self) -> None:
        curses.curs_set(0)
        self.screen.keypad(True)
        self.screen.timeout(-1)
        if curses.has_colors():
            try:
                curses.start_color()
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_CYAN, -1)     # headings
                curses.init_pair(2, curses.COLOR_GREEN, -1)    # good
                curses.init_pair(3, curses.COLOR_YELLOW, -1)   # warning
                curses.init_pair(4, curses.COLOR_RED, -1)      # error
                curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)  # selected
                self.color = True
            except curses.error:
                self.color = False

    def style(self, pair: int = 0, *, bold: bool = False, dim: bool = False) -> int:
        value = curses.color_pair(pair) if self.color else 0
        if bold:
            value |= curses.A_BOLD
        if dim:
            value |= curses.A_DIM
        return value

    def text(self, y: int, x: int, text: str, *, pair: int = 0,
             bold: bool = False, dim: bool = False, width: int | None = None) -> None:
        h, w = self.screen.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        length = max(0, min(w - x - 1, width if width is not None else w - x - 1))
        try:
            self.screen.addnstr(y, x, str(text), length, self.style(pair, bold=bold, dim=dim))
        except curses.error:
            pass

    def wrap(self, y: int, x: int, text: str, width: int, max_lines: int = 5,
             *, pair: int = 0, dim: bool = False) -> int:
        lines = textwrap.wrap(text, width=max(10, width), break_long_words=True) or [""]
        for i, line in enumerate(lines[:max_lines]):
            self.text(y + i, x, line, pair=pair, dim=dim)
        return min(len(lines), max_lines)

    def frame(self) -> tuple[int, int, int, int] | None:
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        if h < 24 or w < 68:
            self.text(1, 2, "Terminal is too small for EasyArch.", pair=3, bold=True)
            self.text(3, 2, "Resize to at least 68 columns x 24 rows.")
            self.text(5, 2, "Press Q to exit.")
            self.screen.refresh()
            return None
        width = min(94, w - 4)
        left = max(1, (w - width) // 2)
        right = left + width - 1
        bottom = h - 2
        rule = "-" * (width - 2)
        self.text(0, left, "+" + rule + "+")
        for y in range(1, bottom):
            self.text(y, left, "|")
            self.text(y, right, "|")
        self.text(bottom, left, "+" + rule + "+")
        self.text(2, left + 3, "E A S Y A R C H", pair=1, bold=True)
        self.text(2, right - 23, f"TERMINAL WIZARD v{VERSION}", dim=True)
        self.text(3, left + 3, "DANGEROUS: FULL DISK ERASE ENABLED" if self.install_enabled else "NO SYSTEM CHANGES (SIMULATION)" if self.dry_run else "PREVIEW ONLY / NO DISK ERASURE", pair=4 if self.install_enabled else 3, bold=True)
        self.text(5, left + 3, f"STEP {self.step + 1}/{len(STEPS)}   {STEPS[self.step].upper()}", pair=1, bold=True)
        progress = "  ".join(("[*]" if i == self.step else "[+]" if i < self.step else "[ ]")
                             for i in range(len(STEPS)))
        self.text(6, left + 3, progress, dim=True)
        self.text(bottom - 4, left + 2, "-" * (width - 4), dim=True)
        self.text(bottom - 3, left + 3, "Arrows: move    Enter: select/continue    B: back    H: help    Q: quit", dim=True)
        if self.step == 2:
            self.text(bottom - 2, left + 3, "SPACE: select disk    R: rescan    N: continue", dim=True)
        elif self.step == 4:
            self.text(bottom - 2, left + 3, "Enter: edit field    N: passwords    TAB: next field", dim=True)
        elif self.step == 5:
            self.text(bottom - 2, left + 3, "Enter: set password    N: continue", dim=True)
        elif self.step == 6:
            action = "Enter: install (ERASES SELECTED DISK)" if self.install_enabled else (
                "Enter: simulate install; no writes" if self.dry_run else "Enter: export preview JSON only")
            self.text(bottom - 2, left + 3, action, pair=4 if self.install_enabled else 3)
        else:
            self.text(bottom - 2, left + 3, "N / Right: continue    Esc: previous page", dim=True)
        if self.message:
            self.text(bottom - 5, left + 3, self.message, pair=4 if self.message_is_error else 2,
                      width=width - 7)
        start_y = 8
        last_content_y = bottom - 6
        return left + 4, start_y, width - 8, max(1, last_content_y - start_y + 1)

    def show(self) -> None:
        geometry = self.frame()
        if geometry is None:
            return
        x, y, width, rows = geometry
        if self.step == 0:
            self.welcome(x, y, width, rows)
        elif self.step == 1:
            self.checks(x, y, width, rows)
        elif self.step == 2:
            self.disk_page(x, y, width, rows)
        elif self.step == 3:
            self.desktop_page(x, y, width, rows)
        elif self.step == 4:
            self.account_page(x, y, width, rows)
        elif self.step == 5:
            self.password_page(x, y, width, rows)
        else:
            self.review(x, y, width, rows)
        self.screen.refresh()

    def welcome(self, x: int, y: int, width: int, rows: int) -> None:
        lines = [
            ("Welcome to the EasyArch terminal wizard", 1, True),
            ("", 0, False),
            ("A straightforward Arch installation walkthrough for a text terminal.", 0, False),
            ("", 0, False),
            ("[1] Check system hardware and connection", 0, True),
            ("[2] Review disks and choose a target", 0, True),
            ("[3] Choose a desktop environment", 0, True),
            ("[4] Configure and review your preferences", 0, True),
            ("", 0, False),
            ("MODE: " + ("REAL INSTALL / FULL DISK ERASE" if self.install_enabled else "SIMULATION - no writes" if self.dry_run else "PREVIEW ONLY - no disk writes") , 4 if self.install_enabled else 3, True),
        ]
        for idx, (line, pair, bold) in enumerate(lines[:rows]):
            self.text(y + idx, x, line, pair=pair, bold=bold, width=width)

    def checks(self, x: int, y: int, width: int, rows: int) -> None:
        self.text(y, x, "System readiness - use Up/Down to scroll", bold=True)
        h = self.hw
        entries = (
            ("Boot mode", h.get("firmware", "Unknown")),
            ("Architecture", h.get("cpu_arch", "Unknown")),
            ("Memory", h.get("memory", "Unknown")),
            ("Network route", "Detected (not proof of internet access)" if h.get("internet_default_route") else "Not detected"),
            ("Detected disks", str(len(self.disks))),
            ("Desktop session", h.get("current_desktop", "Unknown")),
            ("Running as", "root (ArchISO compatible)" if os.geteuid() == 0 else "regular user"),
            ("Disk operations", "FULL ERASE ENABLED" if self.install_enabled else "SIMULATED" if self.dry_run else "DISABLED - preview"),
        )
        visible = max(1, rows - 3)
        start = max(0, min(self.check_cursor - visible // 2, len(entries) - visible))
        for idx in range(start, min(start + visible, len(entries))):
            label, value = entries[idx]
            row = y + 2 + idx - start
            self.text(row, x, (label + ":").ljust(20), dim=True)
            self.text(row, x + 21, str(value), pair=3 if label == "Disk operations" else 0,
                      width=max(1, width - 21))
        self.text(y + rows - 1, x, "R: refresh  |  Network route is not an internet check.", dim=True, width=width)

    def disk_page(self, x: int, y: int, width: int, rows: int) -> None:
        self.text(y, x, "Select disk (ERASES ALL DATA!)" if self.install_enabled else "Select target disk (NO disk changes)", bold=True, width=width)
        self.text(y + 1, x, "Unavailable disks cannot be selected. Press R to rescan.", pair=3, width=width)
        if not self.disks:
            self.text(y + 3, x, "No disks found. Check lsblk installation and press R.", pair=3, width=width)
            return
        slots = max(1, min(len(self.disks), (rows - 5) // 2))
        first = max(0, min(self.disk_cursor - slots // 2, len(self.disks) - slots))
        for index in range(first, min(first + slots, len(self.disks))):
            disk = self.disks[index]
            row = y + 3 + (index - first) * 2
            selected = disk["path"] == self.plan["disk"]
            focus = index == self.disk_cursor
            label = f"{'>' if focus else ' '} {'(*)' if selected else '( )'} {disk['path']} - {disk['model']} - {disk['size']}"
            self.text(row, x, label, pair=5 if focus else 0, bold=focus, width=width)
            reason = disk["reason"] if not disk["eligible"] else f"Eligible target | {disk['partition_count']} partition(s)"
            self.text(row + 1, x + 5, reason, pair=3 if not disk["eligible"] else 2, width=width - 5)
        self.text(y + rows - 1, x, "Mounted, removable, read-only and tiny disks are excluded.", dim=True, width=width)

    def desktop_page(self, x: int, y: int, width: int, rows: int) -> None:
        self.text(y, x, "Choose your desktop environment", bold=True)
        self.text(y + 1, x, "Up/Down and Enter to select.", dim=True)
        slots = max(1, min(len(DESKTOPS), (rows - 3) // 2))
        first = max(0, min(self.desktop_cursor - slots // 2, len(DESKTOPS) - slots))
        for idx in range(first, min(first + slots, len(DESKTOPS))):
            desktop, desc = DESKTOPS[idx], DESCRIPTIONS[idx]
            row = y + 2 + (idx - first) * 2
            focus = idx == self.desktop_cursor
            selected = desktop == self.plan["desktop"]
            self.text(row, x, f"{'>' if focus else ' '} {'(*)' if selected else '( )'} {desktop}",
                      pair=5 if focus else 0, bold=focus)
            self.text(row + 1, x + 5, desc, dim=True, width=width - 5)

    def account_page(self, x: int, y: int, width: int, rows: int) -> None:
        self.text(y, x, "Configure account preferences", bold=True)
        self.text(y + 1, x, "Enter edits a field. Passwords are handled separately.", dim=True, width=width)
        for idx, (key, title, example, _) in enumerate(FIELDS):
            row = y + 3 + idx * 2
            focus = idx == self.account_cursor
            self.text(row, x, f"{'>' if focus else ' '} {title}: {self.plan[key]}",
                      pair=5 if focus else 0, bold=focus, width=width)
            self.text(row + 1, x + 4, f"Example: {example}", dim=True, width=width - 4)
        if rows >= 11:
            self.text(y + rows - 1, x, "N: continue to Passwords after entering valid names.", dim=True, width=width)

    def password_page(self, x: int, y: int, width: int, rows: int) -> None:
        self.text(y, x, "Account passwords (not saved to disk or logs)", bold=True)
        self.text(y + 1, x, "Passwords are required only for real installation.", dim=True)
        for i, role in enumerate(("user", "root")):
            label = "User password" if role == "user" else "Administrator (root) password"
            value = "[set]" if self.passwords.get(role) else "[not set]"
            focused = i == self.password_cursor
            self.text(y + 3 + i * 2, x, f"{'>' if focused else ' '} {label}: {value}",
                      pair=5 if focused else 0, width=width)
        if not self.install_enabled:
            self.text(y + min(rows - 1, 7), x, "No password needed in preview or dry-run mode. Press N.",
                      pair=3, width=width)
        else:
            self.text(y + min(rows - 1, 7), x, "Enter: change highlighted password (minimum 8 characters).", dim=True, width=width)

    def review(self, x: int, y: int, width: int, rows: int) -> None:
        self.text(y, x, "Final review - REAL INSTALL" if self.install_enabled else "Final review - NO WRITES", bold=True)
        disk = next((d for d in self.disks if d["path"] == self.plan["disk"]), None)
        entries = (
            ("Target disk", (disk["path"] + " - " + disk["size"]) if disk else "NOT SELECTED"),
            ("Disk operation", "ERASE ENTIRE DISK" if self.install_enabled else "SIMULATION ONLY" if self.dry_run else "NONE - PREVIEW ONLY"),
            ("Desktop", self.plan["desktop"]),
            ("Hostname", self.plan["hostname"]),
            ("Username", self.plan["username"]),
            ("Timezone", self.plan["timezone"]),
            ("Passwords", "User/root set" if all(self.passwords.get(k) for k in ("user", "root")) else "NOT SET"),
        )
        for i, (label, value) in enumerate(entries[:max(0, rows - 2)]):
            row = y + 1 + i
            self.text(row, x, (label + ":").ljust(18), dim=True)
            self.text(row, x + 20, value, pair=3 if label == "Disk operation" else 0, width=width - 20)
        errors = validate_plan(self.plan, self.disks)
        if self.demo:
            status = "DEMO MODE: simulated disks, exporting disabled."
            pair = 3
        elif errors:
            status = "Cannot export: " + errors[0]
            pair = 4
        elif self.install_enabled:
            status = ("Ready: Enter begins dangerous confirmation; entire disk will be ERASED."
                      if all(self.passwords.get(k) for k in ("user", "root")) else "Set BOTH passwords on previous page first.")
            pair = 4
        elif self.dry_run:
            status = "Enter: simulate backend. No disk writes will occur."
            pair = 2
        else:
            status = "Ready: Enter saves a preview JSON (NOT an archinstall config)."
            pair = 2
        self.text(y + rows - 1, x, status, pair=pair, width=width)
        if self.saved_plan and rows > 11:
            self.text(y + rows - 2, x, "Last saved: " + self.saved_plan, pair=2, width=width)

    def popup(self, heading: str, lines: list[str]) -> None:
        h, w = self.screen.getmaxyx()
        width = min(w - 4, 76)
        if width < 20 or h < 14:
            return
        wrapped: list[str] = []
        for line in lines:
            wrapped.extend(textwrap.wrap(line, width=width - 6) or [""])
        height = min(h - 4, max(9, len(wrapped) + 6))
        y = max(1, (h - height) // 2)
        x = max(1, (w - width) // 2)
        win = curses.newwin(height, width, y, x)
        win.bkgd(" ", self.style(0))
        win.box()
        win.addnstr(1, 3, heading, width - 6, self.style(1, bold=True))
        for i, line in enumerate(wrapped[:height - 5]):
            win.addnstr(3 + i, 3, line, width - 6)
        win.addnstr(height - 2, 3, "Press any key to continue...", width - 6, self.style(0, dim=True))
        win.refresh()
        win.getch()
        del win

    def edit_field(self) -> None:
        key, title, _, limit = FIELDS[self.account_cursor]
        h, w = self.screen.getmaxyx()
        width = min(76, w - 4)
        if width < 30 or h < 16:
            return
        height = 10
        win = curses.newwin(height, width, (h - height) // 2, (w - width) // 2)
        win.keypad(True)
        value = str(self.plan[key])
        self.screen.refresh()
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        while True:
            win.erase()
            win.box()
            win.addnstr(1, 3, "Edit " + title, width - 6, self.style(1, bold=True))
            win.addnstr(3, 3, "Value:", width - 6)
            room = width - 13
            displayed = value[-room:]
            win.addnstr(3, 10, displayed.ljust(room), room)
            win.move(3, 10 + len(displayed))
            win.addnstr(5, 3, "Enter: save | Esc: cancel | Backspace: delete", width - 6, self.style(0, dim=True))
            win.addnstr(6, 3, f"Maximum {limit} characters", width - 6, self.style(0, dim=True))
            win.refresh()
            try:
                ch = win.get_wch()
            except curses.error:
                continue
            if ch in ("\n", "\r", curses.KEY_ENTER):
                self.plan[key] = value.strip()
                self.set_message(f"Saved {title.lower()}.")
                break
            if ch in ("\x1b",):
                break
            if ch in ("\x7f", "\b", curses.KEY_BACKSPACE, curses.KEY_DC):
                value = value[:-1]
            elif isinstance(ch, str) and ch.isprintable() and ch.isascii() and len(value) < limit:
                value += ch
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        del win

    def set_message(self, message: str, error: bool = False) -> None:
        self.message = message
        self.message_is_error = error

    def rescan(self) -> None:
        self.hw = preflight()
        if not self.demo:
            self.disks = enumerate_disks()
        self.disk_cursor = min(self.disk_cursor, max(0, len(self.disks) - 1))
        self.check_cursor = 0
        selected = next((d for d in self.disks if d["path"] == self.plan["disk"]), None)
        if selected is None or not selected["eligible"]:
            self.plan["disk"] = ""
            self.selected_bytes = None
            self.selected_identity = None
        self.set_message("Refreshed hardware and disk list.")

    def select_disk(self, go_next: bool) -> None:
        if not self.disks:
            self.set_message("No disks found. Press R to rescan.", True)
            return
        disk = self.disks[self.disk_cursor]
        if not disk["eligible"]:
            self.set_message("Disk unavailable: " + disk["reason"], True)
            return
        self.plan["disk"] = disk["path"]
        self.selected_bytes = disk["bytes"]
        self.selected_identity = None
        if self.install_enabled:
            try:
                from installer import selected_device_identity
                self.selected_identity = selected_device_identity(disk["path"])
            except (OSError, InstallError) as exc:
                self.plan["disk"] = ""
                self.set_message("Cannot identify device: " + str(exc), True)
                return
        self.set_message("Selected disk: " + disk["path"])
        if go_next:
            self.step += 1

    def input_popup(self, title: str, description: list[str], *, secret: bool = False,
                    limit: int = 128) -> str | None:
        h, w = self.screen.getmaxyx()
        width = min(76, w - 4)
        height = max(12, min(h - 4, 8 + len(description)))
        if width < 42 or height >= h:
            return None
        win = curses.newwin(height, width, (h - height) // 2, (w - width) // 2)
        win.keypad(True)
        value = ""
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        try:
            while True:
                win.erase()
                win.box()
                win.addnstr(1, 2, title, width - 4, self.style(4 if not secret else 1, bold=True))
                for idx, line in enumerate(description):
                    win.addnstr(3 + idx, 2, line[:width - 4], width - 4)
                y = height - 4
                visible = ('*' * len(value) if secret else value)[-(width - 8):]
                win.addnstr(y, 3, visible, width - 7)
                win.move(y, 3 + len(visible))
                win.addnstr(height - 2, 2, "Enter: confirm   Esc: cancel   Backspace: erase", width - 4,
                            self.style(0, dim=True))
                win.refresh()
                try:
                    key = win.get_wch()
                except curses.error:
                    continue
                if key in ('\n', '\r', curses.KEY_ENTER):
                    return value
                if key == '\x1b':
                    return None
                if key in ('\x7f', '\b', curses.KEY_BACKSPACE, curses.KEY_DC):
                    value = value[:-1]
                elif isinstance(key, str) and key.isascii() and key.isprintable() and len(value) < limit:
                    value += key
        finally:
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            del win

    def set_password(self) -> None:
        if not self.install_enabled:
            self.set_message('Passwords are unnecessary in preview/dry-run mode.')
            return
        role = 'user' if self.password_cursor == 0 else 'root'
        password = self.input_popup('Set ' + role + ' password', [
            'Use 8-128 characters. Password text will be hidden.',
            'Do NOT reuse a password you already shared online.',
        ], secret=True)
        if password is None:
            return
        if not 8 <= len(password) <= 128 or any(x in password for x in ':\n\r'):
            self.set_message('Password must be 8-128 characters without colon/newline.', True)
            return
        confirm = self.input_popup('Confirm ' + role + ' password', ['Retype the same password.'], secret=True)
        if confirm != password:
            self.set_message('Passwords do not match. Try again.', True)
            return
        self.passwords[role] = password
        self.set_message(role + ' password configured (in memory only).')

    def render_progress(self, label: str, step: int, total: int, log_path: str) -> None:
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        self.text(2, 3, 'EASYARCH  v0.3  |  ' + ('DRY RUN - NO WRITES' if self.dry_run else 'INSTALLING ARCH LINUX'),
                  pair=3 if self.dry_run else 4, bold=True)
        self.text(4, 3, f'Step {step}/{total}: {label or self.install_label}', pair=1, bold=True)
        size = max(4, min(w - 10, 52))
        count = size * step // total
        self.text(6, 3, '[' + '#' * count + '-' * (size - count) + ']')
        if log_path:
            self.text(8, 3, 'Log: ' + log_path, dim=True)
            try:
                with open(log_path, 'rb') as f:
                    f.seek(0, 2)
                    f.seek(max(0, f.tell() - 1800))
                    lines = f.read().decode('utf-8', 'replace').splitlines()
                for i, line in enumerate(lines[-max(1, min(8, h - 14)):]):
                    self.text(11 + i, 3, line, width=w - 6, dim=True)
            except OSError:
                pass
        self.text(h - 3, 3, 'Do not power off or remove the target disk. Wait for completion.', pair=3)
        self.screen.refresh()

    def install_progress(self, label: str, step: int, total: int, log_path: str) -> None:
        if label:
            self.install_label = label
        self.render_progress(label, step, total, log_path)

    def begin_real_install(self) -> None:
        if not all(self.passwords.get(k) for k in ('user', 'root')):
            self.popup('Passwords missing', ['Go back to the Passwords page and set both passwords.'])
            return
        try:
            preinstall_checks(self.plan, self.selected_bytes, self.selected_identity)
        except (OSError, InstallError) as exc:
            self.popup('Preflight blocked installation', str(exc).splitlines())
            return
        disk = next(d for d in self.disks if d['path'] == self.plan['disk'])
        phrase = 'ERASE ' + disk['path']
        first = self.input_popup('IRREVERSIBLE FULL DISK ERASE', [
            'Disk: ' + disk['path'] + ' | ' + disk['model'] + ' | ' + disk['size'],
            'ALL partitions and data on this disk will be DESTROYED.',
            'No dual-boot or data preservation. Back up your files.',
            'Type EXACTLY: ' + phrase,
        ], limit=128)
        if first != phrase:
            self.popup('Cancelled', ['Disk erasure NOT authorized.'])
            return
        second = self.input_popup('FINAL CONFIRMATION', [
            'This cannot be undone after partitioning starts.',
            'Type EXACTLY: INSTALL',
        ], limit=32)
        if second != 'INSTALL':
            self.popup('Cancelled', ['Second confirmation not given; no changes made.'])
            return
        self.do_install(dry_run=False)

    def do_install(self, *, dry_run: bool) -> None:
        errors = validate_plan(self.plan, self.disks)
        if errors:
            self.popup('Invalid settings', errors)
            return
        self.install_label = 'Starting'
        backend = Installer(self.plan, self.passwords, expected_bytes=self.selected_bytes, expected_identity=self.selected_identity,
                            dry_run=dry_run, progress=self.install_progress)
        try:
            outcome = backend.run_install()
        except (InstallError, OSError) as exc:
            self.result = 'INSTALL FAILED: ' + str(exc)
            self.popup('Installation failed', [str(exc),
                'Disk may already be erased. Do not reboot without reviewing the log.',
                'Log: ' + str(backend.log_path or 'Unavailable')])
        else:
            self.result = outcome
            self.popup('Installation finished', [outcome, 'Remove installation media before rebooting.' if not dry_run else ''])
        self.set_message(self.result, error=self.result.startswith('INSTALL FAILED'))

    def next_step(self) -> None:
        if self.step == len(STEPS) - 1:
            if self.demo:
                self.popup('Demo mode', ['Simulated disks: installation and export are disabled.'])
            elif self.install_enabled:
                self.begin_real_install()
            elif self.dry_run:
                self.do_install(dry_run=True)
            else:
                try:
                    filename = export_plan(self.plan, self.disks)
                except (OSError, ValueError) as exc:
                    self.popup('Cannot export plan', str(exc).splitlines())
                else:
                    self.saved_plan = str(filename)
                    self.popup('Plan saved', [str(filename), 'No disk changes. This is not an archinstall config.'])
            return
        if self.step == 2:
            selected = next((d for d in self.disks if d['path'] == self.plan['disk'] and d['eligible']), None)
            if not selected:
                self.set_message('Select an eligible disk with Enter or Space first.', True)
                return
        if self.step == 4:
            errors = validate_plan(self.plan, self.disks)
            identity_errors = [e for e in errors if not e.startswith(('Select an installation disk', 'That disk'))]
            if identity_errors:
                self.set_message(identity_errors[0], True)
                return
        if self.step == 5 and self.install_enabled and not all(self.passwords.get(k) for k in ('user', 'root')):
            self.set_message('Set user AND root passwords before continuing.', True)
            return
        self.step += 1
        self.set_message('')

    def run(self) -> int:
        self.init_screen()
        while True:
            self.show()
            key = self.screen.getch()
            if key == curses.KEY_RESIZE:
                continue
            if key in (ord("q"), ord("Q")):
                return 0
            if self.screen.getmaxyx()[0] < 24 or self.screen.getmaxyx()[1] < 68:
                continue
            if key in (ord("h"), ord("H"), ord("?")):
                self.popup("EasyArch keyboard help", [
                    "Up/Down: highlight a choice or account field.",
                    "Enter: select options, edit a field, set passwords; on Review performs the chosen mode.",
                    "Space: select a disk or desktop without moving to the next page.",
                    "N/Right: go to the next page; B/Left/Esc: go back.",
                    "R: rescan on hardware and disk pages.",
                    "Q: quit wizard. Actual disk writes require --install and two typed confirmations.",
                ])
                continue
            if key in (ord("b"), ord("B"), curses.KEY_LEFT, 27):
                if self.step > 0:
                    self.step -= 1
                    self.set_message("")
                continue
            if key in (curses.KEY_UP, ord("k")):
                if self.step == 1:
                    self.check_cursor = max(0, self.check_cursor - 1)
                elif self.step == 2 and self.disks:
                    self.disk_cursor = max(0, self.disk_cursor - 1)
                elif self.step == 3:
                    self.desktop_cursor = max(0, self.desktop_cursor - 1)
                elif self.step == 4:
                    self.account_cursor = max(0, self.account_cursor - 1)
                elif self.step == 5:
                    self.password_cursor = max(0, self.password_cursor - 1)
                continue
            if key in (curses.KEY_DOWN, ord("j"), 9):
                if self.step == 1:
                    self.check_cursor = min(7, self.check_cursor + 1)
                elif self.step == 2 and self.disks:
                    self.disk_cursor = min(len(self.disks) - 1, self.disk_cursor + 1)
                elif self.step == 3:
                    self.desktop_cursor = min(len(DESKTOPS) - 1, self.desktop_cursor + 1)
                elif self.step == 4:
                    self.account_cursor = min(len(FIELDS) - 1, self.account_cursor + 1)
                elif self.step == 5:
                    self.password_cursor = min(1, self.password_cursor + 1)
                continue
            if key in (ord("r"), ord("R")) and self.step in (1, 2):
                self.rescan()
                continue
            if key == ord(" "):
                if self.step == 2:
                    self.select_disk(go_next=False)
                elif self.step == 3:
                    self.plan["desktop"] = DESKTOPS[self.desktop_cursor]
                    self.set_message("Selected " + DESKTOPS[self.desktop_cursor])
                continue
            if key in (10, 13, curses.KEY_ENTER):
                if self.step == 2:
                    self.select_disk(go_next=True)
                elif self.step == 3:
                    self.plan["desktop"] = DESKTOPS[self.desktop_cursor]
                    self.next_step()
                elif self.step == 4:
                    self.edit_field()
                elif self.step == 5:
                    self.set_password()
                else:
                    self.next_step()
                continue
            if key in (ord("n"), ord("N"), curses.KEY_RIGHT):
                self.next_step()
                continue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EasyArch TUI alpha; preview by default, full-disk erase with --install")
    parser.add_argument("--demo", action="store_true", help="Show simulated disks for preview; export disabled")
    parser.add_argument("--install", action="store_true", help="ENABLE REAL FULL-DISK INSTALL (ERASES ALL DATA)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate backend without disk or system modifications")
    parser.add_argument("--version", action="version", version=f"EasyArch TUI {VERSION}")
    args = parser.parse_args(argv)
    if sum(bool(x) for x in (args.demo, args.install, args.dry_run)) > 1:
        parser.error("--demo, --install, and --dry-run are mutually exclusive")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("This TUI needs an interactive terminal. Run ./start.sh in a TTY or terminal emulator.", file=sys.stderr)
        return 2
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        locale.setlocale(locale.LC_ALL, "C")
    try:
        return curses.wrapper(lambda scr: Wizard(scr, demo=args.demo, install_enabled=args.install, dry_run=args.dry_run).run())
    except KeyboardInterrupt:
        return 130
    except curses.error as exc:
        print(f"Terminal initialization failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
