from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ModelConfig:
    cheap: str = "openai:gpt-4.1-nano"
    mid: str = "openai:gpt-4.1-mini"
    premium: str = "openai:gpt-4.1"


@dataclass(slots=True)
class CommandsConfig:
    test: str = "pytest -q"
    lint: str = ""


@dataclass(slots=True)
class AegisConfig:
    base_url: str = "https://aegis-backend-production-4b47.up.railway.app"
    control_enabled: str | bool = "auto"


@dataclass(slots=True)
class ProvidersConfig:
    enabled: bool = False
    provider: str = "openai"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: int = 60


@dataclass(slots=True)
class PatchesConfig:
    generate_diff: bool = False
    max_context_chars: int = 12000
    output_file: str = ".aegis/runs/latest.diff"


@dataclass(slots=True)
class AppConfig:
    mode: str = "balanced"
    budget_per_task: float = 1.0
    models: ModelConfig = field(default_factory=ModelConfig)
    commands: CommandsConfig = field(default_factory=CommandsConfig)
    aegis: AegisConfig = field(default_factory=AegisConfig)
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    patches: PatchesConfig = field(default_factory=PatchesConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AegisDecision:
    model_tier: str = "mid"
    context_mode: str = "balanced"
    max_retries: int = 1
    allow_escalation: bool = False
    execution: dict[str, Any] = field(default_factory=dict)
    note: str = ""


@dataclass(slots=True)
class RepoScanSummary:
    file_count: int
    top_level_directories: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_count": self.file_count,
            "top_level_directories": self.top_level_directories,
        }


@dataclass(slots=True)
class CommandResult:
    name: str
    command: str
    status: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    output_preview: str = ""
    full_output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "output_preview": self.output_preview,
            "full_output": self.full_output,
        }
