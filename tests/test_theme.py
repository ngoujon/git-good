import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gitgood.ui.theme import LIGHT, avatar_color


def test_avatar_color_is_deterministic():
    assert avatar_color("git-good") == avatar_color("git-good")


def test_avatar_color_picks_from_lane_palette():
    assert avatar_color("some-repo") in LIGHT["lane_colors"]


def test_avatar_color_varies_by_name():
    colors = {avatar_color(name) for name in ("alpha", "beta", "gamma", "delta", "epsilon")}
    assert len(colors) > 1
