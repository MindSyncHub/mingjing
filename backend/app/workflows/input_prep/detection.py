"""Step 3 外轮廓检测：在矫正裁切后的干净图上精确定位基准圆。

优先用边缘档检测真实边界；失败时退回 Step 1 的 hint（标 hint_fallback
供人工关注）。验收口径（spec §4.1）：矫正后轮廓长短轴比 ≥ 0.95。
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.workflows.input_prep.rectify import CircleHint, _boost, _candidates_edge, _candidates_color

AXIS_RATIO_MIN = 0.95  # spec §4.1 矫正质量指标


@dataclass
class BaselineResult:
    circle: CircleHint
    axis_ratio: float       # 长短轴比（≥0.95 达标）
    edge_support: float     # 圆周边缘支撑率（置信度）
    source: str             # "edge" / "color" / "hint_fallback"
    debug: dict = field(default_factory=dict)


def _result(best: dict, hint: CircleHint, source: str, debug: dict) -> BaselineResult:
    """候选转结果；半径钳制到 hint.r（几何不变量：crop 按 hint 圆裁出，墨迹
    必然在 hint 圆内。最小外接圆会被轮廓毛刺/outlier 撑大，越界即噪声）。"""
    circle = best["circle"]
    if circle.r > hint.r:
        circle = CircleHint(circle.x, circle.y, hint.r)
        debug = {**debug, "r_clamped": True}
    return BaselineResult(circle, best["ellipse"].ratio, best["support"], source, debug)


def detect_baseline(crop_bgr: np.ndarray, hint: CircleHint) -> BaselineResult:
    h, w = crop_bgr.shape[:2]
    gray = _boost(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY))

    for cfg in ((50, 150, 5), (30, 100, 5), (30, 100, 21)):
        cands = _candidates_edge(gray, cfg[:2], cfg[2])
        cands = [c for c in cands if abs(c["circle"].r - hint.r) < 0.2 * hint.r]
        if cands:
            best = max(cands, key=lambda c: c["support"])
            return _result(best, hint, "edge", {"config": cfg, "fill": best["fill"]})

    cands = _candidates_color(crop_bgr, 40)
    cands = [c for c in cands if abs(c["circle"].r - hint.r) < 0.2 * hint.r]
    if cands:
        best = max(cands, key=lambda c: c["support"])
        return _result(best, hint, "color")

    # 检测失败：退回 hint（低置信，供人工关注，spec §2.3 精神不猜但留痕）
    return BaselineResult(hint, AXIS_RATIO_MIN, 0.3, "hint_fallback")
