# TOML to Dynaconf env converter

`toml_to_dynaconf_env.py` converts `settings.toml` and `.secrets.toml` files into environment files that can be injected into containers or systemd services.

The project uses Dynaconf with this prefix:

```text
DYNACONF
```

So a TOML value such as:

```toml
[database]
db_host = "db"
```

becomes:

```text
DYNACONF_DATABASE__DB_HOST="db"
```

## Docker Compose usage

From the repository root:

```bash
uv run python assets/scripts/config/toml_to_dynaconf_env.py \
  --input src/config/settings.toml \
  --output assets/docker-compose/env/py-phone-caller.env

uv run python assets/scripts/config/toml_to_dynaconf_env.py \
  --ignore-missing \
  --input src/config/.secrets.toml \
  --output assets/docker-compose/env/py-phone-caller.secrets.env
```

Then start the stack from `assets/docker-compose`:

```bash
podman compose up -d
```

The generated files are intentionally ignored by Git because they may contain deployment-specific hostnames and secrets.

## Shell usage

To create a file that can be sourced by a shell:

```bash
uv run python assets/scripts/config/toml_to_dynaconf_env.py \
  --format shell \
  --input src/config/settings.toml \
  --input src/config/.secrets.toml \
  --output /tmp/py-phone-caller-env.sh
```

Then:

```bash
set -a
. /tmp/py-phone-caller-env.sh
set +a
```

## Notes

- Later input files override earlier ones, matching the normal `settings.toml` plus `.secrets.toml` layering.
- Lists and dictionaries are exported with Dynaconf's `@json` converter.
- Output files are written with mode `0600` to keep generated secrets private.