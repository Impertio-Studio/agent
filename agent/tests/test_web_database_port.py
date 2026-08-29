from __future__ import annotations

import unittest

from agent.web import database_port


class TestDatabasePort(unittest.TestCase):
    """Impertio C4: physical backup and restore reach the database on the port Press sends."""

    def test_port_from_press_payload(self):
        self.assertEqual(database_port({"private_ip": "10.0.1.3", "db_port": 3316}), 3316)

    def test_port_as_string_is_accepted(self):
        self.assertEqual(database_port({"db_port": "6033"}), 6033)

    def test_older_press_without_port_means_default(self):
        self.assertEqual(database_port({"private_ip": "10.0.1.3"}), 3306)
        self.assertEqual(database_port({"db_port": None}), 3306)
