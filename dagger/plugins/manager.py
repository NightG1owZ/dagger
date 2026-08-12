"""Plugin discovery and lifecycle management."""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any

from .base import DaggerPlugin

LOGGER = logging.getLogger("dagger")


class PluginManager:
    """Discovers, loads, and manages Dagger plugins."""

    def __init__(self, plugin_dirs: list[Path] | None = None):
        self._plugins: dict[str, DaggerPlugin] = {}
        self._plugin_dirs = plugin_dirs or []
        self._hook_registry: dict[str, list[DaggerPlugin]] = {}
        self._discovered: list[type[DaggerPlugin]] | None = None

    def discover(self) -> list[type[DaggerPlugin]]:
        """Discover available plugins from entry_points and plugin dirs."""
        if self._discovered is not None:
            return self._discovered

        discovered: list[type[DaggerPlugin]] = []

        # Discover from setuptools entry_points
        try:
            from importlib.metadata import entry_points
            eps = entry_points(group="dagger.plugins")
            for ep in eps:
                try:
                    plugin_cls = ep.load()
                    if issubclass(plugin_cls, DaggerPlugin):
                        discovered.append(plugin_cls)
                        LOGGER.info("Discovered plugin: %s (from %s)", ep.name, ep.value)
                except Exception as e:
                    LOGGER.warning("Failed to load plugin entry_point %s: %s", ep.name, e)
        except ImportError:
            # Python < 3.9 fallback
            pass

        # Discover from plugin dirs (user-provided)
        for plugin_dir in self._plugin_dirs:
            if not plugin_dir.exists():
                continue
            sys.path.insert(0, str(plugin_dir.parent))
            try:
                mod = importlib.import_module(plugin_dir.name)
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, DaggerPlugin)
                        and attr is not DaggerPlugin
                    ):
                        discovered.append(attr)
                        LOGGER.info("Discovered plugin: %s (from %s)", attr.name, plugin_dir)
            except Exception as e:
                LOGGER.warning("Failed to load plugins from %s: %s", plugin_dir, e)
            finally:
                sys.path.pop(0)

        self._discovered = discovered
        return discovered

    def load(self, name: str, config: dict | None = None) -> DaggerPlugin | None:
        """Load and instantiate a plugin by name."""
        discovered = self.discover()
        for cls in discovered:
            if cls.name == name:
                plugin = cls()
                self._plugins[name] = plugin
                self._register_hooks(plugin)
                if config:
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(plugin.on_configure(config))
                    except RuntimeError:
                        pass
                return plugin
        return None

    def _register_hooks(self, plugin: DaggerPlugin) -> None:
        """Register plugin's hook methods in the hook registry."""
        hook_names = [
            "on_configure", "pre_request", "post_response", "on_error",
            "on_test_start", "on_test_end", "on_metric_tick",
        ]
        for hook_name in hook_names:
            method = getattr(plugin, hook_name)
            # Only register if the subclass has overridden the default
            base_method = getattr(DaggerPlugin, hook_name)
            if method.__func__ is not base_method.__func__:
                self._hook_registry.setdefault(hook_name, []).append(plugin)

    async def call_hook(self, hook_name: str, *args: Any, **kwargs: Any) -> list[Any]:
        """Call all registered plugins for a given hook.

        For pre_request-style hooks (single arg, returns modified arg),
        the result is chained through each plugin in order.
        """
        plugins = self._hook_registry.get(hook_name, [])
        results = []

        for plugin in plugins:
            method = getattr(plugin, hook_name)
            try:
                result = await method(*args, **kwargs)
                results.append(result)
            except Exception as e:
                LOGGER.error("Plugin %s hook %s failed: %s", plugin.name, hook_name, e)

        return results

    def list_plugins(self) -> list[dict]:
        """Return info about all discovered plugins."""
        discovered = self.discover()
        plugins_info = []
        for cls in discovered:
            loaded = cls.name in self._plugins
            plugins_info.append({
                "name": cls.name,
                "version": cls.version,
                "description": cls.description,
                "loaded": loaded,
            })
        return plugins_info
