from __future__ import annotations

import os

from agent.job import job, step
from agent.server import Server

PROXYSQL_WRITER = "/usr/local/sbin/proxysql-configuratie"
ADMIN_DEFAULTS = "/etc/proxysql-admin-tijdelijk.cnf"


class ProxySQL(Server):
    def __init__(self):
        super().__init__()

        self.proxysql_admin_password = self.config.get("proxysql_admin_password")

    def proxysql_execute(self, command):
        command = (
            "mysql -h 127.0.0.1 -P 6032 "
            f"-u frappe -p{self.proxysql_admin_password} "
            f"--disable-column-names -e '{command}'"
        )
        return self.execute(command)

    @job("Configure ProxySQL")
    def configure_job(self, config: str, admin_credentials: str):
        """Impertio C4: write the gateway configuration that Press rendered and load it into the runtime.

        Press is the source; this machine only receives the finished file. The old file is kept
        next to the new one so a change can be undone by hand, and the runtime is loaded from the
        configuration file itself, so that what runs equals what was written."""
        self.write_config(config)
        self.load_config(admin_credentials)

    @step("Write ProxySQL Configuration")
    def write_config(self, config: str):
        """Hand the rendered configuration to the small root helper that places it.

        The file carries the admin password and the password of every site, so it stays 0600 and owned by
        proxysql; this agent runs as an unprivileged user and cannot write it. One narrow sudo rule covers
        exactly that helper (measured on the application server on 29-08: without it the job fails with
        PermissionError on /etc/proxysql.cnf). The configuration goes in on stdin, never through argv,
        because everything on the command line ends up in the process list and in the job log."""
        return self.execute(f"sudo -n {PROXYSQL_WRITER}", input=config)

    @step("Load ProxySQL Configuration")
    def load_config(self, admin_credentials: str):
        """Read the file into the runtime and save it to the internal database, so a restart keeps it.

        The configuration Press sends is the whole truth, so the tables are emptied before they are filled.
        The admin credentials go through a 0600 defaults file, never through the command line,
        because everything on the command line ends up in the process list and in the job log."""
        gebruiker, _, wachtwoord = admin_credentials.partition(":")
        defaults = ADMIN_DEFAULTS
        commands = [
            # FROM CONFIG only adds and overwrites; it never removes. Without emptying the tables first, a user
            # or a node that Press no longer sends keeps its access forever (measured on the gateway, 29-08-2026).
            # The emptying happens in the memory tables, so the running gateway notices nothing until
            # LOAD ... TO RUNTIME below; there is no moment without users or servers.
            "DELETE FROM mysql_users",
            "DELETE FROM mysql_servers",
            "DELETE FROM mysql_galera_hostgroups",
            "LOAD MYSQL VARIABLES FROM CONFIG",
            "LOAD MYSQL SERVERS FROM CONFIG",
            "LOAD MYSQL USERS FROM CONFIG",
            "LOAD MYSQL VARIABLES TO RUNTIME",
            "LOAD MYSQL SERVERS TO RUNTIME",
            "LOAD MYSQL USERS TO RUNTIME",
            "SAVE MYSQL VARIABLES TO DISK",
            "SAVE MYSQL SERVERS TO DISK",
            "SAVE MYSQL USERS TO DISK",
        ]
        fd = os.open(defaults, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(f"[client]\nuser={gebruiker}\npassword={wachtwoord}\nhost=127.0.0.1\nport=6032\n")
            for command in commands:
                self.execute(f"mysql --defaults-file={defaults} --disable-column-names -e '{command}'")
        finally:
            if os.path.exists(defaults):
                os.unlink(defaults)
        return {"opdrachten": len(commands)}

    @job("Add User to ProxySQL")
    def add_user_job(
        self,
        username: str,
        password: str,
        database: str,
        max_connections: int,
        backend: dict,
    ):
        self.add_backend(backend)
        self.add_user(username, password, database, max_connections, backend)

    @job("Add Backend to ProxySQL")
    def add_backend_job(self, backend):
        self.add_backend(backend)

    @step("Add Backend to ProxySQL")
    def add_backend(self, backend):
        backend_id = backend["id"]
        backend_ip = backend["ip"]
        if self.proxysql_execute(f"SELECT 1 from mysql_servers where hostgroup_id = {backend_id}")["output"]:
            return
        commands = [
            (f'INSERT INTO mysql_servers (hostgroup_id, hostname) VALUES ({backend_id}, "{backend_ip}")'),
            "LOAD MYSQL SERVERS TO RUNTIME",
            "SAVE MYSQL SERVERS TO DISK",
        ]
        for command in commands:
            self.proxysql_execute(command)

    @step("Add User to ProxySQL")
    def add_user(self, username: str, password: str, database: str, max_connections: int, backend: dict):
        backend_id = backend["id"]
        commands = [
            (
                "INSERT INTO mysql_users ( "
                "username, password, default_hostgroup, default_schema, "
                "use_ssl, max_connections) "
                "VALUES ( "
                f'"{username}", "{password}", {backend_id}, "{database}", '
                f"1, {max_connections})"
            ),
            "LOAD MYSQL USERS TO RUNTIME",
            "SAVE MYSQL USERS FROM RUNTIME",
            "SAVE MYSQL USERS TO DISK",
        ]
        for command in commands:
            self.proxysql_execute(command)

    @job("Remove User from ProxySQL")
    def remove_user_job(self, username):
        self.remove_user(username)

    @step("Remove User from ProxySQL")
    def remove_user(self, username):
        commands = [
            f'DELETE FROM mysql_users WHERE username = "{username}"',
            "LOAD MYSQL USERS TO RUNTIME",
            "SAVE MYSQL USERS FROM RUNTIME",
            "SAVE MYSQL USERS TO DISK",
        ]
        for command in commands:
            self.proxysql_execute(command)
