"""Launch a verified installed application with a child-owned loopback socket."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import uvicorn


def main() -> None:
    token = os.environ["P2R_LAUNCH_TOKEN"]
    if len(token) < 32 or not token.isascii() or not token.isalnum():
        raise ValueError("Invalid local launch credential")
    ready = Path(os.environ["P2R_READY_FILE"])
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    from app.local_security import LocalAccess
    from app.main import app
    from app.storage import has_active_work

    protected = LocalAccess(app, token=token, port=port)
    server = uvicorn.Server(uvicorn.Config(protected, log_level="warning", access_log=False))

    def shutdown():
        if has_active_work():
            return False
        server.should_exit = True
        return True

    protected.shutdown = shutdown
    # Readiness describes the reserved socket. The launcher must also probe health.
    temporary = ready.with_suffix(".tmp")
    temporary.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    temporary.replace(ready)
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
        ready.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
