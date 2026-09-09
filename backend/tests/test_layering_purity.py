"""Architecture guard:  finance  <-  {decision, knowledge, tools}  <-  agent  <-  routes

These packages are checked by static import analysis (AST). No package below a
line may import a package above it, and the pure layers may not import Flask,
the DB, an LLM client, or a heavyweight ML framework.
"""

import ast
import pathlib

import pytest

_ML_AND_WEB = {
    "flask", "pandas", "numpy", "sklearn", "scipy", "prophet",
    "langchain", "llama_index", "llamaindex", "torch", "tensorflow",
}
_LLM = {"openai", "anthropic", "ollama"}
_DB = {"database", "finance_db", "mysql"}


def _imported_top_levels(pkg: str):
    """Yield (file, top_level_module) for every import in ``pkg``."""
    for path in pathlib.Path(pkg).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield path, alias.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import, always in-package
                    continue
                yield path, (node.module or "").split(".")[0]


def _assert_never_imports(pkg: str, banned: set):
    offenders = sorted(
        {f"{path.as_posix()} -> {mod}"
         for path, mod in _imported_top_levels(pkg)
         if mod in banned}
    )
    assert not offenders, f"{pkg}/ must not import {sorted(banned)}:\n" + "\n".join(offenders)


# --------------------------------------------------------------- finance/ (pure)
def test_finance_layer_is_pure():
    _assert_never_imports("finance", _ML_AND_WEB | _LLM | _DB | {
        "requests", "agent", "tools", "routes", "ai", "decision", "knowledge",
    })


# --------------------------------------------------------------- decision/ (Phase 10)
def test_decision_layer_only_sits_on_finance():
    _assert_never_imports("decision", _ML_AND_WEB | _LLM | _DB | {
        "requests", "agent", "tools", "routes", "ai", "knowledge", "flask",
    })


def test_decision_layer_does_import_finance():
    mods = {mod for _, mod in _imported_top_levels("decision")}
    assert "finance" in mods  # it is built ON the shared kernel, not a reimplementation


# --------------------------------------------------------------- knowledge/ (Phase 11)
def test_knowledge_layer_does_not_reach_up_or_into_the_financial_db():
    # knowledge/ may use ``requests`` (local Ollama only) and stdlib sqlite3.
    _assert_never_imports("knowledge", _ML_AND_WEB | _LLM | _DB | {
        "agent", "tools", "routes", "finance", "decision",
    })


# --------------------------------------------------------------- tools/ boundary
def test_tools_layer_does_not_import_agent_or_flask_or_db():
    _assert_never_imports("tools", {"agent", "routes", "flask", "database"})


# --------------------------------------------------------------- read-only guarantee
@pytest.mark.parametrize("pkg", ["finance", "decision", "knowledge"])
def test_pure_layers_have_no_financial_write_sql(pkg):
    for path in pathlib.Path(pkg).rglob("*.py"):
        up = path.read_text(encoding="utf-8").upper()
        for banned in ("INSERT INTO TRANSACTIONS", "UPDATE ACCOUNTS", "DELETE FROM TRANSACTIONS",
                       "COMMIT=TRUE"):
            assert banned not in up.replace(" ", " "), f"{path} contains {banned}"
