from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class ProfileRecord:
    name: str
    duration_s: float
    thread_id: int = field(default_factory=lambda: threading.get_ident())


@dataclass
class PhaseStats:
    total_time: float = 0.0
    call_count: int = 0
    parallel_time: float = 0.0  # Time spent in parallel sections
    max_thread_time: float = 0.0  # Maximum time spent by any single thread


class ThreadLocalProfiler:
    """Thread-local profiler for tracking parallel work"""
    def __init__(self):
        self._stack: List[float] = []
        self._records: List[ProfileRecord] = []
    
    def start_section(self, name: str) -> None:
        self._stack.append(time.perf_counter())
    
    def end_section(self, name: str) -> float:
        if not self._stack:
            return 0.0
        start = self._stack.pop()
        duration = time.perf_counter() - start
        self._records.append(ProfileRecord(name, duration))
        return duration


class Profiler:
    def __init__(self) -> None:
        self._enabled: bool = False
        self._lock = threading.Lock()
        self._totals: Dict[str, float] = {}
        self._phase_stats: Dict[str, PhaseStats] = {}
        self._records: List[ProfileRecord] = []
        self._stack_local = threading.local()
        self._thread_locals: Dict[int, ThreadLocalProfiler] = {}
        self._main_thread_id = threading.get_ident()

    def enable(self, enabled: bool = True) -> None:
        with self._lock:
            self._enabled = enabled
            self._totals.clear()
            self._records.clear()

    def disable(self) -> None:
        with self._lock:
            self._enabled = False

    def reset(self) -> None:
        with self._lock:
            self._totals.clear()
            self._records.clear()
            self._phase_stats.clear()
            self._thread_locals.clear()

    @property
    def enabled(self) -> bool:
        return bool(self._enabled)

    def _get_thread_local(self) -> ThreadLocalProfiler:
        """Get or create thread-local profiler instance"""
        thread_id = threading.get_ident()
        with self._lock:
            if thread_id not in self._thread_locals:
                self._thread_locals[thread_id] = ThreadLocalProfiler()
            return self._thread_locals[thread_id]

    @contextmanager
    def section(self, name: str):
        if not self._enabled:
            yield
            return
        
        thread_id = threading.get_ident()
        is_main_thread = thread_id == self._main_thread_id
        
        # Use thread-local profiler for parallel sections
        if not is_main_thread:
            thread_local = self._get_thread_local()
            thread_local.start_section(name)
            try:
                yield
            finally:
                duration = thread_local.end_section(name)
                with self._lock:
                    self._update_phase_stats(name, duration, is_parallel=True)
            return
        
        # Main thread: use existing logic
        start = time.perf_counter()
        try:
            yield
        finally:
            end = time.perf_counter()
            dt = end - start
            with self._lock:
                self._totals[name] = self._totals.get(name, 0.0) + dt
                self._records.append(ProfileRecord(name=name, duration_s=dt, thread_id=thread_id))
                self._update_phase_stats(name, dt, is_parallel=False)

    def _update_phase_stats(self, name: str, duration: float, is_parallel: bool) -> None:
        """Update phase statistics with timing information"""
        if name not in self._phase_stats:
            self._phase_stats[name] = PhaseStats()
        
        stats = self._phase_stats[name]
        stats.total_time += duration
        stats.call_count += 1
        
        if is_parallel:
            stats.parallel_time += duration
        
        # Track maximum time spent by any thread
        if duration > stats.max_thread_time:
            stats.max_thread_time = duration

    def summary(self) -> Dict[str, float]:
        with self._lock:
            # Return a shallow copy to avoid external mutation
            return dict(self._totals)

    def total_time(self) -> float:
        with self._lock:
            return sum(self._totals.values())

    def to_text(self) -> str:
        sums = self.summary()
        if not sums:
            return ""
        keys = sorted(sums.keys())
        lines = ["Compile-time profile (seconds):"]
        width = max(len(k) for k in keys)
        
        # Calculate parallelization efficiency
        total_sequential = 0.0
        total_parallel = 0.0
        
        for k in keys:
            stats = self._phase_stats.get(k, PhaseStats())
            if stats.parallel_time > 0:
                total_parallel += stats.parallel_time
            else:
                total_sequential += sums[k]
        
        for k in keys:
            stats = self._phase_stats.get(k, PhaseStats())
            parallel_info = ""
            if stats.parallel_time > 0:
                efficiency = min(100.0, (stats.parallel_time / max(stats.max_thread_time, 0.001)) * 100)
                parallel_info = f" [parallel: {stats.parallel_time:.3f}s, efficiency: {efficiency:.1f}%]"
            lines.append(f"  {k.ljust(width)}  {sums[k]:8.4f}{parallel_info}")
        
        total = sum(sums.values())
        lines.append(f"  {'total'.ljust(width)}  {total:8.4f}")
        
        if total_parallel > 0:
            parallel_efficiency = min(100.0, (total_parallel / max(total_sequential + total_parallel, 0.001)) * 100)
            lines.append(f"  {'parallel_work'.ljust(width)}  {total_parallel:8.4f} ({parallel_efficiency:.1f}% of total)")
            lines.append(f"  {'sequential_work'.ljust(width)}  {total_sequential:8.4f}")
        
        return "\n".join(lines)

    def to_json(self) -> str:
        # Enhanced JSON output with parallelization metrics
        phases = {}
        for name, total_time in self.summary().items():
            stats = self._phase_stats.get(name, PhaseStats())
            phases[name] = {
                "total_time_s": total_time,
                "call_count": stats.call_count,
                "parallel_time_s": stats.parallel_time,
                "max_thread_time_s": stats.max_thread_time,
                "is_parallel": stats.parallel_time > 0,
            }
            if stats.parallel_time > 0:
                efficiency = min(100.0, (stats.parallel_time / max(stats.max_thread_time, 0.001)) * 100)
                phases[name]["parallel_efficiency_percent"] = efficiency
        
        payload = {
            "phases": phases,
            "total": sum(self.summary().values()),
            "threads": int(os.environ.get("ASTRA_THREADS", "0") or 0),
            "thread_count": len(self._thread_locals) + 1,  # +1 for main thread
        }
        return json.dumps(payload, indent=2, sort_keys=True)


# Module-level singleton profiler
profiler = Profiler()
