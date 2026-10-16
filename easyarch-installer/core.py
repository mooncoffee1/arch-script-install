"""Read-only inventory and validation for the EasyArch installer."""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

MIN_DISK_BYTES = 20 * 1024 ** 3
HOST_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
DESKTOPS = ("KDE Plasma", "GNOME", "XFCE", "Minimal")


def command(*args: str, timeout: int = 6) -> str:
    try:
        p = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def enumerate_disks(lsblk_data: dict | None = None) -> list[dict]:
    if lsblk_data is None:
        raw = command("lsblk", "--json", "--bytes", "-o", "NAME,PATH,SIZE,MODEL,TYPE,RM,RO,TRAN,MOUNTPOINTS,FSTYPE")
        try:
            lsblk_data = json.loads(raw)
        except (TypeError, ValueError):
            return []

    def mounted_tree(node: dict) -> bool:
        mp = node.get("mountpoints") or []
        if isinstance(mp, str):
            mp = [mp]
        return any(x for x in mp) or any(mounted_tree(child) for child in (node.get("children") or []))

    disks = []
    for n in lsblk_data.get("blockdevices", []):
        if n.get("type") != "disk":
            continue
        try:
            size = int(n.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        disk = {
            "path": str(n.get("path") or ""),
            "name": str(n.get("name") or ""),
            "model": str(n.get("model") or "Unknown disk").strip(),
            "bytes": size,
            "size": f"{size / 1024**3:.1f} GiB",
            "transport": str(n.get("tran") or "Unknown"),
            "removable": bool(int(n.get("rm") or 0)) or str(n.get("tran") or "").lower() == "usb",
            "read_only": bool(int(n.get("ro") or 0)),
            "mounted": mounted_tree(n),
            "partition_count": len(n.get("children") or []),
            "descendant_names": [],
            "complex_storage": False,
        }
        def walk(children):
            for child in children or []:
                disk["descendant_names"].append(str(child.get("name") or ""))
                fst = str(child.get("fstype") or "")
                typ = str(child.get("type") or "").lower()
                if typ not in ("part",) or fst in ("crypto_LUKS", "LVM2_member", "linux_raid_member"):
                    disk["complex_storage"] = True
                walk(child.get("children"))
        walk(n.get("children"))
        # Refuse disks currently in use, removable media, and undersized disks.
        disk["eligible"] = bool(disk["path"].startswith("/dev/")) and not (
            disk["removable"] or disk["read_only"] or disk["mounted"] or disk["complex_storage"] or size < MIN_DISK_BYTES
        )
        if disk["mounted"]:
            disk["reason"] = "Disk or partition is mounted/in use"
        elif disk["removable"]:
            disk["reason"] = "USB/removable media excluded for safety"
        elif disk["complex_storage"]:
            disk["reason"] = "Complex RAID/LVM/encrypted storage is not supported"
        elif disk["read_only"]:
            disk["reason"] = "Read-only device"
        elif size < MIN_DISK_BYTES:
            disk["reason"] = "Smaller than the 20 GiB minimum"
        else:
            disk["reason"] = "Available for review — ERASE mode requires confirmation"
        disks.append(disk)
    return disks


def installed_memory() -> str:
    lines = command("free", "-h").splitlines()
    return lines[1].split()[1] if len(lines) > 1 and len(lines[1].split()) > 1 else "Unknown"


def preflight() -> dict:
    return {
        "firmware": "UEFI" if Path("/sys/firmware/efi").exists() else "Legacy BIOS or unavailable",
        "internet_default_route": bool(command("ip", "route", "show", "default")),
        "cpu_arch": command("uname", "-m") or "Unknown",
        "memory": installed_memory(),
        "current_desktop": os.environ.get("XDG_CURRENT_DESKTOP", "Unknown"),
    }


def system_timezone() -> str:
    t = command("timedatectl", "show", "-p", "Timezone", "--value")
    return t if t and "/" in t else "UTC"


def validate_plan(plan: dict, disks: list[dict]) -> list[str]:
    errors = []
    selected = next((d for d in disks if d["path"] == plan.get("disk")), None)
    if selected is None:
        errors.append("Select an installation disk.")
    elif not selected["eligible"]:
        errors.append("That disk is not eligible because it is in use, removable, read-only or too small.")
    if plan.get("desktop") not in DESKTOPS:
        errors.append("Choose a desktop environment.")
    if not HOST_RE.fullmatch(str(plan.get("hostname", ""))):
        errors.append("Computer name must contain letters, numbers and hyphens only (1–63 characters).")
    if plan.get("username") in {"root", "nobody", "daemon", "bin"}:
        errors.append("Choose a non-system username.")
    if not USER_RE.fullmatch(str(plan.get("username", ""))):
        errors.append("Username must start with a lowercase letter or underscore, followed by lowercase letters, numbers, hyphens or underscores.")
    tz = str(plan.get("timezone", ""))
    if not tz or len(tz) > 100 or not re.fullmatch(r"[A-Za-z0-9_+./-]+", tz):
        errors.append("Enter a valid time zone, e.g. Europe/Berlin or UTC.")
    return errors


def export_plan(plan: dict, disks: list[dict]) -> Path:
    errors = validate_plan(plan, disks)
    if errors:
        raise ValueError("\n".join(errors))
    target_dir = Path.home() / ".local/share/easyarch/plans"
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = target_dir / f"plan-{stamp}.json"
    # The plan contains no passwords, and should not be used as archinstall config.
    payload = {
        "schema": "easyarch-preview-plan/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "notice": "PREVIEW ONLY: This is not an archinstall configuration. Does not perform installation.",
        "installation_mode": "erase-selected-disk-preview",
        **{k: plan[k] for k in ("disk", "desktop", "hostname", "username", "timezone")},
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(dest), flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return dest
