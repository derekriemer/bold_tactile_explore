"""Drive the real stdio server with raw JSON-RPC lines, so stdout cleanliness is checked too."""

import json
import queue
import shutil
import subprocess
import sys
import threading

import pytest
from conftest import FIXTURE_BBOX, FIXTURE_CACHE

from tactile_terrain import api

EXPECTED_TOOLS = {
    "check_print",
    "doctor",
    "create_sampler",
    "resolve_area",
    "create_model",
    "update_model",
    "describe_model",
    "analyze_model",
    "list_capabilities",
    "list_models",
    "get_spec",
}
TIMEOUT_S = 120


class Server:
    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-I", "-m", "tactile_terrain.cli", "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        self.lines: queue.Queue[str] = queue.Queue()
        self.raw: list[str] = []
        threading.Thread(target=self._pump, daemon=True).start()
        self._id = 0

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(line)

    def send(self, method, params=None, notify=False):
        message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self._id += 1
            message["id"] = self._id
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        return None if notify else self._id

    def reply(self, request_id):
        while True:
            line = self.lines.get(timeout=TIMEOUT_S)
            self.raw.append(line)
            message = json.loads(line)  # anything that is not JSON-RPC fails right here
            assert message["jsonrpc"] == "2.0"
            if message.get("id") == request_id:
                return message

    def call(self, tool, **arguments):
        return self.reply(self.send("tools/call", {"name": tool, "arguments": arguments}))

    def close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture
def server(models_dir):
    shutil.copytree(FIXTURE_CACHE, models_dir / "m" / "cache", dirs_exist_ok=True)
    api.create_model(
        "m",
        area=list(FIXTURE_BBOX),
        print={"scale_m_per_mm": 15, "z_exaggeration": 1.5},
        mode="flat",
        features=[
            {"type": "lift", "provider": "osm", "style": "pointed", "filter": {"aerialway": "all"}}
        ],
    )
    s = Server()
    init = s.reply(
        s.send(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        )
    )
    assert "instructions" in init["result"] and "resolve_area" in init["result"]["instructions"]
    s.send("notifications/initialized", notify=True)
    yield s
    s.close()


def text_of(reply):
    assert not reply["result"].get("isError"), reply
    return "".join(c["text"] for c in reply["result"]["content"] if c["type"] == "text")


def test_lists_the_full_tool_set(server):
    tools = server.reply(server.send("tools/list"))["result"]["tools"]
    assert EXPECTED_TOOLS <= {t["name"] for t in tools}
    assert all(t["description"] for t in tools)


def test_tools_return_text_and_stdout_is_only_json_rpc(server):
    assert "Capabilities" in text_of(server.call("list_capabilities"))
    assert "m: flat" in text_of(server.call("list_models"))
    described = text_of(server.call("describe_model", name="m"))
    assert "Orientation" in described and "Tactile legend" in described
    assert json.loads(text_of(server.call("get_spec", name="m")))["name"] == "m"
    assert server.raw  # every line parsed as JSON in reply()


def test_errors_come_back_as_tool_errors(server):
    reply = server.call("describe_model", name="missing")
    assert reply["result"]["isError"]
    assert "missing" in reply["result"]["content"][0]["text"]


def test_create_model_reports_progress_and_returns_analysis(server, models_dir):
    shutil.copytree(FIXTURE_CACHE, models_dir / "built" / "cache", dirs_exist_ok=True)
    request = server.send(
        "tools/call",
        {
            "name": "create_model",
            "arguments": {
                "name": "built",
                "bbox": list(FIXTURE_BBOX),
                "features": [],
                "scale_m_per_mm": 15,
                "mode": "flat",
            },
            "_meta": {"progressToken": "build-1"},
        },
    )
    reply = server.reply(request)
    text = text_of(reply)
    assert "Built model 'built'" in text and "Analysis:" in text
    progress = [json.loads(r) for r in server.raw if '"notifications/progress"' in r]
    assert progress and all(p["params"]["progressToken"] == "build-1" for p in progress)
    assert any("Running" in p["params"].get("message", "") for p in progress)
