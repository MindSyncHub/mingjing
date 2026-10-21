"""Step 1-2 矫正+裁切单元测试：合成图（不依赖黄金集，CI 可跑）。"""
import cv2
import numpy as np
import pytest

from app.workflows.input_prep.crop import crop_to_painting
from app.workflows.input_prep.rectify import RectifyError, rectify


def _canvas() -> np.ndarray:
    return np.full((1200, 1600, 3), 255, np.uint8)


def _axis_ratio_of_boundary(img: np.ndarray) -> float:
    """测量图中主体边界椭圆的轴比（验证矫正是否拉回正圆）。"""
    from app.workflows.input_prep.rectify import _boost, _candidates_edge
    gray = _boost(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    cands = _candidates_edge(gray, (50, 150), 5)
    assert cands, "应能检测到边界"
    return cands[0]["ellipse"].ratio


def test_tilted_circle_gets_rectified():
    """斜拍圆（已知轴比 0.75）→ 矫正后应回到接近正圆。"""
    img = _canvas()
    cv2.circle(img, (800, 600), 400, (120, 80, 60), 10)
    # 模拟斜拍：垂直方向压缩为 0.75
    tilted = cv2.resize(img, (1600, 900))
    tilted = cv2.copyMakeBorder(tilted, 150, 150, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    assert _axis_ratio_of_boundary(tilted) < 0.8

    r = rectify(tilted)
    assert r.rectified is True
    assert r.axis_ratio_before < 0.8
    assert _axis_ratio_of_boundary(r.image) >= 0.95


def test_star_shape_not_distorted():
    """星形画作（轮廓非椭圆）→ 不做缩放矫正（守住不改画作内容）。"""
    img = _canvas()
    pts = []
    for i in range(16):
        a = np.deg2rad(i * 22.5)
        r_tip = 500 if i % 4 == 0 else 260  # 四角长尖 → 外轮廓明显非椭圆
        pts.append((int(800 + r_tip * np.cos(a)), int(600 + r_tip * np.sin(a))))
    cv2.polylines(img, [np.array(pts)], True, (120, 80, 60), 10)
    r = rectify(img)
    assert r.rectified is False
    # 外接圆半径应覆盖最长尖（≈500）
    assert 480 < r.circle_hint.r < 540


def test_frontal_circle_passthrough():
    img = _canvas()
    cv2.circle(img, (800, 600), 380, (120, 80, 60), 8)
    r = rectify(img)
    assert r.rectified is False
    assert abs(r.circle_hint.r - 380) < 25


def test_blank_raises():
    with pytest.raises(RectifyError):
        rectify(_canvas())


def test_crop_square_with_margin():
    img = _canvas()
    cv2.circle(img, (800, 600), 400, (120, 80, 60), 8)
    r = rectify(img)
    c = crop_to_painting(r.image, r.circle_hint)
    assert c.image.shape[0] == c.image.shape[1]  # 正方形
    assert c.side >= 2 * r.circle_hint.r * 1.02   # 圆完整落入
