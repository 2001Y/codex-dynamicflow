from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from .mini_yaml import load_minimal_yaml, MiniYAMLError


class WorkflowValidationError(ValueError):
    pass


@dataclass(frozen=True)
class TaskSpec:
    id: str
    phase: str
    prompt: str
    role: Optional[str] = None
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    model_profile: Optional[str] = None
    fork_turns: str = "none"
    worktree: str = "read_only"
    output_schema: Optional[str] = None
    timeout_sec: int = 1800
    retries: int = 0
    allow_failure: bool = False
    write_scope: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PhaseSpec:
    id: str
    title: Optional[str]
    concurrency: int
    depends_on: List[str]
    tasks: List[TaskSpec]


@dataclass(frozen=True)
class WorkflowSpec:
    version: int
    name: str
    settings: Dict[str, Any]
    models: Dict[str, Dict[str, str]]
    phases: List[PhaseSpec]

    @property
    def artifact_dir(self) -> str:
        return str(self.settings.get("artifact_dir", ".codex-flow"))

    @property
    def max_concurrency(self) -> int:
        return int(self.settings.get("max_concurrency", 4))


def load_workflow(path: str | Path) -> WorkflowSpec:
    path = Path(path)
    data = _load_mapping(path)
    if not isinstance(data, dict):
        raise WorkflowValidationError("workflow root must be an object")
    return _build_workflow(data)


def _load_mapping(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        try:
            return load_minimal_yaml(text)
        except MiniYAMLError as exc:
            raise WorkflowValidationError(f"invalid YAML: {exc}") from exc
    raise WorkflowValidationError(f"unsupported workflow file type: {path.suffix}")


def _build_workflow(data: Dict[str, Any]) -> WorkflowSpec:
    version = int(data.get("version", 1))
    name = _required_str(data, "name", "workflow")
    settings = dict(data.get("settings") or {})
    models = dict(data.get("models") or {})
    phases_data = data.get("phases")
    if not isinstance(phases_data, list) or not phases_data:
        raise WorkflowValidationError("workflow requires at least one phase")

    phases: List[PhaseSpec] = []
    seen_phase_ids = set()
    seen_task_ids = set()
    default_concurrency = int(settings.get("max_concurrency", 4))

    for phase_raw in phases_data:
        if not isinstance(phase_raw, dict):
            raise WorkflowValidationError("phase must be an object")
        phase_id = _required_str(phase_raw, "id", "phase")
        if phase_id in seen_phase_ids:
            raise WorkflowValidationError(f"duplicate phase id: {phase_id}")
        seen_phase_ids.add(phase_id)
        tasks_raw = phase_raw.get("tasks") or []
        if not isinstance(tasks_raw, list):
            raise WorkflowValidationError(f"phase {phase_id}: tasks must be a list")
        tasks: List[TaskSpec] = []
        for task_raw in tasks_raw:
            task = _build_task(phase_id, task_raw, models)
            if task.id in seen_task_ids:
                raise WorkflowValidationError(f"duplicate task id: {task.id}")
            seen_task_ids.add(task.id)
            tasks.append(task)
        phases.append(
            PhaseSpec(
                id=phase_id,
                title=phase_raw.get("title"),
                concurrency=int(phase_raw.get("concurrency") or default_concurrency),
                depends_on=_string_list(phase_raw.get("depends_on")),
                tasks=tasks,
            )
        )

    return WorkflowSpec(version=version, name=name, settings=settings, models=models, phases=phases)


def _build_task(phase_id: str, raw: Dict[str, Any], models: Dict[str, Dict[str, str]]) -> TaskSpec:
    if not isinstance(raw, dict):
        raise WorkflowValidationError(f"phase {phase_id}: task must be an object")
    task_id = _required_str(raw, "id", "task")
    profile_name = raw.get("model_profile")
    profile: Dict[str, str] = {}
    if profile_name is not None:
        profile_name = str(profile_name)
        if profile_name not in models:
            raise WorkflowValidationError(f"task {task_id}: unknown model_profile {profile_name}")
        profile = models[profile_name]

    model = raw.get("model", profile.get("model"))
    reasoning_effort = raw.get("reasoning_effort", profile.get("reasoning_effort"))
    fork_turns = str(raw.get("fork_turns", "none"))
    worktree = str(raw.get("worktree", "read_only"))
    if worktree not in {"none", "read_only", "isolated"}:
        raise WorkflowValidationError(f"task {task_id}: invalid worktree {worktree}")
    if fork_turns != "none" and fork_turns != "all":
        try:
            if int(fork_turns) <= 0:
                raise ValueError
        except ValueError as exc:
            raise WorkflowValidationError(f"task {task_id}: fork_turns must be none, all, or positive integer") from exc

    if fork_turns == "all" and any(key in raw for key in ("model", "model_profile", "reasoning_effort", "role", "agent_type")):
        raise WorkflowValidationError(
            f"task {task_id}: full-history fork cannot override model, reasoning_effort, or agent role"
        )

    prompt = raw.get("prompt")
    if prompt is None:
        raise WorkflowValidationError(f"task {task_id}: prompt is required")

    return TaskSpec(
        id=task_id,
        phase=phase_id,
        prompt=str(prompt),
        role=raw.get("role") or raw.get("agent_type"),
        model=str(model) if model is not None else None,
        reasoning_effort=str(reasoning_effort) if reasoning_effort is not None else None,
        model_profile=str(profile_name) if profile_name is not None else None,
        fork_turns=fork_turns,
        worktree=worktree,
        output_schema=str(raw["output_schema"]) if raw.get("output_schema") else None,
        timeout_sec=int(raw.get("timeout_sec", 1800)),
        retries=int(raw.get("retries", 0)),
        allow_failure=bool(raw.get("allow_failure", False)),
        write_scope=_string_list(raw.get("write_scope")),
        depends_on=_string_list(raw.get("depends_on")),
    )


def _required_str(data: Dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if value is None or str(value).strip() == "":
        raise WorkflowValidationError(f"{context} requires {key}")
    return str(value)


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    raise WorkflowValidationError("expected string list")
