# -*- coding: utf-8 -*-

from __future__ import print_function

import argparse
import os
import sys
import shutil
import tempfile
import unittest
import uuid

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

    def _args(self, **overrides):
        values = {
            "server_url": "https://main.example/api/v1/observations",
            "interval_seconds": 3600,
            "request_timeout_seconds": 30,
            "machine_token": "dev-token",
            "agent_id": "",
            "heartbeat_url": "",
            "ca_file": "",
            "client_cert_file": "",
            "client_key_file": "",
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_install_config_writes_machine_credentials_and_stable_id_path(self):
        install_dir = r"C:\ProgramData\FlashControlAgent"
        config = installer.build_agent_config(self._args(), install_dir)
        self.assertEqual(config["server_url"], "https://main.example/api/v1/observations")
        self.assertEqual(config["machine_token"], "dev-token")
        self.assertEqual(
            config["agent_id_file"],
            r"C:\ProgramData\FlashControlAgentState\FlashControlAgent.id",
        )
        self.assertEqual(
            config["machine_token_file"],
            r"C:\ProgramData\FlashControlAgentState\FlashControlAgent.token",
        )

    def test_bundled_collector_url_is_used_when_cli_is_empty(self):
        install_dir = r"C:\ProgramData\FlashControlAgent"
        config = installer.build_agent_config(
            self._args(server_url="", machine_token=""),
            install_dir,
            {"server_url": "https://site.example/api/v1/observations"},
        )
        self.assertEqual(config["server_url"], "https://site.example/api/v1/observations")
        self.assertEqual(config["machine_token"], "")

    def test_migrate_agent_id_file_moves_existing_identity(self):
        root = tempfile.mkdtemp(prefix="flashcontrol-agent-id-")
        try:
            install_dir = os.path.join(root, "FlashControlAgent")
            os.makedirs(install_dir)
            old_path = os.path.join(install_dir, "FlashControlAgent.id")
            agent_id = str(uuid.uuid4())
            with open(old_path, "w", encoding="utf-8") as handle:
                handle.write(agent_id + "\n")

            installer.migrate_agent_id_file(install_dir)

            new_path = installer.agent_id_file_path(install_dir)
            self.assertFalse(os.path.exists(old_path))
            with open(new_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read().strip(), agent_id)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
