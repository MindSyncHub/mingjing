"""Step 3-4 检测+圈界提议单元测试：合成图（不依赖黄金集，CI 可跑）。"""
import cv2
import numpy as np

from app.workflows.input_prep.detection import detect_baseline
from app.workflows.input_prep.rectify import CircleHint
from app.workflows.input_prep.rings import propose_rings


def _three_zone_mandala(zones=(0.30, 0.65)) -> tuple[np.ndarray, CircleHint]:
    """三个色环带的合成曼陀罗：真实圈界在 zones[0]*R 与 zones[1]*R。"""
    img = np.full((1000, 1000, 3), 245, np.uint8)
    center, R = (500, 500), 400
    colors = [(60, 90, 200), (80, 160, 60), (200, 60, 160), (60, 140, 220)]
    bounds = [0] + [int(z * R) for z in zones] + [R + 20]
    for i in reversed(range(3)):  # 从外向内填充，避免内层被覆盖
        cv2.circle(img, center, bounds[i + 1], colors[i], -1)
    for rad in bounds[1:]:
        cv2.circle(img, center, rad, (40, 40, 40), 6)  # 圈界黑线最后画
    return img, CircleHint(500, 500, 400)


def test_rings_find_zone_boundaries():
    img, hint = _three_zone_mandala()
    prop = propose_rings(img, hint.x, hint.y, hint.r)
    assert prop.fallback is False
    assert abs(prop.r1 / hint.r - 0.30) < 0.06
    assert abs(prop.r2 / hint.r - 0.65) < 0.06


def test_rings_fallback_on_uniform_disk():
    img = np.full((1000, 1000, 3), 245, np.uint8)
    cv2.circle(img, (500, 500), 400, (80, 160, 60), -1)  # 无圈界结构的纯色圆
    prop = propose_rings(img, 500, 500, 400)
    assert prop.fallback is True
    assert abs(prop.r1 / 400 - 1 / 3) < 0.02


def test_rings_min_separation():
    """r1/r2 不得贴近（最小间距约束）。"""
    img, hint = _three_zone_mandala(zones=(0.45, 0.50))
    prop = propose_rings(img, hint.x, hint.y, hint.r)
    assert prop.r2 - prop.r1 >= 0.12 * hint.r or prop.fallback


def test_detect_baseline_on_crop():
    img, hint = _three_zone_mandala()
    b = detect_baseline(img, hint)
    assert b.source == "edge"
    assert b.axis_ratio >= 0.95
    assert abs(b.circle.r - 400) < 25


def test_detect_baseline_hint_fallback():
    blank = np.full((800, 800, 3), 245, np.uint8)  # 无边界可检
    hint = CircleHint(400, 400, 300)
    b = detect_baseline(blank, hint)
    assert b.source == "hint_fallback"
    assert b.circle.r == 300
