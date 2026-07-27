"""Entry point for the frozen command line.

Companion to :mod:`sidecar_entry`. PyInstaller freezes a *script*, not a module,
so it cannot be pointed at ``hana_engine/cli.py`` directly: run that way the file
has no parent package and its relative imports fail. This launcher imports the
package normally and hands over.

In a development checkout the equivalent command is:

    python -m hana_engine.cli --help
"""

from __future__ import annotations

import sys

from hana_engine.cli import main

if __name__ == "__main__":
    sys.exit(main())
