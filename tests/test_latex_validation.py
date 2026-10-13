from paper_qa.schemas import Status
from paper_qa.services.latex_validation import compare_math


def test_strict_math_detects_change_and_addition() -> None:
    source = [{"type": "inline", "latex": "x + y"}]
    target = [{"type": "inline", "latex": "x - y"}]
    status, counts, issues = compare_math(source, target, "strict")
    assert status == Status.FAIL
    assert counts["matched"] == 0
    assert {issue.code for issue in issues} == {"EQUATION_MISSING_OR_CHANGED", "EQUATION_ADDED"}


def test_normalized_math_only_ignores_whitespace() -> None:
    source = [{"type": "display", "latex": "x  +\n y"}]
    target = [{"type": "display", "latex": "x + y"}]
    status, counts, issues = compare_math(source, target, "normalized")
    assert status == Status.PASS
    assert counts["matched"] == 1
    assert not issues
