from __future__ import annotations

import argparse
import http.server
import os
import socket
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve and open the short-term research log viewer."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Preferred port. If unavailable, the next free port is used.",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="Optional run id to put in the URL hash for manual reference.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the server without opening a browser.",
    )
    return parser.parse_args()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def find_free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free port found from {preferred} to {preferred + 99}.")


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    args = parse_args()
    root = repo_root()
    viewer_path = root / "short_term" / "view" / "research_log_viewer.html"
    if not viewer_path.exists():
        raise RuntimeError(f"Viewer not found: {viewer_path}")

    port = find_free_port(args.port)
    os.chdir(root)

    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("127.0.0.1", port), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}/short_term/view/research_log_viewer.html"
    if args.run_id:
        url += f"#{args.run_id}"

    print(f"Serving repo root: {root}")
    print(f"Viewer URL: {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        webbrowser.open(url)

    try:
        while True:
            thread.join(timeout=1)
    except KeyboardInterrupt:
        print("\nStopping server.")
        server.shutdown()
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()
