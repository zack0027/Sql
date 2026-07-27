"""Entry point for the frozen sidecar.

PyInstaller freezes a *script*, not a module, so it cannot be pointed at
``hana_engine/ipc/server.py`` directly: run that way the file has no parent
package and its relative imports fail. This launcher imports the package
normally and hands over, which keeps ``hana_engine`` a proper package inside
the bundle.

In a development checkout the equivalent command is:

    python -m hana_engine.ipc.server [ruta-de-la-base]
"""

from __future__ import annotations

import sys

from hana_engine.ipc.server import main

if __name__ == "__main__":
    sys.exit(main())
