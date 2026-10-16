import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tui import Wizard, example_disks, main


class NoopScreen:
    pass


class TuiTests(unittest.TestCase):
    def setUp(self):
        with patch("tui.preflight", return_value={}), patch("tui.system_timezone", return_value="UTC"):
            self.wizard = Wizard(NoopScreen(), demo=True)

    def test_demo_disks_safe(self):
        items = example_disks()
        self.assertEqual(len(items), 3)
        self.assertTrue(items[0]["eligible"])
        self.assertFalse(items[1]["eligible"])
        self.assertFalse(items[2]["eligible"])

    def test_disk_selection_and_next(self):
        self.wizard.step = 2
        self.wizard.disk_cursor = 0
        self.wizard.select_disk(go_next=True)
        self.assertEqual(self.wizard.plan["disk"], "/dev/vda")
        self.assertEqual(self.wizard.step, 3)

    def test_cannot_select_removable(self):
        self.wizard.step = 2
        self.wizard.disk_cursor = 1
        self.wizard.select_disk(go_next=True)
        self.assertEqual(self.wizard.plan["disk"], "")
        self.assertEqual(self.wizard.step, 2)
        self.assertTrue(self.wizard.message_is_error)

    def test_cannot_skip_disk_choice(self):
        self.wizard.step = 2
        self.wizard.next_step()
        self.assertEqual(self.wizard.step, 2)
        self.assertTrue(self.wizard.message_is_error)

    def test_reject_bad_identity_on_next(self):
        self.wizard.step = 4
        self.wizard.plan.update(disk="/dev/vda", hostname="bad host")
        self.wizard.next_step()
        self.assertEqual(self.wizard.step, 4)

    def test_demo_does_not_export(self):
        self.wizard.step = 5
        with patch("tui.export_plan") as mock_export, patch.object(self.wizard, "popup") as mock_popup:
            self.wizard.next_step()
            mock_export.assert_not_called()
            mock_popup.assert_called_once()

    def test_reject_non_tty(self):
        with patch("tui.sys.stdin.isatty", return_value=False):
            self.assertEqual(main([]), 2)


if __name__ == "__main__":
    unittest.main()
