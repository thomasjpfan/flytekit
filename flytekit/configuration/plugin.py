"""Defines a plugin API allowing other libraries to modify the behavior of flytekit.

Libraries can register by defining an object that follows the same API as FlytekitPlugin
and providing entry pont with the group name "flytekit.plugin". In `setuptools`,
you can specific them with:

```python
setup(entry_points={
    "flytekit.plugin": ["my_plugin=..."]
})
```

or in pyproject.toml:

```toml
[project.entry-points."flytekit.plugin"]
my_plugin = "..."
```
"""
from typing import Optional

from click import Command
from importlib_metadata import entry_points

from flytekit.configuration import Config, get_config_file
from flytekit.loggers import cli_logger
from flytekit.remote import FlyteRemote


class FlytekitPlugin:
    @staticmethod
    def get_remote(
        config: Optional[str], project: str, domain: str, data_upload_location: Optional[str] = None
    ) -> FlyteRemote:
        """Get FlyteRemote object for CLI session."""
        cfg_file = get_config_file(config)
        if cfg_file is None:
            cfg_obj = Config.for_sandbox()
            cli_logger.info("No config files found, creating remote with sandbox config")
        else:  # pragma: no cover
            cfg_obj = Config.auto(config)
            cli_logger.info(f"Creating remote with config {cfg_obj}" + (f" with file {config}" if config else ""))
        return FlyteRemote(
            cfg_obj, default_project=project, default_domain=domain, data_upload_location=data_upload_location
        )

    @staticmethod
    def configure_pyflyte_cli(main: Command) -> Command:
        """Configure pyflyte's CLI."""
        return main


def _get_plugin():
    """Get plugin for entrypoint."""
    plugins = list(entry_points(group="flytekit.plugin"))

    if not plugins:
        return FlytekitPlugin

    if len(plugins) >= 2:
        plugin_names = [p.name for p in plugins]
        cli_logger.info(f"Multiple plugins seen for flytekit.plugin: {plugin_names}")

    plugin_to_load = plugins[0]
    cli_logger.info(f"Loading plugin: {plugin_to_load.name}")
    return plugin_to_load.load()


_GLOBAL_CONFIG = {"plugin": _get_plugin()}


def get_plugin():
    """Get current plugin"""
    return _GLOBAL_CONFIG["plugin"]
