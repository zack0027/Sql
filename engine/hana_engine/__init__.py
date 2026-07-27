"""HANA Knowledge Engine — local technical knowledge engine.

The engine is a plain Python package: no Tauri, no web server, no network. It can
be imported, tested and driven from a script without any part of the desktop
application present.
"""

from .engine import EngineStatus, KnowledgeEngine, ProjectStats

__all__ = ["KnowledgeEngine", "EngineStatus", "ProjectStats", "__version__"]

__version__ = "0.1.0"
