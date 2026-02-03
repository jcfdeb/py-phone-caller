"""
Configuration management using Dynaconf.
"""

import os
import warnings
from pathlib import Path
from dynaconf import Dynaconf

warnings.filterwarnings("ignore", category=SyntaxWarning)


def get_config_dir():
    """
    Determines the configuration directory.
    Priority:
    1. Environment variable 'CALLER_CONFIG_DIR'
    2. Environment variable 'CALLER_CONFIG' (takes the parent directory)
    3. Default local paths relative to the source tree
    4. Current working directory
    """
    for env_var in ["CALLER_CONFIG_DIR", "CALLER_CONFIG"]:
        path_str = os.environ.get(env_var)
        if path_str:
            p = Path(path_str).resolve()
            if p.is_dir():
                return p
            return p.parent

    current_file = Path(__file__).resolve()

    p_src_config = current_file.parent.parent.parent.parent / "src" / "config"
    if p_src_config.is_dir():
        return p_src_config

    p_alt_config = current_file.parent.parent / "config"
    if p_alt_config.is_dir():
        return p_alt_config

    p_cwd_src_config = Path.cwd() / "src" / "config"
    if p_cwd_src_config.is_dir():
        return p_cwd_src_config

    p_cwd_config = Path.cwd() / "config"
    if p_cwd_config.is_dir():
        return p_cwd_config

    return p_src_config


CONFIG_DIR = get_config_dir()

settings_files = [
    CONFIG_DIR / "settings.toml",
    CONFIG_DIR / ".secrets.toml",
]

env_caller_config = os.environ.get("CALLER_CONFIG")
if env_caller_config:
    p_env = Path(env_caller_config).resolve()
    if p_env.is_file() and p_env not in settings_files:
        settings_files.insert(0, p_env)

settings = Dynaconf(
    envvar_prefix="DYNACONF",
    settings_files=settings_files,
    environments=False,
    load_dotenv=True,
    merge_enabled=True,
)
