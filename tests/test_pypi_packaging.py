"""Tests for PyPI wheel/sdist packaging and CLI entrypoints."""

from __future__ import annotations

from argparse import Namespace
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
PYPI_BUILDER_PATH = REPO_ROOT / "deploy" / "packaging" / "pypi" / "build_pypi_packages.py"

SPEC = importlib.util.spec_from_file_location("build_pypi_packages", PYPI_BUILDER_PATH)
PYPI_BUILDER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(PYPI_BUILDER)


class PyPIPackagingTests(unittest.TestCase):
    def test_all_13_packages_build_clean_wheels_and_sdists(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".test-pypi-") as tmp:
            out_dir = Path(tmp) / "pypi"
            args = Namespace(
                package=None,
                source_revision="a" * 40,
                output_dir=str(out_dir),
                force=False,
            )
            manifest = PYPI_BUILDER.build_all(args)
            self.assertEqual(manifest["package_count"], 13)
            self.assertTrue((out_dir / "SHA256SUMS").is_file())
            self.assertTrue((out_dir / "release.json").is_file())

            wheels = list(out_dir.glob("*.whl"))
            sdists = list(out_dir.glob("*.tar.gz"))
            self.assertEqual(len(wheels), 13)
            self.assertEqual(len(sdists), 13)

            # Ensure caller_sms wheel includes caller_sms/backend/
            sms_wheel, = out_dir.glob("caller_sms-*.whl")
            with zipfile.ZipFile(sms_wheel, "r") as zf:
                self.assertIn("caller_sms/backend/twilio.py", zf.namelist())
                self.assertIn("caller_sms/backend/rust_on_premise.py", zf.namelist())

            # Ensure py_phone_caller_ui wheel includes blueprints and templates
            ui_wheel, = out_dir.glob("py_phone_caller_ui-*.whl")
            with zipfile.ZipFile(ui_wheel, "r") as zf:
                names = zf.namelist()
                self.assertIn("py_phone_caller_ui/calls/__init__.py", names)
                self.assertIn("py_phone_caller_ui/calls/constants.py", names)
                self.assertTrue(any(n.startswith("py_phone_caller_ui/templates/") for n in names))
                self.assertTrue(any(n.startswith("py_phone_caller_ui/translations/") for n in names))

    def test_meta_package_cli_list_services(self) -> None:
        cli_path = REPO_ROOT / "deploy" / "packaging" / "pypi" / "meta_package" / "py_phone_caller" / "cli.py"
        pkg_init = REPO_ROOT / "deploy" / "packaging" / "pypi" / "meta_package" / "py_phone_caller" / "__init__.py"
        import sys
        sys.path.insert(0, str(pkg_init.parents[1]))
        try:
            spec = importlib.util.spec_from_file_location("py_phone_caller.cli", cli_path)
            mod = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(mod)
            self.assertEqual(len(mod.SERVICE_REGISTRY), 11)
            self.assertEqual(mod.main(["list-services"]), 0)
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
