"""Phase 0 整合性の pytest。"""

from src.validate import run_integrity_checks, run_phase0
from src.io import load_all


def test_integrity_checks_pass():
    data = load_all()
    results = run_integrity_checks(data)
    failed = [r for r in results if not r.get("ok", True)]
    assert not failed, failed


def test_phase0_outputs_exist():
    result = run_phase0()
    assert result["docs"]["issues"].exists()
    assert result["docs"]["questions"].exists()
    assert result["figure"].exists()
    for p in result["marts"].values():
        assert p.exists()
