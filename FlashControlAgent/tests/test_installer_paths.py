# -*- coding: utf-8 -*-

from __future__ import print_function

import os
import sys
import shutil
import tempfile
import unittest

AGENT_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AGENT_DIRECTORY not in sys.path:
    sys.path.insert(0, AGENT_DIRECTORY)

import installer


class InstallerPathTests(unittest.TestCase):
    def test_queue_path_lives_outside_install_dir(self):
        install_dir = r"C:\ProgramData\FlashControlAgent"
        expected_state_dir = r"C:\ProgramData\FlashControlAgentState"
        expected_queue_path = r"C:\ProgramData\FlashControlAgentState\FlashControlAgent.queue.db"

        self.assertEqual(installer.state_dir(install_dir), expected_state_dir)
        self.assertEqual(installer.queue_path(install_dir), expected_queue_path)

    def test_queue_path_follows_custom_install_dir_parent(self):
        install_dir = r"D:\Apps\FlashControlAgent"
        expected_state_dir = r"D:\Apps\FlashControlAgentState"
        expected_queue_path = r"D:\Apps\FlashControlAgentState\FlashControlAgent.queue.db"

        self.assertEqual(installer.state_dir(install_dir), expected_state_dir)
        self.assertEqual(installer.queue_path(install_dir), expected_queue_path)

    def test_migrate_queue_file_moves_existing_cache(self):
        root = tempfile.mkdtemp(prefix="flashcontrol-installer-")
        try:
            install_dir = os.path.join(root, "FlashControlAgent")
            os.makedirs(install_dir)
            old_queue_path = os.path.join(install_dir, "FlashControlAgent.queue.db")
            with open(old_queue_path, "w", encoding="utf-8") as handle:
                handle.write("queued-event")

            installer.migrate_queue_file(install_dir)

            new_queue_path = installer.queue_path(install_dir)
            self.assertFalse(os.path.exists(old_queue_path))
            self.assertTrue(os.path.exists(new_queue_path))
            with open(new_queue_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "queued-event")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
