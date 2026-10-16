#!/usr/bin/env python3
# Vendored from HyTri scripts/docker/collect_defects4j_v3.py @ 4039de468073f7a81c3eab2f577654880205467f
# Provided as-is for provenance of data/sources; not re-run for this release.
"""Collect Defects4J failures WITH DIFFS for change-aware evaluation - v3.

Key addition: Uses `defects4j diff` and `defects4j export` to get:
1. The actual unified diff (buggy → fixed)
2. List of modified source classes

This enables change-aware triage evaluation with REAL ground truth:
- Each failure knows which files were changed for its bug
- The diff shows exactly what code was modified

Usage in Docker:
    docker run -v $(pwd)/data:/output defects4j-collector python3 collect_defects4j_v3.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("/output")
WORK_DIR = Path("/tmp/defects4j_work")

# Defects4J projects and their bug counts
DEFECTS4J_PROJECTS = {
    "Chart": 26,
    "Cli": 40,
    "Closure": 176,
    "Codec": 18,
    "Collections": 4,
    "Compress": 47,
    "Csv": 16,
    "Gson": 18,
    "JacksonCore": 26,
    "JacksonDatabind": 112,
    "JacksonXml": 6,
    "Jsoup": 93,
    "JxPath": 22,
    "Lang": 65,
    "Math": 106,
    "Mockito": 38,
    "Time": 27,
}


def run_command(cmd, cwd=None, timeout=600):
    """Run a command and return output."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Timeout", "returncode": -1}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}


def checkout_bug(project: str, bug_id: int, work_dir: Path) -> bool:
    """Checkout a buggy version."""
    bug_dir = work_dir / f"{project}_{bug_id}"
    if bug_dir.exists():
        shutil.rmtree(bug_dir, ignore_errors=True)
    bug_dir.mkdir(parents=True)
    
    result = run_command(f"defects4j checkout -p {project} -v {bug_id}b -w {bug_dir}", timeout=300)
    return result["success"] and bug_dir.exists()


def compile_bug(project: str, bug_id: int, work_dir: Path) -> bool:
    """Compile the buggy version."""
    bug_dir = work_dir / f"{project}_{bug_id}"
    result = run_command("defects4j compile", cwd=str(bug_dir), timeout=600)
    return result["success"]


def get_bug_diff(project: str, bug_id: int, work_dir: Path) -> dict:
    """Get the diff between buggy and fixed versions.
    
    Strategy:
    1. Try Defects4J's internal patch files first (most reliable)
    2. Fall back to `defects4j diff` command
    
    Returns:
        {
            "diff": str,           # Full unified diff
            "changed_files": [],   # List of changed file paths
            "additions": int,      # Lines added
            "deletions": int,      # Lines deleted
        }
    """
    bug_dir = work_dir / f"{project}_{bug_id}"
    diff_content = ""
    
    # Strategy 1: Read from Defects4J patch files (most reliable)
    patch_paths = [
        f"/opt/defects4j/framework/projects/{project}/patches/{bug_id}.src.patch",
        f"/opt/defects4j/framework/projects/{project}/patches/{bug_id}.test.patch",
    ]
    
    for patch_path in patch_paths:
        try:
            # Try UTF-8 first, then fall back to latin-1 (handles all byte values)
            content = None
            for encoding in ['utf-8', 'latin-1', 'cp1252']:
                try:
                    with open(patch_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            
            if content:
                diff_content += content + "\n"
        except (FileNotFoundError, IOError, Exception) as e:
            # Gracefully skip if file can't be read
            pass
    
    # Strategy 2: Try defects4j diff command as fallback
    if not diff_content:
        result = run_command("defects4j diff", cwd=str(bug_dir), timeout=60)
        if result["success"] and result["stdout"]:
            diff_content = result["stdout"]
    
    if not diff_content:
        print(f"[no diff]", end="")
        return {"diff": "", "changed_files": [], "additions": 0, "deletions": 0}
    
    # Parse the diff to extract changed files and stats
    changed_files = []
    additions = 0
    deletions = 0
    
    for line in diff_content.split("\n"):
        # Extract file paths from diff headers
        # Format: diff -u a/path/to/File.java b/path/to/File.java
        # or:     --- a/path/to/File.java
        # or:     --- path/to/File.java (without a/ prefix)
        if line.startswith("diff "):
            match = re.search(r'b/(.+)$', line)
            if match:
                changed_files.append(match.group(1))
        elif line.startswith("--- "):
            # Handle both "--- a/path" and "--- path" formats
            file_path = line[4:].strip()
            if file_path.startswith("a/"):
                file_path = file_path[2:]
            # Remove timestamp if present (e.g., "File.java 2023-01-01 00:00:00")
            file_path = file_path.split("\t")[0].split(" ")[0]
            if file_path and file_path not in changed_files and not file_path.startswith("/dev/null"):
                changed_files.append(file_path)
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    
    return {
        "diff": diff_content[:100000],  # Limit size
        "changed_files": changed_files,
        "additions": additions,
        "deletions": deletions,
    }


def get_modified_classes(project: str, bug_id: int, work_dir: Path) -> list[str]:
    """Get the list of modified source classes.
    
    Uses `defects4j export -p classes.modified` which returns
    fully qualified class names like "org.apache.commons.lang.StringUtils"
    
    Returns list of file paths like "org/apache/commons/lang/StringUtils.java"
    """
    bug_dir = work_dir / f"{project}_{bug_id}"
    
    # Correct syntax: -p is for property name, run from checked-out dir
    result = run_command(
        "defects4j export -p classes.modified",
        cwd=str(bug_dir),
        timeout=30,
    )
    
    if not result["success"] or not result["stdout"]:
        print(f"    [export failed: {result['stderr'][:100]}]", end="")
        return []
    
    # Convert class names to file paths
    # "org.apache.commons.lang.StringUtils" → "org/apache/commons/lang/StringUtils.java"
    classes = []
    for line in result["stdout"].strip().split("\n"):
        line = line.strip()
        if line:
            file_path = line.replace(".", "/") + ".java"
            classes.append(file_path)
    
    return classes


def run_tests(project: str, bug_id: int, work_dir: Path) -> list[dict]:
    """Run tests and parse failures from failing_tests file."""
    bug_dir = work_dir / f"{project}_{bug_id}"
    
    # Run all tests
    run_command("defects4j test", cwd=str(bug_dir), timeout=600)
    
    # Parse failing_tests file
    failing_tests_file = bug_dir / "failing_tests"
    if not failing_tests_file.exists():
        return []
    
    with open(failing_tests_file) as f:
        content = f.read()
    
    # Parse format: each failure starts with "--- test.name::method"
    failures = []
    blocks = re.split(r'^--- ', content, flags=re.MULTILINE)
    
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        
        lines = block.split('\n')
        if not lines:
            continue
        
        # First line is test name
        test_name = lines[0].strip()
        if not test_name or '::' not in test_name:
            continue
        
        # Rest is the stack trace
        stack_trace = '\n'.join(lines[1:]).strip()
        
        # Parse exception
        exc_type = "TestFailure"
        exc_message = ""
        
        for line in lines[1:5]:
            match = re.match(r'^([\w.]+(?:Error|Exception)):\s*(.*)$', line.strip())
            if match:
                exc_type = match.group(1).split('.')[-1]
                exc_message = match.group(2)[:500]
                break
            
            if 'expected:' in line.lower():
                exc_type = "AssertionError"
                assert_match = re.search(r'expected:<(.+?)> but was:<(.+?)>', line)
                if assert_match:
                    exc_message = f"expected:<{assert_match.group(1)[:100]}> but was:<{assert_match.group(2)[:100]}>"
                break
        
        # Extract stack frames
        frames = []
        frame_pattern = re.compile(r'at\s+([\w.$]+)\.([\w$<>]+)\(([\w.]+):(\d+)\)')
        for match in frame_pattern.finditer(stack_trace):
            class_name = match.group(1)
            method = match.group(2)
            file_name = match.group(3)
            line_num = int(match.group(4))
            
            frames.append({
                "file": file_name,
                "line": line_num,
                "func": f"{class_name.split('.')[-1]}.{method}",
            })
        
        failures.append({
            "test_name": test_name,
            "exception_type": exc_type,
            "exception_message": exc_message,
            "stack_trace": stack_trace[:5000],
            "frames": frames[:20],
        })
    
    return failures


def main():
    """Main collection function with diff extraction."""
    print("=" * 60)
    print("Defects4J Failure Collection v3 (WITH DIFFS)")
    print("=" * 60)
    
    os.system("java -version 2>&1 | head -1")
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    
    # Get configuration
    projects_str = os.environ.get("PROJECTS", "")
    if projects_str:
        projects = {p: DEFECTS4J_PROJECTS.get(p, 10) for p in projects_str.split(",") if p in DEFECTS4J_PROJECTS}
    else:
        projects = DEFECTS4J_PROJECTS
    
    max_bugs = int(os.environ.get("MAX_BUGS", "100"))
    
    print(f"\nProjects: {', '.join(projects.keys())}")
    print(f"Max bugs per project: {max_bugs}")
    
    all_failures = []
    all_builds = []
    
    # Also store per-bug diff info separately for easy lookup
    bug_diffs = {}
    
    stats = {
        "bugs_processed": 0, 
        "failures_captured": 0, 
        "compile_errors": 0, 
        "passed": 0,
        "diffs_collected": 0,
    }
    
    for project, total_bugs in projects.items():
        print(f"\n{'='*60}")
        print(f"Processing: {project} ({min(total_bugs, max_bugs)} bugs)")
        print(f"{'='*60}")
        
        project_failures = []
        
        for bug_id in range(1, min(total_bugs, max_bugs) + 1):
            print(f"\n  Bug {bug_id}: ", end="", flush=True)
            stats["bugs_processed"] += 1
            
            bug_key = f"{project}-{bug_id}"
            
            try:
                # Checkout
                if not checkout_bug(project, bug_id, WORK_DIR):
                    print("checkout failed")
                    continue
                
                # Compile
                if not compile_bug(project, bug_id, WORK_DIR):
                    print("compile failed")
                    stats["compile_errors"] += 1
                    continue
                
                # ===== NEW: Get diff information =====
                diff_info = get_bug_diff(project, bug_id, WORK_DIR)
                modified_classes = get_modified_classes(project, bug_id, WORK_DIR)
                
                # Merge: prefer diff-extracted files, fall back to modified_classes
                changed_files = diff_info["changed_files"] if diff_info["changed_files"] else modified_classes
                
                # Store for later reference
                bug_diffs[bug_key] = {
                    "changed_files": changed_files,
                    "diff": diff_info["diff"],
                    "additions": diff_info["additions"],
                    "deletions": diff_info["deletions"],
                    "modified_classes": modified_classes,
                }
                
                if diff_info["diff"]:
                    stats["diffs_collected"] += 1
                # =====================================
                
                # Run tests and parse failures
                failures = run_tests(project, bug_id, WORK_DIR)
                
                if not failures:
                    print(f"PASSED (+{diff_info['additions']}/-{diff_info['deletions']})")
                    stats["passed"] += 1
                    # Still save the diff info even if tests pass
                    continue
                
                # Create failure instances WITH DIFF INFO
                for i, failure in enumerate(failures[:20]):
                    build_id = f"defects4j_{project}_{bug_id}"
                    
                    failure_data = {
                        "build_id": build_id,
                        "failure_id": f"{build_id}::failure_{i}",
                        "test_name": failure["test_name"],
                        "exception_type": failure["exception_type"],
                        "exception_message": failure["exception_message"],
                        "stack_trace": failure["stack_trace"],
                        "frames": failure["frames"],
                        "stderr": "",
                        "stdout": "",
                        "project": project,
                        "bug_id": bug_key,
                        "timestamp": datetime.now().isoformat(),
                        # ===== CHANGE INFO =====
                        "changed_files": changed_files,
                        "file_diffs": {f: diff_info["diff"] for f in changed_files[:5]},  # Map files to diff
                        "diff_stats": {
                            "additions": diff_info["additions"],
                            "deletions": diff_info["deletions"],
                        },
                        # =======================
                        "ground_truth": {
                            "root_cause_id": bug_key,
                            "changed_files": changed_files,
                        },
                        "language": "java",
                    }
                    project_failures.append(failure_data)
                    stats["failures_captured"] += 1
                
                print(f"✓ {len(failures)} failures, {len(changed_files)} files (+{diff_info['additions']}/-{diff_info['deletions']})")
                
                # Cleanup
                bug_dir = WORK_DIR / f"{project}_{bug_id}"
                if bug_dir.exists():
                    shutil.rmtree(bug_dir, ignore_errors=True)
                    
            except Exception as e:
                print(f"ERROR: {type(e).__name__}: {str(e)[:100]}")
                # Cleanup on error too
                bug_dir = WORK_DIR / f"{project}_{bug_id}"
                if bug_dir.exists():
                    shutil.rmtree(bug_dir, ignore_errors=True)
                continue
        
        if project_failures:
            all_failures.extend(project_failures)
            
            # Create build entry
            unique_bugs = list(set(f["bug_id"] for f in project_failures))
            all_builds.append({
                "build_id": f"defects4j_{project}_all",
                "project": project,
                "bug_ids": unique_bugs,
                "num_failures": len(project_failures),
                "num_bugs": len(unique_bugs),
                "language": "java",
                "timestamp": datetime.now().isoformat(),
            })
    
    # Save output
    if all_failures:
        failures_path = OUTPUT_DIR / "failure_instances_defects4j.jsonl"
        builds_path = OUTPUT_DIR / "builds_defects4j.jsonl"
        diffs_path = OUTPUT_DIR / "defects4j_diffs.json"
        
        with open(failures_path, "w") as f:
            for failure in all_failures:
                f.write(json.dumps(failure, default=str) + "\n")
        
        with open(builds_path, "w") as f:
            for build in all_builds:
                f.write(json.dumps(build, default=str) + "\n")
        
        # Save diffs separately for easy lookup
        with open(diffs_path, "w") as f:
            json.dump(bug_diffs, f, indent=2)
        
        print(f"\n{'='*60}")
        print("Dataset saved!")
        print(f"  - {failures_path}: {len(all_failures)} failures")
        print(f"  - {builds_path}: {len(all_builds)} builds")
        print(f"  - {diffs_path}: {len(bug_diffs)} bug diffs")
    
    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Sample output
    if all_failures:
        print(f"\n{'='*60}")
        print("Sample failure with diff info:")
        print(f"{'='*60}")
        sample = all_failures[0]
        print(f"  test_name: {sample['test_name']}")
        print(f"  exception_type: {sample['exception_type']}")
        print(f"  bug_id: {sample['bug_id']}")
        print(f"  changed_files: {sample['changed_files']}")
        print(f"  diff_stats: {sample['diff_stats']}")


if __name__ == "__main__":
    main()
