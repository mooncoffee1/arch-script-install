# EasyArch TUI — v0.2.0

**A keyboard-driven installer wizard prototype for Arch Linux terminals and the official ArchISO.**

> **Important:** This is an **interactive preview, not a working OS installer**. It **does not** partition, erase, mount, format, pacstrap, create users, or install bootloaders. It generates a **preview JSON plan only**, which is **not** an `archinstall` config. Do not advertise it as capable of installing Arch.

## Features

- Full-screen, keyboard-controlled TUI built with Python's standard-library `curses` (no GTK, Qt, or graphical environment)
- Simple workflow: Welcome -> Checks -> Disk -> Desktop -> Account -> Review
- Read-only UEFI/BIOS, architecture, RAM, and route checks
- Disk inventory via `lsblk`; disks with reported mounts, removable/read-only disks, and disks smaller than 20 GiB cannot be selected
- KDE Plasma, GNOME, XFCE, or Minimal desktop choices
- Validated hostname, username and time zone; no passwords collected
- Exports private JSON preview plans to `~/.local/share/easyarch/plans/`
- `--demo` simulates disks and blocks plan export for safe interface exploration
- Rescan key, interactive field editing, help overlay, and adaptive narrow-terminal notice
- **Never makes system modifications**

## Run

On the official Arch ISO (normally already includes Python) or a normal Arch Linux terminal:

```bash
# If Python is missing, install it first (network connection required):
# pacman -S --needed python

./start.sh
# Or preview on virtual sample disks without exporting a plan:
./start.sh --demo
```

Works in a text console or terminal emulator. **Run it as your current user**; root is neither needed nor used for disk writes, although the ArchISO shell normally starts as root. Minimum usable terminal size: 68 columns x 24 rows; 90x30 recommended. If your terminal is too small, enlarge it.

### Controls

| Key | Function |
| --- | --- |
| `Up` / `Down`, `j` / `k` | Highlight disk, desktop or form field |
| `Enter` | Select and proceed on disk/desktop pages; edit on account page; export on review |
| `Space` | Select disk or desktop without advancing |
| `N` / `Right` | Next step |
| `B` / `Left` / `Esc` | Previous step |
| `R` | Refresh hardware and disk info on checks/disk screens |
| `Tab` | Next field/item |
| `H` / `?` | Help |
| `Q` | Quit |

Text editing: `Enter` saves the field, `Esc` cancels, `Backspace` removes a character.

### Project files

```text
easyarch-installer/
├── README.md
├── LICENSE
├── .gitignore
├── start.sh
├── tui.py
├── core.py
└── tests/
    ├── test_core.py
    └── test_tui.py
```

### Tests

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile tui.py core.py
bash -n start.sh
```

### Safety notes

- **No disk writes** whatsoever in this release. The stored disk path refers to a **future hypothetical erase-disk flow**, NOT an authorized installation.
- Mounted/removable/read-only filtering is only a **basic preview guard**. It is NOT sufficient for production partitioning (e.g. encrypted/LVM/multipath, loop mounts, stale filesystem signatures, existing OS installations). A future destructive backend needs additional explicit detection, two-step confirmation and VM testing.
- This prototype makes no assumptions about firmware/driver choice; it doesn't yet install the selected desktop.
- Never enter passwords into plan fields; exported plans contain hostname, username, time zone and target disk path.
- A default route does not verify functional internet access.
- The terminal wizard does **not** change Arch's installation process or make a bootable installer USB by itself.

## Next milestone

1. Add profile selection and secure password entry in-memory only (never in plans/logs).
2. Develop a separate VM-only installation engine using a tested, pinned release of `archinstall` or a rigorously reviewed native backend.
3. Add robust block-device safety checks, backup/disk-wipe confirmation, ESP/bootloader configurations, file system choices and optional encryption.
4. Test in disposable QEMU/UEFI VMs with failure injection and recovery, then package for ArchISO.
5. Only after exhaustive tests, expose real installation functionality with careful warnings.

## Contribution

Pull requests and bug reports welcome. This project is MIT licensed. The code intentionally separates the terminal UI (`tui.py`) from read-only inventory/validation (`core.py`).
