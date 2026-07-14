import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gitgood.ui.widgets.diff_view import _aligned_lines


def test_equal_lines_have_no_kind():
    left, right, lk, rk = _aligned_lines(["a", "b"], ["a", "b"])
    assert left == right == ["a", "b"]
    assert lk == rk == [None, None]


def test_replace_pads_shorter_side():
    left, right, lk, rk = _aligned_lines(["old1", "old2"], ["new1"])
    assert left == ["old1", "old2"]
    assert right == ["new1", ""]
    assert lk == ["del", "del"]
    assert rk == ["ins", None]


def test_pure_insertion_pads_left():
    left, right, lk, rk = _aligned_lines(["a"], ["a", "b", "c"])
    assert left == ["a", "", ""]
    assert right == ["a", "b", "c"]
    assert lk == [None, None, None]
    assert rk == [None, "ins", "ins"]


def test_pure_deletion_pads_right():
    left, right, lk, rk = _aligned_lines(["a", "b", "c"], ["a"])
    assert left == ["a", "b", "c"]
    assert right == ["a", "", ""]
    assert lk == [None, "del", "del"]
    assert rk == [None, None, None]
