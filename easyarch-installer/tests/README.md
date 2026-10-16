# EasyArch tests

Run `python3 -m unittest discover -s tests -v`.

These tests exercise data validation, TUI state, confirmation barriers, preview mode and
command generation. **They do not test real disk partitioning, pacstrap, bootloader
installation or successful boot of a VM.** End-to-end tests in disposable OVMF/UEFI
VMs are required before deployment.
