from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError, ValidationError  # type: ignore[import-untyped]
from referencing import Registry, Resource

from .errors import IntegrityError


def validate_document(root: Path, schema_name: str, value: Any) -> None:
    start = root.resolve()
    schema_dir: Path | None = None
    starts = (start, Path.cwd().resolve())
    for candidate_start in starts:
        for directory in (candidate_start, *candidate_start.parents):
            candidate = directory / "contracts"
            if (candidate / f"{schema_name}.schema.json").is_file():
                schema_dir = candidate
                break
        if schema_dir is not None:
            break
    if schema_dir is None:
        raise IntegrityError(f"cannot find contracts/{schema_name}.schema.json from {root}")
    schemas: dict[str, dict[str, Any]] = {}
    registry = Registry()
    for path in sorted(schema_dir.glob("*.schema.json")):
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise IntegrityError(f"invalid JSON Schema: {path}: {error}") from error
        if not isinstance(schema, dict) or not isinstance(schema.get("$id"), str):
            raise IntegrityError(f"JSON Schema has no absolute $id: {path}")
        schemas[path.stem.removesuffix(".schema")] = schema
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    try:
        schema = schemas[schema_name]
    except KeyError as error:
        raise IntegrityError(f"unknown JSON Schema: {schema_name}") from error
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(
            schema,
            registry=registry,
            format_checker=FormatChecker(),
        ).validate(value)
    except (SchemaError, ValidationError) as error:
        location = ".".join(str(item) for item in error.absolute_path) or "<root>"
        raise IntegrityError(
            f"{schema_name} schema validation failed at {location}: {error.message}"
        ) from error
