#!/usr/bin/env python3
# Vendored from HyTri scripts/docker/collect_bears.py @ 4039de468073f7a81c3eab2f577654880205467f
# Provided as-is for provenance of data/sources; not re-run for this release.
"""Bears Benchmark Collection Script.

Collects test failures from the Bears benchmark for HyTri evaluation.
Bears provides reproducible Java bugs with failing tests and code patches.

Repository: https://github.com/bears-bugs/bears-benchmark

The dataset is provided as JSON files containing:
- Buggy and fixed commit SHAs
- Failing test information
- Build tool configuration
- Travis CI build IDs

Usage:
    python collect_bears.py --output data/bears
    python collect_bears.py --list  # List available bugs

Requirements:
    - Git
    - Network access to GitHub
"""

import argparse
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error


# Bears benchmark repository
BEARS_REPO_URL = "https://github.com/bears-bugs/bears-benchmark"
BEARS_RAW_URL = "https://raw.githubusercontent.com/bears-bugs/bears-benchmark/master"


@dataclass
class FailureInstance:
    """Represents a single test failure (same format as BugSwarm)."""
    build_id: str
    failure_id: str
    test_name: str
    exception_type: str
    exception_message: str
    stack_trace: str
    frames: List[Dict[str, Any]]
    stderr: str
    stdout: str
    project: str
    bug_id: str
    timestamp: str
    ground_truth: Dict[str, Any]
    language: str


@dataclass
class BuildInfo:
    """Build-level information including code changes."""
    build_id: str
    project: str
    repo: str
    language: str
    image_tag: str
    num_failures: int
    changed_files: List[str]
    file_diffs: Dict[str, str]
    additions: int
    deletions: int
    diff_url: str
    classification: Dict[str, str]
    timestamp: str


def fetch_bears_index() -> List[Dict]:
    """Fetch the Bears benchmark index from GitHub.
    
    Returns:
        List of bug metadata dictionaries
    """
    index_url = f"{BEARS_RAW_URL}/docs/data/bears-bugs.json"
    
    print(f"Fetching Bears index from {index_url}...")
    
    try:
        req = urllib.request.Request(index_url, headers={"User-Agent": "HyTri-Collector/1.0"})
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        
        print(f"Found {len(data)} bugs in Bears benchmark")
        return data
    except Exception as e:
        print(f"Error fetching Bears index: {e}")
        return []


def fetch_bug_details(bug_id: str) -> Optional[Dict]:
    """Fetch detailed information for a specific bug.
    
    Args:
        bug_id: The Bears bug identifier (e.g., "Bears-1")
        
    Returns:
        Bug details dictionary or None
    """
    # Bug details are in individual JSON files
    details_url = f"{BEARS_RAW_URL}/docs/data/{bug_id}.json"
    
    try:
        req = urllib.request.Request(details_url, headers={"User-Agent": "HyTri-Collector/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return None
    except Exception as e:
        print(f"  Error fetching bug details: {e}")
        return None


def get_code_diff(repo_slug: str, buggy_commit: str, fixed_commit: str) -> Dict[str, Any]:
    """Get code diff between buggy and fixed commits from GitHub.
    
    Args:
        repo_slug: Repository in format "owner/repo"
        buggy_commit: Buggy commit SHA
        fixed_commit: Fixed commit SHA
        
    Returns:
        Dictionary with changed_files, file_diffs, additions, deletions
    """
    diff_url = f"https://github.com/{repo_slug}/compare/{buggy_commit}...{fixed_commit}.diff"
    
    try:
        req = urllib.request.Request(diff_url, headers={"User-Agent": "HyTri-Collector/1.0"})
        with urllib.request.urlopen(req, timeout=60) as response:
            diff_content = response.read().decode("utf-8", errors="replace")
        
        return parse_unified_diff(diff_content)
    except Exception as e:
        print(f"    Error fetching diff: {e}")
        return {"changed_files": [], "file_diffs": {}, "additions": 0, "deletions": 0}


def parse_unified_diff(diff_content: str) -> Dict[str, Any]:
    """Parse unified diff to extract changed files and statistics.
    
    Args:
        diff_content: Raw unified diff content
        
    Returns:
        Dictionary with changed_files, file_diffs, additions, deletions
    """
    changed_files = []
    file_diffs = {}
    total_additions = 0
    total_deletions = 0
    
    current_file = None
    current_diff_lines = []
    
    for line in diff_content.split("\n"):
        # New file marker
        if line.startswith("diff --git"):
            # Save previous file
            if current_file and current_diff_lines:
                file_diffs[current_file] = "\n".join(current_diff_lines)
            
            # Extract filename from "diff --git a/path b/path"
            match = re.search(r"diff --git a/(.+?) b/(.+)", line)
            if match:
                current_file = match.group(2)
                if current_file not in changed_files:
                    changed_files.append(current_file)
                current_diff_lines = [line]
        
        elif current_file:
            current_diff_lines.append(line)
            
            # Count additions/deletions
            if line.startswith("+") and not line.startswith("+++"):
                total_additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                total_deletions += 1
    
    # Save last file
    if current_file and current_diff_lines:
        file_diffs[current_file] = "\n".join(current_diff_lines)
    
    # Filter to source files only
    source_extensions = {".java", ".py", ".js", ".ts", ".cpp", ".c", ".h", ".cs", ".go", ".rb", ".scala", ".kt"}
    changed_files = [f for f in changed_files if any(f.endswith(ext) for ext in source_extensions)]
    file_diffs = {k: v for k, v in file_diffs.items() if any(k.endswith(ext) for ext in source_extensions)}
    
    return {
        "changed_files": changed_files,
        "file_diffs": file_diffs,
        "additions": total_additions,
        "deletions": total_deletions
    }


def parse_java_stack_trace(trace: str, max_frames: int = 20) -> List[Dict[str, Any]]:
    """Parse Java stack trace into frames.
    
    Args:
        trace: Raw stack trace string
        max_frames: Maximum frames to extract
        
    Returns:
        List of frame dictionaries
    """
    frames = []
    # Match: at package.Class.method(File.java:123)
    pattern = r"at\s+([\w.$]+)\(([\w.]+):(\d+)\)"
    
    for match in re.finditer(pattern, trace):
        func = match.group(1)
        file = match.group(2)
        line = int(match.group(3))
        
        frames.append({
            "file": file,
            "line": line,
            "func": func
        })
        
        if len(frames) >= max_frames:
            break
    
    return frames


def collect_bug(bug_info: Dict, details: Optional[Dict] = None) -> tuple[List[FailureInstance], Optional[BuildInfo]]:
    """Collect failure information from a Bears bug.
    
    Args:
        bug_info: Basic bug metadata from index
        details: Detailed bug information (optional)
        
    Returns:
        Tuple of (failures list, build info)
    """
    bug_id = bug_info.get("bugId", "unknown")
    repo_name = bug_info.get("repository", {}).get("name", "")
    # Convert "FasterXML-jackson-databind" to "FasterXML/jackson-databind"
    repo_slug = repo_name.replace("-", "/", 1) if "-" in repo_name else repo_name
    
    print(f"\nProcessing: {bug_id}")
    print(f"  Repository: {repo_slug}")
    
    # Get commits - they're under 'commits' not 'builds'
    buggy_commit = bug_info.get("commits", {}).get("buggyBuild", {}).get("sha", "")
    fixed_commit = bug_info.get("commits", {}).get("fixerBuild", {}).get("sha", "")
    
    if not buggy_commit or not fixed_commit:
        print(f"  Missing commit information, skipping")
        return [], None
    
    print(f"  Buggy commit: {buggy_commit[:8]}")
    print(f"  Fixed commit: {fixed_commit[:8]}")
    
    # Get failing tests from failureDetails (has the actual failure info)
    failing_tests = bug_info.get("tests", {}).get("failureDetails", [])
    if not failing_tests:
        # Fallback to failingClasses
        failing_tests = bug_info.get("tests", {}).get("failingClasses", [])
    
    print(f"  Failing tests: {len(failing_tests)}")
    
    # Get code diff
    print(f"  Fetching code diff...")
    diff_info = get_code_diff(repo_slug, buggy_commit, fixed_commit)
    print(f"    Changed files: {len(diff_info['changed_files'])}")
    print(f"    Lines: +{diff_info['additions']} -{diff_info['deletions']}")
    
    # Create failure instances
    failures = []
    build_id = f"bears_{bug_id}"
    project = repo_slug.replace("/", "_")
    diff_url = f"https://github.com/{repo_slug}/compare/{buggy_commit}...{fixed_commit}"
    
    for i, test in enumerate(failing_tests):
        # Handle failureDetails format
        if isinstance(test, dict):
            test_class = test.get("testClass", "")
            test_method = test.get("testMethod", "")
            test_name = f"{test_class}::{test_method}" if test_method else test_class
            
            # failureName is the exception class (e.g., "com.fasterxml.jackson.databind.JsonMappingException")
            failure_name = test.get("failureName", "TestFailure")
            exception_type = failure_name.split(".")[-1] if "." in failure_name else failure_name
            
            # detail contains the exception message
            exception_message = test.get("detail", "")
            
            # Bears doesn't include full stack traces in the JSON, so we construct a minimal one
            stack_trace = f"{failure_name}: {exception_message}"
            if test_class and test_method:
                stack_trace += f"\n\tat {test_class}.{test_method}(Unknown:0)"
        else:
            # Simple string format (fallback)
            test_name = str(test)
            exception_type = "TestFailure"
            exception_message = ""
            stack_trace = ""
        
        frames = parse_java_stack_trace(stack_trace) if stack_trace else []
        
        # If no frames from stack trace, create one from test info
        if not frames and isinstance(test, dict):
            test_class = test.get("testClass", "")
            test_method = test.get("testMethod", "")
            if test_class:
                # Extract filename from class name (e.g., Creator1476Test from ...Creator1476Test)
                class_name = test_class.split(".")[-1]
                frames = [{
                    "file": f"{class_name}.java",
                    "line": 0,
                    "func": f"{test_class}.{test_method}" if test_method else test_class
                }]
        
        failure = FailureInstance(
            build_id=build_id,
            failure_id=f"{build_id}::failure_{i}",
            test_name=test_name,
            exception_type=exception_type,
            exception_message=exception_message[:500] if exception_message else "",
            stack_trace=stack_trace[:5000] if stack_trace else "",
            frames=frames,
            stderr="",
            stdout="",
            project=project,
            bug_id=bug_id,
            timestamp=datetime.now().isoformat(),
            ground_truth={
                "root_cause_id": bug_id,
                "changed_files": diff_info["changed_files"],
                "diff_url": diff_url,
                "additions": diff_info["additions"],
                "deletions": diff_info["deletions"],
                "has_diffs": len(diff_info["changed_files"]) > 0,
                "buggy_commit": buggy_commit,
                "fixed_commit": fixed_commit,
            },
            language="java"
        )
        failures.append(failure)
    
    # Create build info
    build_info = BuildInfo(
        build_id=build_id,
        project=project,
        repo=repo_slug,
        language="java",
        image_tag=bug_id,
        num_failures=len(failures),
        changed_files=diff_info["changed_files"],
        file_diffs=diff_info["file_diffs"],
        additions=diff_info["additions"],
        deletions=diff_info["deletions"],
        diff_url=diff_url,
        classification={"code": "Yes", "build": "NA", "test": "NA"},
        timestamp=datetime.now().isoformat()
    )
    
    return failures, build_info


def save_failures(failures: List[FailureInstance], output_path: str):
    """Save failures to JSONL file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "a") as f:
        for failure in failures:
            f.write(json.dumps(asdict(failure)) + "\n")


def save_build_info(build_info: BuildInfo, output_path: str):
    """Save build info to JSONL file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "a") as f:
        f.write(json.dumps(asdict(build_info)) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Collect Bears benchmark data")
    parser.add_argument("--list", action="store_true", help="List available bugs")
    parser.add_argument("--limit", type=int, default=None, help="Maximum bugs to collect")
    parser.add_argument("--output", type=str, default="data/bears", help="Output directory")
    parser.add_argument("--min-failures", type=int, default=1, help="Minimum failing tests per bug")
    
    args = parser.parse_args()
    
    # Fetch index
    bugs = fetch_bears_index()
    
    if not bugs:
        print("Failed to fetch Bears index")
        return
    
    # Filter by minimum failures
    bugs = [b for b in bugs if len(b.get("tests", {}).get("failingClasses", [])) >= args.min_failures or 
            len(b.get("tests", {}).get("failingTests", [])) >= args.min_failures]
    
    print(f"Bugs with ≥{args.min_failures} failing tests: {len(bugs)}")
    
    if args.list:
        print("\n=== Available Bears Bugs ===")
        print(f"{'Bug ID':<15} {'Repository':<40} {'Failing Tests':<15}")
        print("-" * 75)
        for bug in bugs[:50]:
            bug_id = bug.get("bugId", "?")
            repo = bug.get("repository", {}).get("name", "?")
            num_tests = len(bug.get("tests", {}).get("failingClasses", [])) or \
                        len(bug.get("tests", {}).get("failingTests", []))
            print(f"{bug_id:<15} {repo:<40} {num_tests:<15}")
        if len(bugs) > 50:
            print(f"... and {len(bugs) - 50} more")
        return
    
    # Limit number of bugs
    if args.limit:
        bugs = bugs[:args.limit]
    
    print(f"\n=== Collecting {len(bugs)} Bears bugs ===")
    
    # Output files
    failures_file = os.path.join(args.output, "failure_instances_bears.jsonl")
    builds_file = os.path.join(args.output, "builds_bears.jsonl")
    
    # Clear existing files
    for f in [failures_file, builds_file]:
        if os.path.exists(f):
            os.remove(f)
    
    os.makedirs(args.output, exist_ok=True)
    
    total_failures = 0
    successful_bugs = 0
    
    for i, bug in enumerate(bugs):
        print(f"\n[{i+1}/{len(bugs)}]", end="")
        
        try:
            # Fetch detailed info
            bug_id = bug.get("bugId", "")
            details = fetch_bug_details(bug_id)
            
            failures, build_info = collect_bug(bug, details)
            
            if failures:
                save_failures(failures, failures_file)
                total_failures += len(failures)
                successful_bugs += 1
            
            if build_info:
                save_build_info(build_info, builds_file)
                
        except Exception as e:
            print(f"  Error: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print(f"\n{'='*60}")
    print(f"=== Collection Complete ===")
    print(f"{'='*60}")
    print(f"Successful bugs: {successful_bugs}/{len(bugs)}")
    print(f"Total failures collected: {total_failures}")
    print(f"\nOutput files:")
    print(f"  Failures: {failures_file}")
    print(f"  Builds: {builds_file}")


if __name__ == "__main__":
    main()

