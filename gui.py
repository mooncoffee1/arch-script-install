#!/usr/bin/env python3
"""EasyArch graphical wizard, PREVIEW ONLY: never executes installation commands."""
import sys

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk, GLib
except (ImportError, ValueError) as exc:
    sys.exit("GTK4/PyGObject is required. On Arch: sudo pacman -S --needed gtk4 python-gobject\n" + str(exc))

from core import enumerate_disks, preflight, system_timezone, DESKTOPS, validate_plan, export_plan

STEPS = ("Welcome", "System check", "Choose disk", "Desktop", "Your account", "Review")
CSS = b"""
window { background: #0e1422; color: #edf2ff; }
label { color: #edf2ff; }
.sidebar { background: #121c30; padding: 26px 18px; border-right: 1px solid #26334e; }
.brand { font-size: 25px; font-weight: 800; color: #c9d7ff; }
.caption { font-size: 12px; color: #9dabca; }
.step { font-size: 14px; color: #a7bad8; padding: 10px 8px; }
.step-active { color: #ffffff; font-weight: bold; background: #334975; border-radius: 10px; }
.main { padding: 28px 40px; }
.page-title { font-size: 28px; font-weight: 800; }
.subtitle { color: #a9b7d0; font-size: 14px; }
.panel { background: #19253c; border: 1px solid #2e4062; border-radius: 15px; padding: 18px; }
.panel-title { font-size: 16px; font-weight: 700; }
warning { color: #ffc989; }
.warning { color: #ffc989; }
.ok { color: #94e0c1; }
.error { color: #ffc0b8; }
button.suggested-action { background: #7189fa; color: #0b1230; font-weight: bold; }
entry { min-height: 34px; }
.footer { border-top: 1px solid #2a3851; padding: 16px 40px; }
"""


def label(text, css=None, wrap=True):
    widget = Gtk.Label(label=text, xalign=0)
    widget.set_wrap(wrap)
    if css:
        widget.add_css_class(css)
    return widget


def vertical(spacing=14):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    box.set_hexpand(True)
    return box


def panel(title, body):
    box = vertical(8)
    box.add_css_class("panel")
    box.append(label(title, "panel-title"))
    box.append(label(body, "subtitle"))
    return box


class InstallerWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="EasyArch Installer — Preview")
        self.set_default_size(1040, 650)
        self.set_size_request(800, 560)
        self.step = 0
        self.disks = enumerate_disks()
        self.hw = preflight()
        self.plan = {"disk": "", "desktop": "KDE Plasma", "hostname": "arch-pc", "username": "user", "timezone": system_timezone()}
        self.fields = {}
        self.root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.set_child(self.root)
        self.side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        self.side.set_size_request(230, -1)
        self.side.add_css_class("sidebar")
        self.root.append(self.side)
        self.side.append(label("◈  EasyArch", "brand"))
        self.side.append(label("INSTALLER PROTOTYPE • V0.1", "caption"))
        self.side.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.step_labels = []
        for i, step in enumerate(STEPS):
            step_lbl = label(f"{i+1:02d}   {step}", "step")
            self.side.append(step_lbl)
            self.step_labels.append(step_lbl)
        self.side.append(Gtk.Box(vexpand=True))
        self.side.append(label("Safe preview: never formats disks or installs software.", "caption"))
        self.right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.right.set_hexpand(True)
        self.root.append(self.right)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content.add_css_class("main")
        self.content.set_vexpand(True)
        self.right.append(self.content)
        self.footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.footer.add_css_class("footer")
        self.right.append(self.footer)
        self.back_btn = Gtk.Button(label="← Back")
        self.back_btn.connect("clicked", lambda *_: self.navigate(-1))
        self.footer.append(self.back_btn)
        self.footer.append(Gtk.Box(hexpand=True))
        self.next_btn = Gtk.Button(label="Continue →")
        self.next_btn.add_css_class("suggested-action")
        self.next_btn.connect("clicked", lambda *_: self.navigate(1))
        self.footer.append(self.next_btn)
        self.render()

    def alert(self, text):
        dlg = Gtk.AlertDialog()
        dlg.set_message("EasyArch Installer")
        dlg.set_detail(text)
        dlg.show(self)

    def render(self):
        while (child := self.content.get_first_child()) is not None:
            self.content.remove(child)
        self.fields.clear()
        for i, item in enumerate(self.step_labels):
            item.remove_css_class("step-active")
            if i == self.step:
                item.add_css_class("step-active")
        self.back_btn.set_sensitive(self.step > 0)
        self.next_btn.set_label("Export safe plan" if self.step == 5 else "Continue →")
        titles = ("Install Arch without the headaches", "Check your computer", "Where should Arch go?", "Make it yours", "Create your account", "Ready to review")
        self.content.append(label(titles[self.step], "page-title"))
        self.content.append(label("Nothing will be installed or erased. This version demonstrates the installation flow.", "subtitle"))
        self.content.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.content.append(scroll)
        inner = vertical(14)
        inner.set_margin_top(22)
        inner.set_margin_bottom(16)
        scroll.set_child(inner)
        (self.welcome, self.checks, self.disk_page, self.desktop_page, self.account, self.review)[self.step](inner)

    def welcome(self, c):
        c.append(panel("Welcome! 👋", "Our goal: a friendly setup wizard that eventually handles partitioning, drivers, boot configuration and the desktop for you."))
        c.append(panel("What works today", "Automatic hardware inventory, disk discovery, desktop selection, account details, validation, and exporting a safe installation plan."))
        c.append(panel("Coming in later releases", "A carefully tested installation backend, full partitioning support, encryption, Wi-Fi setup, and a bootable live ISO."))
        c.append(label("⚠ This build is a preview, NOT a functioning OS installer.", "warning"))

    def checks(self, c):
        h = self.hw
        for title, val in (
            ("Boot mode", h["firmware"]), ("Processor architecture", h["cpu_arch"]),
            ("Memory", h["memory"]), ("Network route", "Present (not an internet connectivity test)" if h["internet_default_route"] else "No default route detected"),
            ("Current desktop", h["current_desktop"]),
            ("Disks detected", str(len(self.disks))),
        ):
            c.append(panel(title, val))
        c.append(label("Later we will add real network checks, Secure Boot and graphics-driver compatibility checks.", "subtitle"))

    def disk_page(self, c):
        c.append(label("Select a disk to preview. Mounted, removable, read-only and very small devices are not selectable.", "subtitle"))
        c.append(label("⚠ A real 'erase disk' installation would DESTROY all data on that disk. This prototype makes no changes.", "warning"))
        self.disk_group = None
        if not self.disks:
            c.append(panel("No disks detected", "Ensure lsblk is installed; this prototype will not proceed without a disk."))
        for disk in self.disks:
            row = vertical(7)
            row.add_css_class("panel")
            cb = Gtk.CheckButton(label=f"{disk['model']}  ·  {disk['size']}  ·  {disk['path']}")
            if self.disk_group is not None:
                cb.set_group(self.disk_group)
            else:
                self.disk_group = cb
            cb.set_sensitive(disk["eligible"])
            if disk["path"] == self.plan["disk"]:
                cb.set_active(True)
            cb.connect("toggled", lambda obj, p=disk["path"]: self.plan.__setitem__("disk", p) if obj.get_active() else None)
            row.append(cb)
            row.append(label(disk["reason"] + f"  ·  Partitions: {disk['partition_count']}", "caption"))
            c.append(row)

    def desktop_page(self, c):
        c.append(label("Choose the look and feel of your new Linux system.", "subtitle"))
        group = None
        for name, desc in (
            ("KDE Plasma", "Feature-rich, familiar desktop with excellent customization."),
            ("GNOME", "Focused workspace with a clean, simple interface."),
            ("XFCE", "Traditional, lightweight desktop."),
            ("Minimal", "No graphical desktop; for advanced users."),
        ):
            box = vertical(6)
            box.add_css_class("panel")
            cb = Gtk.CheckButton(label=name)
            if group is not None:
                cb.set_group(group)
            else:
                group = cb
            cb.set_active(self.plan["desktop"] == name)
            cb.connect("toggled", lambda obj, n=name: self.plan.__setitem__("desktop", n) if obj.get_active() else None)
            box.append(cb)
            box.append(label(desc, "subtitle"))
            c.append(box)

    def account(self, c):
        c.append(label("Choose your computer name, username and timezone. Passwords are deliberately not collected in this preview.", "subtitle"))
        for key, title, hint in (
            ("hostname", "Computer name", "e.g. my-arch-pc"),
            ("username", "Username", "e.g. alex"),
            ("timezone", "Timezone", "e.g. Europe/Berlin"),
        ):
            c.append(label(title, "panel-title"))
            field = Gtk.Entry()
            field.set_text(self.plan[key])
            field.set_placeholder_text(hint)
            self.fields[key] = field
            c.append(field)
        c.append(panel("Passwords and encryption", "A real release will ask for passwords securely at installation time and will never put plaintext passwords into exported plans."))

    def save_fields(self):
        for key, field in self.fields.items():
            self.plan[key] = field.get_text().strip()

    def review(self, c):
        self.save_fields()
        selected = next((d for d in self.disks if d["path"] == self.plan["disk"]), None)
        items = (
            ("Installation disk", f"{self.plan['disk']} ({selected['size']})" if selected else "Not selected"),
            ("Install mode", "Erase selected disk — PLANNED ONLY"),
            ("Desktop", self.plan["desktop"]),
            ("Computer", self.plan["hostname"]),
            ("User", self.plan["username"]),
            ("Timezone", self.plan["timezone"]),
        )
        for k, v in items:
            c.append(panel(k, v))
        errors = validate_plan(self.plan, self.disks)
        if errors:
            c.append(label("Please fix: " + "  •  ".join(errors), "error"))
        else:
            c.append(label("✓ Plan validated. Exporting will ONLY save a JSON preview; it will NOT install Arch.", "ok"))
        self.next_btn.set_sensitive(not errors)

    def navigate(self, direction):
        self.save_fields()
        if self.step == 5 and direction > 0:
            try:
                path = export_plan(self.plan, self.disks)
            except (OSError, ValueError) as exc:
                self.alert(str(exc))
            else:
                self.alert(f"Preview plan saved to:\n{path}\n\nNo disks were modified and no installation was performed.")
            return
        # In preview, the user may explore all steps without selecting a disk.
        # Export still requires a verified eligible disk.
        if self.step == 4 and direction > 0:
            test = dict(self.plan)
            test["disk"] = test["disk"] or "/dev/invalid"
            errors = [x for x in validate_plan(test, self.disks) if not x.startswith("Select an installation disk") and not x.startswith("That disk")]
            if errors:
                self.alert("\n".join(errors))
                return
        self.step = max(0, min(len(STEPS) - 1, self.step + direction))
        self.next_btn.set_sensitive(True)
        self.render()


def main():
    app = Gtk.Application(application_id="org.easyarch.InstallerPreview")
    def activate(application):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        InstallerWindow(application).present()
    app.connect("activate", activate)
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
