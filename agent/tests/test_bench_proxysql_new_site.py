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

    def test_site_user_is_registered_before_bench_new_site(self):
        calls = self._run(proxysql_users=True)
        self.assertEqual([c[0] for c in calls], ["execute", "docker", "drop"])
        site, docker, _drop = calls
        self.assertEqual(site[1], "/usr/local/sbin/proxysql-site-gebruiker --stdin")
        self.assertEqual(json.loads(site[2]), {"db_user": "_abc123", "db_password": "site-pw"})
        self.assertIn("--db-password site-pw ", docker[1])
        self.assertIn("--db-name _abc123 site.test", docker[1])

    def test_no_password_reaches_the_helper_through_argv(self):
        for kind, cmd, _ in self._run(proxysql_users=True):
            if kind == "execute":
                self.assertNotIn("pw", cmd)


class TestTemporaryUserThroughProxySQL(unittest.TestCase):
    """Impertio C4: the temporary root-like user is registered in ProxySQL when it is created
    and removed when it is dropped, so new site, restore and drop site all route through."""

    def _bench(self, proxysql_users: bool) -> Bench:
        bench = _bench(proxysql_users)
        bench.host = "172.17.0.1"
        bench.db_port = 6033
        bench.sites_directory = "/tmp/bench"
        return bench

    def test_create_registers_and_drop_unregisters(self):
        bench = self._bench(True)
        calls: list[tuple[str, str | None]] = []
        with ExitStack() as stack:
            stack.enter_context(patch.object(Bench, "get_random_string", return_value="tmp-pw"))
            stack.enter_context(
                patch.object(
                    Bench, "execute", side_effect=lambda cmd, input=None, **k: calls.append((cmd, input))
                )
            )
            database, user, _password = bench.create_mariadb_user("site.test", "root-pw")
            bench.drop_mariadb_user("site.test", "root-pw", database)
        self.assertEqual(user, f"{database}_limited")
        registered = [c for c in calls if c[0] == "/usr/local/sbin/proxysql-site-gebruiker --stdin"]
        self.assertEqual(json.loads(registered[0][1]), {"db_user": user, "db_password": "tmp-pw"})
        self.assertIn((f"/usr/local/sbin/proxysql-site-gebruiker --verwijder {user}", None), calls)
        # the registration happens after the user exists on the database, the removal after it is dropped
        created_at = next(i for i, c in enumerate(calls) if "CREATE OR REPLACE USER" in c[0])
        self.assertLess(created_at, calls.index(registered[0]))

    def test_without_proxysql_no_helper_calls(self):
        bench = self._bench(False)
        calls: list[tuple[str, str | None]] = []
        with ExitStack() as stack:
            stack.enter_context(patch.object(Bench, "get_random_string", return_value="tmp-pw"))
            stack.enter_context(
                patch.object(
                    Bench, "execute", side_effect=lambda cmd, input=None, **k: calls.append((cmd, input))
                )
            )
            database, _user, _password = bench.create_mariadb_user("site.test", "root-pw")
            bench.drop_mariadb_user("site.test", "root-pw", database)
        self.assertFalse([c for c in calls if "proxysql-site-gebruiker" in c[0]])
