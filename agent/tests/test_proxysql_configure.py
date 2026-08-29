from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.proxysql import ProxySQL


class TestConfigureProxySQL(unittest.TestCase):
    """Impertio C4: the agent writes what Press rendered and loads it, without secrets on the command line."""

    def _proxysql(self):
        p = ProxySQL.__new__(ProxySQL)
        p.directory = tempfile.gettempdir()
        # step_record en job_record zijn eigenschappen die naar de server wijzen; die vullen we daar
        p.server = SimpleNamespace(config={}, step_record=MagicMock(), job_record=MagicMock())
        return p

    def test_write_config_writes_atomically_and_keeps_the_previous_file(self):
        p = self._proxysql()
        with tempfile.TemporaryDirectory() as d:
            pad = os.path.join(d, "proxysql.cnf")
            with open(pad, "w") as f:
                f.write("oude configuratie")
            with ExitStack() as stack:
                stack.enter_context(patch("agent.proxysql.PROXYSQL_CONFIG", pad))
                stack.enter_context(patch("agent.proxysql.os.chmod"))
                stack.enter_context(patch("agent.proxysql.shutil.chown"))
                uit = ProxySQL.write_config.__wrapped__(p, "nieuwe configuratie")
            with open(pad) as f:
                self.assertEqual(f.read(), "nieuwe configuratie")
            with open(pad + ".vorige") as f:
                self.assertEqual(f.read(), "oude configuratie", "de vorige configuratie moet bewaard blijven")
            self.assertFalse(os.path.exists(pad + ".nieuw"), "het tijdelijke bestand moet zijn hernoemd")
            self.assertEqual(uit["bytes"], len("nieuwe configuratie"))

    def test_load_config_uses_a_defaults_file_and_removes_it(self):
        p = self._proxysql()
        commands: list[str] = []
        gemaakt: dict = {}

        def nep_execute(command, *a, **k):
            commands.append(command)
            # het bestand moet bestaan terwijl de opdrachten draaien
            gemaakt["bestond"] = os.path.exists("/etc/proxysql-admin-tijdelijk.cnf")
            return {"output": ""}

        with ExitStack() as stack:
            stack.enter_context(patch.object(ProxySQL, "execute", side_effect=nep_execute))
            geopend = {}
            echte_open = os.open  # vastpakken voordat we patchen, anders roept de nep zichzelf aan

            def nep_open(pad, vlaggen, modus=0o777):
                geopend["pad"], geopend["modus"] = pad, modus
                return echte_open(
                    os.path.join(tempfile.gettempdir(), "proxysql-admin-toets.cnf"), vlaggen, modus
                )

            stack.enter_context(patch("agent.proxysql.os.open", side_effect=nep_open))
            stack.enter_context(patch("agent.proxysql.os.path.exists", return_value=True))
            stack.enter_context(patch("agent.proxysql.ADMIN_DEFAULTS", "/etc/proxysql-admin-tijdelijk.cnf"))
            verwijderd = []
            stack.enter_context(patch("agent.proxysql.os.unlink", side_effect=verwijderd.append))
            ProxySQL.load_config.__wrapped__(p, "admin:GEHEIM")

        self.assertEqual(geopend["modus"], 0o600, "het aanmeldbestand moet 600 zijn")
        self.assertEqual(
            verwijderd, ["/etc/proxysql-admin-tijdelijk.cnf"], "het aanmeldbestand moet na afloop weg zijn"
        )
        self.assertEqual(
            len(commands), 9, "drie keer laden uit config, drie keer naar runtime, drie keer opslaan"
        )
        for c in commands:
            self.assertNotIn("GEHEIM", c, "het wachtwoord mag niet in de opdrachtregel staan")
            self.assertIn("--defaults-file=", c)
        self.assertIn("LOAD MYSQL SERVERS FROM CONFIG", " ".join(commands))
        self.assertIn("SAVE MYSQL USERS TO DISK", " ".join(commands))
