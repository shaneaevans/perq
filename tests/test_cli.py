import json
import subprocess
import sys
import tomllib
from pathlib import Path

from perq import Query, SQLiteStore, index

ROOT = Path(__file__).resolve().parents[1]


def cli(*args, input=None):
    return subprocess.run(
        [sys.executable, "-m", "perq", *map(str, args)],
        input=input,
        text=True,
        capture_output=True,
    )


def test_build_match_inspect_examples(tmp_path):
    path = tmp_path / "index.sqlite"
    result = cli("build", "--index", path, "--queries", ROOT / "examples/queries.jsonl")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stderr)["indexed_queries"] == 3
    result = cli("match", "--index", path, "--documents", ROOT / "examples/documents.jsonl")
    assert result.returncode == 0, result.stderr
    assert [json.loads(line) for line in result.stdout.splitlines()] == [
        {"id": "doc-1", "matches": ["data-alert"]},
        {"id": "doc-2", "matches": ["python-route", "price-only"]},
        {"id": "doc-3", "matches": []},
    ]
    result = cli("inspect", "--index", path)
    assert result.returncode == 0
    assert len(result.stdout.splitlines()) == 3


def test_invalid_input_line_and_atomic_rebuild(tmp_path):
    path = tmp_path / "index.sqlite"
    with SQLiteStore(path) as store:
        index([Query.from_text(1, "alpha")], store)
    result = cli(
        "build", "--index", path, input='{"id":2,"terms":[["beta"]]}\n{"id":3,"terms":[[]]}\n'
    )
    assert result.returncode == 2
    assert "-:2:" in result.stderr
    assert "Traceback" not in result.stderr
    result = cli("match", "--index", path, input='{"text":"alpha"}\n')
    assert json.loads(result.stdout) == {"id": 0, "matches": [1]}


def test_missing_index_fails_cleanly(tmp_path):
    result = cli("match", "--index", tmp_path / "missing", input='{"text":"alpha"}')
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_version():
    result = cli("--version")
    assert result.returncode == 0
    expected = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert result.stdout.strip() == expected
