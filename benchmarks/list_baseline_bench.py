#!/usr/bin/env python3
"""Vyne fixed-``List`` performance benchmark harness.

Measures the fixed-extent virtualized list (``vyne.List``) end to end through
the real Runtime/transport pipeline, plus pure-planner and source-adapter
costs, so a future list implementation can be compared against a
reproducible baseline.

The harness is reproducible from M0 forward: run it once per worktree state
and store one JSON per state.  The pre-M0 baseline numbers were captured by
the M0 review workstream and are recorded in
``.pi-subagents/list-implementation-plan.md``; this harness only became
runnable on the M0 tree.

Run it, store one JSON per worktree state, and compare:

    python benchmarks/list_baseline_bench.py --samples 25 --warmup 3 \\
        --json /tmp/before.json
    # ... change the code ...
    python benchmarks/list_baseline_bench.py --samples 25 --warmup 3 \\
        --json /tmp/after.json
    python benchmarks/list_baseline_bench.py --compare /tmp/before.json \\
        --json /tmp/after.json --regression-pct 10

``--regression-pct`` fails the run (exit 1) when any comparable case's median
or p95 degrades beyond the given percentage.  A ``noise_floor_ms`` of 0.005
exempts sub-microsecond baselines (timer granularity dominates there).  The
harness writes nothing to the project tree except the JSON file you name; do
not commit machine-specific result files.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from typing import Any, Callable

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(_ROOT, "packages", "vyne", "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from vyne import Column, List, Text, state  # noqa: E402
from vyne._lists import (  # noqa: E402
    FixedExtentLayout,
    FixedVirtualListController,
    FixedVirtualListSpec,
    IndexRange,
    RenderMask,
    SequenceDataSource,
    ViewportMetrics,
    WindowConfig,
    compose_fixed_window,
    plan_mask,
    select_window,
)
from vyne._lists.fixed import _capped_planning_viewport  # noqa: E402
from vyne.lists import FixedLinearLayout, VirtualList  # noqa: E402
from vyne.runtime import Runtime  # noqa: E402
from vyne.transport import MemoryTransport  # noqa: E402

# The public default is a bounded projection of 3 viewports.
PUBLIC_MAX_AHEAD = 3.0
DEFAULT_CONFIG = WindowConfig(overscan_viewports=1)
CAP_CONFIG = WindowConfig(
    overscan_viewports=1, max_render_ahead_viewports=PUBLIC_MAX_AHEAD
)

_SOURCE_FILES = [
    "packages/vyne/src/vyne/_lists/__init__.py",
    "packages/vyne/src/vyne/_lists/_shared.py",
    "packages/vyne/src/vyne/_lists/contracts.py",
    "packages/vyne/src/vyne/_lists/fixed.py",
    "packages/vyne/src/vyne/_lists/generic.py",
    "packages/vyne/src/vyne/_lists/model.py",
    "packages/vyne/src/vyne/_lists/source.py",
    "packages/vyne/src/vyne/_lists/window.py",
    "packages/vyne/src/vyne/lists.py",
]


# ---------------------------------------------------------------------------
# environment + timing helpers
# ---------------------------------------------------------------------------


def env_fingerprint() -> dict[str, str]:
    def git(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=_ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except Exception:
            return "unknown"

    digest = hashlib.sha256()
    for name in _SOURCE_FILES:
        try:
            with open(os.path.join(_ROOT, name), "rb") as fh:
                digest.update(fh.read())
        except OSError:
            digest.update(b"<missing>")
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "revision": git("describe", "--always", "--dirty"),
        "source_hash": digest.hexdigest()[:16],
        "src": SRC,
    }


def _stats_ms(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    n = len(ordered)
    p95 = ordered[min(n - 1, max(0, int(0.95 * (n - 1))))]
    p05 = ordered[max(0, int(0.05 * (n - 1)))]
    return {
        "median_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(p95, 4),
        "p05_ms": round(p05, 4),
        "mean_ms": round(statistics.mean(ordered), 4),
        "min_ms": round(ordered[0], 4),
        "max_ms": round(ordered[-1], 4),
        "samples": n,
    }


def _timed(
    name: str,
    *,
    samples: int,
    warmup: int,
    work: Callable[[], float],
    per_event: bool = False,
) -> dict[str, Any]:
    """Warmup runs then timed samples; ``work`` returns one sample's ms."""
    for _ in range(warmup):
        work()
    per_sample: list[float] = []
    for _ in range(samples):
        gc.collect()
        gc.disable()
        ms = work()
        gc.enable()
        per_sample.append(ms)
    stats = _stats_ms(per_sample)
    unit = " ms/event" if per_event else " ms"
    print(
        f"{name:<56} {stats['median_ms']:>10.4f}{unit}  "
        f"p95={stats['p95_ms']:>9.4f}  p05={stats['p05_ms']:>9.4f}"
    )
    return {"name": name, **stats}


def timed_case(
    name: str,
    fn: Callable[[], Any],
    *,
    samples: int,
    warmup: int,
    loops: int = 1,
) -> dict[str, Any]:
    """Time ``loops`` calls of ``fn`` per sample."""

    def work() -> float:
        t0 = time.perf_counter_ns()
        for _ in range(loops):
            fn()
        return (time.perf_counter_ns() - t0) / 1e6 / loops

    return _timed(name, samples=samples, warmup=warmup, work=work)


def timed_events(
    name: str,
    make_runtime: Callable[[], Runtime],
    events_per_sample: int,
    *,
    samples: int,
    warmup: int,
    driver: Callable[[Runtime, int], None],
    capture: Callable[[Runtime], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Time ``events_per_sample`` events on a fresh runtime per sample.

    ``capture`` runs against the last sample's runtime so callers can record
    bookkeeping (sends, cell/node counts) from the runtime that actually
    received every event.
    """
    holder: dict[str, Runtime] = {}

    def work() -> float:
        runtime = make_runtime()
        holder["runtime"] = runtime
        t0 = time.perf_counter_ns()
        for index in range(events_per_sample):
            driver(runtime, index)
        return (time.perf_counter_ns() - t0) / 1e6 / events_per_sample

    result = _timed(name, samples=samples, warmup=warmup, work=work, per_event=True)
    if capture is not None and holder.get("runtime") is not None:
        result.update(capture(holder["runtime"]))
    return result


# ---------------------------------------------------------------------------
# shared fixtures
# ---------------------------------------------------------------------------


def scroll_metrics(
    offset: float,
    *,
    projected: float | None = None,
    velocity: float = 0.0,
    extent: float = 100.0,
) -> dict:
    projected = offset if projected is None else projected
    return {
        "offset_x": 0.0,
        "offset_y": offset,
        "viewport_width": 300.0,
        "viewport_height": extent,
        "content_width": 300.0,
        "content_height": 10_000_000.0,
        "velocity_x": 0.0,
        "velocity_y": velocity,
        "projected_offset_x": 0.0,
        "projected_offset_y": projected,
        "event_time": 1,
    }


def emit_scroll(
    runtime: Runtime,
    *,
    offset: float,
    seq: int = 1,
    projected: float | None = None,
    velocity: float = 0.0,
) -> None:
    for node in runtime._coordinator.accepted_index.values():
        handler = node.listeners.get("scroll_metrics")
        if handler is None:
            continue
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": seq,
                "target": node.id,
                "event": "scroll_metrics",
                "handler": handler,
                "payload": scroll_metrics(
                    offset, projected=projected, velocity=velocity
                ),
            }
        )
        return
    raise RuntimeError("no scroll_metrics listener")


def _cell(item: Any, index: int) -> Text:
    return Text(text=str(item), key=f"cell-{item}")


def make_app(
    data: Any,
    *,
    item_extent: float = 10,
    max_render_ahead: float = PUBLIC_MAX_AHEAD,
    button: bool = False,
    replacement: Any = None,
):
    """Public List fixture; ``button`` taps replace the state-derived data."""

    def app() -> Any:
        data_cell = state(data)
        extras = (
            [
                Text(
                    text="button",
                    key="btn",
                    on_click=lambda event: data_cell.set(replacement),
                )
            ]
            if button
            else []
        )
        return Column(
            List(
                data_cell.value,
                render_item=_cell,
                key_for_item=lambda item, index: item,
                item_extent=item_extent,
                overscan=1,
                max_render_ahead_viewports=max_render_ahead,
                width=300,
                height=100,
            ),
            *extras,
        )

    return app


def commit_counts(runtime: Runtime) -> dict[str, int]:
    commit = getattr(runtime, "latest_commit", None)
    if commit is None:
        return {}
    ops = commit.get("ops", [])
    return {
        "commit_ops": len(ops),
        "commit_created": sum(1 for op in ops if op.get("op") == "create"),
    }


def click_button(runtime: Runtime, seq: int = 1) -> None:
    node = next(
        node
        for node in runtime._coordinator.accepted_index.values()
        if node.kind == "Text" and node.key == "btn"
    )
    runtime.dispatch_event(
        {
            "type": "event",
            "seq": seq,
            "target": node.id,
            "event": "click",
            "handler": node.listeners["click"],
            "payload": {},
        }
    )


def window_bookkeeping(runtime: Runtime) -> dict[str, Any]:
    result: dict[str, Any] = {
        "cells": sum(
            1
            for node in runtime._coordinator.accepted_index.values()
            if node.kind == "Text" and str(node.key or "").startswith("cell-")
        ),
        "total_nodes": len(runtime._coordinator.accepted_index),
        "sends": runtime.transport.send_count,
    }
    result.update(commit_counts(runtime))
    return result


# ---------------------------------------------------------------------------
# benchmark groups
# ---------------------------------------------------------------------------


def bench_pure(samples: int, warmup: int) -> list[dict]:
    out: list[dict] = []
    layout = FixedExtentLayout(100_000, 10)
    steady = ViewportMetrics(5000, 100)
    projected = ViewportMetrics(50_000, 100)
    actual = ViewportMetrics(0, 100)

    def plan_for(viewport: ViewportMetrics) -> None:
        plan_mask(layout, select_window(layout, viewport, DEFAULT_CONFIG).mask)

    cases = [
        (
            "P1 select_window steady 100k",
            200,
            lambda: select_window(layout, steady, DEFAULT_CONFIG),
        ),
        (
            "P2 select+segments (composed planner) 100k",
            200,
            lambda: plan_for(steady),
        ),
        (
            "P5 capped planning (+select) 100k",
            200,
            lambda: select_window(
                layout,
                _capped_planning_viewport(projected, actual, CAP_CONFIG),
                CAP_CONFIG,
            ),
        ),
    ]
    for name, loops, fn in cases:
        out.append(timed_case(name, fn, samples=samples, warmup=warmup, loops=loops))

    spec = FixedVirtualListSpec(
        source=SequenceDataSource(tuple(range(1000))),
        controller=FixedVirtualListController(),
        render_item=lambda item, index, key: Text(text=str(item)),
        item_extent=10,
        axis="vertical",
        initial_mask=RenderMask.from_ranges(IndexRange(0, 5)),
        retained_mask=RenderMask(),
        window_config=DEFAULT_CONFIG,
        scroll_props={"width": 300, "height": 100},
    )
    mask = RenderMask.from_ranges(IndexRange(100, 130))
    out.append(
        timed_case(
            "P6 compose_fixed_window 30-cell mask",
            lambda: compose_fixed_window(
                spec, mask, on_scroll_metrics=lambda event: None
            ),
            samples=samples,
            warmup=warmup,
            loops=50,
        )
    )

    for count in (1_000, 100_000):
        items = tuple(range(count))
        out.append(
            timed_case(
                f"P8 SequenceDataSource construction (lazy) n={count}",
                lambda items=items: SequenceDataSource(items, lambda item, index: item),
                samples=samples,
                warmup=warmup,
                loops=1 if count > 10_000 else 10,
            )
        )
    return out


def bench_mount(samples: int, warmup: int) -> list[dict]:
    out: list[dict] = []
    for count in (1_000, 100_000):
        data = list(range(count))

        def mount(data=data):
            runtime = Runtime(make_app(data), transport=MemoryTransport())
            runtime.mount()
            return runtime

        result = timed_case(
            f"R1 mount List n={count}", mount, samples=samples, warmup=warmup
        )
        runtime = mount(data)
        result.update(window_bookkeeping(runtime))
        out.append(result)
    return out


def bench_same_window(samples: int, warmup: int) -> list[dict]:
    def make():
        runtime = Runtime(make_app(list(range(1000))), transport=MemoryTransport())
        runtime.mount()
        return runtime

    def driver(runtime: Runtime, index: int) -> None:
        emit_scroll(runtime, offset=5 + (index % 3) * 2, seq=index + 1)

    result = timed_events(
        "R2 same-window scroll (no commit) n=1000",
        make,
        events_per_sample=10,
        samples=samples,
        warmup=warmup,
        driver=driver,
        capture=lambda runtime: {"sends_after_10": runtime.transport.send_count},
    )
    return [result]


def bench_window_move(samples: int, warmup: int) -> list[dict]:
    out: list[dict] = []
    for count in (1_000, 100_000):
        data = list(range(count))

        def make(data=data):
            runtime = Runtime(make_app(data), transport=MemoryTransport())
            runtime.mount()
            return runtime

        def driver(runtime: Runtime, index: int, data=data) -> None:
            emit_scroll(runtime, offset=100 + index * 300, seq=index + 1)

        result = timed_events(
            f"R3 window-moving scroll n={count}",
            make,
            events_per_sample=6,
            samples=samples,
            warmup=warmup,
            driver=driver,
            capture=lambda runtime: {"sends_total_6": runtime.transport.send_count},
        )
        out.append(result)
    return out


def bench_fling(samples: int, warmup: int) -> list[dict]:
    out: list[dict] = []
    data = list(range(100_000))

    def make(max_render_ahead: float):
        runtime = Runtime(
            make_app(data, max_render_ahead=max_render_ahead),
            transport=MemoryTransport(),
        )
        runtime.mount()
        return runtime

    def driver(runtime: Runtime, index: int) -> None:
        emit_scroll(
            runtime, offset=0, projected=50_000.0, velocity=50_000.0, seq=index + 1
        )

    result = timed_events(
        "R4 fling unbounded (project 50k px) n=100k",
        lambda: make(0.0),
        events_per_sample=1,
        samples=samples,
        warmup=warmup,
        driver=driver,
        capture=window_bookkeeping,
    )
    out.append(result)

    result = timed_events(
        "R5 fling default cap=3 (project 50k px) n=100k",
        lambda: make(PUBLIC_MAX_AHEAD),
        events_per_sample=1,
        samples=samples,
        warmup=warmup,
        driver=driver,
        capture=window_bookkeeping,
    )
    runtime = make(PUBLIC_MAX_AHEAD)
    driver(runtime, 0)
    follow = []
    for index, offset in enumerate((2000.0, 10_000.0, 30_000.0), start=1):
        t0 = time.perf_counter_ns()
        emit_scroll(
            runtime, offset=offset, projected=50_000.0, velocity=50_000.0, seq=index + 1
        )
        follow.append(round((time.perf_counter_ns() - t0) / 1e6, 4))
    result["capped_followup_commits_ms"] = follow
    out.append(result)
    return out


def bench_replacement(
    samples: int,
    warmup: int,
    *,
    kind: str,
    label: str,
    replace: Callable[[list[int]], list[Any]],
) -> list[dict]:
    """Shared R6/R7 harness: replace state-derived data via a button tap."""
    out: list[dict] = []
    for count in (1_000, 100_000):
        base = list(range(count))
        replacement = replace(base)

        def make(base=base, replacement=replacement):
            runtime = Runtime(
                make_app(base, button=True, replacement=replacement),
                transport=MemoryTransport(),
            )
            runtime.mount()
            return runtime

        result = timed_events(
            f"{kind} n={count}",
            make,
            events_per_sample=1,
            samples=samples,
            warmup=warmup,
            driver=click_button,
            capture=commit_counts,
        )
        result["replacement"] = label
        out.append(result)
    return out


def bench_update(samples: int, warmup: int) -> list[dict]:
    return bench_replacement(
        samples,
        warmup,
        kind="R6 data update (same length, new ids)",
        label="new-ids",
        replace=lambda base: [f"v{i}" for i in range(len(base))],
    )


def bench_reorder(samples: int, warmup: int) -> list[dict]:
    return bench_replacement(
        samples,
        warmup,
        kind="R7 reorder (rotate-left, keys kept)",
        label="rotate",
        replace=lambda base: list(base[1:]) + list(base[:1]),
    )


# ---------------------------------------------------------------------------


def bench_generic(samples: int, warmup: int) -> list[dict]:
    """M2 generic VirtualList costs: mount and window-moving scrolls."""
    out: list[dict] = []

    def make_virtual(count: int, layout):
        data = list(range(count))

        def app():
            return Column(
                VirtualList(
                    data,
                    render_item=lambda item, index: Text(
                        text=str(item), key=f"g-{item}"
                    ),
                    layout=layout,
                    key_for_item=lambda item, index: item,
                    width=300,
                    height=100,
                )
            )

        return Runtime(app, transport=MemoryTransport())

    def make_mounted(count: int, layout) -> Runtime:
        runtime = make_virtual(count, layout)
        runtime.mount()
        return runtime

    class _GridLayout:
        """Minimal uniform-grid layout for the generic benchmark."""

        def __init__(self, columns: int, cell: float) -> None:
            self.columns = columns
            self.cell = cell

        def place(self, request):
            from vyne.lists import LayoutResult, VirtualPlacement

            columns = self.columns
            cell = self.cell
            item_count = request.item_count
            rows = -(-item_count // columns) if item_count else 0
            content_width = columns * cell
            content_height = rows * cell
            real_start = request.realization_viewport.y
            real_stop = real_start + request.realization_viewport.height
            first = max(0, int(real_start // cell) - 1)
            last = min(rows, int(real_stop // cell) + 2)
            placements = [
                VirtualPlacement(
                    index,
                    (index % columns) * cell,
                    (index // columns) * cell,
                    cell,
                    cell,
                )
                for index in range(first * columns, last * columns)
                if index < item_count
            ]
            return LayoutResult(content_width, content_height, tuple(placements))

        def offset_for_index(self, index, *, measurement_for_index):
            return (
                (index % self.columns) * self.cell,
                (index // self.columns) * self.cell,
            )

    grid_layout = _GridLayout(columns=3, cell=40)

    for count in (1_000, 100_000):
        layout = FixedLinearLayout(10, "vertical")

        def mount(count=count, layout=layout):
            return make_mounted(count, layout)

        result = timed_case(
            f"G1 mount VirtualList fixed-linear n={count}",
            mount,
            samples=samples,
            warmup=warmup,
        )
        runtime = mount()
        result.update(window_bookkeeping(runtime))
        out.append(result)

    result = timed_case(
        "G2 mount VirtualList grid 3-col n=10k",
        lambda: make_mounted(10_000, grid_layout),
        samples=samples,
        warmup=warmup,
    )
    runtime = make_mounted(10_000, grid_layout)
    result.update(window_bookkeeping(runtime))
    out.append(result)

    for count in (1_000, 100_000):

        def make(count=count):
            return make_mounted(count, FixedLinearLayout(10, "vertical"))

        def driver(runtime: Runtime, index: int) -> None:
            emit_scroll(runtime, offset=100 + index * 300, seq=index + 1)

        result = timed_events(
            f"G3 generic window-moving scroll n={count}",
            make,
            events_per_sample=6,
            samples=samples,
            warmup=warmup,
            driver=driver,
            capture=lambda runtime: {"sends_total_6": runtime.transport.send_count},
        )
        out.append(result)
    return out


def load_results(path: str) -> list[dict]:
    with open(path) as fh:
        raw = json.load(fh)
    return raw["results"] if isinstance(raw, dict) else raw


def compare_results(
    base_path: str,
    results: list[dict],
    *,
    regression_pct: float = 0.0,
    noise_floor_ms: float = 0.005,
) -> bool:
    """Print median/p95 deltas; optionally flag regressions.

    Returns True when no comparable case regressed beyond ``regression_pct``
    (or when the gate is disabled).  Only cases present in both runs are
    comparable.  ``noise_floor_ms`` is an absolute-noise floor: a case whose
    baseline median sits below it (sub-microsecond timings where timer
    granularity dominates) is never flagged, because a few hundred
    nanoseconds of jitter can exceed any percentage threshold.
    """
    base = {item["name"]: item for item in load_results(base_path)}
    print("\nbefore/after comparison (median / p95):")
    print(
        f"{'case':<56} {'Δmed%':>8} {'Δp95%':>8} {'before med':>10} {'after med':>10}"
    )
    regressed: list[str] = []
    for result in results:
        previous = base.get(result["name"])
        if previous is None:
            continue
        before = previous["median_ms"]
        after = result["median_ms"]
        med_delta = (after - before) / before * 100 if before else float("inf")
        before_p95 = previous.get("p95_ms")
        after_p95 = result.get("p95_ms")
        p95_delta = None
        if before_p95 and after_p95 is not None:
            p95_delta = (after_p95 - before_p95) / before_p95 * 100
        p95_text = "  n/a" if p95_delta is None else f"{p95_delta:>7.1f}%"
        print(
            f"{result['name']:<56} {med_delta:>7.1f}% {p95_text} "
            f"{before:>10.4f} {after:>10.4f}"
        )
        if regression_pct <= 0:
            continue
        if before < noise_floor_ms:
            continue
        if med_delta > regression_pct:
            regressed.append(result["name"])
        elif p95_delta is not None and p95_delta > regression_pct:
            regressed.append(result["name"])

    if regression_pct > 0:
        if regressed:
            print(f"\nREGRESSIONS beyond {regression_pct}%: {', '.join(regressed)}")
            return False
        print(f"\nno regression beyond {regression_pct}% in comparable cases")
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--json", type=str, default="")
    ap.add_argument(
        "--compare", type=str, default="", help="baseline JSON to diff this run against"
    )
    ap.add_argument(
        "--regression-pct",
        type=float,
        default=0.0,
        help="fail when a comparable median/p95 degrades by this %%",
    )
    ap.add_argument(
        "--skip",
        type=str,
        default="",
        help="comma-separated bench groups: pure,mount,samewindow,"
        "windowmove,fling,update,reorder",
    )
    args = ap.parse_args()

    skip = set(group.strip() for group in args.skip.split(",") if group.strip())
    results: list[dict] = []

    env = env_fingerprint()
    print(
        f"env: python={env['python']} platform={env['platform']} "
        f"revision={env['revision']}"
    )
    print(f"cmd: python {' '.join(sys.argv)}")
    print(f"samples={args.samples} warmup={args.warmup} gc=off-during-timing")
    print("-" * 96)

    groups = {
        "pure": bench_pure,
        "mount": bench_mount,
        "samewindow": bench_same_window,
        "windowmove": bench_window_move,
        "fling": bench_fling,
        "update": bench_update,
        "reorder": bench_reorder,
        "generic": bench_generic,
    }
    for name, fn in groups.items():
        if name in skip:
            continue
        print(f"[{name}]")
        results.extend(fn(args.samples, args.warmup))

    ok = True
    if args.compare:
        ok = compare_results(args.compare, results, regression_pct=args.regression_pct)

    if args.json and (results or not os.path.exists(args.json)):
        payload = {"env": env, "results": results}
        with open(args.json, "w") as fh:
            json.dump(payload, fh, indent=2)
        print(f"wrote {args.json}")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
