"""Keep the documentation honest: READMEs, quickstart code, metadata."""

from __future__ import annotations

import re
import shutil

import datadouble

from conftest import REPO_ROOT


def test_readme_translations_and_metadata_are_consistent():
    # The three READMEs are parallel translations; identical line counts
    # keep them reviewable side by side.
    counts = {
        name: len((REPO_ROOT / name).read_text(encoding="utf-8").splitlines())
        for name in ("README.md", "README.zh.md", "README.ja.md")
    }
    assert len(set(counts.values())) == 1, counts
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{datadouble.__version__}"' in pyproject
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"[{datadouble.__version__}]" in changelog
    license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in license_text
    assert "Copyright (c) 2026 JaydenCJ" in license_text


def test_readme_quickstart_python_block_runs(tmp_path, monkeypatch, capsys):
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"```python\n(.*?)```", text, re.DOTALL)
    assert match, "README.md must contain a python quickstart block"
    shutil.copy(REPO_ROOT / "examples" / "orders.csv", tmp_path / "orders.csv")
    monkeypatch.chdir(tmp_path)
    exec(compile(match.group(1), "README.md", "exec"), {})  # noqa: S102
    assert "orders_twin.csv" in capsys.readouterr().out
    twin = (tmp_path / "orders_twin.csv").read_text(encoding="utf-8")
    assert len(twin.splitlines()) == 201  # header + one twin row per source row
