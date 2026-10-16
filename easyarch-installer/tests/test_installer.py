import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer import (Installer, InstallError, DISPLAY_MANAGER, DESKTOP_PACKAGES,
                       partition_path, preinstall_checks, strict_timezone)

PLAN = {'disk': '/dev/vda', 'desktop': 'KDE Plasma', 'hostname': 'archbox',
        'username': 'alex', 'timezone': 'Etc/UTC'}

class InstallerTests(unittest.TestCase):
    def test_partition_path(self):
        self.assertEqual(partition_path('/dev/sda', 2), '/dev/sda2')
        self.assertEqual(partition_path('/dev/nvme0n1', 1), '/dev/nvme0n1p1')
        self.assertEqual(partition_path('/dev/mmcblk0', 2), '/dev/mmcblk0p2')
        self.assertEqual(partition_path('/dev/vda', 2), '/dev/vda2')

    def test_preview_backend_executes_no_destructive_programs(self):
        phases = []
        backend = Installer(PLAN, {}, expected_bytes=None, dry_run=True,
                            progress=lambda msg, idx, total, log: phases.append(msg))
        with patch('installer.subprocess.Popen', side_effect=AssertionError('Unexpected destructive process')), \
             patch('installer.subprocess.run', side_effect=AssertionError('Unexpected process')), \
             patch('installer.graphics_packages', return_value=['mesa']), \
             patch('installer.cpu_microcode', return_value='amd-ucode'), \
             patch('installer.preinstall_checks', side_effect=AssertionError('Unexpected preflight')):
            self.assertIn('NOTHING changed', backend.run_install())
        self.assertEqual(backend.step, 12)
        self.assertEqual(len([v for v in phases if v]), 13)  # banner + phases
        self.assertFalse(backend.did_partition)
        self.assertIsNone(backend.log_path)

    def test_default_run_refused_outside_archiso(self):
        backend = Installer(PLAN, {'root': 'testrootpass', 'user': 'testuserpass'},
                            expected_bytes=None, dry_run=False)
        with patch('installer.os.geteuid', return_value=0), \
             patch('installer.Path.exists', return_value=False):
            with self.assertRaisesRegex(InstallError, 'Live ArchISO'):
                backend.run_install()

    def test_kde_uses_plasma_login_manager_not_sddm(self):
        self.assertEqual(DISPLAY_MANAGER['KDE Plasma'], 'plasmalogin')
        self.assertIn('plasma-meta', DESKTOP_PACKAGES['KDE Plasma'])
        self.assertNotIn('sddm', DESKTOP_PACKAGES['KDE Plasma'])

    def test_timezone_traversal_rejected(self):
        self.assertFalse(strict_timezone('../../etc/passwd'))

    def test_password_never_in_argv_dry_run(self):
        secrets = {'root': 'passwordABC123', 'user': 'passwordABC456'}
        backend = Installer(PLAN, secrets, expected_bytes=None, dry_run=True)
        with patch('installer.graphics_packages', return_value=['mesa']), \
             patch('installer.cpu_microcode', return_value=None):
            backend.run_install()
        self.assertEqual(secrets, {})  # cleared on exit

    def test_run_error_reports_command_without_password(self):
        backend = Installer(PLAN, {}, expected_bytes=None, dry_run=False)
        bad = MagicMock()
        bad.returncode = 1
        with patch('installer.subprocess.run', return_value=bad):
            with self.assertRaises(InstallError) as ctx:
                backend.run(['arch-chroot', '/mnt/easyarch', 'chpasswd'], input_text='root:SUPERSECRET\n')
        self.assertNotIn('SUPERSECRET', str(ctx.exception))

if __name__ == '__main__':
    unittest.main()

# Confirmation tests (no real curses terminal or block devices required).
from tui import Wizard

class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        with patch('tui.preflight', return_value={}), patch('tui.system_timezone', return_value='Etc/UTC'):
            self.wizard = Wizard(object(), install_enabled=True)
        self.wizard.plan = dict(PLAN)
        self.wizard.disks = [{'path': '/dev/vda', 'model': 'Test blank disk', 'size': '64.0 GiB'}]
        self.wizard.passwords = {'user': 'longuserpass', 'root': 'longrootpass'}
        self.wizard.selected_bytes = 64 * 1024 ** 3

    def test_first_confirmation_must_match_disk_path_exactly(self):
        with patch('tui.preinstall_checks'), patch.object(self.wizard, 'input_popup', return_value='ERASE /dev/sda'), \
             patch.object(self.wizard, 'do_install') as install, patch.object(self.wizard, 'popup'):
            self.wizard.begin_real_install()
            install.assert_not_called()

    def test_second_confirmation_must_say_install(self):
        with patch('tui.preinstall_checks'), patch.object(self.wizard, 'input_popup',
             side_effect=['ERASE /dev/vda', 'NOT YET']), patch.object(self.wizard, 'do_install') as install, \
             patch.object(self.wizard, 'popup'):
            self.wizard.begin_real_install()
            install.assert_not_called()

    def test_full_two_step_confirmation_enables_install(self):
        with patch('tui.preinstall_checks'), patch.object(self.wizard, 'input_popup',
             side_effect=['ERASE /dev/vda', 'INSTALL']), patch.object(self.wizard, 'do_install') as install:
            self.wizard.begin_real_install()
            install.assert_called_once_with(dry_run=False)
