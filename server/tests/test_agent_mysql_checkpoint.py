import asyncio
import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest


pytestmark = pytest.mark.skipif(not os.environ.get("AGENT_TEST_CHECKPOINT_URL"), reason="Explicit isolated MySQL URL required")


def run(phase, thread):
    result = subprocess.run([sys.executable, "-m", "tests.agent_checkpoint_probe", phase, thread],
        capture_output=True, text=True, timeout=40)
    # Never include stderr/connection URLs in an assertion output.
    assert result.returncode == 0, f"checkpoint subprocess {phase} failed (exit {result.returncode})"
    return json.loads(result.stdout.splitlines()[-1])


def test_mysql_interrupt_survives_fresh_process_and_resume():
    thread = str(uuid4())
    assert run("prepare", thread)["status"] == "awaiting_confirmation"
    assert run("read", thread)["status"] == "awaiting_confirmation"
    resumed = run("resume", thread)
    assert resumed["status"] == "completed" and resumed["result"]["probe"] == thread
    assert run("read", thread) == resumed


def test_mysql_threads_are_isolated():
    a, b = str(uuid4()), str(uuid4())
    run("prepare", a); run("prepare", b)
    run("resume", a)
    assert run("read", b)["status"] == "awaiting_confirmation"
    assert run("read", a)["status"] == "completed"
