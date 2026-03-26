from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "contracts"


class ContractValidationError(ValueError):
    pass


def _path_for(contract_name: str) -> Path:
    token = str(contract_name or "").strip()
    if not token:
        raise ContractValidationError("Contract name is required")
    path = (_CONTRACT_ROOT / f"{token}.json").resolve()
    if not path.exists():
        raise ContractValidationError(f"Contract not found: {token}")
    return path


def load_contract(contract_name: str) -> dict[str, Any]:
    path = _path_for(contract_name)
    return json.loads(path.read_text(encoding="utf-8"))


def _expect_type(value: Any, expected: str, path: str) -> None:
    if expected == "object":
        if not isinstance(value, dict):
            raise ContractValidationError(f"{path}: expected object")
        return
    if expected == "array":
        if not isinstance(value, list):
            raise ContractValidationError(f"{path}: expected array")
        return
    if expected == "string":
        if not isinstance(value, str):
            raise ContractValidationError(f"{path}: expected string")
        return
    if expected == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ContractValidationError(f"{path}: expected number")
        return
    if expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ContractValidationError(f"{path}: expected integer")
        return
    if expected == "boolean":
        if not isinstance(value, bool):
            raise ContractValidationError(f"{path}: expected boolean")
        return
    raise ContractValidationError(f"{path}: unsupported schema type '{expected}'")


def _validate_schema(value: Any, schema: dict[str, Any], path: str) -> None:
    expected_type = schema.get("type")
    if expected_type:
        _expect_type(value, str(expected_type), path)

    if "enum" in schema:
        allowed = list(schema.get("enum") or [])
        if value not in allowed:
            raise ContractValidationError(f"{path}: value {value!r} not in enum {allowed!r}")

    if expected_type == "object":
        props = dict(schema.get("properties") or {})
        required = list(schema.get("required") or [])
        additional = bool(schema.get("additionalProperties", True))

        for key in required:
            if key not in value:
                raise ContractValidationError(f"{path}: missing required key '{key}'")

        if not additional:
            unknown = sorted(k for k in value if k not in props)
            if unknown:
                raise ContractValidationError(
                    f"{path}: unknown keys not allowed: {', '.join(unknown)}"
                )

        for key, child in props.items():
            if key not in value:
                continue
            if not isinstance(child, dict):
                continue
            _validate_schema(value[key], child, f"{path}.{key}")

    if expected_type == "array":
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            raise ContractValidationError(
                f"{path}: expected at least {min_items} items, got {len(value)}"
            )
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                _validate_schema(item, item_schema, f"{path}[{idx}]")


def validate_contract_data(payload: dict[str, Any], contract_name: str) -> None:
    schema = load_contract(contract_name)
    _validate_schema(payload, schema, "$")


def validate_contract_file(path: str | Path, contract_name: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ContractValidationError("Contract payload must be a JSON object")
    validate_contract_data(payload, contract_name)
    return payload
