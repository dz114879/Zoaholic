from __future__ import annotations

import gc
import os
import sys
from collections import Counter
from typing import Any

from fastapi import APIRouter

router = APIRouter()

_baseline: dict[str, int] | None = None


def _get_rss_mb() -> float | None:
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        pass
    return None


def _type_census() -> dict[str, int]:
    counter: Counter[str] = Counter()
    for obj in gc.get_objects():
        counter[type(obj).__name__] += 1
    return dict(counter.most_common(30))


def _coroutine_census() -> dict[str, int]:
    counter: Counter[str] = Counter()
    for obj in gc.get_objects():
        if type(obj).__name__ == 'coroutine':
            code = getattr(obj, 'cr_code', None)
            if code:
                loc = f"{code.co_filename}:{code.co_name}"
            else:
                loc = "<unknown>"
            counter[loc] += 1
    return dict(counter.most_common(20))


@router.get("/debug/memory")
async def debug_memory():
    gc_stats = gc.get_stats()
    top_types = _type_census()
    return {
        "rss_mb": _get_rss_mb(),
        "gc_stats": gc_stats,
        "gc_tracked_objects": len(gc.get_objects()),
        "top30_types": top_types,
        "coroutine_details": _coroutine_census(),
    }


@router.get("/debug/memory/diff")
async def debug_memory_diff():
    global _baseline
    current = _type_census()
    if _baseline is None:
        _baseline = current
        return {"message": "baseline taken, call again to see diff", "rss_mb": _get_rss_mb(), "baseline_top30": current}

    diff = {}
    all_keys = set(current) | set(_baseline)
    for k in all_keys:
        c = current.get(k, 0)
        b = _baseline.get(k, 0)
        d = c - b
        if d != 0:
            diff[k] = {"current": c, "baseline": b, "diff": d}

    sorted_diff = dict(sorted(diff.items(), key=lambda x: -abs(x[1]["diff"]))[:20])
    _baseline = current
    return {"rss_mb": _get_rss_mb(), "top20_growth": sorted_diff}
