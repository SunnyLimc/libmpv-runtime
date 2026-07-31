# Contributing

Changes to the runtime contract, source selection, normalization, validation,
package generation, or workflows must pass:

```shell
uv run libmpv-runtime contract validate
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

Run the affected native probe and real MediaKit consumer before handoff. Do not
weaken a gate or manually mark evidence true to accept a new upstream release.
When a candidate fails, preserve the previous promotion and fix the validator,
source rule, or upstream issue explicitly.
