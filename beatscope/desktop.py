"""Double-click entry point for the portable Beathi Studio build."""
from __future__ import annotations

import ctypes
import os

from beatscope.server import serve


def main() -> int:
    try:
        # Port zero avoids colliding with a development server. Release smoke
        # tests can pin a port and suppress the browser without maintaining a
        # second executable entry point.
        port = int(os.environ.get("BEATSCOPE_STUDIO_PORT", "0"))
        open_browser = os.environ.get("BEATSCOPE_NO_BROWSER") != "1"
        serve("127.0.0.1", port, open_browser=open_browser)
    except Exception as exc:  # pragma: no cover - desktop-only last resort
        ctypes.windll.user32.MessageBoxW(
            0,
            f"Beathi Studio could not start.\n\n{exc}",
            "Beathi Studio",
            0x10,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
