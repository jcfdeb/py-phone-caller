"""Synthetic ingress contracts; no inventory, remote hosts, or container runtime."""

import base64
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from ansible.plugins.filter import mathstuff
from ansible.plugins.filter.core import FilterModule
from jinja2 import Environment, StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import yaml


ANSIBLE = Path(__file__).resolve().parents[1]
ROLES = ANSIBLE / "roles"


def load(path):
    return yaml.safe_load(path.read_text())


def environment(native=False):
    env = (NativeEnvironment if native else Environment)(undefined=StrictUndefined, trim_blocks=True)
    default = env.filters["default"]
    env.filters.update(FilterModule().filters())
    env.filters.update(mathstuff.FilterModule().filters())
    env.filters["default"] = default
    env.filters["urlsplit"] = lambda value, field: getattr(urlsplit(value), field)
    env.tests["search"] = lambda value, regex: re.search(regex, str(value)) is not None
    env.tests["match"] = lambda value, regex: re.match(regex, str(value)) is not None
    return env


def evaluate(expression, values):
    return environment(native=True).from_string(expression).render(values)


def entries(role, filename="main.yml"):
    def flatten(tasks, inherited=()):
        for task in tasks:
            conditions = task.get("when", [])
            if isinstance(conditions, str):
                conditions = [conditions]
            conditions = [*inherited, *conditions]
            if "block" in task:
                yield from flatten(task["block"], conditions)
            else:
                yield task | {"when": conditions}
    return list(flatten(load(ROLES / role / "tasks" / filename)))


def selected(task, values):
    return all(evaluate("{{ " + condition + " }}", values) for condition in task["when"])


def render(role, filename, **overrides):
    values = load(ROLES / "deploy_py-phone-caller/defaults/main.yml") | {
        "py_phone_caller_topology": "enterprise",
        "py_phone_caller_connectivity": "online",
        "py_phone_caller_ingress": "caddy",
        "py_phone_caller_tls_mode": "internal",
        "py_phone_caller_public_url": "https://edge.example.invalid",
        "caddy_domain_name": "edge.example.invalid",
        "caddy_email": "",
        "_ppc_ingress_upstream": "127.0.0.1:9080",
        "py_phone_caller_service_host": "127.0.0.1",
        "py_phone_caller_manage_postgresql": False,
        "py_phone_caller_keycloak_image": "registry.invalid/keycloak@sha256:" + "a" * 64,
        "py_phone_caller_final_config": {"database": {"db_host": "127.0.0.1"}},
        "_ppc_keycloak_db_password": "legacy-secret",
        "_ppc_keycloak_admin_password": "admin-secret",
        "_ppc_apisix_dashboard_password": "dashboard-secret",
        "gateway_keycloak_postgresql_url": "jdbc:postgresql://database.invalid:5432/iam",
        "gateway_keycloak_postgresql_username": "iam",
        "gateway_keycloak_postgresql_password": "SYNTHETIC-secret",
    } | overrides
    return environment().from_string((ROLES / role / "templates" / filename).read_text()).render(values)


class TopologyIngressTests(unittest.TestCase):
    def test_shared_gateway_credential_directory_has_one_permission_policy(self):
        tasks = yaml.safe_load((ROLES / 'gateway/tasks/main.yml').read_text())
        policies = []
        for task in tasks:
            settings = task.get('ansible.builtin.file', {})
            if settings.get('path') == '/etc/py-phone-caller' or '/etc/py-phone-caller' in task.get('loop', []):
                policies.append({key: settings[key] for key in ('owner', 'group', 'mode')})
        credentials = yaml.safe_load((ROLES / 'deploy_py-phone-caller/tasks/credentials.yml').read_text())
        settings = next(task for task in credentials if task['name'] == 'Ensure target credential directory exists')['ansible.builtin.file']
        self.assertEqual(policies, [{key: settings[key] for key in ('owner', 'group', 'mode')}])

    def test_gateway_owned_mapped_loopback_is_not_a_foreign_listener(self):
        tasks = yaml.safe_load((ROLES / 'gateway/tasks/preflight.yml').read_text())
        guard = next(task for task in tasks if task['name'] == 'Refuse foreign gateway listener ownership')
        for host, pid, expected in (("127.0.0.1", "123", True), ("[::ffff:127.0.0.1]", "123", True),
                                    ("[::1]", "123", True), ("0.0.0.0", "123", False),
                                    ("[::ffff:192.0.2.1]", "123", False), ("127.0.0.1", "456", False)):
            with self.subTest(host=host, pid=pid):
                context = {"gateway_listener_pids": ["123"],
                           "item": f'LISTEN 0 4096 {host}:8180 *:* users:(("java",pid={pid},fd=5))'}
                self.assertEqual(all(environment().compile_expression(condition)(context)
                                     for condition in guard['ansible.builtin.assert']['that']), expected)

    def test_single_host_keycloak_does_not_open_cluster_ports(self):
        enterprise = render("gateway", "keycloak.env.j2")
        self.assertIn("KC_CACHE=local\n", enterprise)
        self.assertNotIn("KC_CACHE=local", render("gateway", "keycloak.env.j2", py_phone_caller_topology="legacy"))

    def test_private_ca_and_local_dns_reach_gateway_without_disabling_tls(self):
        values = {"py_phone_caller_tls_ca_bundle": "/etc/ssl/certs/private-ca.pem",
                  "py_phone_caller_gateway_extra_hosts": {"caller.internal": "127.0.0.1"},
                  "py_phone_caller_tls_ca_stat": {"stat": {"checksum": "a" * 64}}}
        unit = render("gateway", "service-apisix.j2", **values)
        self.assertIn("/etc/ssl/certs/private-ca.pem:/opt/issuer-ca.pem:ro,z", unit)
        self.assertIn("--add-host=caller.internal:127.0.0.1", unit)
        self.assertIn("--label io.py-phone-caller.issuer-ca=" + "a" * 64, unit)
        self.assertNotEqual(unit, render("gateway", "service-apisix.j2", **(values | {
            "py_phone_caller_tls_ca_stat": {"stat": {"checksum": "b" * 64}},
        })))
        config = yaml.safe_load(render("gateway", "apisix_config.yaml.j2", **values))
        self.assertEqual(config["apisix"]["ssl"]["ssl_trusted_certificate"], "/opt/issuer-ca.pem")
        self.assertNotIn("ssl_trusted_certificate", yaml.safe_load(render("gateway", "apisix_config.yaml.j2"))["apisix"]["ssl"])

    def test_supplied_certificates_require_strict_server_verification(self):
        tasks = yaml.safe_load((ROLES / "deploy_py-phone-caller/tasks/topology_host.yml").read_text())
        verify = next(task for task in tasks if task["name"] == "Validate the supplied leaf and CA with strict server certificate verification")
        self.assertEqual(verify["ansible.builtin.command"]["argv"][:5],
                         ["openssl", "verify", "-x509_strict", "-purpose", "sslserver"])
        self.assertIn("-verify_hostname", verify["ansible.builtin.command"]["argv"])
        self.assertFalse(verify["changed_when"])
        self.assertTrue(verify["no_log"])

    def test_caddy_explicit_tls_does_not_guess_from_suffix(self):
        for mode, domain in (("internal", "edge.example.com"), ("acme", "edge.test")):
            with self.subTest(mode=mode):
                text = render("reverse_proxy", "Caddyfile.j2", py_phone_caller_tls_mode=mode,
                              caddy_domain_name=domain, py_phone_caller_public_url=f"https://{domain}")
                self.assertEqual("tls internal" in text, mode == "internal")
                self.assertEqual("issuer acme" in text, mode == "acme")
                self.assertIn("reverse_proxy 127.0.0.1:9080", text)
                self.assertIn("header_up X-Forwarded-Proto https", text)
                self.assertIn("header_up X-Forwarded-Port 443", text)
        provided = render("reverse_proxy", "Caddyfile.j2", py_phone_caller_tls_mode="provided",
                          py_phone_caller_tls_certificate="/etc/tls/server.crt",
                          py_phone_caller_tls_private_key="/etc/tls/server.key")
        self.assertIn('tls "/etc/tls/server.crt" "/etc/tls/server.key"', provided)
        standard = render("reverse_proxy", "Caddyfile.j2", py_phone_caller_topology="standard",
                          _ppc_ingress_upstream="127.0.0.1:5000")
        self.assertIn("reverse_proxy 127.0.0.1:5000", standard)

    def test_legacy_caddy_still_uses_suffix(self):
        for domain in ("edge.local", "edge.example.com", ""):
            text = render("reverse_proxy", "Caddyfile.j2", py_phone_caller_topology="legacy",
                          caddy_domain_name=domain)
            self.assertEqual("tls internal" in text, domain == "edge.local")
            self.assertNotIn("header_up", text)
            self.assertIn((domain or ":80") + " {", text)

    def test_gateway_production_and_private_listeners(self):
        unit = render("gateway", "service-keycloak.j2")
        env = render("gateway", "keycloak.env.j2")
        self.assertNotIn("start-dev", unit)
        self.assertRegex(unit, r" start(?:\s|\\)")
        self.assertIn("KC_HTTP_HOST=127.0.0.1", env)
        self.assertIn("KC_HTTP_ENABLED=true", env)
        self.assertIn("KC_PROXY_TRUSTED_ADDRESSES=127.0.0.1,::1", env)
        self.assertIn("KC_HOSTNAME=https://edge.example.invalid", env)
        self.assertIn("KC_DB_URL=jdbc:postgresql://database.invalid:5432/iam", env)
        self.assertNotIn("SYNTHETIC-secret", unit)
        config = yaml.safe_load(render("gateway", "apisix_config.yaml.j2"))
        self.assertEqual(config["apisix"]["node_listen"][0]["ip"], "127.0.0.1")
        self.assertFalse(config["apisix"]["ssl"]["enable"])
        self.assertEqual(config["apisix"]["trusted_addresses"], ["127.0.0.1/32", "::1/128"])
        self.assertEqual(config["deployment"]["admin"]["admin_listen"]["ip"], "127.0.0.1")
        dashboard = yaml.safe_load(render("gateway", "apisix_dashboard_conf.yaml.j2"))
        self.assertEqual(dashboard["conf"]["listen"]["host"], "127.0.0.1")

    def test_legacy_gateway_keeps_legacy_service(self):
        self.assertIn("start-dev", render("gateway", "service-keycloak.j2", py_phone_caller_topology="legacy"))
        config = yaml.safe_load(render("gateway", "apisix_config.yaml.j2", py_phone_caller_topology="legacy"))
        self.assertNotIn("ip", config["apisix"]["node_listen"][0])

    def test_offline_units_never_pull(self):
        for filename in ("service-keycloak.j2", "service-apisix.j2", "service-etcd.j2", "service-apisix-dashboard.j2"):
            with self.subTest(filename=filename):
                offline = render("gateway", filename, py_phone_caller_connectivity="airgapped")
                self.assertIn("--pull=never", offline)
                self.assertNotIn("podman pull", offline)
                self.assertNotIn("--pull=never", render("gateway", filename, py_phone_caller_topology="legacy"))

    def test_offline_caddy_has_no_repository_or_download_fallback(self):
        tasks = entries("reverse_proxy")
        for family in ("Debian", "RedHat"):
            values = {"ansible_facts": {"os_family": family}, "py_phone_caller_connectivity": "airgapped"}
            for task in tasks:
                if any(module in task for module in ("ansible.builtin.get_url", "ansible.builtin.apt_repository")) or "repository" in task.get("name", "").lower() or "signing key" in task.get("name", "").lower():
                    self.assertFalse(selected(task, values), task["name"])
        install = next(task for task in tasks if task.get("name") == "Install Caddy")
        self.assertTrue(selected(install, values))

    def test_firewall_explicit_never_adds_backend_bypass(self):
        for task in entries("firewall"):
            if task.get("name") != "Open the application ports":
                continue
            values = {"py_phone_caller_topology": "enterprise", "py_phone_caller_manage_gateway": True,
                      "py_phone_caller_firewall_ports": [80, 443, 5000],
                      "py_phone_caller_firewall_extra_ports": [8180, 9001],
                      "py_phone_caller_gateway_firewall_ports": [9080, 9443]}
            self.assertEqual(evaluate(task["loop"], values), [80, 443])
            values["py_phone_caller_topology"] = "legacy"
            self.assertEqual(evaluate(task["loop"], values), [80, 443, 5000, 8180, 9001, 9080, 9443])

    def test_route_provisioner_disables_admin_and_overwrites_forwarded_origin(self):
        path = ROLES / "gateway/files/setup_apisix_routes.py"
        for topology in ("legacy", "enterprise"):
            with self.subTest(topology=topology), patch.dict(os.environ, {
                "PPC_TOPOLOGY": topology, "PPC_PUBLIC_URL": "https://edge.example.invalid:4443",
                "APISIX_DASHBOARD_PASS": "SYNTHETIC-secret",
            }):
                script = runpy.run_path(str(path))
                response = Mock()
                response.json.return_value = {"code": 0, "data": {"token": "token"}}
                with patch("requests.post", return_value=response), patch("requests.put", return_value=response) as put:
                    script["main"]()
                payloads = [call.kwargs["json"] for call in put.call_args_list]
                admin = next(payload for payload in payloads if payload["id"] == "route-keycloak-admin")
                self.assertEqual(admin["status"], 1 if topology == "legacy" else 0)
                if topology == "enterprise":
                    for payload in payloads:
                        headers = payload["plugins"]["proxy-rewrite"]["headers"]["set"]
                        self.assertEqual(headers["X-Forwarded-Proto"], "https")
                        self.assertEqual(headers["X-Forwarded-Host"], "edge.example.invalid:4443")
                        self.assertEqual(headers["X-Forwarded-Port"], "4443")

    def test_declarative_routes_share_the_private_admin_and_origin_policy(self):
        for topology in ("legacy", "enterprise"):
            routes = yaml.safe_load(render("gateway", "apisix_routes.yaml.j2", py_phone_caller_topology=topology))["routes"]
            admin = next(route for route in routes if route["id"] == "route-keycloak-admin")
            self.assertEqual(admin.get("status", 1), 1 if topology == "legacy" else 0)
            if topology == "enterprise":
                for route in routes:
                    rewrite = route["plugins"]["proxy-rewrite"]
                    self.assertNotIn("use_real_request_uri_unsafe", rewrite)
                    self.assertEqual(rewrite["headers"]["set"]["X-Forwarded-Port"], "443")

    def test_invalid_gateway_origin_fails_before_api_calls(self):
        for origin in ("", "http://edge.invalid", "https://user:password@edge.invalid", "https://edge.invalid/path"):
            with self.subTest(origin=origin), patch.dict(os.environ, {"PPC_TOPOLOGY": "enterprise", "PPC_PUBLIC_URL": origin}):
                script = runpy.run_path(str(ROLES / "gateway/files/setup_apisix_routes.py"))
                with patch("requests.post") as post, self.assertRaises(ValueError):
                    script["main"]()
                post.assert_not_called()

    def test_explicit_gateway_never_generates_legacy_certificate(self):
        task = next(task for task in entries("gateway") if task["name"] == "Generate self-signed TLS certificate for Gateway & Keycloak")
        values = {"py_phone_caller_topology": "enterprise", "_ppc_gateway_cert_stat": {"stat": {"exists": False}}}
        self.assertFalse(selected(task, values))
        self.assertTrue(selected(task, values | {"py_phone_caller_topology": "legacy"}))

    def run_assertions(self, tasks, variables):
        with tempfile.TemporaryDirectory(prefix=".topology-test-", dir=ANSIBLE / "tests") as directory:
            base = Path(directory)
            playbook = base / "preflight.yml"
            playbook.write_text(yaml.safe_dump([{"hosts": "localhost", "gather_facts": False,
                                               "vars": variables, "tasks": tasks}]))
            config = base / "ansible.cfg"
            config.write_text("[defaults]\n")
            return subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,",
                                   "-c", "local", str(playbook)], capture_output=True, text=True, timeout=30,
                                  env=os.environ | {"ANSIBLE_CONFIG": str(config), "ANSIBLE_NOCOLOR": "1",
                                                    "ANSIBLE_LOCAL_TEMP": str(base / "local-tmp"),
                                                    "ANSIBLE_REMOTE_TEMP": str(base / "remote-tmp")})

    def test_foreign_listener_cannot_be_forced_in_explicit_profile(self):
        guard = next(task for task in entries("reverse_proxy", "preflight.yml")
                     if task.get("name") == "Refuse to install a second reverse proxy")
        values = {"py_phone_caller_topology": "standard", "py_phone_caller_caddy_force": True,
                  "_ppc_nat": {"stdout_lines": [], "rc": 0},
                  "_ppc_nat6": {"stdout_lines": [], "rc": 0},
                  "_ppc_listeners": {"stdout_lines": ['LISTEN 0 128 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=42,fd=1))'], "rc": 0},
                  "_ppc_ingress_upstream": "127.0.0.1:5000"}
        denied = self.run_assertions([guard], values)
        self.assertNotEqual(denied.returncode, 0, denied.stdout + denied.stderr)
        self.assertIn("Something else already owns", denied.stdout)
        values["_ppc_listeners"]["stdout_lines"] = []
        allowed = self.run_assertions([guard], values)
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        for field in ("_ppc_nat", "_ppc_nat6"):
            with self.subTest(field=field):
                diversion = {"stdout_lines": ["-A PREROUTING -p tcp --dport 443 -j REDIRECT --to-ports 8443"], "rc": 0}
                denied = self.run_assertions([guard], values | {field: diversion})
                self.assertNotEqual(denied.returncode, 0, denied.stdout + denied.stderr)

    def test_foreign_caddy_configuration_is_rejected(self):
        guard = next(task for task in entries("reverse_proxy", "preflight.yml")
                     if task["name"] == "Refuse to replace a foreign Caddy configuration")
        values = {"py_phone_caller_topology": "standard", "_ppc_listeners": {"stdout": 'users:(("caddy",pid=12,fd=1))'},
                  "gateway_existing_caddy_config": {"content": "IyBPcGVyYXRvciBtYW5hZ2VkCg=="}}
        denied = self.run_assertions([guard], values)
        self.assertNotEqual(denied.returncode, 0, denied.stdout + denied.stderr)
        self.assertIn("not owned by this deployment", denied.stdout)
        values["gateway_existing_caddy_config"]["content"] = base64.b64encode(
            b"# Managed by Ansible (role: deploy_py-phone-caller).\n").decode()
        allowed = self.run_assertions([guard], values)
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)

    def test_offline_images_missing_or_wrong_digest_fail_closed(self):
        guard = next(task for task in entries("gateway", "preflight.yml")
                     if task["name"] == "Require locally available reviewed image digests")
        digest = "registry.invalid/image@sha256:" + "a" * 64
        for rc, digests, success in ((0, [digest], True), (0, [], False), (1, [], False),
                                     (0, ["registry.invalid/image@sha256:" + "b" * 64], False)):
            with self.subTest(rc=rc, digests=digests):
                values = {"py_phone_caller_connectivity": "airgapped", "gateway_offline_images": {
                    "results": [{"rc": rc, "item": digest, "stdout": json.dumps([{"RepoDigests": digests}])}]}}
                result = self.run_assertions([guard], values)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_gateway_listener_must_be_owned_and_loopback(self):
        guard = next(task for task in entries("gateway", "preflight.yml")
                     if task["name"] == "Refuse foreign gateway listener ownership")
        values = {"py_phone_caller_topology": "enterprise", "py_phone_caller_gateway_http_port": 9080,
                  "py_phone_caller_gateway_https_port": 9443, "py_phone_caller_gateway_dashboard_port": 9001,
                  "py_phone_caller_keycloak_http_port": 8180, "py_phone_caller_keycloak_https_port": 8443,
                  "gateway_owned_processes": {"results": [{"stdout_lines": ["HPID", "42"]}]}}
        for address, pid, success in (("127.0.0.1", 42, True), ("127.0.0.1", 99, False), ("0.0.0.0", 42, False)):
            with self.subTest(address=address, pid=pid):
                result = self.run_assertions([guard], values | {"gateway_existing_listeners": {
                    "stdout_lines": [f'LISTEN 0 128 {address}:9080 0.0.0.0:* users:(("nginx",pid={pid},fd=1))']}})
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_provided_tls_missing_files_are_rejected_without_content_disclosure(self):
        guard = next(task for task in entries("reverse_proxy", "preflight.yml")
                     if task["name"] == "Require existing regular TLS files")
        values = {"py_phone_caller_topology": "standard", "py_phone_caller_tls_mode": "provided"}
        for stat, success in (({"exists": True, "isreg": True}, True), ({"exists": False}, False),
                              ({"exists": True, "isreg": False}, False)):
            with self.subTest(stat=stat):
                result = self.run_assertions([guard], values | {"gateway_ingress_tls_files": {
                    "results": [{"stat": stat, "item": "SYNTHETIC-private-key-path"}]}})
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                self.assertNotIn("SYNTHETIC-private-key-path", result.stdout + result.stderr)

    def test_offline_acme_is_rejected(self):
        guard = next(task for task in entries("reverse_proxy", "preflight.yml")
                     if task["name"] == "Validate explicit Caddy TLS selection")
        values = {"py_phone_caller_topology": "standard", "py_phone_caller_connectivity": "airgapped",
                  "py_phone_caller_tls_mode": "acme", "py_phone_caller_public_url": "https://edge.invalid"}
        result = self.run_assertions([guard], values)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_enterprise_database_is_required_and_secrets_are_suppressed(self):
        guard = next(task for task in entries("gateway", "preflight.yml")
                     if task.get("name") == "Require operator-provisioned Keycloak PostgreSQL")
        values = {"py_phone_caller_topology": "enterprise",
                  "gateway_keycloak_postgresql_url": "jdbc:postgresql://database.invalid:5432/iam",
                  "gateway_keycloak_postgresql_username": "iam",
                  "gateway_keycloak_postgresql_password": "SYNTHETIC-secret"}
        result = self.run_assertions([guard], values)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for field, invalid in (("url", ""), ("url", "jdbc:h2:mem:test"), ("username", ""),
                               ("password", ""), ("password", "SYNTHETIC-secret\nINJECT=true")):
            with self.subTest(field=field, invalid=invalid):
                result = self.run_assertions([guard], values | {"gateway_keycloak_postgresql_" + field: invalid})
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("SYNTHETIC-secret", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
