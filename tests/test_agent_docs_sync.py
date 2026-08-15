"""AGENTS.md and CLAUDE.md must never drift apart."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_agent_docs_are_byte_identical():
    canonical = ROOT / "AGENTS.md"
    mirror = ROOT / "CLAUDE.md"

    assert canonical.exists(), "AGENTS.md (canonical) is missing"
    assert mirror.exists(), "CLAUDE.md (mirror) is missing"
    assert canonical.read_bytes() == mirror.read_bytes(), (
        "AGENTS.md and CLAUDE.md differ. Run: python scripts/check_agent_docs_sync.py --fix"
    )


def test_agent_docs_are_not_symlinked():
    """Deliberate: both must be real files, so neither tool follows a link."""
    assert not (ROOT / "AGENTS.md").is_symlink()
    assert not (ROOT / "CLAUDE.md").is_symlink()


def test_contract_covers_required_sections():
    text = (ROOT / "AGENTS.md").read_text()
    for required in [
        "Thesis",
        "Canonical demo chain",
        "Architecture",
        "Authority model",
        "Actor / verifier permissions",
        "Evidence and data rules",
        "State model",
        "Tools",
        "Smoke-test requirements",
        "MUST NOT DO",
        "Preferences",
        "AWS safety constraints",
        "Escalate",
        "Repository sync requirement",
    ]:
        assert required in text, f"AGENTS.md missing required section: {required}"
