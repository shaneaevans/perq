"""Verify the built wheel and CLI outside the source checkout, without extras."""

import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    wheels = list((root / "dist").glob("perq-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("expected exactly one built wheel in dist/")
    with tempfile.TemporaryDirectory(prefix="perq-wheel-") as directory:
        directory = Path(directory)
        venv.EnvBuilder(with_pip=True).create(directory / "venv")
        python = directory / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(
            [str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheels[0])],
            check=True,
            cwd=directory,
        )
        command = [str(python), "-I", "-m", "perq"]
        index = directory / "queries.sqlite"
        subprocess.run(
            command + ["build", "--index", str(index)],
            input='{"id":"test","terms":[["alpha"]]}\n',
            text=True,
            check=True,
            cwd=directory,
        )
        result = subprocess.run(
            command + ["match", "--index", str(index)],
            input='{"text":"ALPHA"}\n',
            text=True,
            capture_output=True,
            check=True,
            cwd=directory,
        )
        assert json.loads(result.stdout) == {"id": 0, "matches": ["test"]}
        subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "from perq import MemoryStore, Query, QueryMatcher, Document, index; "
                "s=MemoryStore(); index([Query.from_text(1,'alpha')],s); "
                "assert list(QueryMatcher(s).matches(Document.from_text('ALPHA')))==[1]",
            ],
            check=True,
            cwd=directory,
        )
    print("Clean wheel install, MemoryStore, SQLiteStore, and CLI passed without extras.")


if __name__ == "__main__":
    main()
