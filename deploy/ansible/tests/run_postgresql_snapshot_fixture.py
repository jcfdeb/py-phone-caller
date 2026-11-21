"""Isolated PostgreSQL recovery rehearsal, with no TCP listener or system services.

Requires local initdb/postgres/pg_ctl/psql/pg_dump/pg_restore binaries. All data
is created under tests/.runtime and the child server is stopped in finally.
This is not a Debian/Ubuntu systemd-host qualification.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ANSIBLE = Path(__file__).resolve().parents[1]
HELPER = ANSIBLE / "roles/stack_lifecycle/files/stack_snapshot.py"


class PostgreSQLSnapshotFixture(unittest.TestCase):
    def test_real_dump_verified_snapshot_and_database_restore(self):
        self.assertNotEqual(os.geteuid(), 0, "Run this fixture as a non-root user")
        for name in ("initdb", "postgres", "pg_ctl", "psql", "pg_dump", "pg_restore"):
            self.assertIsNotNone(shutil.which(name), f"Install the local PostgreSQL test prerequisite: {name}")
        runtime = ANSIBLE / "tests/.runtime"
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="pg-recovery-", dir=runtime) as temporary:
            root = Path(temporary)
            data = root / "cluster"
            environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
            environment.update(PGHOST="/proc/self/cwd/s", PGPORT="55432", PGUSER="snapshot_fixture",
                               PGDATABASE="postgres", PGCONNECT_TIMEOUT="2")
            initialized = subprocess.run(
                ["initdb", "-D", str(data), "--auth=trust", "--no-locale", "-U", "snapshot_fixture"],
                env=environment, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            (data / "s").mkdir(mode=0o700)

            def command(arguments, check=True):
                result = subprocess.run(arguments, cwd=data, env=environment,
                                        capture_output=True, text=True, timeout=30)
                if check:
                    self.assertEqual(result.returncode, 0, result.stderr)
                return result

            with (root / "postgres.log").open("w") as log:
                server = subprocess.Popen(
                    ["postgres", "-D", str(data), "-k", "/proc/self/cwd/s", "-p", "55432",
                     "-c", "listen_addresses=", "-c", "max_connections=10"],
                    cwd=data, env=environment, stdout=log, stderr=subprocess.STDOUT,
                )
                try:
                    ready = False
                    for _ in range(80):
                        if server.poll() is not None:
                            break
                        if command(["psql", "-XAt", "-c", "SELECT 1"], check=False).returncode == 0:
                            ready = True
                            break
                        time.sleep(0.1)
                    self.assertTrue(ready, "The isolated PostgreSQL fixture failed to start")
                    self.assertEqual(command(["psql", "-XAt", "-c", "SHOW listen_addresses"]).stdout.strip(), "")
                    command(["psql", "-X", "-v", "ON_ERROR_STOP=1", "-c",
                             "CREATE TABLE recovery_probe (id integer PRIMARY KEY, value text); "
                             "INSERT INTO recovery_probe VALUES (1, 'preserved');"])
                    dumps = root / "dumps"
                    dumps.mkdir(mode=0o700)
                    configuration = root / "configuration"
                    configuration.mkdir(mode=0o700)
                    (configuration / "settings.toml").write_text('release = "fixture-v1"\n')
                    plan = root / "plan.json"
                    plan.write_text(json.dumps({
                        "paths": [str(configuration), str(dumps)],
                        "metadata": {"kind": "full", "schema_id": "fixture-v1", "release_id": "fixture-v1",
                                     "units": [], "postgresql": ["postgres"]},
                    }))
                    command(["pg_dump", "--format=custom", "--dbname=postgres", "--file", str(dumps / "postgres.dump")])
                    snapshot = root / "snapshot"
                    helper = [sys.executable, str(HELPER)]
                    command(helper + ["create", "--plan", str(plan), "--destination", str(snapshot)])
                    command(["psql", "-X", "-v", "ON_ERROR_STOP=1", "-c",
                             "UPDATE recovery_probe SET value='after-upgrade'; INSERT INTO recovery_probe VALUES (2, 'new');"])
                    (configuration / "settings.toml").write_text('release = "fixture-v2"\n')
                    (dumps / "postgres.dump").write_bytes(b"damaged staging copy")
                    command(helper + ["verify", "--snapshot", str(snapshot), "--plan", str(plan)])
                    command(helper + ["restore", "--snapshot", str(snapshot), "--plan", str(plan)])
                    command(["pg_restore", "--clean", "--if-exists", "--exit-on-error", "--single-transaction",
                             "--dbname=postgres", str(dumps / "postgres.dump")])
                    restored = command(["psql", "-XAt", "-c", "SELECT id,value FROM recovery_probe ORDER BY id"])
                    self.assertEqual(restored.stdout.strip(), "1|preserved")
                    self.assertEqual((configuration / "settings.toml").read_text(), 'release = "fixture-v1"\n')
                    self.assertEqual(snapshot.stat().st_mode & 0o777, 0o700)
                finally:
                    if server.poll() is None:
                        stopped = command(["pg_ctl", "-D", str(data), "-m", "fast", "-w", "stop"], check=False)
                        self.assertEqual(stopped.returncode, 0, stopped.stderr)
                    server.wait(timeout=15)
                    self.assertIsNotNone(server.returncode)


if __name__ == "__main__":
    unittest.main()