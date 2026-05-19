from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from aegis_code.api.errors import AegisApiError
import aegis_code.server.contracts as contracts
import aegis_code.server.handlers as handlers


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    category: str
    input_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "input_schema": self.input_schema,
        }


def _object_schema(*, properties: dict[str, Any], required: list[str] | None = None, additional_properties: bool = False) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": additional_properties,
    }


TOOL_DEFINITIONS: dict[str, ToolDefinition] = {
    "health": ToolDefinition(
        name="health",
        description="Service liveness and adapter readiness metadata.",
        category="read_only",
        input_schema=_object_schema(
            properties={"workspace": {"type": "string", "description": "Optional project workspace path."}}
        ),
    ),
    "setup_check": ToolDefinition(
        name="setup_check",
        description="Project setup/readiness status.",
        category="read_only",
        input_schema=_object_schema(properties={"workspace": {"type": "string"}}),
    ),
    "status": ToolDefinition(
        name="status",
        description="Current project state and latest run summary.",
        category="read_only",
        input_schema=_object_schema(properties={"workspace": {"type": "string"}}),
    ),
    "report": ToolDefinition(
        name="report",
        description="Detailed latest run report with typed summary sections.",
        category="read_only",
        input_schema=_object_schema(properties={"workspace": {"type": "string"}}),
    ),
    "latest_diff": ToolDefinition(
        name="latest_diff",
        description="Latest accepted diff path and optional diff text preview.",
        category="read_only",
        input_schema=_object_schema(
            properties={
                "workspace": {"type": "string"},
                "include_text": {"type": "boolean"},
                "max_text_bytes": {"type": "integer", "minimum": 1},
            }
        ),
    ),
    "patch": ToolDefinition(
        name="patch",
        description="Generate a proposal-only patch (no source mutation).",
        category="proposal",
        input_schema=_object_schema(
            properties={
                "workspace": {"type": "string"},
                "task": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}},
                "operation": {"type": "string"},
                "anchor": {"type": "string"},
                "symbol": {"type": "string"},
                "allow_create": {"type": "boolean"},
                "max_files": {"type": "integer", "minimum": 1},
                "dry_run": {"type": "boolean"},
                "mode": {"type": "string"},
                "target": {"type": "string"},
                "budget": {"type": "number"},
                "analyze_failures": {"type": "boolean"},
                "session": {"type": "string"},
                "no_report": {"type": "boolean"},
                "provider_timeout_seconds": {"type": "integer", "minimum": 1},
            },
            required=["task", "files"],
        ),
    ),
    "apply_check": ToolDefinition(
        name="apply_check",
        description="Run apply safety/validation checks without mutating source files.",
        category="mutation",
        input_schema=_object_schema(
            properties={
                "workspace": {"type": "string"},
                "diff_path": {"type": "string"},
            }
        ),
    ),
    "apply_confirm": ToolDefinition(
        name="apply_confirm",
        description="Apply an approved diff with explicit mutation confirmation.",
        category="mutation",
        input_schema=_object_schema(
            properties={
                "workspace": {"type": "string"},
                "diff_path": {"type": "string"},
                "run_tests": {"type": "boolean"},
            }
        ),
    ),
}


_TOOL_DISPATCH: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    "health": lambda args: handlers.health_handler(workspace=str(args.get("workspace", "."))),
    "setup_check": lambda args: handlers.setup_check_handler(args),
    "status": lambda args: handlers.status_handler(args),
    "report": lambda args: handlers.report_handler(args),
    "latest_diff": lambda args: handlers.latest_diff_handler(
        args,
        include_text=bool(args.get("include_text", True)),
        max_text_bytes=int(args.get("max_text_bytes", handlers.guards.MAX_DIFF_TEXT_BYTES)),
    ),
    "patch": lambda args: handlers.patch_handler(args),
    "apply_check": lambda args: handlers.apply_check_handler(args),
    "apply_confirm": lambda args: handlers.apply_confirm_handler(args),
}


def get_tool(name: str) -> ToolDefinition | None:
    return TOOL_DEFINITIONS.get(str(name))


def list_tools() -> list[dict[str, Any]]:
    return [TOOL_DEFINITIONS[name].to_dict() for name in sorted(TOOL_DEFINITIONS.keys())]


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)


def _validate_schema_value(*, schema: Mapping[str, Any], value: Any, path: str) -> list[str]:
    errors: list[str] = []
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, Mapping):
            return [f"{path} must be an object"]
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional = bool(schema.get("additionalProperties", True))
        if isinstance(required, list):
            for field in required:
                if field not in value:
                    errors.append(f"{path}.{field} is required")
        if isinstance(properties, Mapping):
            for key, child in properties.items():
                if key in value and isinstance(child, Mapping):
                    errors.extend(_validate_schema_value(schema=child, value=value[key], path=f"{path}.{key}"))
            if not additional:
                unknown = sorted(set(str(item) for item in value.keys()) - set(str(item) for item in properties.keys()))
                for field in unknown:
                    errors.append(f"{path}.{field} is not allowed")
        return errors
    if schema_type == "string":
        if not isinstance(value, str):
            errors.append(f"{path} must be a string")
        return errors
    if schema_type == "boolean":
        if not isinstance(value, bool):
            errors.append(f"{path} must be a boolean")
        return errors
    if schema_type == "integer":
        if not _is_integer(value):
            errors.append(f"{path} must be an integer")
        else:
            minimum = schema.get("minimum")
            if minimum is not None and value < int(minimum):
                errors.append(f"{path} must be >= {int(minimum)}")
        return errors
    if schema_type == "number":
        if not _is_number(value):
            errors.append(f"{path} must be a number")
        else:
            minimum = schema.get("minimum")
            if minimum is not None and float(value) < float(minimum):
                errors.append(f"{path} must be >= {float(minimum)}")
        return errors
    if schema_type == "array":
        if not isinstance(value, (list, tuple)):
            errors.append(f"{path} must be an array")
            return errors
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(value):
                errors.extend(_validate_schema_value(schema=items, value=item, path=f"{path}[{index}]"))
        return errors
    return errors


def _validate_arguments(tool_name: str, schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> list[str]:
    return _validate_schema_value(schema=schema, value=arguments, path=f"arguments({tool_name})")


def _attach_request_id(envelope: dict[str, Any], request_id: str | None) -> dict[str, Any]:
    if request_id is None:
        return envelope
    meta = envelope.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        envelope["meta"] = meta
    meta["request_id"] = str(request_id)
    return envelope


def invoke_tool(
    name: str,
    arguments: Mapping[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    tool_name = str(name)
    if arguments is None:
        args: dict[str, Any] = {}
    elif isinstance(arguments, Mapping):
        args = dict(arguments)
    else:
        return _attach_request_id(
            contracts.to_error(
                AegisApiError("MCP tool arguments must be an object."),
                details={
                    "code": "INVALID_ARGUMENTS",
                    "tool": tool_name,
                    "expected_type": "object",
                },
            ),
            request_id,
        )
    tool = get_tool(tool_name)
    if tool is None:
        return _attach_request_id(
            contracts.to_error(
                AegisApiError(f"Unknown MCP tool: {tool_name}"),
                workspace=str(args.get("workspace", ".")),
                details={
                    "code": "UNKNOWN_TOOL",
                    "tool": tool_name,
                    "available_tools": sorted(TOOL_DEFINITIONS.keys()),
                    "valid_tool_names": sorted(TOOL_DEFINITIONS.keys()),
                },
            ),
            request_id,
        )
    dispatch = _TOOL_DISPATCH.get(tool_name)
    if dispatch is None:
        return _attach_request_id(
            contracts.to_error(
                AegisApiError(f"MCP tool is not dispatchable: {tool_name}"),
                workspace=str(args.get("workspace", ".")),
                details={"code": "MISSING_DISPATCH", "tool": tool_name},
            ),
            request_id,
        )
    validation_errors = _validate_arguments(tool_name, tool.input_schema, args)
    if validation_errors:
        return _attach_request_id(
            contracts.to_error(
                AegisApiError(f"Invalid arguments for MCP tool: {tool_name}"),
                workspace=str(args.get("workspace", ".")),
                details={
                    "code": "INVALID_ARGUMENTS",
                    "tool": tool_name,
                    "validation_errors": validation_errors,
                },
            ),
            request_id,
        )
    try:
        return _attach_request_id(dispatch(args), request_id)
    except Exception as exc:
        return _attach_request_id(
            contracts.to_error(
                exc,
                workspace=str(args.get("workspace", ".")),
                details={"handler": "invoke_tool", "tool": tool_name},
            ),
            request_id,
        )
