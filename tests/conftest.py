"""Unit tests run against a seed-only registry: the repo's live registry grows during real runs."""

import json

import pytest

SEED = [
    {"name": "start", "path": "routines/seed/start", "source": "seed"},
    {"name": "ask-student", "path": "routines/seed/ask-student", "source": "seed"},
]


@pytest.fixture(autouse=True)
def seed_registry(tmp_path_factory, monkeypatch):
    import growth.grow as grow
    import harness.controller as controller

    path = tmp_path_factory.mktemp("registry") / "registry.json"
    path.write_text(json.dumps(SEED))
    monkeypatch.setattr(controller, "DEFAULT_REGISTRY", path)
    monkeypatch.setattr(grow, "REGISTRY", path)
    return path


@pytest.fixture(autouse=True)
def scratch_runs_dir(tmp_path_factory, monkeypatch):
    """Event logs created during tests (e.g. `manifest warden audit`) go to a temp dir, not .manifest/runs/."""
    import harness.log as hlog

    monkeypatch.setattr(hlog, "RUNS_DIR", tmp_path_factory.mktemp("runs"))
