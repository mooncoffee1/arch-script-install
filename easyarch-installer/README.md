# EasyArch Installer — v0.3.0-alpha

**A keyboard-controlled terminal wizard with an experimental real Arch Linux installation backend.**

> ⚠️ **EXPERIMENTAL, UNVERIFIED ON A BOOTED TEST INSTALL. DO NOT USE ON A COMPUTER CONTAINING IMPORTANT DATA.**
>
> `./start.sh --install` can **permanently destroy every partition and file on the selected disk**. This release has unit tests and a TUI smoke test, but has **NOT** passed an end-to-end UEFI virtual-machine install and reboot test. Start with a disposable UEFI virtual machine and an empty virtual disk. **Do not advertise this alpha as production-ready.**

## Supported in the experimental backend

- Official **Arch Linux live ISO**, x86_64, booted in **UEFI mode**, with internet and **Secure Boot disabled**.
- One selected **unmounted, non-USB, non-removable disk** (minimum 20 GiB), **entire disk erased**.
- GPT partition table, ~1 GiB FAT32 ESP mounted at `/boot`, ext4 root, no other partitions.
- `pacstrap -K` with Arch Linux base, `linux`, `linux-firmware`, `mkinitcpio`, NetworkManager, PipeWire, hardware firmware, and appropriate open-source GPU packages.
- CPU microcode for AMD or Intel, English (`en_US.UTF-8`) locale, hostname, local timezone, user and root passwords.
- KDE Plasma + Plasma Login Manager, GNOME + GDM, XFCE + LightDM, or Minimal (console only).
- `genfstab -U`, systemd-boot, boot entry pointing to the ext4 root UUID, service enabling.
- A private log under `/run/easyarch/install-<UTC-timestamp>.log`, copied to `/var/log/easyarch-installer.log` in the installed system if possible.

## NOT supported — do not use this release for

- Dual boot, keeping old partitions or files, resizing partitions.
- Legacy BIOS/MBR, Secure Boot, encryption/LUKS, LVM/RAID, Btrfs, manual partitioning.
- Installing to USB disks, most specialized storage stacks, non-x86_64 computers.
- Managing existing EFI bootloaders on other drives, recovery of interrupted installs.
- Automatic proprietary NVIDIA driver installation; NVIDIA support requires separate verification.
- Additional locale/keyboard layouts, Wi-Fi credentials on the installed system, multiple users, swap/hibernation.

The host ArchISO needs working network access before beginning. If you use Wi-Fi, connect first (e.g. using `iwctl` or `nmcli`). Check your internet before installation.

## Usage

On an installed Arch system, **only run the preview**:

```bash
./start.sh --demo      # simulated disk inventory, cannot perform install
./start.sh             # real disk inventory, preview JSON export only
```

On a **disposable UEFI VM booted into the official ArchISO**, from an interactive root terminal:

```bash
./start.sh --dry-run   # inspect target disks and simulate commands, no disk changes
./start.sh --install   # DANGEROUS: really erases the chosen entire disk
```

The real installation mode requires both a user and administrator password, checked hardware prerequisites, and two exact typed confirmations (`ERASE /dev/...`, then `INSTALL`). Review the disk model, size and partition count carefully. **There is no undo.**

`--demo`, `--dry-run`, and `--install` are mutually exclusive. The normal command `./start.sh` cannot modify partitions or install an OS.

### Installation in the Arch live ISO

Python 3, `lsblk`, `sgdisk`, `wipefs`, `partprobe`, `mkfs.fat`, `mkfs.ext4`, `pacstrap`, `arch-chroot`, `bootctl`, `genfstab`, `blkid` and `udevadm` are needed. The latest official Arch ISO normally provides them. Confirm with the **installer system checks**, or use `command -v` in its terminal. 

Bring the project onto the ISO through an existing Git clone, copy it in, or download a release. Since the live environment is ephemeral, source files are lost at reboot unless you save them elsewhere. The launcher requires a real terminal (TTY) of at least 68×24.

### Test it in a virtual machine (recommended)

1. Create a **new disposable UEFI VM** in virt-manager, with OVMF/UEFI firmware, at least 4 GiB RAM, a new **64 GiB virtual disk**, and a virtual network connection.
2. Attach the *official* Arch Linux ISO as a virtual CD-ROM. Boot the ISO in UEFI mode, with Secure Boot disabled.
3. Ensure the VM can connect to the internet and install/copy the EasyArch source into the ISO session.
4. Run `./start.sh --demo` for the interface, then `./start.sh --dry-run` and inspect the settings.
5. **Only if this is a throwaway VM:** run `./start.sh --install`, choose the VM's new empty virtual disk, and type both confirmation phrases.
6. When the installer reports success, power down the VM, **detach the Arch ISO**, and boot the virtual disk. Verify login, network, `findmnt /boot`, `systemctl --failed`, display-manager startup, and package updates.
7. If installation fails, save the `/run/easyarch/install-*.log` file **before shutting down**. The target filesystem may still be mounted at `/mnt/easyarch` for recovery. The installer does not perform automatic rollback.

**Do not pass a physical disk through to the VM** when testing this release. Verify the VM has access only to virtual test disks.

## Files

```text
easyarch-installer/
├── core.py             # inventory, disk filtering, plan validation
├── tui.py              # curses wizard, password entry, confirmation and progress
├── installer.py        # actual root installation engine; destructive in --install
├── start.sh            # launch script
├── tests/              # unit tests for safety, dry run and TUI
├── README.md
├── LICENSE
└── .gitignore
```

## Safety design

- Real installation is opt-in with `--install`; normal usage is a preview.
- It refuses to run the destructive backend outside a live ArchISO, without root, without UEFI, with Secure Boot enabled, on a mounted/USB/removable/read-only/undersized disk, or with detected active LVM/RAID stacks.
- The target disk is re-scanned and its size and block-device identity compared again before wiping.
- Two confirmations must match exactly; any mismatch cancels the installation.
- User and root passwords are entered masked, passed to `chpasswd` over standard input, and never exported to JSON or written to command logs. Sensitive strings still exist in process memory while installing. Keep logs private.
- Commands are executed directly as argument arrays, not constructed shell strings.
- On an error *after formatting*, the installer attempts to keep the filesystems available for repair; this does **not** restore erased data.
- It does not promise correct or complete detection of all dangerous storage configurations; testing and independent review are still required before real hardware use.

## Development tests

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile core.py installer.py tui.py
bash -n start.sh
```

## Source reference

Installation steps are based on the official [ArchWiki Installation guide](https://wiki.archlinux.org/title/Installation_guide) and [systemd-boot](https://wiki.archlinux.org/title/Systemd-boot) documentation. This project is not affiliated with the Arch Linux team. See `LICENSE` (MIT).
