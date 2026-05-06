from __future__ import annotations

import argparse
import http.server
import json
import socket
import socketserver
import sys
import threading
import webbrowser
from functools import partial
from pathlib import Path
from urllib.parse import parse_qs, urlparse


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


def discover_runs(root: Path) -> list[dict[str, object]]:
    research_root = root / "short_term" / "research_logs"
    if not research_root.exists():
        return []

    runs: list[dict[str, object]] = []
    for run_dir in research_root.iterdir():
        if not run_dir.is_dir():
            continue
        run_meta = run_dir / "run_meta.json"
        if not run_meta.exists():
            continue
        try:
            meta = json.loads(run_meta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
        stat = run_meta.stat()
        runs.append(
            {
                "run_id": run_dir.name,
                "meeting_id": meta.get("meeting_id", ""),
                "model_name": meta.get("model_name", ""),
                "mtime": stat.st_mtime,
            }
        )
    runs.sort(key=lambda row: (float(row["mtime"]), str(row["run_id"])))
    return runs


def build_run_manifest(root: Path, run_id: str) -> dict[str, object]:
    run_dir = _safe_run_dir(root, run_id)
    if not run_dir.exists():
        return {"run_id": run_id, "files": {}}

    files: dict[str, list[str]] = {}
    for folder in ("responses", "prompts", "tool_calls", "candidates"):
        path = run_dir / folder
        files[folder] = sorted(
            child.name for child in path.iterdir() if child.is_file()
        ) if path.exists() else []

    files["root"] = sorted(
        child.name for child in run_dir.iterdir() if child.is_file()
    )
    return {"run_id": run_id, "files": files}


def _safe_run_dir(root: Path, run_id: str) -> Path:
    clean_run_id = run_id.strip()
    if not clean_run_id or Path(clean_run_id).name != clean_run_id:
        raise ValueError(f"Invalid run_id: {run_id!r}")
    research_root = (root / "short_term" / "research_logs").resolve()
    run_dir = (research_root / clean_run_id).resolve()
    if run_dir.parent != research_root:
        raise ValueError(f"Invalid run_id: {run_id!r}")
    return run_dir


class ViewerHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args: object, root: Path, **kwargs: object) -> None:
        self.root = root
        super().__init__(*args, directory=str(root), **kwargs)

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/short_term/view/runs.json":
            self._send_json({"runs": discover_runs(self.root)})
            return
        if path == "/short_term/view/run_manifest.json":
            run_id = parse_qs(parsed.query).get("run_id", [""])[0]
            try:
                self._send_json(build_run_manifest(self.root, run_id))
            except ValueError as exc:
                self.send_error(400, str(exc))
            return
        super().do_GET()

    def _send_json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    args = parse_args()
    root = repo_root()
    viewer_path = root / "short_term" / "view" / "research_log_viewer.html"
    if not viewer_path.exists():
        raise RuntimeError(f"Viewer not found: {viewer_path}")

    port = find_free_port(args.port)

    socketserver.TCPServer.allow_reuse_address = True
    handler = partial(ViewerHandler, root=root)
    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
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
