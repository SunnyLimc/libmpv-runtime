# Contributing

Run the complete local control-plane gate before handoff:

```shell
uv sync --locked --extra dev
uv run libmpv-runtime contract validate
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest --cov=libmpv_runtime --cov-report=term-missing --cov-fail-under=80
```

Also parse every shell script and run `actionlint` after workflow changes. Build
the wheel and confirm that `src/libmpv_runtime/templates/` is present in it.

Contract changes must update typed models, JSON Schemas, fixtures, generated
package expectations, and documentation together. A validator may emit only a
raw report; only the evidence layer seals reports, and only the validation
fan-in may declare a cross-platform run complete. Never rediscover an upstream
release after a plan exists and never manually turn a failed report into a pass.

Run the affected native probe and both minimum/current real MediaKit consumers
when the necessary host is available. A local unit test may exercise orchestration
but is not a substitute for the platform validator used by promotion.
