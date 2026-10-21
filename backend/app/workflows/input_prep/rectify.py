"""Step 1 透视矫正：把斜拍造成的椭圆形变拉回正圆。

判定逻辑（区分"斜拍形变"与"画作本身的形状"）：
- 画作外轮廓若高度贴合椭圆（support ≥ 0.9）→ 它本来是圆，椭圆只能是
  斜拍投影 → 按轴比各向异性缩放 + 旋转拉回正圆；
- 轮廓不贴合椭圆（星形/花瓣/花边）→ 椭圆感来自画作形状而非镜头，
  不做缩放（守住"不改画作内容"红线），仅空操作通过；
- 基准圆统一取轮廓最小外接圆（spec：非正圆以外接圆为基准）。
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

MAX_DIM = 1600              # 处理分辨率（保画质，时延预算内）
PLAUSIBLE_R = (0.15, 0.92)  # 外接圆半径占短边比例合理区间
NO_TILT_RATIO = 0.97        # 轴比 ≥ 此值视为无形变，空操作
FILL_BAND = (0.60, 1.15)    # 凸包面积÷椭圆面积合格带：圆≈1.0，星/瓣形 0.6-1.0；矩形纸≈1.27 出带排除
MIN_ELLIPSE_SUPPORT = 0.9   # 轮廓贴合椭圆的比例：≥0.9 判定为"圆的斜拍投影"

# 多档检测配置，按"先清晰后补救"顺序尝试，命中即返回：
# 小核优先保贴合；降阈值档针对淡彩弱边界；大核档补救碎片化边界（花边碎珠）
CONFIGS = (
    {"canny": (50, 150), "close": 5},
    {"canny": (30, 100), "close": 5},
    {"canny": (30, 100), "close": 21},
)
S_THRESHOLD = 40  # 颜色兜底档：HSV 饱和度阈值（彩铅 >40，白纸 ≈0-15）


@dataclass
class Ellipse:
    center: tuple[float, float]
    major: float          # 长轴全长
    minor: float          # 短轴全长
    theta: float          # 长轴相对 x 轴的角度（度，[-90, 90)）

    @property
    def ratio(self) -> float:
        return self.minor / self.major


@dataclass
class CircleHint:
    x: float
    y: float
    r: float


@dataclass
class RectifyResult:
    image: np.ndarray            # 拉正后的图像
    circle_hint: CircleHint      # 期望基准圆（拉正坐标系，供 Step 2 裁切/Step 3 检测初值）
    axis_ratio_before: float     # 矫正前轴比（形变度量）
    rectified: bool              # 是否做了矫正（False = 空操作）
    angle_applied: float         # 施加的旋转角
    scale: float                 # 相对原图的缩放比
    debug: dict = field(default_factory=dict)


class RectifyError(Exception):
    """找不到可靠几何参照（spec §2.3：转提示重拍/人工，不猜）。"""


def load_photo(path: str) -> np.ndarray:
    """EXIF 感知读图：iPhone 照片带旋转标记，Pillow 先转正再进 OpenCV。"""
    from PIL import Image, ImageOps

    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        return cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2BGR)


def _resize(img: np.ndarray) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    scale = min(1.0, MAX_DIM / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img, scale


def _boost(gray: np.ndarray) -> np.ndarray:
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)


def _fit(hull: np.ndarray) -> Ellipse:
    (ex, ey), (ax1, ax2), angle = cv2.fitEllipse(hull)
    if ax1 >= ax2:
        major, minor, theta = ax1, ax2, angle
    else:
        major, minor, theta = ax2, ax1, angle + 90.0
    theta = ((theta + 90.0) % 180.0) - 90.0
    return Ellipse((ex, ey), major, minor, theta)


def _ellipse_support(hull: np.ndarray, el: Ellipse, tol: float = 0.08) -> float:
    """凸包点贴合椭圆边界的比例：圆/斜拍椭圆≈1，星形/花瓣显著更低。"""
    (cx, cy), a, b = el.center, el.major / 2, el.minor / 2
    th = np.deg2rad(el.theta)
    pts = hull.reshape(-1, 2).astype(float)
    dx, dy = pts[:, 0] - cx, pts[:, 1] - cy
    xr = dx * np.cos(th) + dy * np.sin(th)
    yr = -dx * np.sin(th) + dy * np.cos(th)
    val = (xr / a) ** 2 + (yr / b) ** 2
    return float(np.mean(np.abs(val - 1.0) < tol))


def _fill_ratio(cnt: np.ndarray, el: Ellipse) -> float:
    """轮廓凸包面积 ÷ 拟合椭圆面积：圆≈1.0，矩形纸≈1.27（出带排除）。"""
    hull = cv2.convexHull(cnt)
    ellipse_area = np.pi * (el.major / 2) * (el.minor / 2)
    return float(cv2.contourArea(hull) / ellipse_area) if ellipse_area > 0 else 0.0


def _screen(contours, h: int, w: int) -> list[dict]:
    """按尺寸/位置/填充比筛选轮廓，返回候选 dict 列表。"""
    cx_img, cy_img = w / 2, h / 2
    out = []
    for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        if len(cnt) < 40 or cv2.contourArea(cnt) < 0.04 * h * w:
            continue
        hull = cv2.convexHull(cnt)
        if len(hull) < 5:
            continue
        el = _fit(hull)
        r = el.major / 2
        if not (PLAUSIBLE_R[0] * min(h, w) <= r <= PLAUSIBLE_R[1] * min(h, w)):
            continue
        if np.hypot(el.center[0] - cx_img, el.center[1] - cy_img) > 0.35 * min(h, w):
            continue
        fill = _fill_ratio(cnt, el)
        if not (FILL_BAND[0] <= fill <= FILL_BAND[1]):
            continue
        (ex, ey), er = cv2.minEnclosingCircle(hull)  # spec：非正圆以外接圆为基准
        out.append({
            "ellipse": el, "fill": fill,
            "support": _ellipse_support(hull, el),
            "circle": CircleHint(float(ex), float(ey), float(er)),
        })
    return out


def _candidates_edge(gray: np.ndarray, canny: tuple[int, int], close: int) -> list[dict]:
    edges = cv2.Canny(gray, *canny)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((close, close), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return _screen(contours, *gray.shape)


def _candidates_color(img: np.ndarray, s_thresh: int) -> list[dict]:
    """颜色兜底档：饱和度阈值分割出彩色画作区域（极淡彩边界 Canny 失效时）。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, s_thresh, 0), (179, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return _screen(contours, mask.shape[0], mask.shape[1])


def fit_outer_ellipse(image_bgr: np.ndarray) -> tuple[dict, np.ndarray, float, dict]:
    """找画作外边界。返回 (候选, 工作图, 缩放比, 调试信息)。"""
    img, scale = _resize(image_bgr)
    gray = _boost(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    for cfg in CONFIGS:
        cands = _candidates_edge(gray, cfg["canny"], cfg["close"])
        if cands:
            best = max(cands, key=lambda c: c["support"])
            return best, img, scale, {"config": cfg, **{k: round(v, 3) if isinstance(v, float) else v for k, v in best.items() if k != "ellipse"}, "ellipse": best["ellipse"]}
    cands = _candidates_color(img, S_THRESHOLD)
    if cands:
        best = max(cands, key=lambda c: c["support"])
        return best, img, scale, {"config": {"color": S_THRESHOLD}, "fill": best["fill"], "support": best["support"]}
    raise RectifyError("找不到可靠的几何参照")


def rectify(image_bgr: np.ndarray) -> RectifyResult:
    cand, img, scale, debug = fit_outer_ellipse(image_bgr)
    el: Ellipse = cand["ellipse"]
    h, w = img.shape[:2]

    # 轮廓贴合椭圆（它本是圆）且确有形变 → 斜拍矫正；
    # 不贴合（星形/花瓣/花边）→ 形状即如此，不做缩放（不改画作内容）
    if cand["support"] >= MIN_ELLIPSE_SUPPORT and el.ratio < NO_TILT_RATIO:
        M_rot = cv2.getRotationMatrix2D((w / 2, h / 2), el.theta, 1.0)
        rotated = cv2.warpAffine(img, M_rot, (w, h), flags=cv2.INTER_CUBIC)
        cx, cy = (M_rot @ np.array([*el.center, 1.0]))[:2]
        s = 1.0 / el.ratio  # 拉伸短轴方向（y），椭圆拉回正圆
        M_scale = np.array([[1.0, 0.0, 0.0], [0.0, s, cy * (1 - s)]])
        out = cv2.warpAffine(rotated, M_scale, (w, h), flags=cv2.INTER_CUBIC)
        hint = CircleHint(float(cx), float(cy), el.major / 2)
        return RectifyResult(out, hint, el.ratio, True, el.theta, scale, debug)

    # 空操作：画作本身形状非圆（或已正），基准圆取轮廓外接圆
    return RectifyResult(img, cand["circle"], el.ratio, False, 0.0, scale, debug)
