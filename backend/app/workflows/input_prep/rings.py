"""Step 4 圈界自动提议：径向色差跳变分析，把 r1/r2 提议在画面自然分区处。

信号：对每个半径带，沿 720 个角度采样带内侧/外侧一对像素，计算 LAB
色差后沿角度取均值。真圈界（图案组之间的分界线）在大多数角度上都分隔
两个不同色区，跳变强且整圈连续；组内纹理（螺旋、花瓣等）的颜色差经
角度平均后相互抵消，跳变弱。相比"色带均值差 + 边缘密度"，它不会被
细节密度带带偏（黄金集 d191 标定：人类手绘圈界 0.28/0.60，本信号
提议 0.287/0.646）。

r1/r2 都取各自区间内最强峰（r2 与 r1 保持最小间距）。嵌套装饰圈
（如中央图案的内层描线）若比中央组外边界更强，可能抢走 r1——黄金集
d191 上该情况靠检测半径钳制后自然落在搜索区间外，暂不特殊处理。

分区不清晰（清晰度低于阈值）时退回固定比例兜底（spec §2.2 Step 4：
约 1/3、2/3，标注"默认比例"）。
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

N_BANDS = 120
N_THETA = 720           # 角度采样数：足够细，单圈线只占 1-2 个角度 bin
JUMP_WIDTH = 0.012      # 内外采样点半径偏移（占 R）
R1_RANGE = (0.18, 0.48)  # r1 占 R 的合理区间（内/中分界）
R2_RANGE = (0.52, 0.82)  # r2 占 R 的合理区间（中/外分界）
CLARITY_MIN = 0.55       # 峰值/外圈参照 的清晰度下限，低于则兜底
MIN_SEPARATION = 0.13    # r1/r2 最小间距（占 R）
FALLBACK = (1.0 / 3.0, 2.0 / 3.0)


@dataclass
class RingProposal:
    r1: float               # 像素（以圆心为原点）
    r2: float
    clarity: float          # 两峰清晰度的较小值
    fallback: bool          # 是否走了固定比例兜底
    signal: list[float] = field(default_factory=list)  # 径向信号留痕（调参/审计）


def _jump_signal(crop_bgr: np.ndarray, cx: float, cy: float, R: float) -> np.ndarray:
    """径向色差跳变信号，长度 N_BANDS：每带内外采样点的平均 LAB 色差。"""
    h, w = crop_bgr.shape[:2]
    lab = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    k = np.arange(N_BANDS)
    r_in = ((k + 0.5) / N_BANDS - JUMP_WIDTH) * R
    r_out = ((k + 0.5) / N_BANDS + JUMP_WIDTH) * R
    ths = np.linspace(0, 2 * np.pi, N_THETA, endpoint=False)
    xs_in = (cx + np.outer(r_in, np.cos(ths))).astype(int).clip(0, w - 1)
    ys_in = (cy + np.outer(r_in, np.sin(ths))).astype(int).clip(0, h - 1)
    xs_out = (cx + np.outer(r_out, np.cos(ths))).astype(int).clip(0, w - 1)
    ys_out = (cy + np.outer(r_out, np.sin(ths))).astype(int).clip(0, h - 1)
    jump = np.linalg.norm(lab[ys_out, xs_out] - lab[ys_in, xs_in], axis=2).mean(axis=1)
    kernel = np.ones(5) / 5  # 轻度平滑去毛刺
    return np.convolve(jump, kernel, mode="same")


def _peaks(sig: np.ndarray, lo: float, hi: float) -> list[tuple[int, float]]:
    """[lo, hi] 区间内的局部峰列表（带序号, 信号值），按半径从小到大。"""
    k_lo, k_hi = int(lo * N_BANDS), int(hi * N_BANDS)
    return [(k, float(sig[k])) for k in range(max(1, k_lo), min(N_BANDS - 1, k_hi))
            if sig[k] >= sig[k - 1] and sig[k] >= sig[k + 1]]


def _strongest_peak(sig: np.ndarray, lo: float, hi: float, ref: float) -> tuple[int, float]:
    """在占比 [lo, hi] 区间内找最强局部峰，返回 (带序号, 清晰度=峰/参照)。"""
    cands = _peaks(sig, lo, hi)
    if not cands:
        k = int((lo + hi) / 2 * N_BANDS)
        return k, float(sig[k] / (ref + 1e-6))
    best_k, best_v = max(cands, key=lambda kv: kv[1])
    return best_k, float(best_v / (ref + 1e-6))




def propose_rings(crop_bgr: np.ndarray, cx: float, cy: float, R: float) -> RingProposal:
    sig = _jump_signal(crop_bgr, cx, cy, R)
    if float(sig.max()) < 1e-6:  # 全零信号（如纯色图）直接兜底
        return RingProposal(R * FALLBACK[0], R * FALLBACK[1], 0.0, True,
                            sig.round(4).tolist())
    # 外圈参照：画作外边界（r∈[0.85R, R]）的信号高分位——每幅画自带标定
    outer_ref = float(np.percentile(sig[int(0.85 * N_BANDS):], 95))
    k1, c1 = _strongest_peak(sig, *R1_RANGE, outer_ref)
    r1 = (k1 + 0.5) / N_BANDS * R
    # r2 搜索区间与 r1 保持最小间距，避免两条圈界贴在一起
    lo2 = max(R2_RANGE[0], r1 / R + MIN_SEPARATION)
    k2, c2 = _strongest_peak(sig, lo2, R2_RANGE[1], outer_ref)
    clarity = min(c1, c2)
    if clarity < CLARITY_MIN:
        return RingProposal(R * FALLBACK[0], R * FALLBACK[1], clarity, True, sig.round(4).tolist())
    return RingProposal(r1, (k2 + 0.5) / N_BANDS * R, clarity, False,
                        sig.round(4).tolist())
