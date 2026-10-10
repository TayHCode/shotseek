"""All product-derived identifiers."""
NAME = "shotseek"
ENV_PREFIX = NAME.upper() + "_"
CONFIG_FILE = "config.toml"


def env(suffix):
    return ENV_PREFIX + suffix
