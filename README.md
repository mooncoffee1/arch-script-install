# EasyArch Installer — GUI prototype v0.1

**A working GTK4 multi-step GUI; NOT a real operating system installer.**

This demo offers a welcoming wizard, checks local system properties, displays disks via `lsblk`, lets you select an *eligible* disk in preview mode, chooses KDE/GNOME/XFCE/Minimal, validates username/hostname/timezone, previews the plan, and exports it as JSON. **It never formats, mounts, partitions, writes bootloaders, installs packages, or asks for passwords.** The exported plan is *not* a valid `archinstall` configuration.

## Launch on an existing Arch Linux desktop

```bash
sudo pacman -S --needed python python-gobject gtk4
./start.sh
```

On other distributions, install Python 3, GTK4 and PyGObject using that distribution's package manager. Run it as your **normal desktop user**, **not root**.

The script needs an existing desktop session; it will **not** launch a graphical desktop from the standard text-only Arch Linux ISO. That requires building a custom ArchISO with a graphical environment and appropriate packages.

## Safety controls

- Runs unprivileged. There are **no install, mkfs, wipefs, mount, pacstrap, or bootloader commands** in the project.
- Mounted/in-use, read-only, removable and sub-20 GiB disks cannot be selected.
- On a machine whose only internal disk is mounted, you can still explore every wizard page, but you cannot export a validated plan without an eligible disk.
- Doesn't request or store passwords. Plans contain disk path and chosen nonsecret options.
- The preview plan is written with owner-only permissions under `~/.local/share/easyarch/plans/`.

## Test logic without GTK

```bash
python3 -m unittest discover -s tests -v
```

## Proposed milestones toward a real installer

1. **Preview (this release):** safe UI and detection.
2. **VM-only backend:** integrate with a pinned/tested `archinstall` release or Calamares; create correct config schema for that release, validate plan in a disposable VM only.
3. **Custom ArchISO:** Archiso + Wayland compositor + GTK4 runtime + network manager + preinstalled backend; launcher starts automatically.
4. **Real install workflow:** graphical Wi-Fi connection, encryption, partition editor, desktop profiles, firmware/driver selection, strong double-confirmation for destructive actions, progress view, error recovery, bootability testing.
5. **Release quality:** automated QEMU UEFI and BIOS integration tests, NVMe/SATA/USB and multi-disk tests, full-disk encryption tests, Secure Boot handling, dual-boot protectors and accessibility testing.

## Current limitations

- BIOS/UEFI and network tests are informative only. A default network route is not proof of internet access.
- Disk selection and profile options do not yet produce a complete actionable install configuration.
- Disk-in-use detection uses lsblk reported mounts (not exhaustive for complex LVM/RAID setups). This matters when implementing a real destructive backend.
- No live ISO or installation backend is included.
- The UI has been statically checked and backend unit-tested, but needs a GUI smoke-test in a real GTK4 desktop.

Built for experimentation. **Do not present v0.1 as an installer capable of installing Arch Linux.**
