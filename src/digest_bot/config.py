"""Load non-secret settings from config.yaml."""
import yaml


def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)
