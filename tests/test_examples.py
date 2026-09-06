import json
import re
import runpy
from pathlib import Path

import jsonschema

from perq import Document, Query

ROOT = Path(__file__).resolve().parents[1]


def test_examples_follow_json_schemas():
    for name, factory in [("query", Query.from_dict), ("document", Document.from_dict)]:
        schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        filename = "queries" if name == "query" else "documents"
        for line in (ROOT / f"examples/{filename}.jsonl").read_text().splitlines():
            record = json.loads(line)
            jsonschema.validate(record, schema)
            factory(record)


def test_python_recipe():
    runpy.run_path(str(ROOT / "examples/alerts.py"), run_name="__main__")


def test_readme_python_examples():
    namespace = {}
    for code in re.findall(r"```python\n(.*?)```", (ROOT / "README.md").read_text(), re.DOTALL):
        exec(compile(code, "README.md", "exec"), namespace)
