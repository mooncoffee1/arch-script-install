"""Experimental full-disk Arch Linux installation backend.

WARNING: --install with typed confirmations irreversibly erases a selected disk.
This is not an installer for dual-boot, Secure Boot, encryption, or BIOS systems.
All subprocesses are argv arrays; passwords are sent only via chpasswd stdin.
"""
from __future__ import annotations

import fcntl
import os
import re
import shutil
import stat
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from core import enumerate_disks, validate_plan

TARGET = Path('/mnt/easyarch')
NEEDED = ('lsblk', 'sgdisk', 'wipefs', 'partprobe', 'udevadm', 'mkfs.fat',
          'mkfs.ext4', 'mount', 'umount', 'pacstrap', 'genfstab', 'arch-chroot',
          'bootctl', 'blkid', 'findmnt')
DESKTOP_PACKAGES = {
    'KDE Plasma': ('plasma-meta', 'konsole', 'dolphin', 'xorg-xwayland'),
    'GNOME': ('gnome-shell', 'gnome-session', 'gnome-control-center',
              'gnome-console', 'gdm', 'nautilus', 'xdg-desktop-portal-gnome'),
    'XFCE': ('xfce4-session', 'xfce4-panel', 'xfwm4', 'xfdesktop', 'xfce4-settings',
             'xfce4-appfinder', 'xfce4-terminal', 'xfce4-power-manager',
             'thunar', 'lightdm', 'lightdm-gtk-greeter', 'xorg-server',
             'network-manager-applet'),
    'Minimal': (),
}
DISPLAY_MANAGER = {'KDE Plasma': 'plasmalogin', 'GNOME': 'gdm', 'XFCE': 'lightdm'}

class InstallError(RuntimeError):
    pass


def selected_device_identity(path: str) -> tuple[int, int]:
    """Major/minor identifies the underlying block device across rescans."""
    info = os.stat(path)
    if not stat.S_ISBLK(info.st_mode):
        raise InstallError(f'Not a block device: {path}')
    return (os.major(info.st_rdev), os.minor(info.st_rdev))


def check_secure_boot() -> bool:
    for f in Path('/sys/firmware/efi/efivars').glob('SecureBoot-*'):
        try:
            data = f.read_bytes()
            if len(data) >= 5 and data[4] == 1:
                return True
        except OSError as exc:
            raise InstallError(f'Cannot read Secure Boot state: {exc}') from exc
    return False


def strict_timezone(tz: str) -> bool:
    base = Path('/usr/share/zoneinfo').resolve()
    try:
        check = (base / tz).resolve(strict=True)
        return check.is_file() and check.is_relative_to(base)
    except (OSError, RuntimeError):
        return False


def cpu_microcode() -> str | None:
    try:
        cpuinfo = Path('/proc/cpuinfo').read_text(errors='replace')
    except OSError:
        return None
    if 'AuthenticAMD' in cpuinfo:
        return 'amd-ucode'
    if 'GenuineIntel' in cpuinfo:
        return 'intel-ucode'
    return None


def graphics_packages() -> list[str]:
    """Open-source graphics only; no proprietary NVIDIA selection."""
    try:
        cards = subprocess.run(['lspci', '-nn'], capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ['mesa']
    lines = [x.lower() for x in cards.splitlines() if ('vga compatible' in x.lower() or '3d controller' in x.lower())]
    packages = ['mesa']
    if any('[1002:' in x for x in lines):
        packages += ['vulkan-radeon', 'libva-mesa-driver']
    if any('[8086:' in x for x in lines):
        packages += ['vulkan-intel', 'intel-media-driver']
    return packages


def partition_path(disk: str, index: int) -> str:
    # nvme0n1p1 and mmcblk0p1, but sda1 and vda1
    return f'{disk}{"p" if disk[-1].isdigit() else ""}{index}'


def preinstall_checks(plan: dict, expected_bytes: int | None = None,
                      expected_identity: tuple[int, int] | None = None) -> tuple[int, int]:
    """Recheck *immediately before* the destructive step; no writes here."""
    if os.geteuid() != 0:
        raise InstallError('Actual installation requires root (run from official ArchISO).')
    if not Path('/run/archiso').exists():
        raise InstallError('Live ArchISO not detected. Refusing to run on an installed system.')
    if not Path('/sys/firmware/efi').exists():
        raise InstallError('UEFI boot is required. Legacy BIOS is not supported.')
    if not Path('/sys/firmware/efi/efivars').is_dir():
        raise InstallError('UEFI variables are not available; bootloader cannot be configured.')
    if check_secure_boot():
        raise InstallError('Secure Boot appears enabled. Unsigned systemd-boot is unsupported.')
    if subprocess.run(['uname', '-m'], capture_output=True, text=True).stdout.strip() != 'x86_64':
        raise InstallError('Only x86_64 is supported.')
    try:
        with urllib.request.urlopen('https://archlinux.org/', timeout=8) as response:
            if response.status != 200:
                raise InstallError('Arch Linux internet check did not succeed.')
    except (OSError, ValueError) as exc:
        raise InstallError('Internet/DNS/HTTPS unavailable; fix network/time before erasing: ' + str(exc)) from exc
    missing = [name for name in NEEDED if shutil.which(name) is None]
    if missing:
        raise InstallError('Required ArchISO tools missing: ' + ', '.join(missing))
    if plan.get('username') in {'root', 'nobody', 'daemon', 'bin', 'systemd-network', 'systemd-resolve'}:
        raise InstallError('Choose a non-system username.')
    if not strict_timezone(str(plan.get('timezone', ''))):
        raise InstallError('Time zone not installed in ArchISO zoneinfo: ' + str(plan.get('timezone')))
    disks = enumerate_disks()
    issues = validate_plan(plan, disks)
    if issues:
        raise InstallError('; '.join(issues))
    disk = next(x for x in disks if x['path'] == plan['disk'])
    if expected_bytes is not None and disk['bytes'] != expected_bytes:
        raise InstallError('Selected disk size changed since it was selected. Rescan and review.')
    if disk.get('transport', '').lower() == 'usb':
        raise InstallError('USB target disks are disabled (avoid wiping installation media).')
    if not os.path.realpath(plan['disk']).startswith('/dev/'):
        raise InstallError('Invalid device path.')
    identity = selected_device_identity(plan['disk'])
    if expected_identity is not None and identity != expected_identity:
        raise InstallError('Selected disk identity changed. Rescan and reselect it.')
    if TARGET.is_mount():
        raise InstallError(f'{TARGET} is already mounted; unmount manually before retrying.')
    if TARGET.exists() and any(TARGET.iterdir()):
        raise InstallError(f'{TARGET} is not empty. Refusing to use it.')
    # Explicitly block active holder devices, LVM/RAID, and encrypted stacks.
    for entry in [disk['name']] + disk.get('descendant_names', []):
        holders = Path('/sys/class/block') / entry / 'holders'
        if holders.exists() and any(holders.iterdir()):
            raise InstallError('Selected disk participates in an active device-mapper/RAID stack.')
    if disk.get('complex_storage'):
        raise InstallError('Disk contains RAID/LVM/crypto metadata or stacked devices. Manual handling required.')
    return identity


class Installer:
    def __init__(self, plan: dict, passwords: dict[str, str], *, expected_bytes: int | None,
                 expected_identity: tuple[int, int] | None = None, dry_run: bool, progress: Callable[[str, int, int, str], None] | None = None):
        self.plan = dict(plan)
        self.passwords = passwords
        self.expected_bytes = expected_bytes
        self.expected_identity = expected_identity
        self.dry_run = dry_run
        self.progress = progress or (lambda *args: None)
        self.log_path: Path | None = None
        self.log = None
        self.did_partition = False
        self.total = 12
        self.step = 0

    def notify(self, message: str) -> None:
        self.step += 1
        self.progress(message, self.step, self.total, str(self.log_path or ''))
        self.record('# PHASE: ' + message)

    def record(self, line: str) -> None:
        if self.log is not None:
            self.log.write(line + '\n')
            self.log.flush()

    def run(self, argv: list[str], *, input_text: str | None = None, capture: bool = False) -> str:
        self.record('$ ' + ' '.join(argv))
        if self.dry_run:
            return 'DRY_RUN'
        try:
            if capture:
                proc = subprocess.run(argv, capture_output=True, text=True,
                                      input=input_text, check=False)
                if proc.returncode:
                    self.record(proc.stderr[-1800:])
                    raise InstallError(f'Command failed ({proc.returncode}): {argv[0]}. See log.')
                return proc.stdout.strip()
            if input_text is not None:
                # stdin pipe, never in process arguments, environment, report, or logs
                proc = subprocess.run(argv, input=input_text, stdout=self.log, stderr=subprocess.STDOUT,
                                      text=True, check=False)
                if proc.returncode:
                    raise InstallError(f'Command failed ({proc.returncode}): {argv[0]}. See log.')
                return ''
            with subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=self.log,
                                  stderr=subprocess.STDOUT) as proc:
                while proc.poll() is None:
                    self.progress('', self.step, self.total, str(self.log_path or ''))
                    time.sleep(0.35)
                if proc.returncode:
                    raise InstallError(f'Command failed ({proc.returncode}): {argv[0]}. See log.')
            return ''
        except OSError as exc:
            raise InstallError(f'Cannot run {argv[0]}: {exc}') from exc

    def chroot(self, *argv: str, input_text: str | None = None) -> str:
        return self.run(['arch-chroot', str(TARGET), *argv], input_text=input_text)

    def write_target(self, relative: str, contents: str, *, mode: int = 0o644) -> None:
        if self.dry_run:
            self.record('Would write ' + relative)
            return
        dest = TARGET / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        # All relative paths are literal installer-owned paths, never from plan strings
        with dest.open('w', encoding='utf-8') as f:
            f.write(contents)
        dest.chmod(mode)

    def run_install(self) -> str:
        if self.dry_run:
            self.progress('DRY RUN: no commands or files will be modified', 0, 12, '')
        else:
            preinstall_checks(self.plan, self.expected_bytes, self.expected_identity)
            if set(self.passwords) != {'user', 'root'}:
                raise InstallError('Both user and root passwords are required.')
            for val in self.passwords.values():
                if not (8 <= len(val) <= 128) or '\n' in val or ':' in val:
                    raise InstallError('Passwords must be 8–128 characters and contain no colon/newline.')
            Path('/run/easyarch').mkdir(parents=True, exist_ok=True, mode=0o700)

        try:
            if not self.dry_run:
                lock = (Path('/run/easyarch') / 'install.lock').open('w')
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.lock = lock
                # Recheck after acquiring the process lock
                preinstall_checks(self.plan, self.expected_bytes, self.expected_identity)
                stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
                self.log_path = Path(f'/run/easyarch/install-{stamp}.log')
                self.log = self.log_path.open('x', encoding='utf-8', buffering=1)
                self.log_path.chmod(0o600)
            self.record('EasyArch experimental installer; target=' + self.plan['disk'])
            self.notify('Final disk verification')
            if not self.dry_run:
                preinstall_checks(self.plan, self.expected_bytes, self.expected_identity)
            disk = self.plan['disk']
            esp = partition_path(disk, 1)
            root = partition_path(disk, 2)

            self.notify('ERASING disk and creating GPT partitions')
            self.did_partition = not self.dry_run
            self.run(['wipefs', '-a', disk])
            self.run(['sgdisk', '--zap-all', disk])
            self.run(['sgdisk', '--clear', '--new=1:0:+1G', '--typecode=1:ef00',
                      '--change-name=1:EasyArch EFI', '--new=2:0:0',
                      '--typecode=2:8300', '--change-name=2:EasyArch root', disk])
            self.run(['partprobe', disk])
            self.run(['udevadm', 'settle'])
            if not self.dry_run:
                for _ in range(15):
                    if Path(esp).exists() and Path(root).exists():
                        break
                    time.sleep(0.5)
                if not Path(esp).exists() or not Path(root).exists():
                    raise InstallError('Partition device nodes not found after repartitioning.')

            self.notify('Formatting EFI (FAT32) and root (ext4)')
            self.run(['mkfs.fat', '-F', '32', esp])
            self.run(['mkfs.ext4', '-F', '-L', 'EasyArchRoot', root])

            self.notify('Mounting target filesystems')
            if not self.dry_run:
                TARGET.mkdir(parents=True, exist_ok=True)
            self.run(['mount', root, str(TARGET)])
            if not self.dry_run:
                (TARGET / 'boot').mkdir(exist_ok=True)
            self.run(['mount', esp, str(TARGET / 'boot')])

            self.notify('Installing Arch packages (can take a while)')
            packages = ['base', 'linux', 'linux-firmware', 'mkinitcpio', 'sudo', 'nano',
                        'networkmanager', 'wireless-regdb', 'bash-completion', 'man-db',
                        'pipewire', 'pipewire-pulse', 'pipewire-alsa', 'wireplumber']
            ucode = cpu_microcode()
            if ucode:
                packages.append(ucode)
            packages += graphics_packages() + list(DESKTOP_PACKAGES[self.plan['desktop']])
            self.run(['pacstrap', '-K', str(TARGET), *dict.fromkeys(packages)])

            self.notify('Generating filesystem mount table')
            fstab = self.run(['genfstab', '-U', str(TARGET)], capture=True)
            if not self.dry_run and (' / ' not in fstab or '/boot' not in fstab):
                raise InstallError('genfstab output missing root or EFI mount; refusing to continue.')
            self.write_target('etc/fstab', fstab + '\n')

            self.notify('Configuring hostname, time zone and locale')
            hostname = self.plan['hostname']
            self.write_target('etc/hostname', hostname + '\n')
            self.write_target('etc/hosts', '127.0.0.1 localhost\n::1 localhost\n'
                              f'127.0.1.1 {hostname}.localdomain {hostname}\n')
            self.write_target('etc/locale.conf', 'LANG=en_US.UTF-8\n')
            self.write_target('etc/locale.gen', 'en_US.UTF-8 UTF-8\n')
            if not self.dry_run:
                tz_link = TARGET / 'etc/localtime'
                if tz_link.exists() or tz_link.is_symlink():
                    tz_link.unlink()
                tz_link.symlink_to('/usr/share/zoneinfo/' + self.plan['timezone'])
            self.chroot('locale-gen')

            self.notify('Creating user, administrator access and passwords')
            username = self.plan['username']
            self.chroot('useradd', '-m', '-U', '-G', 'wheel', '-s', '/bin/bash', username)
            self.write_target('etc/sudoers.d/10-easyarch-wheel', '%wheel ALL=(ALL:ALL) ALL\n', mode=0o440)
            if not self.dry_run:
                self.chroot('chpasswd', input_text='root:' + self.passwords['root'] + '\n')
                self.chroot('chpasswd', input_text=username + ':' + self.passwords['user'] + '\n')
            else:
                self.record('Would assign user/root passwords by stdin (not logged)')

            self.notify('Enabling networking and desktop login')
            self.chroot('systemctl', 'enable', 'NetworkManager.service')
            dm = DISPLAY_MANAGER.get(self.plan['desktop'])
            if dm:
                self.chroot('systemctl', 'enable', dm + '.service')

            self.notify('Preparing kernel and initramfs')
            self.chroot('mkinitcpio', '-P')
            if not self.dry_run:
                for file in ('vmlinuz-linux', 'initramfs-linux.img'):
                    if not (TARGET / 'boot' / file).is_file():
                        raise InstallError(f'Missing kernel boot file: {file}')

            self.notify('Installing and configuring systemd-boot')
            # arch-chroot -S avoids a PID namespace that suppresses EFI NVRAM writes.
            self.run(['arch-chroot', '-S', str(TARGET), 'bootctl', '--esp-path=/boot', 'install'])
            root_uuid = self.run(['blkid', '-s', 'UUID', '-o', 'value', root], capture=True)
            if not self.dry_run and not re.fullmatch(r'[0-9a-fA-F-]{16,64}', root_uuid):
                raise InstallError('Unable to determine root filesystem UUID.')
            self.write_target('boot/loader/loader.conf', 'default easyarch.conf\ntimeout 3\neditor no\n')
            # Current mkinitcpio uses the microcode hook to embed early microcode
            # in initramfs-linux.img. Do not also load a separate microcode image.
            self.write_target('boot/loader/entries/easyarch.conf',
                              'title EasyArch Linux\nlinux /vmlinuz-linux\n'
                              'initrd /initramfs-linux.img\n'
                              + f'options root=UUID={root_uuid} rw\n')

            self.notify('Finishing installation and preserving log')
            if not self.dry_run:
                self.log.flush()
                shutil.copyfile(self.log_path, TARGET / 'var/log/easyarch-installer.log')
                (TARGET / 'var/log/easyarch-installer.log').chmod(0o600)
                self.run(['umount', '-R', str(TARGET)])
            return 'Dry run completed: NOTHING changed.' if self.dry_run else 'Install completed. Reboot after removing the ISO.'
        except Exception as exc:
            self.record('ERROR: ' + str(exc))
            if not self.dry_run and self.did_partition and TARGET.is_mount() and self.log_path:
                try:
                    dest = TARGET / 'var/log/easyarch-installer.log'
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    self.log.flush()
                    shutil.copyfile(self.log_path, dest)
                    dest.chmod(0o600)
                except OSError:
                    pass
            if isinstance(exc, InstallError):
                raise
            raise InstallError(str(exc)) from exc
        finally:
            self.passwords.clear()
            if self.log:
                self.log.close()
            if hasattr(self, 'lock'):
                self.lock.close()
