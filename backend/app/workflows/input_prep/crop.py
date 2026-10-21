"""Step 2 裁切：沿基准圆外接正方形裁切，去除画纸外背景。

输入是 Step 1 拉正后的图（circle_hint 期望基准圆）。
输出正方形图：圆居中、含窄边距；圆超出画面时按可见区域尽力裁并标记
（完整圆被裁切的情况由 Step 3 检测的低置信兜底，spec §2.3）。
"""

from dataclasses import dataclass

import numpy as np

MARGIN = 0.03  # 圆外留边比例（3%）


@dataclass
class CropResult:
    image: np.ndarray
    circle_hint: "CircleHintOut"  # 裁切后坐标系中的期望基准圆
    side: int
    clamped: bool  # 是否因圆靠边而收紧裁切


@dataclass
class CircleHintOut:
    x: float
    y: float
    r: float


def crop_to_painting(rectified: np.ndarray, hint, margin: float = MARGIN) -> CropResult:
    h, w = rectified.shape[:2]
    side = int(round(2 * hint.r * (1 + margin)))
    x0 = int(round(hint.x - side / 2))
    y0 = int(round(hint.y - side / 2))
    clamped = False
    if x0 < 0 or y0 < 0 or x0 + side > w or y0 + side > h:
        clamped = True
        # 以圆心为中心尽力取最大可用正方形
        x0 = min(max(0, x0), w - side) if w >= side else 0
        y0 = min(max(0, y0), h - side) if h >= side else 0
        side = min(side, w - x0, h - y0)
    crop = rectified[y0:y0 + side, x0:x0 + side]
    # 若 clamped，实际边距可能不足，保持 hint 不变（Step 3 按实际像素重新检测）
    return CropResult(crop, CircleHintOut(hint.x - x0, hint.y - y0, hint.r), side, clamped)
