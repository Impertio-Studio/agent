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

    def test_write_config_goes_through_the_root_helper_on_stdin(self):
        """Het bestand is 0600 van proxysql; de agent draait onbevoegd en geeft de configuratie door.

        Gemeten op de applicatiemachine 29-08: zonder deze weg faalt de baan met PermissionError op
        /etc/proxysql.cnf, want de agent draait als frappe."""
        p = self._proxysql()
        gezien = {}

        def nep_execute(command, *a, **k):
            gezien["command"] = command
            gezien["input"] = k.get("input")
            return {"output": ""}

        with patch.object(ProxySQL, "execute", side_effect=nep_execute):
            ProxySQL.write_config.__wrapped__(p, "nieuwe configuratie met GEHEIM erin")

        self.assertIn("sudo -n /usr/local/sbin/proxysql-configuratie", gezien["command"])
        self.assertEqual(gezien["input"], "nieuwe configuratie met GEHEIM erin")
        self.assertNotIn("GEHEIM", gezien["command"], "de configuratie mag niet in de opdrachtregel staan")

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
            len(commands),
            12,
            "drie keer legen, drie keer laden uit config, drie keer naar runtime, drie keer opslaan",
        )
        for c in commands:
            self.assertNotIn("GEHEIM", c, "het wachtwoord mag niet in de opdrachtregel staan")
            self.assertIn("--defaults-file=", c)
        self.assertIn("LOAD MYSQL SERVERS FROM CONFIG", " ".join(commands))
        self.assertIn("SAVE MYSQL USERS TO DISK", " ".join(commands))

    def test_load_config_empties_the_tables_before_it_fills_them(self):
        """Zonder legen houdt een gebruiker die Press niet meer stuurt zijn toegang (gemeten op de gateway)."""
        p = self._proxysql()
        commands: list[str] = []

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(ProxySQL, "execute", side_effect=lambda c, *a, **k: commands.append(c))
            )
            echte_open = os.open

            def nep_open(pad, vlaggen, modus=0o777):
                return echte_open(
                    os.path.join(tempfile.gettempdir(), "proxysql-admin-toets.cnf"), vlaggen, modus
                )

            stack.enter_context(patch("agent.proxysql.os.open", side_effect=nep_open))
            stack.enter_context(patch("agent.proxysql.os.path.exists", return_value=True))
            stack.enter_context(patch("agent.proxysql.os.unlink"))
            ProxySQL.load_config.__wrapped__(p, "admin:GEHEIM")

        for tabel in ("mysql_users", "mysql_servers", "mysql_galera_hostgroups"):
            legen = next(i for i, c in enumerate(commands) if f"DELETE FROM {tabel}" in c)
            laden = next(i for i, c in enumerate(commands) if "FROM CONFIG" in c)
            naar_runtime = next(i for i, c in enumerate(commands) if "TO RUNTIME" in c)
            self.assertLess(legen, laden, f"{tabel} moet leeg zijn voordat de configuratie erin gaat")
            self.assertLess(
                legen, naar_runtime, f"{tabel} mag pas naar de runtime nadat hij opnieuw gevuld is"
            )
