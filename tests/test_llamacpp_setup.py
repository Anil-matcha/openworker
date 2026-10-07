"""llama.cpp set up and run by OpenWorker (providers/llamacpp_setup.py, UX-057): where
models go, what it offers, the download into llama.cpp's cache, and the managed server's
start, check, switch, stop and clean-up — against a stand-in llama-server."""

from __future__ import annotations

import json
import os
import signal
import sys
import textwrap
import time
from pathlib import Path

import httpx
import pytest

from coworker.providers import llamacpp_setup as setup
from coworker.providers import local_machine

GB = 1024**3


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LLAMA_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "ollama"))
    monkeypatch.setattr(local_machine, "model_memory_bytes", lambda: 32 * GB)
    monkeypatch.setattr(setup, "_runner", None)
    yield
    if setup._runner is not None:
        setup._runner.shutdown()


def test_cache_dir_follows_llama_cpp(monkeypatch, tmp_path):
    for key in ("LLAMA_CACHE", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "HF_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(key, raising=False)
    assert setup.cache_dir() == Path.home() / ".cache" / "huggingface" / "hub"
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    assert setup.cache_dir() == tmp_path / "hf" / "hub"
    monkeypatch.setenv("LLAMA_CACHE", str(tmp_path / "llama"))
    assert setup.cache_dir() == tmp_path / "llama"


def _ollama_model(root: Path, name: str, tag: str, size: int, ns: str = "library") -> Path:
    digest = f"sha256:{name}{tag}".replace(".", "")
    manifest = root / "manifests" / "registry.ollama.ai" / ns / name / tag
    manifest.parent.mkdir(parents=True, exist_ok=True)
    layers = [
        {"mediaType": "application/vnd.ollama.image.license", "digest": "sha256:lic", "size": 10},
        {"mediaType": "application/vnd.ollama.image.model", "digest": digest, "size": size},
    ]
    manifest.write_text(json.dumps({"layers": layers}))
    blob = root / "blobs" / digest.replace(":", "-")
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(b"GGUF")
    return blob


def test_ollama_models_are_read_from_its_manifests(tmp_path):
    root = tmp_path / "ollama"
    blob = _ollama_model(root, "qwen3-coder", "30b", 18 * GB)
    _ollama_model(root, "mymodel", "latest", GB, ns="someone")
    # A manifest whose model file is missing is not offered.
    gone = root / "manifests" / "registry.ollama.ai" / "library" / "gone" / "1b"
    gone.parent.mkdir(parents=True)
    gone.write_text(json.dumps({"layers": [{"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:nope", "size": 1}]}))
    models = {m["name"]: m for m in setup.ollama_models()}
    assert set(models) == {"qwen3-coder:30b", "someone/mymodel:latest"}
    assert models["qwen3-coder:30b"]["path"] == str(blob)
    assert models["qwen3-coder:30b"]["size"] == 18 * GB


def test_overview_offers_what_fits_and_the_pull_commands(tmp_path, monkeypatch):
    _ollama_model(tmp_path / "ollama", "qwen3-coder", "30b", 18 * GB)
    _ollama_model(tmp_path / "ollama", "huge", "1t", 400 * GB)
    monkeypatch.setattr(setup, "find_llama_server", lambda: None)
    o = setup.overview()
    ids = [m["id"] for m in o["suggested"]]
    # 32 GB: the 36 GB Nemotron is too large; the others are offered.
    assert "nemotron-3.5-lightning" not in ids
    assert "gpt-oss-20b" in ids and "qwen3-coder-30b" in ids
    assert [m["name"] for m in o["ollama"]] == ["qwen3-coder:30b"]
    # Ollama already has qwen3-coder, so only gpt-oss gets a download command.
    assert [p["command"] for p in o["ollama_pull"]] == ["ollama pull gpt-oss:20b"]
    assert o["installed"] is None and o["install_command"] == "brew install llama.cpp"
    assert o["cache_dir"].endswith("cache") and o["phase"] == "idle" and o["autostart"] is False


def test_a_file_with_an_mtp_draft_beside_it_runs_with_the_draft(tmp_path):
    model = tmp_path / "Nemo-Q8_0.gguf"
    model.write_bytes(b"GGUF")
    plan = setup.runner()._plan({"kind": "file", "path": str(model)})
    assert "draft" not in plan
    (tmp_path / "mtp-Nemo-Q8_0.gguf").write_bytes(b"GGUF")
    plan = setup.runner()._plan({"kind": "file", "path": str(model)})
    assert plan["draft"].endswith("mtp-Nemo-Q8_0.gguf") and plan["spec_type"] == "draft-mtp"
    with pytest.raises(ValueError):
        setup.runner()._plan({"kind": "file", "path": str(tmp_path / "x.bin")})


def test_download_lands_in_the_hugging_face_layout_and_resumes(tmp_path, monkeypatch):
    entry = {"id": "t", "name": "T", "repo": "org/t-GGUF", "file": "t.gguf", "draft": "mtp-t.gguf"}
    blobs = {"t.gguf": b"M" * 5000, "mtp-t.gguf": b"D" * 300}
    monkeypatch.setattr(
        setup, "_hf_files", lambda repo: ("c0ffee", {f: {"size": len(b), "oid": f"oid-{f}"} for f, b in blobs.items()})
    )
    # Half of the main file is already there from an interrupted run.
    part = setup._repo_dir("org/t-GGUF") / "blobs" / "oid-t.gguf.incomplete"
    part.parent.mkdir(parents=True)
    part.write_bytes(blobs["t.gguf"][:2000])
    ranges = []

    def handler(req: httpx.Request) -> httpx.Response:
        name = req.url.path.rsplit("/", 1)[-1]
        assert "/resolve/c0ffee/" in req.url.path
        body = blobs[name]
        rng = req.headers.get("range")
        ranges.append((name, rng))
        if rng:
            start = int(rng.split("=")[1].rstrip("-"))
            return httpx.Response(206, content=body[start:])
        return httpx.Response(200, content=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "stream", lambda method, url, headers=None, **kw: client.stream(method, url, headers=headers))
    got = setup.runner()._download(entry)
    assert ranges == [("t.gguf", "bytes=2000-"), ("mtp-t.gguf", None)]
    snap = setup._repo_dir("org/t-GGUF") / "snapshots" / "c0ffee"
    assert Path(got["file"]) == snap / "t.gguf" and (snap / "t.gguf").is_symlink()
    assert (snap / "t.gguf").read_bytes() == blobs["t.gguf"]
    assert Path(got["draft"]).read_bytes() == blobs["mtp-t.gguf"]
    assert (setup._repo_dir("org/t-GGUF") / "refs" / "main").read_text() == "c0ffee"
    assert setup._downloaded(entry)
    assert setup.runner().progress["done"] == setup.runner().progress["total"] == 5300


# -- the managed server, against a stand-in llama-server --------------------------------

FAKE = textwrap.dedent(
    """
    import json, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1])
    alias = args[args.index("--alias") + 1]
    if "broken" in alias:
        print("E llama_model_load: error loading model", flush=True)
        sys.exit(1)
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def _send(self, obj):
            data = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            self._send({"status": "ok"} if self.path == "/health" else {"data": [{"id": alias}]})
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            msg = {"role": "assistant", "content": "hello"}
            if body.get("tools") and "notools" not in alias:
                msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function", "function": {"name": "get_time", "arguments": "{}"}}]}
            self._send({"choices": [{"message": msg}]})
    HTTPServer(("127.0.0.1", port), H).serve_forever()
    """
)


@pytest.fixture
def fake_server(tmp_path, monkeypatch):
    script = tmp_path / "fake_llama_server.py"
    script.write_text(FAKE)
    exe = tmp_path / "llama-server"
    exe.write_text(f"#!/bin/sh\nexec {sys.executable} {script} \"$@\"\n")
    exe.chmod(0o755)
    monkeypatch.setattr(setup, "find_llama_server", lambda: str(exe))
    monkeypatch.setattr(setup, "DEFAULT_PORT", 18_900)
    return exe


def _settle(r: setup.LlamaCppRunner, timeout: float = 30) -> dict:
    end = time.monotonic() + timeout
    while r.busy() and time.monotonic() < end:
        time.sleep(0.1)
    return r.state()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _gguf(tmp_path: Path, name: str) -> str:
    p = tmp_path / f"{name}.gguf"
    p.write_bytes(b"GGUF")
    return str(p)


def test_start_checks_points_the_provider_and_switches(fake_server, tmp_path):
    r = setup.runner()
    told = []
    r.on_running = lambda url, alias: told.append((url, alias))
    assert r.start({"kind": "file", "path": _gguf(tmp_path, "good")})["ok"]
    st = _settle(r)
    assert st["phase"] == "running", st["error"]
    assert st["check"] == {"answers": True, "tools": True}
    assert told == [(f"http://127.0.0.1:{st['address'].split(':')[1]}", "good")]
    first = json.loads(setup._state_path("llamacpp.pid").read_text())
    assert _alive(first["pid"]) and _alive(first["watcher"])
    assert setup._load_settings()["choice"]["path"].endswith("good.gguf")

    # Switch: the first server goes, the new one answers but cannot call tools.
    r.start({"kind": "file", "path": _gguf(tmp_path, "notools")})
    st = _settle(r)
    assert st["phase"] == "running" and st["check"] == {"answers": True, "tools": False}
    assert not _alive(first["pid"])

    r.stop()
    assert r.state()["phase"] == "idle"
    assert not setup._state_path("llamacpp.pid").exists()


def test_a_model_that_fails_to_load_shows_the_error(fake_server, tmp_path):
    r = setup.runner()
    r.start({"kind": "file", "path": _gguf(tmp_path, "broken")})
    st = _settle(r)
    assert st["phase"] == "failed"
    assert "error loading model" in st["error"]


def test_the_server_does_not_outlive_openworker(fake_server, tmp_path):
    """The desktop app ends its server with SIGKILL: the watcher stops llama-server."""
    import subprocess

    code = textwrap.dedent(
        f"""
        import json, os, signal, sys, time
        sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})
        from coworker.providers import llamacpp_setup as s
        s.find_llama_server = lambda: {str(fake_server)!r}
        s.DEFAULT_PORT = 18950
        r = s.runner()
        r.start({{"kind": "file", "path": {_gguf(tmp_path, "orphan")!r}}})
        while r.busy():
            time.sleep(0.1)
        print(json.dumps(r.state()["phase"]), flush=True)
        os.kill(os.getpid(), signal.SIGKILL)
        """
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env=os.environ)
    assert '"running"' in out.stdout, out.stderr
    pid = json.loads(setup._state_path("llamacpp.pid").read_text())["pid"]
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.2)
    assert not _alive(pid)


def test_app_start_reaps_a_leftover_and_honours_autostart(fake_server, tmp_path, monkeypatch):
    import subprocess

    leftover = subprocess.Popen(["sleep", "60"])
    setup._state_path("llamacpp.pid").parent.mkdir(parents=True, exist_ok=True)
    setup._state_path("llamacpp.pid").write_text(json.dumps({"pid": leftover.pid}))
    monkeypatch.setattr(setup, "_is_llama_server", lambda pid: pid == leftover.pid)
    monkeypatch.setattr(setup, "supported", lambda: True)
    r = setup.runner()
    r.on_app_start()
    leftover.wait(timeout=10)
    assert r.state()["phase"] == "idle"  # autostart is off by default

    setup._save_settings({"autostart": True, "choice": {"kind": "file", "path": _gguf(tmp_path, "auto")}})
    r.on_app_start()
    assert _settle(r)["phase"] == "running"
