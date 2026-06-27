"""Pytest plugin: make `import voluptuous` resolve to probatio (drop-in proof).

This is a thin wrapper around ``probatio.compat.install_as_voluptuous``, the
supported, shipped mechanism (it also provides the ``voluptuous.schema_builder.
_compile_scalar`` internal that Home Assistant's ``annotatedyaml`` dependency
imports directly). The plugin only exists to call it before pytest collects Home
Assistant's tests, so the alias is in place when cv and its dependencies import
voluptuous.
"""

from probatio.compat import install_as_voluptuous

install_as_voluptuous()
