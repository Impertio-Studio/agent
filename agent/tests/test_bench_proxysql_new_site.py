from __future__ import annotations

import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.bench import Bench


def _bench(proxysql_users: bool) -> Bench:
    bench = Bench.__new__(Bench)
    bench.name = "bench-test"
    # bench_new_site is a @step: the decorator records the step on the server's job.
    bench.server = SimpleNamespace(
        config={"proxysql_users": proxysql_users}, step_record=MagicMock(), job_record=MagicMock()
    )
    return bench


class TestBenchNewSiteThroughProxySQL(unittest.TestCase):
    """Impertio C4: with ProxySQL in front of the databases, `bench new-site` only works when
    the temporary user and the site user are registered in ProxySQL before bench runs."""

    def _run(self, proxysql_users: bool):
        bench = _bench(proxysql_users)
        calls: list[tuple[str, str, str | None]] = []
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    Bench, "create_mariadb_user", return_value=("_abc123", "_abc123_limited", "tmp-pw")
                )
            )
            stack.enter_context(
                patch.object(
                    Bench, "drop_mariadb_user", side_effect=lambda *a, **k: calls.append(("drop", "", None))
                )
            )
            stack.enter_context(patch.object(Bench, "get_random_string", return_value="site-pw"))
            stack.enter_context(
                patch.object(
                    Bench,
                    "execute",
                    side_effect=lambda cmd, input=None, **k: calls.append(("execute", cmd, input)),
                )
            )
            stack.enter_context(
                patch.object(
                    Bench, "docker_execute", side_effect=lambda cmd, **k: calls.append(("docker", cmd, None))
                )
            )
            bench.bench_new_site("site.test", "root-pw", "admin-pw")
        return calls

    def test_without_proxysql_nothing_changes(self):
        calls = self._run(proxysql_users=False)
        self.assertEqual([c[0] for c in calls], ["docker", "drop"])
        self.assertNotIn("--db-password", calls[0][1])

    def test_users_are_registered_before_bench_new_site_and_temp_user_removed_after(self):
        calls = self._run(proxysql_users=True)
        self.assertEqual([c[0] for c in calls], ["execute", "execute", "docker", "drop", "execute"])
        temp, site, docker, _drop, cleanup = calls
        self.assertEqual(temp[1], "/usr/local/sbin/proxysql-site-gebruiker --stdin")
        self.assertEqual(json.loads(temp[2]), {"db_user": "_abc123_limited", "db_password": "tmp-pw"})
        self.assertEqual(json.loads(site[2]), {"db_user": "_abc123", "db_password": "site-pw"})
        self.assertIn("--db-password site-pw ", docker[1])
        self.assertIn("--db-name _abc123 site.test", docker[1])
        self.assertEqual(cleanup[1], "/usr/local/sbin/proxysql-site-gebruiker --verwijder _abc123_limited")

    def test_no_password_reaches_the_helper_through_argv(self):
        for kind, cmd, _ in self._run(proxysql_users=True):
            if kind == "execute":
                self.assertNotIn("pw", cmd)
