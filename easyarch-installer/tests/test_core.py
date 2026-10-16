import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import enumerate_disks, validate_plan


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.disk_data = {"blockdevices": [
            {"name": "sda", "path": "/dev/sda", "type": "disk", "size": 256 * 1024**3,
             "rm": False, "ro": False, "tran": "sata", "model": "Test Drive", "mountpoints": [None],
             "children": [{"type": "part", "mountpoints": ["/"]}]},
            {"name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk", "size": 512 * 1024**3,
             "rm": False, "ro": False, "tran": "nvme", "model": "Spare Disk", "mountpoints": [None],
             "children": []},
            {"name": "sdb", "path": "/dev/sdb", "type": "disk", "size": 64 * 1024**3,
             "rm": True, "ro": False, "tran": "usb", "model": "Install USB", "mountpoints": [None]},
        ]}
        self.disks = enumerate_disks(self.disk_data)

    def test_in_use_and_removable_disks_blocked(self):
        self.assertFalse(self.disks[0]["eligible"])
        self.assertTrue(self.disks[1]["eligible"])
        self.assertFalse(self.disks[2]["eligible"])

    def test_valid_plan(self):
        valid = {"disk": "/dev/nvme0n1", "desktop": "KDE Plasma", "hostname": "home-pc", "username": "alex", "timezone": "Europe/Berlin"}
        self.assertEqual(validate_plan(valid, self.disks), [])

    def test_reject_missing_or_mounted_disk(self):
        invalid = {"disk": "/dev/sda", "desktop": "KDE Plasma", "hostname": "home-pc", "username": "alex", "timezone": "Europe/Berlin"}
        self.assertTrue(validate_plan(invalid, self.disks))

    def test_reject_bad_identity(self):
        bad = {"disk": "/dev/nvme0n1", "desktop": "GNOME", "hostname": "bad host!", "username": "Root Name", "timezone": "Europe/Berlin"}
        self.assertEqual(len(validate_plan(bad, self.disks)), 2)


if __name__ == "__main__":
    unittest.main()
