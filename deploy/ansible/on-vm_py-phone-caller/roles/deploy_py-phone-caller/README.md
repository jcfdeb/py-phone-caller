## Notes

* No `PYTHONPATH` is set. `uv sync` installs every workspace member into the
  virtualenv as an editable install pointing at `<install_dir>/src`, which is
  why that path must not move.
* `PrivateTmp` is deliberately off: `caller_sms` and `celery_worker` share the
  on-premise SMS SQLite database under `/tmp`.
* Migrations are not run from Ansible. `caller_register` applies them at
  startup, exactly as in the container and Kubernetes stacks, so there is one
  implementation rather than two.

### API Gateway & Keycloak IAM Integration (Opt-In)

| Variable | Default | Description |
| --- | --- | --- |
| `py_phone_caller_manage_gateway` | `false` | Enable Apache APISIX gateway and Keycloak IAM |
| `py_phone_caller_gateway_http_port` | `9080` | APISIX plaintext ingress port |
| `py_phone_caller_gateway_https_port` | `9443` | APISIX TLS reverse proxy port |
| `py_phone_caller_gateway_dashboard_port` | `9001` | APISIX Manager Dashboard port |
| `py_phone_caller_keycloak_http_port` | `8180` | Keycloak plaintext HTTP port |
| `py_phone_caller_keycloak_https_port` | `8443` | Keycloak TLS HTTPS port |
| `py_phone_caller_keycloak_realm` | `"py-phone-caller"` | Keycloak security realm |
| `py_phone_caller_keycloak_admin_user` | `"admin"` | Keycloak administrative account |
| `py_phone_caller_credentials_dir` | `"{{ inventory_dir }}/credentials"` | Control node secret storage |
| `py_phone_caller_server_credentials_path` | `"/etc/py-phone-caller/credentials.env"` | Target emergency credential export (0600) |

#### Method 1: Automatic Secret Generation with Ansible Vault

When `py_phone_caller_manage_gateway: true`, the role automatically resolves or generates cryptographically strong 32-character secrets on the Ansible control node using `lookup('password')`.

1. **Automatic Generation**: Secrets are stored in `deploy/ansible/on-vm_py-phone-caller/credentials/` on the control node for:
   - Keycloak Master Admin (`admin`)
   - Keycloak SSO Users (`admin_user`, `operator_user`, `viewer_user`)
   - Web UI Local Fallback Admin (`admin@py-phone-caller.link`)
   - APISIX Dashboard Admin (`admin`)
   - Infrastructure & M2M secrets (`keycloak_db_password`, `keycloak_m2m_client_secret`)
2. **Inspect Credentials**: Inspect credentials on the control node anytime:
   ```bash
   ./show-credentials.sh
   ```
3. **Ansible Vault Encryption**: Encrypt the generated secret files with:
   ```bash
   ansible-vault encrypt deploy/ansible/on-vm_py-phone-caller/credentials/*
   ```
4. **Execution with Vault**: Run the playbook providing the vault password:
   ```bash
   ansible-playbook deploy_py-phone-caller.yml --ask-vault-pass
   # or with password file:
   ansible-playbook deploy_py-phone-caller.yml --vault-password-file ~/.vault_pass
   ```
5. **Target Server Reference**: On the target host, credentials are saved to `/etc/py-phone-caller/credentials.env` with strict `0600 root:root` permissions for administrative recovery.
