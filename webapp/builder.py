"""Keeps one build_worker.py process alive for the web app and sends it build jobs.

Every program is screened with check_code first. A job that takes longer than the timeout
kills the worker (the next job starts a fresh one), so a hanging program cannot block the app.
"""
import json
import queue
import subprocess
import sys
import threading
from pathlib import Path

from candidates import check_code

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_SECONDS = 120


class Builder:
    def __init__(self):
        self.process = None
        self.replies = queue.Queue()
        self.lock = threading.Lock()  # one job at a time

    def _start(self):
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "build_worker.py")], cwd=ROOT, text=True, bufsize=1,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.replies = queue.Queue()
        threading.Thread(target=self._read, args=(self.process, self.replies), daemon=True).start()
        self.replies.get(timeout=TIMEOUT_SECONDS)  # wait for {"ready": true}

    @staticmethod
    def _read(process, replies):
        for line in process.stdout:
            try:
                replies.put(json.loads(line))
            except json.JSONDecodeError:
                continue  # not a reply (e.g. a library writing to stdout while loading)

    def _stop(self):
        if self.process:
            self.process.kill()
            self.process = None

    def warm_up(self):
        """Start the build process ahead of the first job (CadQuery takes about 5 s to load)."""
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self._start()

    def build(self, code_path, output_path, overrides=None):
        """Export the program with overrides to output_path. Returns an error message or None."""
        problems = check_code(Path(code_path).read_text(encoding="utf-8"))
        if problems:
            return "rejected before running: " + "; ".join(problems)
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self._start()
            job = {"code": str(code_path), "output": str(output_path), "overrides": overrides or {}}
            self.process.stdin.write(json.dumps(job) + "\n")
            self.process.stdin.flush()
            try:
                reply = self.replies.get(timeout=TIMEOUT_SECONDS)
            except queue.Empty:
                self._stop()
                return f"timed out after {TIMEOUT_SECONDS} s"
        return None if reply.get("ok") else reply.get("error", "build failed")

    def close(self):
        self._stop()
