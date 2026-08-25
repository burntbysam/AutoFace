"""AutoFace — batch flat-pattern DWG exporter for Autodesk Inventor drawings."""

# Deliberately does NOT re-export a name `version`: that would shadow the
# `autoface.version` submodule, so `from autoface import version` would hand
# back a function and `version.build_info` would fail confusingly.
from .version import build_details, build_id, build_info, describe, version as _version

__version__ = _version()

__all__ = ["__version__", "build_details", "build_id", "build_info", "describe"]
