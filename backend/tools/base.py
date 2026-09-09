"""Tool base class, context, result and registry."""

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, Optional

from tools._common import validate_args


@dataclass
class ToolContext:
    """Everything a tool needs that does NOT come from the LLM."""
    user_id: int
    as_of: date
    repo_factory: Callable  # () -> finance.repository.FinanceRepository


@dataclass
class ToolResult:
    ok: bool
    tool: str
    data: dict = field(default_factory=dict)   # full structured deterministic result
    summary: dict = field(default_factory=dict)  # compact view for the responder LLM
    error: Optional[str] = None

    @classmethod
    def success(cls, tool, data, summary=None):
        return cls(ok=True, tool=tool, data=data, summary=summary if summary is not None else data)

    @classmethod
    def failure(cls, tool, error):
        return cls(ok=False, tool=tool, error=str(error))


class Tool:
    """Subclass and set ``name``, ``description``, ``schema``; implement ``run``."""

    name: str = ""
    description: str = ""
    schema: Dict[str, dict] = {}

    def __init__(self, repo_factory: Callable):
        self._repo_factory = repo_factory

    # -- helpers -----------------------------------------------------------
    def repo(self):
        return self._repo_factory()

    def run(self, ctx: ToolContext, args: dict) -> ToolResult:  # pragma: no cover - abstract
        raise NotImplementedError

    # -- validated entry point ------------------------------------------
    def execute(self, ctx: ToolContext, raw_args: dict) -> ToolResult:
        try:
            cleaned = validate_args(self.schema, raw_args)
        except ValueError as exc:
            return ToolResult.failure(self.name, f"invalid arguments — {exc}")
        try:
            return self.run(ctx, cleaned)
        except ValueError as exc:
            return ToolResult.failure(self.name, str(exc))
        except Exception:  # never leak a stack trace to the agent
            return ToolResult.failure(self.name, "the financial engine could not complete that request")

    # -- catalog entry for the planner --------------------------------
    def catalog_entry(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": {
                k: {kk: vv for kk, vv in v.items() if kk != "default"}
                for k, v in self.schema.items()
            },
        }


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        if not tool.name:
            raise ValueError("tool has no name")
        if tool.name in self._tools:
            raise ValueError(f"tool '{tool.name}' already registered")
        self._tools[tool.name] = tool
        return tool

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return sorted(self._tools)

    def catalog(self) -> List[dict]:
        return [self._tools[n].catalog_entry() for n in self.names()]

    def run(self, name: str, ctx: ToolContext, raw_args: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.failure(name, f"unknown tool '{name}'")
        return tool.execute(ctx, raw_args)
