"""Persistent child services with bounded waits; blocking FUSE cannot hang the coordinator."""

import json
import queue
import subprocess
import sys
import threading
import time


class TaskTimeout(TimeoutError):
    pass


class IsolatedService:
    def __init__(self, module, timeout=120, heartbeat=None, environment=None):
        self.module, self.timeout = module, timeout
        self.heartbeat = heartbeat or (lambda: None)
        self.environment = environment
        self.process = None
        self.messages = None

    def _start(self):
        self.messages = queue.Queue()
        self.process = subprocess.Popen(
            [sys.executable, "-u", "-m", self.module], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=None, text=True, encoding="utf-8",
            start_new_session=True, env=self.environment,
        )
        process, messages = self.process, self.messages

        def read():
            try:
                for line in process.stdout:
                    messages.put(line)
            finally:
                messages.put(None)
        threading.Thread(target=read, daemon=True).start()

    def call(self, request, timeout=None):
        if self.process is None or self.process.poll() is not None:
            self.close()
            self._start()
        self.process.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        try:
            while True:
                self.heartbeat()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TaskTimeout(f"{self.module}: task exceeded deadline")
                try:
                    line = self.messages.get(timeout=min(0.5, remaining))
                except queue.Empty:
                    continue
                if line is None:
                    raise RuntimeError(f"{self.module}: service exited unexpectedly")
                result = json.loads(line)
                if not result.get("ok"):
                    raise RuntimeError(f"{self.module}: {result.get('error', 'unknown error')}")
                return result.get("value")
        except BaseException:
            self.close()
            raise

    def close(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    # D-state kernel I/O may survive kill; do not block here.
                    pass
        # A reader owns stdout. Closing it from this thread can itself block on
        # the buffered-reader lock if a child is stuck in kernel/FUSE I/O.
        if process.poll() is not None and process.stdin:
            process.stdin.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def serve(handler):
    for line in sys.stdin:
        try:
            value = handler(json.loads(line))
            response = {"ok": True, "value": value}
        except Exception as error:
            response = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        print(json.dumps(response, ensure_ascii=True), flush=True)
