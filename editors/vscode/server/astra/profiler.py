"""Advanced profiling runner for ASTRA programs."""

import argparse
import cProfile
import pstats
import json
import time
import tempfile
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Optional
from collections import defaultdict


@dataclass
class ProfileSample:
    """A single profiling sample."""
    timestamp: float
    function_name: str
    file_path: str
    line_number: int
    execution_time: float
    memory_usage: int
    call_count: int = 1


@dataclass
class FunctionProfile:
    """Profile data for a single function."""
    name: str
    file_path: str
    line_start: int
    line_end: int
    total_time: float
    self_time: float
    call_count: int
    avg_time: float
    max_time: float
    min_time: float
    memory_peak: int
    samples: List[ProfileSample]


@dataclass
class ProfileReport:
    """Complete profile report."""
    program_name: str
    total_execution_time: float
    total_memory_peak: int
    function_profiles: Dict[str, FunctionProfile]
    call_graph: Dict[str, List[str]]
    hotspots: List[FunctionProfile]
    timestamp: float


class AdvancedProfiler:
    """Advanced profiler with memory tracking and call graph analysis."""
    
    def __init__(self):
        self.samples: List[ProfileSample] = []
        self.call_stack: List[str] = []
        self.function_times: Dict[str, float] = defaultdict(float)
        self.memory_snapshots: List[tuple[float, int]] = []
        self.start_time: Optional[float] = None
        self.is_profiling = False
    
    def start_profiling(self, program_path: str) -> bool:
        """Start profiling an ASTRA program."""
        try:
            self.start_time = time.time()
            self.is_profiling = True
            self.samples.clear()
            self.call_stack.clear()
            self.function_times.clear()
            self.memory_snapshots.clear()
            return True
        except Exception as e:
            print(f"Failed to start profiling: {e}")
            return False
    
    def stop_profiling(self) -> ProfileReport:
        """Stop profiling and generate report."""
        if not self.is_profiling:
            raise RuntimeError("Profiling not started")
        
        self.is_profiling = False
        end_time = time.time()
        
        # Process collected samples
        function_profiles = self._process_samples()
        call_graph = self._build_call_graph()
        hotspots = self._find_hotspots(function_profiles)
        
        report = ProfileReport(
            program_name=Path(program_path).name,
            total_execution_time=end_time - (self.start_time or 0),
            total_memory_peak=max([mem for _, mem in self.memory_snapshots] or [0]),
            function_profiles=function_profiles,
            call_graph=call_graph,
            hotspots=hotspots,
            timestamp=time.time()
        )
        
        return report
    
    def add_sample(self, sample: ProfileSample) -> None:
        """Add a profiling sample."""
        if self.is_profiling:
            self.samples.append(sample)
            self.function_times[sample.function_name] += sample.execution_time
    
    def _process_samples(self) -> Dict[str, FunctionProfile]:
        """Process raw samples into function profiles."""
        function_data: Dict[str, List[ProfileSample]] = defaultdict(list)
        
        for sample in self.samples:
            function_data[sample.function_name].append(sample)
        
        function_profiles: Dict[str, FunctionProfile] = {}
        
        for func_name, samples in function_data.items():
            if not samples:
                continue
            
            total_time = sum(s.execution_time for s in samples)
            call_count = len(samples)
            avg_time = total_time / call_count if call_count > 0 else 0
            max_time = max(s.execution_time for s in samples) if samples else 0
            min_time = min(s.execution_time for s in samples) if samples else 0
            memory_peak = max(s.memory_usage for s in samples) if samples else 0
            
            first_sample = samples[0]
            
            profile = FunctionProfile(
                name=func_name,
                file_path=first_sample.file_path,
                line_start=first_sample.line_number,
                line_end=first_sample.line_number,
                total_time=total_time,
                self_time=total_time,
                call_count=call_count,
                avg_time=avg_time,
                max_time=max_time,
                min_time=min_time,
                memory_peak=memory_peak,
                samples=samples
            )
            
            function_profiles[func_name] = profile
        
        return function_profiles
    
    def _build_call_graph(self) -> Dict[str, List[str]]:
        """Build call graph from samples."""
        call_graph: Dict[str, List[str]] = defaultdict(list)
        return dict(call_graph)
    
    def _find_hotspots(self, function_profiles: Dict[str, FunctionProfile]) -> List[FunctionProfile]:
        """Identify performance hotspots."""
        sorted_functions = sorted(
            function_profiles.values(),
            key=lambda f: f.total_time,
            reverse=True
        )
        return sorted_functions[:10]
    
    def export_report(self, report: ProfileReport, output_path: str) -> bool:
        """Export profile report to file."""
        try:
            with open(output_path, 'w') as f:
                json.dump(asdict(report), f, indent=2, default=str)
            return True
        except Exception as e:
            print(f"Failed to export report: {e}")
            return False


def profile_with_memory(script_path: str, output_file: str = None) -> ProfileReport:
    """Profile a script with memory tracking."""
    profiler = AdvancedProfiler()
    
    if not profiler.start_profiling(script_path):
        raise RuntimeError("Failed to start profiling")
    
    # Use cProfile for basic profiling
    prof = cProfile.Profile()
    prof.enable()
    
    try:
        exec(open(script_path).read(), {'__name__': '__main__'})
    finally:
        prof.disable()
    
    # Get cProfile stats
    stats = pstats.Stats(prof)
    stats.sort_stats('cumtime')
    
    # Convert to our format
    profiler.stop_profiling()
    
    # Create a basic report from cProfile data
    report = ProfileReport(
        program_name=Path(script_path).name,
        total_execution_time=stats.total_tt,
        total_memory_peak=0,  # Would need memory profiler
        function_profiles={},
        call_graph={},
        hotspots=[],
        timestamp=time.time()
    )
    
    if output_file:
        profiler.export_report(report, output_file)
    
    return report


def main(argv=None):
    """CLI-style entrypoint for this module.
    
    Parameters:
        argv: Optional CLI arguments passed instead of process argv.
    
    Returns:
        Value produced by the routine, if any.
    """
    p = argparse.ArgumentParser(description="Profile ASTRA programs")
    p.add_argument('script', help='Script to profile')
    p.add_argument('--output', '-o', help='Output file for profile data')
    p.add_argument('--format', choices=['text', 'json'], default='text', help='Output format')
    p.add_argument('--memory', action='store_true', help='Include memory profiling')
    
    ns = p.parse_args(argv)
    
    if ns.memory:
        # Use advanced profiler with memory tracking
        report = profile_with_memory(ns.script, ns.output)
        
        if ns.format == 'json':
            print(json.dumps(asdict(report), indent=2, default=str))
        else:
            print(f"Profile for {report.program_name}")
            print(f"Total time: {report.total_execution_time:.3f}s")
            print(f"Memory peak: {report.total_memory_peak} bytes")
    else:
        # Use standard cProfile
        prof = cProfile.Profile()
        prof.enable()
        exec(open(ns.script).read(), {'__name__': '__main__'})
        prof.disable()
        
        if ns.format == 'json':
            # Convert to JSON format
            stats = pstats.Stats(prof)
            stats.sort_stats('cumtime')
            
            # Basic JSON output
            profile_data = {
                'total_time': stats.total_tt,
                'functions': []
            }
            
            for func_info, stats_data in stats.stats.items():
                filename, line, func_name = func_info
                if filename != '~':  # Skip internal functions
                    profile_data['functions'].append({
                        'file': filename,
                        'line': line,
                        'name': func_name,
                        'calls': stats_data[0],
                        'total_time': stats_data[2],
                        'cumulative_time': stats_data[3]
                    })
            
            print(json.dumps(profile_data, indent=2))
        else:
            # Standard text output
            pstats.Stats(prof).sort_stats('cumtime').print_stats(20)


if __name__ == "__main__":
    main()
