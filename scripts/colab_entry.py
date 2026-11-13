"""Notebook facade: fresh Python imports per CLI, detached long-running worker."""

import os
import subprocess
import sys
import tempfile


class NotebookCrawler:
    def __init__(self, student_id, drive_root, code_root):
        self.student_id, self.drive_root, self.code_root = str(student_id), str(drive_root), code_root

    def command(self, action, *args):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.code_root / "src")
        command = [sys.executable, "-u", "-m", "ids_arxiv.colab_app", action,
                   "--student-id", self.student_id, "--drive-root", self.drive_root, *args]
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(command, cwd=self.code_root, env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            offset = 0
            try:
                for _ in range(200):
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
                    end = log.seek(0, 2)
                    log.seek(offset)
                    data = log.read(end-offset)
                    offset = end
                    if data:
                        print(data.decode("utf-8", errors="replace"), end="", flush=True)
                    if process.poll() is not None:
                        if process.returncode:
                            raise RuntimeError("Crawler control failed; inspect output above. No duplicate worker was started.")
                        return
                process.kill()
                raise TimeoutError("Control timeout; inspect existing worker before retrying")
            finally:
                # This is only a short-lived UI/CLI process, never the worker.
                if process.poll() is None:
                    process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass

    def monitor(self, seconds=30):
        if not 0 <= seconds <= 120:
            raise ValueError("Use short observations (0..120s); no keepalive loops")
        return self.command("monitor", "--seconds", str(seconds))

    def stop(self, confirm_run_id):
        if not confirm_run_id:
            raise ValueError("Exact run_id is required")
        return self.command("stop", "--confirm-run-id", confirm_run_id)


def start(student_id, drive_root, code_root):
    app = NotebookCrawler(student_id, drive_root, code_root)
    app.command("start")
    return app
