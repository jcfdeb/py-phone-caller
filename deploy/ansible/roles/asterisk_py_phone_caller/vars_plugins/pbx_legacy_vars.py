"""Preserve the legacy PBX playbook's adjacent variables across its site import."""

from pathlib import Path

from ansible.plugins.loader import vars_loader
from ansible.plugins.vars import BaseVarsPlugin


DOCUMENTATION = """
name: pbx_legacy_vars
short_description: Load legacy PBX playbook-adjacent host and group variables
description:
  - Enabled only by the legacy PBX ansible.cfg.
  - Delegates matching, Vault decryption and parsing to host_group_vars.
extends_documentation_fragment:
  - vars_plugin_staging
options:
  stage:
    default: task
"""


class VarsModule(BaseVarsPlugin):
    REQUIRES_ENABLED = True
    is_stateless = True

    def get_vars(self, loader, path, entities, cache=True):
        legacy = Path(__file__).resolve().parents[3] / "asterisk_py-phone-caller"
        plugin = vars_loader.get("ansible.builtin.host_group_vars")
        return plugin.get_vars(loader, str(legacy), entities, cache=cache)