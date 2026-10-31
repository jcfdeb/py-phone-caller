"""Offline Python-role contracts; never loads an inventory or starts services."""

import ast
import base64
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import threading
import tomllib
import unittest

from ansible.plugins.filter.core import FilterModule
from jinja2 import Environment, StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import yaml


ANSIBLE = Path(__file__).resolve().parents[1]
ROOT = ANSIBLE.parents[1]
ROLE = ANSIBLE / "roles/deploy_py-phone-caller"


def load(path):
    return yaml.safe_load(path.read_text())


def environment(native=False):
    env = (NativeEnvironment if native else Environment)(undefined=StrictUndefined)
    default_filter = env.filters["default"]
    env.filters.update(FilterModule().filters())
    env.filters["default"] = default_filter
    env.filters["to_json"] = json.dumps
    return env


def evaluate(expression, values):
    return environment(native=True).from_string(expression).render(values)


def task_entries(entries, inherited_when=()):
    for entry in entries:
        conditions = entry.get("when", [])
        if isinstance(conditions, str):
            conditions = [conditions]
        conditions = [*inherited_when, *conditions]
        if "block" in entry:
            for section in ("block", "rescue", "always"):
                yield from task_entries(entry.get(section, []), conditions)
        else:
            result = copy.deepcopy(entry)
            if inherited_when:
                result["when"] = conditions
            yield result


def task(filename, name, role=ROLE):
    return next(item for item in task_entries(load(role / "tasks" / filename)) if item.get("name") == name)


class GatewayAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def respond(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):
        self.server.calls.append(("GET", self.path, None))
        if self.server.failure == self.path:
            self.respond(500, {"error": "Synthetic lookup failure"})
        elif self.path == "/admin/realms":
            self.respond(200, [{"realm": "synthetic"}])
        elif self.path == "/admin/realms/synthetic/roles":
            self.respond(200, [{"name": f"alert-{name}", "id": name}
                               for name in ("admin", "operator", "viewer")])
        elif self.path == "/admin/realms/synthetic/clients":
            self.respond(200, [{"clientId": f"py-phone-caller-{name}", "id": name}
                               for name in ("ui", "m2m")])
        elif self.path == "/admin/realms/synthetic/clients/m2m/service-account-user":
            self.respond(200, {"id": "service-account"})
        elif self.path == "/admin/realms/synthetic/users":
            self.respond(200, [{"username": f"{name}_user", "id": name}
                               for name in ("admin", "operator", "viewer")])
        else:
            self.respond(404, {"error": "Unexpected test endpoint"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
        self.server.calls.append(("POST", self.path, body))
        if self.path == "/realms/master/protocol/openid-connect/token":
            self.respond(200, {"access_token": "synthetic-token"})
        elif self.path == "/apisix/admin/user/login":
            self.respond(200, {"code": 0, "data": {"token": "synthetic-token"}})
        elif self.path.endswith("/role-mappings/realm"):
            self.respond(500 if self.server.failure == self.path else 204, {})
        else:
            self.respond(404, {"error": "Unexpected test endpoint"})

    def do_PUT(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        self.server.calls.append(("PUT", self.path, body))
        if self.path.startswith("/apisix/admin/routes/"):
            self.respond(200, {"code": 10000 if self.server.failure == "apisix" else 0})
        elif self.path in ("/admin/realms/synthetic/clients/ui", "/admin/realms/synthetic/clients/m2m"):
            self.respond(204, {})
        elif self.path.endswith("/reset-password"):
            self.respond(204, {})
        else:
            self.respond(404, {"error": "Unexpected test endpoint"})


class PythonRoleTests(unittest.TestCase):
    def setUp(self):
        self.defaults = load(ROLE / "defaults/main.yml")
        self.internal = load(ROLE / "vars/main.yml")
        self.config = copy.deepcopy(self.defaults["py_phone_caller_config_defaults"])

    def render_config(self, config, secret):
        return tomllib.loads(environment().from_string(
            (ROLE / "templates/settings.toml.j2").read_text()
        ).render(py_phone_caller_final_config=config, _ppc_render_secrets=secret,
                 py_phone_caller_secret_paths=self.defaults["py_phone_caller_secret_paths"]))

    def test_nested_oauth_secret_is_not_written_to_public_settings(self):
        self.config["auth"]["oauth2"]["client_secret"] = 'synthetic-"secret"\\value'
        public = self.render_config(self.config, False)
        private = self.render_config(self.config, True)
        self.assertNotIn("client_secret", public["auth"]["oauth2"])
        self.assertEqual(private["auth"]["oauth2"]["client_secret"], 'synthetic-"secret"\\value')
        combined = FilterModule().filters()["combine"](public, private, recursive=True)
        self.assertEqual(combined, self.config)

    def test_top_level_secrets_and_array_tables_round_trip(self):
        self.config["caller_sms"]["modems"] = [{"port": "/dev/ttyUSB0", "baudrate": 115200}]
        public = self.render_config(self.config, False)
        private = self.render_config(self.config, True)
        self.assertNotIn("asterisk_pass", public["commons"])
        self.assertNotIn("db_password", public["database"])
        self.assertEqual(private["database"]["db_password"], "change_me")
        self.assertEqual(public["caller_sms"]["modems"], self.config["caller_sms"]["modems"])

    def test_git_and_local_delivery_use_same_protection_filters(self):
        local = task("source.yml", "Synchronise application sources into app directory")
        git = task("source.yml", "Synchronise Git application sources into app directory")
        self.assertEqual(local["ansible.posix.synchronize"]["rsync_opts"], "{{ _ppc_app_rsync_filters }}")
        self.assertIn("_ppc_app_rsync_filters", git["ansible.builtin.command"]["argv"])
        self.assertFalse(task("source.yml", "Clone the repository")["ansible.builtin.git"]["force"])

    def test_rsync_preserves_runtime_state_and_is_unchanged_on_second_run(self):
        values = self.defaults | {"py_phone_caller_user": pwd.getpwuid(os.getuid()).pw_name,
                                  "py_phone_caller_group": str(os.getgid())}
        filters = evaluate(self.internal["_ppc_app_rsync_filters"], values)
        with tempfile.TemporaryDirectory(prefix=".role-test-", dir=ROLE) as directory:
            base = Path(directory)
            source, target = base / "source", base / "app"
            for tree in (source, target):
                for relative in ("config", "generate_audio/audio", "generate_audio/pre_trained_models",
                                 "caller_sms", "data"):
                    (tree / relative).mkdir(parents=True)
            protected = ("config/settings.toml", "config/.secrets.toml", "generate_audio/audio/a.wav",
                         "generate_audio/pre_trained_models/model.bin", "data/sms.db")
            for relative in protected:
                (target / relative).write_text("persistent")
                (source / relative).write_text("must not overwrite")
            (target / "config").chmod(0o750)
            (source / "caller_sms/main.py").write_text("version one")
            (target / "caller_sms/obsolete.py").write_text("obsolete")
            command = ["rsync", "-a", "--delete", "--out-format=<<CHANGED>>%i %n%L", *filters,
                       f"{source}/", f"{target}/"]
            first = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertIn("caller_sms/main.py", first.stdout)
            self.assertFalse((target / "caller_sms/obsolete.py").exists())
            for relative in protected:
                self.assertEqual((target / relative).read_text(), "persistent")
            self.assertEqual((target / "config").stat().st_mode & 0o777, 0o750)
            second = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertEqual(second.stdout, "")

    def test_workspace_metadata_translation_has_git_local_parity(self):
        local = task("source.yml", "Deliver local workspace metadata with app workspace paths")
        git = task("source.yml", "Deliver Git workspace metadata with app workspace paths")
        env = environment()
        env.globals["lookup"] = lambda plugin, path, **kwargs: Path(path).read_text()
        for filename in ("pyproject.toml", "uv.lock"):
            raw = (ROOT / filename).read_bytes()
            common = {"py_phone_caller_local_src_path": str(ROOT)}
            from_local = env.from_string(local["ansible.builtin.copy"]["content"]).render(
                common | {"item": filename})
            from_git = env.from_string(git["ansible.builtin.copy"]["content"]).render(
                common | {"item": {"item": filename, "content": base64.b64encode(raw).decode()}})
            self.assertEqual(from_local, from_git)
            self.assertNotIn('"src/', from_git)
            tomllib.loads(from_git)

    def test_source_changes_select_only_consumers_and_shared_utils_select_all(self):
        record = task("source.yml", "Record services affected by application source changes")
        for output, expected in (("", []), (">f.st...... caller_sms/caller_sms.py", ["caller_sms"]),
                                 (">f.st...... py-phone-caller-utils/config.py",
                                  [s["name"] for s in self.defaults["py_phone_caller_services"]])):
            selected = [s["name"] for s in self.defaults["py_phone_caller_services"]
                        if evaluate("{{ " + record["when"] + " }}",
                                    {"item": s, "_ppc_source_changes": output})]
            self.assertEqual(selected, expected)

    def test_external_services_do_not_require_local_service_variables(self):
        values = self.defaults | {"py_phone_caller_final_config": self.config,
                                  "py_phone_caller_manage_queue": True,
                                  "py_phone_caller_manage_postgresql": True,
                                  "py_phone_caller_manage_local_postgres": False,
                                  "item": self.defaults["py_phone_caller_services"][0]}
        self.config["database"]["db_host"] = "database.example.invalid"
        self.config["queue"]["queue_host"] = "queue.example.invalid"
        unit = environment().from_string((ROLE / "templates/service.j2").read_text()).render(values)
        self.assertNotIn("postgresql.service", unit)
        self.assertNotIn("redis-server.service", unit)
        for role, section, host in (("postgresql", "database", "db_host"), ("queue", "queue", "queue_host")):
            block, = load(ANSIBLE / f"roles/{role}/tasks/main.yml")
            self.assertIn(f"py_phone_caller_final_config.{section}.{host} in py_phone_caller_local_db_hosts",
                          block["when"])

    def test_dependency_install_keeps_the_entire_frozen_workspace(self):
        command = task("install.yml", "Build the virtualenv from uv.lock")["ansible.builtin.command"]["cmd"]
        self.assertIn("--frozen --all-packages --no-dev", command)
        self.assertNotIn("--no-deps", command)
        self.assertEqual(self.defaults["py_phone_caller_python_version"], "3.14.5")
        self.assertEqual(self.defaults["py_phone_caller_uv_version"], "0.11.15")

    def test_reviewed_downloads_and_optional_model_guard(self):
        for name in ("Download the reviewed uv installer", "Download the reviewed spaCy English model for Kokoro"):
            download = task("install.yml", name)
            self.assertIn("checksum", download["ansible.builtin.get_url"])
        model = task("install.yml", "Download the reviewed spaCy English model for Kokoro")
        self.assertEqual(model["when"], "py_phone_caller_final_config.generate_audio.tts_engine == 'kokoro_tts'")
        self.assertEqual(self.defaults["py_phone_caller_uv_installer_checksum"], "")
        self.assertEqual(self.defaults["py_phone_caller_spacy_model_checksum"], "")

    def test_secrets_are_private_and_output_is_suppressed(self):
        secret = task("config.yml", "Render .secrets.toml")
        self.assertEqual(secret["ansible.builtin.template"]["mode"], "0600")
        self.assertTrue(secret["no_log"])
        self.assertFalse(secret["diff"])
        database = load(ANSIBLE / "roles/postgresql/tasks/database.yml")
        for entry in database:
            if any(key.startswith("community.postgresql.") and "login_password" in value
                   for key, value in entry.items() if isinstance(value, dict)):
                self.assertTrue(entry["no_log"])
                self.assertFalse(entry["diff"])

    def test_restart_handlers_use_explicit_owned_units(self):
        handlers = load(ROLE / "handlers/main.yml")
        restart = next(item for item in handlers if item["name"] == "Restart affected installed Python units")
        self.assertEqual(restart["ansible.builtin.systemd_service"]["state"], "restarted")
        self.assertIn("item.item.name", restart["ansible.builtin.systemd_service"]["name"])
        self.assertIn("item.stat.exists | default(false)", restart["when"])
        self.assertIn("item.item.name in (_ppc_changed_services | default([]))", restart["when"])

    def test_debian_packages_do_not_require_removed_contrib_metapackage(self):
        packages = load(ROLE / "vars/Debian.yml")["py_phone_caller_postgres_packages"]
        self.assertIn("postgresql", packages)
        self.assertNotIn("postgresql-contrib", packages)

    def test_gateway_provisioning_runs_only_for_new_inputs(self):
        role = ANSIBLE / "roles/gateway"
        for component, name in (("keycloak", "Provision Keycloak realm, roles, clients, and users"),
                                ("apisix", "Provision APISIX Gateway routes via Manager API")):
            command = task("main.yml", name, role)
            self.assertIn("ansible.builtin.command", command)
            conditions = command["when"]
            if isinstance(conditions, str):
                conditions = [conditions]
            self.assertTrue(conditions)
            expression = "{{ " + " and ".join(f"({condition})" for condition in conditions) + " }}"
            desired = "a" * 64
            state_name = f"gateway_{component}_provision_state"
            values = {f"gateway_{component}_fingerprint": desired, state_name: {"stat": {}}}
            self.assertTrue(evaluate(expression, values))
            values[state_name]["stat"]["checksum"] = hashlib.sha256(desired.encode()).hexdigest()
            self.assertFalse(evaluate(expression, values))
            values[f"gateway_{component}_fingerprint"] = "b" * 64
            self.assertTrue(evaluate(expression, values))

    def test_gateway_task_lookup_traverses_blocks_and_preserves_conditions(self):
        role = ANSIBLE / "roles/gateway"
        name = "Provision APISIX Gateway routes via Manager API"
        original = task("main.yml", name, role)
        with tempfile.TemporaryDirectory(prefix=".role-test-", dir=role) as directory:
            nested = Path(directory)
            (nested / "tasks").mkdir()
            (nested / "tasks/main.yml").write_text(yaml.safe_dump([
                {"name": name, "when": "gateway_enabled", "block": [
                    {"name": "Nested real gateway tasks", "when": ["gateway_ready"],
                     "block": load(role / "tasks/main.yml")}]}]))
            found = task("main.yml", name, nested)
            self.assertEqual(found["ansible.builtin.command"], original["ansible.builtin.command"])
            self.assertEqual(found["when"], ["gateway_enabled", "gateway_ready", original["when"]])
            values = {"gateway_enabled": True, "gateway_ready": True,
                      "gateway_apisix_provision_state": {"stat": {}}, "gateway_apisix_fingerprint": "new"}
            self.assertTrue(all(evaluate("{{ " + condition + " }}", values) for condition in found["when"]))
            for condition in ("gateway_enabled", "gateway_ready"):
                self.assertFalse(all(evaluate("{{ " + item + " }}", values | {condition: False})
                                     for item in found["when"]))

    def test_gateway_fingerprints_cover_scripts_and_all_provisioning_inputs(self):
        role = ANSIBLE / "roles/gateway"
        variables = load(role / "vars/main.yml")
        for component in ("keycloak", "apisix"):
            with self.subTest(component=component):
                env = environment()
                script = (role / f"files/setup_{component}.py" if component == "keycloak"
                          else role / "files/setup_apisix_routes.py").read_text()
                env.globals["lookup"] = lambda *args: script
                expression = env.from_string(variables[f"gateway_{component}_fingerprint"])
                inputs = {key: f"synthetic-{key}" for key in variables[f"gateway_{component}_environment"]}
                values = {f"gateway_{component}_environment": inputs,
                          f"py_phone_caller_{component}_image": "synthetic@sha256:" + "a" * 64,
                          "py_phone_caller_final_config": {"database": {"db_host": "127.0.0.1", "db_name": "synthetic"}}}
                initial = expression.render(values)
                self.assertRegex(initial, r"^[0-9a-f]{64}$")
                reordered = dict(reversed(list(inputs.items())))
                self.assertEqual(initial, expression.render(values | {f"gateway_{component}_environment": reordered}))
                for key in inputs:
                    with self.subTest(input=key):
                        self.assertNotEqual(initial, expression.render(values | {
                            f"gateway_{component}_environment": inputs | {key: "changed"}}))
                self.assertNotEqual(initial, expression.render(values | {
                    f"py_phone_caller_{component}_image": "synthetic@sha256:" + "b" * 64}))
                if component == "keycloak":
                    self.assertNotEqual(initial, expression.render(values | {
                        "py_phone_caller_final_config": {"database": {"db_host": "127.0.0.1", "db_name": "other"}}}))
                script += "\n# changed script\n"
                self.assertNotEqual(initial, expression.render(values))

    def test_gateway_restarts_only_changed_units_and_configuration_consumers(self):
        apply = task("main.yml", "Apply changed gateway units and configurations", ANSIBLE / "roles/gateway")
        results = ("_ppc_apisix_conf", "_ppc_gateway_tls", "_ppc_apisix_dash_conf", "_ppc_keycloak_env")
        triggers = {"etcd": (), "apisix": results[:2], "apisix-dashboard": (results[2],),
                    "keycloak": (results[1], results[3])}
        for changed in (None, *results, "unit"):
            for unit, consumers in triggers.items():
                with self.subTest(changed=changed, unit=unit):
                    values = {name: {"changed": name == changed} for name in results}
                    values["_ppc_gateway_config_changed"] = {
                        name: evaluate(expression, values) if isinstance(expression, str) else expression
                        for name, expression in apply["vars"]["_ppc_gateway_config_changed"].items()}
                    values["item"] = {"item": {"unit": unit}, "changed": changed == "unit"}
                    self.assertEqual(evaluate(apply["ansible.builtin.systemd"]["state"], values),
                                     "restarted" if changed == "unit" or changed in consumers else "started")
        for changed in (False, True):
            for first in (False, True):
                self.assertEqual(evaluate(apply["ansible.builtin.systemd"]["daemon_reload"], {
                    "_ppc_gateway_units": {"changed": changed}, "ansible_loop": {"first": first}}), changed and first)

    def test_gateway_real_provisioning_stamps_success_only_and_skips_unchanged_rerun(self):
        role = ANSIBLE / "roles/gateway"
        server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayAPIHandler)
        server.calls = []
        server.failure = None
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for component, label, name in (
                ("keycloak", "Keycloak", "Provision Keycloak realm, roles, clients, and users"),
                ("apisix", "APISIX", "Provision APISIX Gateway routes via Manager API"),
            ):
                with self.subTest(component=component), tempfile.TemporaryDirectory(prefix=".role-test-", dir=role) as directory:
                    base = Path(directory)
                    stamp = base / "provision.sha256"
                    read = task("main.yml", f"Read {label} provisioning completion stamp", role)
                    provision = task("main.yml", name, role)
                    record = task("main.yml", f"Record successful {label} provisioning inputs", role)
                    order = [entry.get("name") for entry in task_entries(load(role / "tasks/main.yml"))]
                    self.assertLess(order.index(read["name"]), order.index(provision["name"]))
                    self.assertLess(order.index(provision["name"]), order.index(record["name"]))
                    self.assertTrue(provision["no_log"])
                    self.assertTrue(record["no_log"])
                    self.assertFalse(record["diff"])
                    self.assertEqual(record["ansible.builtin.copy"]["mode"], "0600")
                    read["ansible.builtin.stat"]["path"] = str(stamp)
                    record["ansible.builtin.copy"].update(dest=str(stamp), owner=str(os.getuid()), group=str(os.getgid()))
                    provision.update(retries=1, delay=0)
                    variables = load(role / "vars/main.yml")
                    for name in ("setup_keycloak.py", "setup_apisix_routes.py"):
                        for key in ("gateway_keycloak_fingerprint", "gateway_apisix_fingerprint"):
                            variables[key] = variables[key].replace(f"'{name}'", repr(str(role / "files" / name)))
                    variables.update({
                        "py_phone_caller_venv_dir": str(Path(sys.executable).parent.parent),
                        "py_phone_caller_uv_dir": str(role / "files"),
                        "py_phone_caller_keycloak_http_port": server.server_port,
                        "py_phone_caller_gateway_dashboard_port": server.server_port,
                        "py_phone_caller_keycloak_admin_user": "synthetic-admin",
                        "py_phone_caller_keycloak_realm": "synthetic",
                        "py_phone_caller_apisix_dashboard_user": "synthetic-admin",
                        "py_phone_caller_service_host": "127.0.0.1",
                        "py_phone_caller_final_config": {"database": {"db_name": "synthetic"}},
                        "_ppc_effective_public_url": "https://synthetic.invalid",
                        "py_phone_caller_keycloak_image": "synthetic@sha256:" + "a" * 64,
                        "py_phone_caller_apisix_image": "synthetic@sha256:" + "b" * 64,
                    })
                    for key in ("_ppc_keycloak_admin_password", "_ppc_keycloak_m2m_client_secret",
                                "_ppc_keycloak_user_admin_password", "_ppc_keycloak_user_operator_password",
                                "_ppc_keycloak_user_viewer_password", "_ppc_apisix_dashboard_password"):
                        variables[key] = "SYNTHETIC-secret-one"
                    playbook = base / "provision.yml"
                    play = [{"name": "Exercise real gateway provisioning on a synthetic local API", "hosts": "localhost",
                             "gather_facts": False, "vars": variables, "tasks": [read, provision, record]}]
                    command = [sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", "-c", "local",
                               str(playbook), "-e", f"ansible_python_interpreter={sys.executable}"]
                    (base / "ansible.cfg").write_text("[defaults]\n")
                    env = os.environ | {"ANSIBLE_CONFIG": str(base / "ansible.cfg"), "ANSIBLE_NOCOLOR": "1",
                                        "ANSIBLE_LOCAL_TEMP": str(base / "local-tmp"),
                                        "ANSIBLE_REMOTE_TEMP": str(base / "remote-tmp"),
                                        "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}

                    def run():
                        playbook.write_text(yaml.safe_dump(play))
                        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
                        self.assertNotIn("SYNTHETIC-secret", result.stdout + result.stderr)
                        return result

                    failures = ("/admin/realms/synthetic/clients/m2m/service-account-user",
                                "/admin/realms/synthetic/users/service-account/role-mappings/realm") if component == "keycloak" else ("apisix",)
                    for failure in failures:
                        server.failure = failure
                        failed = run()
                        self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)
                        self.assertFalse(stamp.exists())
                    server.failure = None
                    first = run()
                    self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                    self.assertIn("changed=2", first.stdout)
                    self.assertRegex(stamp.read_text(), r"^[0-9a-f]{64}$")
                    self.assertEqual(stamp.stat().st_mode & 0o777, 0o600)
                    successful_stamp = stamp.read_bytes()
                    calls = len(server.calls)
                    timestamp = stamp.stat().st_mtime_ns
                    second = run()
                    self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                    self.assertIn("changed=0", second.stdout)
                    self.assertEqual(len(server.calls), calls)
                    self.assertEqual(stamp.stat().st_mtime_ns, timestamp)
                    variables["_ppc_keycloak_user_operator_password" if component == "keycloak"
                              else "_ppc_apisix_dashboard_password"] = "SYNTHETIC-secret-two"
                    server.failure = ("/admin/realms/synthetic/users/operator/role-mappings/realm"
                                      if component == "keycloak" else "apisix")
                    failed = run()
                    self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)
                    self.assertEqual(stamp.read_bytes(), successful_stamp)
                    server.failure = None
                    recovered = run()
                    self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
                    self.assertIn("changed=2", recovered.stdout)
                    self.assertNotEqual(stamp.read_bytes(), successful_stamp)
                    calls = len(server.calls)
                    final = run()
                    self.assertEqual(final.returncode, 0, final.stdout + final.stderr)
                    self.assertIn("changed=0", final.stdout)
                    self.assertEqual(len(server.calls), calls)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_runtime_fixture_covers_direct_service_setting_reads(self):
        fixture = load(ANSIBLE / "tests/fixtures/python-runtime.yml")
        config = FilterModule().filters()["combine"](
            fixture["py_phone_caller_config"], fixture["py_phone_caller_config_secrets"], recursive=True)
        files = [ROOT / "src" / service["name"] / "constants.py"
                 for service in self.defaults["py_phone_caller_services"] if service["name"] != "celery_worker"]
        files.append(ROOT / "src/py-phone-caller-utils/py_phone_caller_utils/tasks/constants.py")
        for path in files:
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                parts = []
                while isinstance(node, ast.Attribute):
                    parts.insert(0, node.attr)
                    node = node.value
                if not isinstance(node, ast.Name) or node.id != "settings":
                    continue
                value = config
                for part in parts:
                    with self.subTest(file=path.name, setting=".".join(parts)):
                        if part == "get":
                            self.assertTrue(callable(value.get))
                            break
                        self.assertIn(part, value)
                    value = value[part]

    def test_runtime_fixture_constrains_all_eleven_units(self):
        fixture = load(ANSIBLE / "tests/fixtures/python-runtime.yml")
        config = fixture["py_phone_caller_config"]
        self.assertEqual(config["generate_audio"]["tts_engine"], "google_gtts")
        self.assertEqual(config["caller_prometheus_webhook"]["prometheus_webhook_receivers"], [])
        self.assertEqual(config["caller_sms"]["modems"], [])
        self.assertEqual(config["asterisk_recaller"]["times_to_dial"], 0)
        self.assertEqual(config["asterisk_recaller"]["call_backup_callee_max_times"], 0)
        self.assertEqual(config["queue"]["queue_url"], "redis://127.0.0.1:6379/15")
        self.assertEqual(config["database"]["db_name"], "py_phone_caller_runtime")
        self.assertTrue(fixture["py_phone_caller_manage_firewall"])
        self.assertEqual(fixture["py_phone_caller_firewall_ports"], [])
        services = self.defaults["py_phone_caller_services"]
        self.assertEqual(len(services), 11)
        values = self.defaults | fixture | load(ROLE / "vars/Debian.yml") | {
            "py_phone_caller_final_config": config, "_ppc_ui_host": "127.0.0.1", "_ppc_ui_port": 5000}
        for service in services:
            with self.subTest(service=service["name"]):
                unit = environment().from_string((ROLE / "templates/service.j2").read_text()).render(
                    values | {"item": service})
                self.assertIn("IPAddressDeny=any", unit)
                self.assertIn("IPAddressAllow=localhost", unit)
                self.assertIn("After=postgresql.service", unit)
                self.assertIn("After=redis-server.service", unit)

    def test_real_ansible_template_render_is_idempotent_and_private(self):
        with tempfile.TemporaryDirectory(prefix=".role-test-", dir=ROLE) as directory:
            base = Path(directory)
            play = [{"name": "Render synthetic configuration only", "hosts": "localhost", "gather_facts": False,
                     "vars_files": [str(ROLE / "defaults/main.yml"),
                                    str(ANSIBLE / "tests/fixtures/python-runtime.yml")],
                     "tasks": [task("main.yml", "Build the effective configuration"),
                               {"name": "Render configuration", "ansible.builtin.template": {
                                   "src": str(ROLE / "templates/settings.toml.j2"),
                                   "dest": str(base / "{{ item.name }}"), "mode": "0600"},
                                "vars": {"_ppc_render_secrets": "{{ item.secret }}"},
                                "loop": [{"name": "settings.toml", "secret": False},
                                         {"name": ".secrets.toml", "secret": True}], "no_log": True}]}]
            playbook = base / "render.yml"
            playbook.write_text(yaml.safe_dump(play))
            command = [sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", "-c", "local",
                       str(playbook), "-e", f"ansible_python_interpreter={sys.executable}"]
            env = os.environ | {"ANSIBLE_CONFIG": str(ANSIBLE / "ansible.cfg"),
                                "ANSIBLE_LOCAL_TEMP": str(base / "local-tmp"),
                                "ANSIBLE_REMOTE_TEMP": str(base / "remote-tmp"), "ANSIBLE_NOCOLOR": "1"}
            for expected in ("changed=1", "changed=0"):
                result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(expected, result.stdout)
            public = tomllib.loads((base / "settings.toml").read_text())
            private = tomllib.loads((base / ".secrets.toml").read_text())
            self.assertNotIn("client_secret", public["auth"]["oauth2"])
            self.assertEqual(private["auth"]["oauth2"]["client_secret"], "")
            self.assertNotIn("SYNTHETIC", (base / "settings.toml").read_text())
            self.assertEqual((base / ".secrets.toml").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()