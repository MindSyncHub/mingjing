"""感知记分牌 UI 集成（薄封装，D-119）：按 run 的输入图匹配真值表，调用
scripts/perception_score.py 的判分逻辑（importlib 按路径加载，不复制代码）。

设计口径：
- 真值表按 truth["image"] 的文件名与 run 输入图文件名精确匹配（basename 相等）；
- 无匹配真值表 → 返回 None（UI 显示"该图暂无真值表"）；
- 判分对象为 perception.md 全文（含中心放大复核段，D-118 并入同一文件）。
"""
from __future__ import annotations

import importlib.util
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCORE_SCRIPT = REPO_ROOT / "backend" / "scripts" / "perception_score.py"
TRUTH_DIR = REPO_ROOT / "eval" / "golden-perception"


@lru_cache(maxsize=1)
def _scorer() -> Any:
    spec = importlib.util.spec_from_file_location("perception_score_script", SCORE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载记分牌脚本: {SCORE_SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def find_truth(image_basename: str, truth_dir: Path | None = None) -> tuple[Path, dict[str, Any]] | None:
    """按输入图文件名匹配真值表；无匹配返回 None。"""
    truth_dir = truth_dir or TRUTH_DIR
    for path in sorted(truth_dir.glob("*.truth.json")):
        truth = json.loads(path.read_text(encoding="utf-8"))
        if Path(truth.get("image", "")).name == image_basename:
            return path, truth
    return None


def score_run(run_dir: Path, image_basename: str, truth_dir: Path | None = None) -> dict[str, Any] | None:
    """对单个 run 的 perception.md 判分；无真值表返回 None。"""
    found = find_truth(image_basename, truth_dir)
    if found is None:
        return None
    truth_path, truth = found
    perception = (run_dir / "perception.md").read_text(encoding="utf-8")
    scorer = _scorer()
    items = []
    hits = 0
    for item in truth["items"]:
        verdict, note = scorer.score_item(item, perception)
        if verdict == "✓":
            hits += 1
        items.append({"region": item["region"], "item": item["item"],
                      "truth_desc": item["truth_desc"], "verdict": verdict, "note": note})
    return {"truth": truth_path.name, "painting": truth.get("painting", ""),
            "hit": hits, "total": len(items), "items": items}
