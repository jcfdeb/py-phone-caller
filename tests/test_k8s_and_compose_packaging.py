"""Tests for Kubernetes (Raw Manifests + Helm Chart) and Docker Compose packaging."""

from __future__ import annotations

from argparse import Namespace
import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
K8S_BUILDER_PATH = REPO_ROOT / "deploy" / "packaging" / "k8s" / "build_k8s_bundle.py"

SPEC = importlib.util.spec_from_file_location("build_k8s_bundle", K8S_BUILDER_PATH)
K8S_BUILDER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(K8S_BUILDER)


class K8sAndComposePackagingTests(unittest.TestCase):
    def test_k8s_manifests_and_helm_chart_package_and_validate(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".test-k8s-") as tmp:
            out_dir = Path(tmp) / "k8s"
            manifest = K8S_BUILDER.build_all(Namespace(output_dir=str(out_dir), force=False))
            self.assertEqual(manifest["version"], "1.1.0")
            self.assertIn("04_caller_secrets.yml", manifest["kustomize_resources"])
            self.assertIn("17_openalertd.yml", manifest["kustomize_resources"])
            self.assertIn("18_gateway_apisix_keycloak.yml", manifest["kustomize_resources"])

            chart_tgz = out_dir / "py-phone-caller-1.1.0.tgz"
            self.assertTrue(chart_tgz.is_file())
            with tarfile.open(chart_tgz, "r:gz") as tf:
                names = set(tf.getnames())
                self.assertIn("py-phone-caller/Chart.yaml", names)
                self.assertIn("py-phone-caller/values.yaml", names)
                self.assertIn("py-phone-caller/templates/microservices.yaml", names)
                self.assertIn("py-phone-caller/templates/openalertd.yaml", names)
                self.assertIn("py-phone-caller/templates/secret.yaml", names)
                ms_tpl = tf.extractfile("py-phone-caller/templates/microservices.yaml").read().decode("utf-8")
                self.assertIn("/app/py-phone-caller/config/settings.toml", ms_tpl)
                self.assertNotIn("/app/src/", ms_tpl)
                ep_tpl = tf.extractfile("py-phone-caller/templates/asterisk-endpoint.yaml").read().decode("utf-8")
                self.assertIn("kind: EndpointSlice", ep_tpl)
                self.assertNotIn("kind: Endpoints\n", ep_tpl)

            ast_ep_text = (REPO_ROOT / "deploy" / "k8s" / "01_asterisk_endpoint.yml").read_text(encoding="utf-8")
            self.assertIn("kind: EndpointSlice", ast_ep_text)
            self.assertNotIn("kind: Endpoints\n", ast_ep_text)

            for yml_file in sorted((REPO_ROOT / "deploy" / "k8s").glob("*.yml")):
                text = yml_file.read_text(encoding="utf-8")
                self.assertNotIn("/app/src/", text, f"Found /app/src/ in {yml_file.name}")

    def test_docker_compose_files_and_gateway_consistency(self) -> None:
        root_compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        deploy_compose = yaml.safe_load((REPO_ROOT / "deploy" / "compose" / "docker-compose.yml").read_text(encoding="utf-8"))
        gateway_compose = yaml.safe_load((REPO_ROOT / "deploy" / "compose" / "docker-compose.gateway.yml").read_text(encoding="utf-8"))

        self.assertIn("openalertd", root_compose["services"])
        self.assertIn("openalertd", deploy_compose["services"])
        self.assertEqual(deploy_compose["services"]["db"]["image"], "docker.io/library/postgres:17-alpine")

        # Verify gateway compose references `db` (which exists in deploy/compose/docker-compose.yml)
        kc_depends = gateway_compose["services"]["keycloak"]["depends_on"]
        self.assertIn("db", kc_depends)
        self.assertNotIn("postgres", kc_depends)

        # Verify mounted APISIX config files exist on disk
        self.assertTrue((REPO_ROOT / "deploy" / "gateway" / "apisix" / "config.yaml").is_file())
        self.assertTrue((REPO_ROOT / "deploy" / "gateway" / "apisix" / "apisix.yaml").is_file())
        self.assertTrue((REPO_ROOT / "deploy" / "gateway" / "apisix" / "dashboard_conf.yaml").is_file())


if __name__ == "__main__":
    unittest.main()
