"""Drive tests/session_peer.py: one real, independent ISyCode session owner per process."""
import json
import os
import subprocess
import sys
from pathlib import Path

PEER = Path(__file__).with_name("session_peer.py")
SRC = Path(__file__).resolve().parents[1] / "src"


class PeerProcess:
    def __init__(self, root: Path, sessions: Path, **extra_env: str):
        env = {**os.environ, **extra_env,
               "PYTHONPATH": os.pathsep.join([str(SRC), os.environ.get("PYTHONPATH", "")])}
        self.process = subprocess.Popen(
            [sys.executable, str(PEER), str(root), str(sessions)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)

    def send(self, **command):
        self.process.stdin.write(json.dumps(command) + "\n")
        self.process.stdin.flush()

    def receive(self):
        line = self.process.stdout.readline()
        assert line, "peer process exited"
        return json.loads(line)

    def __call__(self, **command):
        self.send(**command)
        return self.receive()

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        self.process.wait(timeout=10)
