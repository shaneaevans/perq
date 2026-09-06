# Contributing

Use Python 3.11 or later and install `.[dev,lmdb]` in a virtual environment.
Run `python -m pytest`, `ruff check .`, and `ruff format --check .` before submitting
a change. CI tests supported Python versions and all storage backends on Linux,
macOS, and Windows, and builds and validates both wheel and source distributions.

Changes to Boolean selection must include an independent reference comparison.
Changes to storage must test rollback, replacement, reopening, and snapshot consistency.
Treat input order and the published JSON schema as part of the public API. Add a
file-format version change and migration guidance when changing persistent encoding.
Read-only use must never disable LMDB's reader coordination.

Run performance experiments with `benchmarks/run.py`; record the full command,
environment, workload, build cost, memory, and match counts. Report synthetic results
as synthetic. Open an issue with representative query/document shapes when proposing
another database backend or a new query operator.

Release preparation: update the version and changelog; run the complete checks;
build distributions with `python -m build`; validate with `twine check dist/*`;
install the wheel in a clean environment and exercise the CLI outside this checkout.
The CI workflow produces reviewable artifacts. The separate `publish.yml` workflow
publishes a version tag to PyPI when manually dispatched; see [releasing](docs/releasing.md)
for the trusted publisher configuration and release commands.
