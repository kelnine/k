"""A fake plug-in package used to test registry discovery."""

from kterminal.core.registry import Registry

PLUGINS: Registry[type] = Registry("sample")
