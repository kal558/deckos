import pytest


@pytest.fixture
def root(tmp_path, monkeypatch):
    """Point every deckOS path at a temporary filesystem root."""
    monkeypatch.setenv("DECKOS_ROOT", str(tmp_path))
    (tmp_path / "run/deckos").mkdir(parents=True)
    return tmp_path
