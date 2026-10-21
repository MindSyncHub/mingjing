"""黄金集批量跑 Step 1-4（矫正→裁切→检测→圈界提议），输出叠加图 + JSON 报告。

用法：.venv/bin/python -m app.workflows.input_prep.preview \
        --src ../samples/paintings-raw --out ../state/rectify-preview
叠加图：绿色 = Step 3 基准圆；蓝色 = Step 4 提议的 r1/r2 圈界。
"""
import argparse
import json
import time
from pathlib import Path

import cv2

from app.workflows.input_prep.crop import crop_to_painting
from app.workflows.input_prep.detection import detect_baseline
from app.workflows.input_prep.rectify import RectifyError, load_photo, rectify
from app.workflows.input_prep.rings import propose_rings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for p in sorted(src.iterdir()):
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        t0 = time.time()
        try:
            img = load_photo(str(p))
            r = rectify(img)
            c = crop_to_painting(r.image, r.circle_hint)
            b = detect_baseline(c.image, c.circle_hint)
            prop = propose_rings(c.image, b.circle.x, b.circle.y, b.circle.r)
        except RectifyError as e:
            rows.append({"file": p.name, "ok": False, "error": str(e)})
            continue
        elapsed = time.time() - t0

        overlay = c.image.copy()
        cv2.circle(overlay, (round(b.circle.x), round(b.circle.y)), round(b.circle.r), (0, 200, 0), 3)
        for rr in (prop.r1, prop.r2):
            cv2.circle(overlay, (round(b.circle.x), round(b.circle.y)), round(rr), (230, 120, 0), 4)
        cv2.imwrite(str(out / f"{p.stem}_final.jpg"), overlay)
        rows.append({
            "file": p.name, "ok": True,
            "rectified": r.rectified, "axis_ratio_before": round(r.axis_ratio_before, 3),
            "baseline_source": b.source, "axis_ratio": round(b.axis_ratio, 3),
            "edge_support": round(b.edge_support, 3),
            "r1_ratio": round(prop.r1 / b.circle.r, 3), "r2_ratio": round(prop.r2 / b.circle.r, 3),
            "clarity": round(prop.clarity, 2), "fallback": prop.fallback,
            "seconds": round(elapsed, 2),
        })

    (out / "report.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    ok = sum(1 for x in rows if x.get("ok"))
    fb = sum(1 for x in rows if x.get("fallback"))
    print(f"通过 {ok}/{len(rows)}（兜底 {fb} 张）")
    for x in rows:
        if x.get("ok"):
            print(f"  ✓ {x['file']}  轴比{x['axis_ratio']}  支{x['edge_support']}  "
                  f"r1={x['r1_ratio']} r2={x['r2_ratio']}  清晰{x['clarity']}"
                  f"{'  [兜底]' if x['fallback'] else ''}  {x['seconds']}s")
        else:
            print(f"  ✗ {x['file']}  {x.get('error')}")


if __name__ == "__main__":
    main()
