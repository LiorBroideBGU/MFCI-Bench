#!/usr/bin/env python3
# Vendored from HyTri scripts/docker/collect_bugswarm.py @ 4039de468073f7a81c3eab2f577654880205467f
# Provided as-is for provenance of data/sources; not re-run for this release.
"""BugSwarm Failure Collection Script (Code-Aware Edition).

Collects test failures from BugSwarm artifacts for HyTri evaluation.
BugSwarm provides real CI failures from GitHub projects via Docker images.

This version extracts CODE DIFFS between the passing and failing versions,
enabling code-aware fault localization (like Build Sheriff paper).

Usage:
    # List available artifacts
    python collect_bugswarm.py --list --min-failures 3
    
    # Collect failures from specific artifacts
    python collect_bugswarm.py --image-tags tag1 tag2 tag3
    
    # Collect failures with code diffs (default now!)
    python collect_bugswarm.py --min-failures 3 --limit 50 --output /output

Requirements:
    - Docker installed and running
    - Network access to BugSwarm API and DockerHub
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import ssl
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path


# BugSwarm API endpoint
BUGSWARM_API_URL = "https://www.bugswarm.org/_datatables/"
BUGSWARM_DOCKER_REPO = "bugswarm/images"


@dataclass
class StackFrame:
    """Represents a single frame in a stack trace."""
    file: str
    line: int
    func: str


@dataclass
class FailureInstance:
    """Represents a single test failure."""
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


def get_ssl_context() -> ssl.SSLContext:
    """Create SSL context (skip verification for BugSwarm API)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_bugswarm_artifacts(
    languages: List[str] = ["Java", "Python"],
    min_failures: int = 1,
) -> List[Dict]:
    """Fetch artifact metadata from BugSwarm API.
    
    Args:
        languages: Languages to filter (Java, Python)
        min_failures: Minimum number of test failures
        
    Returns:
        List of artifact metadata dictionaries
    """
    filter_obj = {
        "lang": languages,
        "build_system": ["Maven", "Ant", "Gradle", "NA"],
        "classification": {
            "code": ["Yes", "Partial", "No", "NA"],
            "build": ["Yes", "Partial", "No", "NA"],
            "test": ["Yes", "Partial", "No", "NA"]
        }
    }
    filter_str = json.dumps(filter_obj)
    encoded = urllib.parse.quote(filter_str, safe="")
    url = f"{BUGSWARM_API_URL}?filter={encoded}"
    
    req = urllib.request.Request(url, headers={"User-Agent": "HyTri-Collector/1.0"})
    ctx = get_ssl_context()
    
    print(f"Fetching artifacts from BugSwarm API...")
    with urllib.request.urlopen(req, timeout=60, context=ctx) as response:
        data = json.loads(response.read().decode("utf-8"))
    
    # Filter by minimum failures
    filtered = []
    for artifact in data:
        num_failed = artifact.get("failed_job", {}).get("num_tests_failed", 0)
        if num_failed >= min_failures:
            artifact["_num_failures"] = num_failed
            filtered.append(artifact)
    
    # Sort by number of failures (descending) for prioritization
    filtered.sort(key=lambda x: x["_num_failures"], reverse=True)
    
    print(f"Found {len(filtered)} artifacts with ≥{min_failures} failures")
    return filtered


def pull_docker_image(image_tag: str) -> bool:
    """Pull a BugSwarm Docker image.
    
    Args:
        image_tag: The BugSwarm image tag
        
    Returns:
        True if successful
    """
    full_image = f"{BUGSWARM_DOCKER_REPO}:{image_tag}"
    print(f"  Pulling Docker image: {full_image}")
    
    try:
        result = subprocess.run(
            ["docker", "pull", full_image],
            capture_output=True,
            text=True,
            timeout=650
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"    Timeout pulling image")
        return False
    except Exception as e:
        print(f"    Error pulling image: {e}")
        return False


def get_stored_test_log(image_tag: str) -> Optional[str]:
    """Get the pre-captured test log from a BugSwarm container.
    
    BugSwarm containers include original CI logs, which is faster than re-running
    tests and works on any architecture (avoids amd64/arm64 issues).
    
    Args:
        image_tag: The BugSwarm image tag
        
    Returns:
        Test log content or None if not found
    """
    full_image = f"{BUGSWARM_DOCKER_REPO}:{image_tag}"
    
    # The image tag often contains the failing job ID - extract it
    # Format: owner-repo-JOBID
    parts = image_tag.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        job_id = parts[1]
    else:
        job_id = None
    
    try:
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "--entrypoint", "/bin/bash",
                full_image,
                "-c", f"""
                # Find the correct build directory (github or travis)
                if [ -d /home/github/build ]; then
                    BUILD_BASE=/home/github/build
                elif [ -d /home/travis/build ]; then
                    BUILD_BASE=/home/travis/build
                else
                    echo "ERROR: Cannot find build directory"
                    exit 1
                fi
                
                # Look for stored test logs
                # Newer BugSwarm: *-orig.log files
                # Try to find the failing job log (the one matching this image tag's job ID)
                LOG_FILE=""
                if [ -n "{job_id or ''}" ]; then
                    LOG_FILE=$(find $BUILD_BASE -name "{job_id}-orig.log" 2>/dev/null | head -1)
                fi
                
                # Fallback: find any -orig.log that looks like a failed build
                if [ -z "$LOG_FILE" ]; then
                    LOG_FILE=$(find $BUILD_BASE -name "*-orig.log" 2>/dev/null | head -1)
                fi
                
                # Output the log
                if [ -n "$LOG_FILE" ] && [ -f "$LOG_FILE" ]; then
                    cat "$LOG_FILE"
                else
                    echo "NO_LOG_FOUND"
                fi
                """
            ],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        output = result.stdout
        if "NO_LOG_FOUND" in output:
            return None
        return output
        
    except subprocess.TimeoutExpired:
        print(f"    Timeout reading log")
        return None
    except Exception as e:
        print(f"    Error reading log: {e}")
        return None


def run_failing_tests(image_tag: str, language: str) -> Optional[str]:
    """Get test failure output from a BugSwarm container.
    
    First tries to read pre-captured logs (faster, architecture-independent).
    Falls back to re-running tests if no logs are available.
    
    Args:
        image_tag: The BugSwarm image tag
        language: "Java" or "Python"
        
    Returns:
        Test output or None if failed
    """
    # First try to get stored logs (faster and works on any architecture)
    print(f"    Reading stored test logs...")
    log_content = get_stored_test_log(image_tag)
    if log_content:
        return log_content
    
    # Fallback: re-run tests (may fail on ARM Macs for amd64 images)
    print(f"    No stored logs found, attempting to re-run tests...")
    full_image = f"{BUGSWARM_DOCKER_REPO}:{image_tag}"
    
    try:
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "--entrypoint", "/bin/bash",
                full_image,
                "-c", """
                # Find the correct build directory (github or travis)
                if [ -d /home/github/build/failed ]; then
                    BUILD_BASE=/home/github/build
                elif [ -d /home/travis/build/failed ]; then
                    BUILD_BASE=/home/travis/build
                else
                    echo "ERROR: Cannot find build directory"
                    exit 1
                fi
                
                cd $BUILD_BASE/failed/*/* 2>/dev/null || cd $BUILD_BASE/failed
                /usr/local/bin/run_failed.sh 2>&1 || true
                """
            ],
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        print(f"    Test execution timeout")
        return None
    except Exception as e:
        print(f"    Error running tests: {e}")
        return None


def extract_code_diff(image_tag: str) -> Dict[str, Any]:
    """Extract code diff between passed and failed versions.
    
    This is the key function for code-aware fault localization!
    It compares the passing (previous) version to the failing (current) version.
    
    Args:
        image_tag: The BugSwarm image tag
        
    Returns:
        Dictionary with:
        - changed_files: List of changed file paths
        - file_diffs: Dict mapping file path to unified diff
        - additions: Total lines added
        - deletions: Total lines deleted
    """
    full_image = f"{BUGSWARM_DOCKER_REPO}:{image_tag}"
    
    # First, get list of changed files
    try:
        # Use diff -rq for quick file comparison
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "--entrypoint", "/bin/bash",
                full_image,
                "-c", """
                # Find the correct build directory (github or travis)
                if [ -d /home/github/build/failed ]; then
                    BUILD_BASE=/home/github/build
                elif [ -d /home/travis/build/failed ]; then
                    BUILD_BASE=/home/travis/build
                else
                    echo "ERROR: Cannot find build directory"
                    exit 1
                fi
                
                cd $BUILD_BASE
                
                # Find the actual repo directories (they're named after the repo)
                FAILED_DIR=$(ls -d failed/*/* 2>/dev/null | head -1)
                PASSED_DIR=$(ls -d passed/*/* 2>/dev/null | head -1)
                
                if [ -z "$FAILED_DIR" ] || [ -z "$PASSED_DIR" ]; then
                    # Try alternate structure
                    FAILED_DIR="failed"
                    PASSED_DIR="passed"
                fi
                
                echo "BUILD_BASE=$BUILD_BASE"
                echo "FAILED_DIR=$FAILED_DIR"
                echo "PASSED_DIR=$PASSED_DIR"
                echo "DIFF_START"
                diff -rq "$PASSED_DIR" "$FAILED_DIR" 2>/dev/null || true
                echo "DIFF_END"
                """
            ],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        quick_diff = result.stdout
        
    except subprocess.TimeoutExpired:
        print(f"    Timeout getting file list")
        return {"changed_files": [], "file_diffs": {}, "additions": 0, "deletions": 0}
    except Exception as e:
        print(f"    Error getting file list: {e}")
        return {"changed_files": [], "file_diffs": {}, "additions": 0, "deletions": 0}
    
    # Parse changed files from quick diff
    changed_files = []
    
    # Extract debug info and diff output
    build_base = ""
    failed_dir = ""
    passed_dir = ""
    
    for line in quick_diff.strip().split("\n"):
        if line.startswith("BUILD_BASE="):
            build_base = line.split("=", 1)[1]
        elif line.startswith("FAILED_DIR="):
            failed_dir = line.split("=", 1)[1]
        elif line.startswith("PASSED_DIR="):
            passed_dir = line.split("=", 1)[1]
    
    # Extract the diff output between markers
    if "DIFF_START" in quick_diff and "DIFF_END" in quick_diff:
        diff_section = quick_diff.split("DIFF_START")[1].split("DIFF_END")[0]
    else:
        diff_section = quick_diff
    
    for line in diff_section.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        
        # Pattern: "Files X and Y differ" or "Only in X: filename"
        if line.startswith("Files ") and " differ" in line:
            # Extract the file path from "Files passed/.../file and failed/.../file differ"
            parts = line.split(" and ")
            if len(parts) >= 2:
                file_path = parts[1].replace(" differ", "").strip()
                # Remove the failed/owner/repo prefix to get relative path
                # e.g., "failed/forge/roaster/impl/src/..." -> "impl/src/..."
                if failed_dir and file_path.startswith(failed_dir):
                    file_path = file_path[len(failed_dir):].lstrip("/")
                elif "failed/" in file_path:
                    # Fallback: split on failed/ and take after repo name
                    parts_split = file_path.split("failed/", 1)
                    if len(parts_split) > 1:
                        # Skip owner/repo prefix
                        remaining = parts_split[1]
                        path_parts = remaining.split("/", 2)
                        if len(path_parts) > 2:
                            file_path = path_parts[2]
                        else:
                            file_path = remaining
                
                # Skip non-source files
                if not should_skip_file(file_path):
                    changed_files.append(file_path)
                    
        elif line.startswith("Only in "):
            # New or deleted file
            # "Only in failed/repo/path: filename"
            if ": " in line:
                dir_part, filename = line.rsplit(": ", 1)
                dir_path = dir_part.replace("Only in ", "")
                
                # Skip .git directories
                if "/.git" in dir_path or dir_path.endswith(".git"):
                    continue
                
                # Determine relative path
                if failed_dir and dir_path.startswith(failed_dir):
                    rel_path = dir_path[len(failed_dir):].lstrip("/")
                elif passed_dir and dir_path.startswith(passed_dir):
                    rel_path = dir_path[len(passed_dir):].lstrip("/")
                elif "failed/" in dir_path:
                    parts_split = dir_path.split("failed/", 1)
                    if len(parts_split) > 1:
                        remaining = parts_split[1]
                        path_parts = remaining.split("/", 2)
                        rel_path = path_parts[2] if len(path_parts) > 2 else ""
                    else:
                        rel_path = ""
                elif "passed/" in dir_path:
                    parts_split = dir_path.split("passed/", 1)
                    if len(parts_split) > 1:
                        remaining = parts_split[1]
                        path_parts = remaining.split("/", 2)
                        rel_path = path_parts[2] if len(path_parts) > 2 else ""
                    else:
                        rel_path = ""
                else:
                    continue
                
                full_path = os.path.join(rel_path, filename) if rel_path else filename
                if not should_skip_file(full_path):
                    changed_files.append(full_path)
    
    if not changed_files:
        print(f"    No source file changes detected")
        return {"changed_files": [], "file_diffs": {}, "additions": 0, "deletions": 0}
    
    print(f"    Found {len(changed_files)} changed files")
    
    # Now get actual diffs for changed source files (limit to first 20)
    file_diffs = {}
    total_additions = 0
    total_deletions = 0
    
    for file_path in changed_files[:20]:
        diff_content = get_file_diff(image_tag, file_path)
        if diff_content:
            file_diffs[file_path] = diff_content
            # Count additions/deletions
            for line in diff_content.split("\n"):
                if line.startswith("+") and not line.startswith("+++"):
                    total_additions += 1
                elif line.startswith("-") and not line.startswith("---"):
                    total_deletions += 1
    
    return {
        "changed_files": changed_files,
        "file_diffs": file_diffs,
        "additions": total_additions,
        "deletions": total_deletions
    }


def should_skip_file(file_path: str) -> bool:
    """Check if a file should be skipped (non-source, build artifacts, etc.)."""
    skip_patterns = [
        ".git", ".svn", ".hg",
        "__pycache__", ".pyc", ".pyo",
        ".class", ".jar", ".war",
        "node_modules", "target/", "build/", "dist/",
        ".log", ".tmp", ".cache",
        ".png", ".jpg", ".gif", ".ico",
        ".pdf", ".doc", ".docx",
        "package-lock.json", "yarn.lock",
        ".idea", ".vscode", ".eclipse",
    ]
    
    file_lower = file_path.lower()
    for pattern in skip_patterns:
        if pattern in file_lower:
            return True
    
    return False


def get_file_diff(image_tag: str, file_path: str) -> Optional[str]:
    """Get unified diff for a specific file between passed and failed versions.
    
    Args:
        image_tag: The BugSwarm image tag
        file_path: Relative path to the file
        
    Returns:
        Unified diff string or None
    """
    full_image = f"{BUGSWARM_DOCKER_REPO}:{image_tag}"
    
    # Escape the file path for shell
    escaped_path = file_path.replace("'", "'\\''")
    
    try:
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "--entrypoint", "/bin/bash",
                full_image,
                "-c", f"""
                # Find the correct build directory (github or travis)
                if [ -d /home/github/build/failed ]; then
                    BUILD_BASE=/home/github/build
                elif [ -d /home/travis/build/failed ]; then
                    BUILD_BASE=/home/travis/build
                else
                    exit 1
                fi
                
                cd $BUILD_BASE
                
                # Find the actual repo directories
                FAILED_DIR=$(ls -d failed/*/* 2>/dev/null | head -1)
                PASSED_DIR=$(ls -d passed/*/* 2>/dev/null | head -1)
                
                if [ -z "$FAILED_DIR" ] || [ -z "$PASSED_DIR" ]; then
                    FAILED_DIR="failed"
                    PASSED_DIR="passed"
                fi
                
                PASSED_FILE="$PASSED_DIR/{escaped_path}"
                FAILED_FILE="$FAILED_DIR/{escaped_path}"
                
                # Handle file existence
                if [ -f "$PASSED_FILE" ] && [ -f "$FAILED_FILE" ]; then
                    diff -u "$PASSED_FILE" "$FAILED_FILE" 2>/dev/null || true
                elif [ -f "$FAILED_FILE" ]; then
                    echo "--- /dev/null"
                    echo "+++ $FAILED_FILE"
                    echo "@@ -0,0 +1,$(wc -l < "$FAILED_FILE") @@"
                    cat "$FAILED_FILE" | sed 's/^/+/'
                elif [ -f "$PASSED_FILE" ]; then
                    echo "--- $PASSED_FILE"
                    echo "+++ /dev/null"
                    echo "@@ -1,$(wc -l < "$PASSED_FILE") +0,0 @@"
                    cat "$PASSED_FILE" | sed 's/^/-/'
                fi
                """
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        diff_output = result.stdout.strip()
        if diff_output:
            # Truncate very long diffs
            if len(diff_output) > 10000:
                diff_output = diff_output[:10000] + "\n... [truncated]"
            return diff_output
        return None
        
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


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


def parse_python_stack_trace(trace: str, max_frames: int = 20) -> List[Dict[str, Any]]:
    """Parse Python stack trace into frames.
    
    Args:
        trace: Raw stack trace string
        max_frames: Maximum frames to extract
        
    Returns:
        List of frame dictionaries
    """
    frames = []
    # Match: File "path/to/file.py", line 123, in function_name
    pattern = r'File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+(\w+)'
    
    for match in re.finditer(pattern, trace):
        file = os.path.basename(match.group(1))
        line = int(match.group(2))
        func = match.group(3)
        
        frames.append({
            "file": file,
            "line": line,
            "func": func
        })
        
        if len(frames) >= max_frames:
            break
    
    return frames


def clean_log_line(line: str) -> str:
    """Remove timestamps and ANSI codes from log lines.
    
    Handles GitHub Actions format: 2024-12-03T10:34:22.2422644Z [ERROR] ...
    """
    # Remove GitHub Actions timestamp prefix
    line = re.sub(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s*', '', line)
    # Remove ANSI color codes
    line = re.sub(r'\x1b\[[0-9;]*m', '', line)
    return line


def parse_junit_output(output: str, artifact: Dict) -> List[FailureInstance]:
    """Parse JUnit/Maven test output to extract failures.
    
    Args:
        output: Raw test output (may include GitHub Actions timestamps)
        artifact: Artifact metadata
        
    Returns:
        List of FailureInstance objects
    """
    failures = []
    image_tag = artifact["image_tag"]
    repo = artifact["repo"]
    language = artifact["lang"]
    
    # Clean the output - remove timestamps for easier parsing
    cleaned_lines = [clean_log_line(line) for line in output.split('\n')]
    cleaned_output = '\n'.join(cleaned_lines)
    
    # Pattern for Maven/Surefire test errors
    # [ERROR] org.jboss.forge.test.roaster.model.JavaClassTest.testParse -- Time elapsed: 0.003 s <<< ERROR!
    # java.lang.IllegalStateException: Missing system library
    
    test_error_pattern = r'\[ERROR\]\s+([a-zA-Z0-9_.]+(?:\.[a-zA-Z0-9_]+)+)\s+--\s+Time elapsed:.*<<<\s*(ERROR|FAILURE)!'
    
    failure_idx = 0
    seen_tests = set()
    
    lines = cleaned_output.split('\n')
    for i, line in enumerate(lines):
        match = re.search(test_error_pattern, line)
        if match:
            full_test_name = match.group(1)  # e.g., org.jboss.forge.test.roaster.model.JavaClassTest.testParse
            error_type = match.group(2)  # ERROR or FAILURE
            
            # Skip duplicates
            if full_test_name in seen_tests:
                continue
            seen_tests.add(full_test_name)
            
            # Look for exception in next few lines
            exception_type = "UnknownException"
            exception_message = ""
            stack_trace_lines = []
            
            for j in range(i + 1, min(i + 30, len(lines))):
                next_line = lines[j].strip()
                if not next_line:
                    continue
                    
                # Check for exception line (e.g., "java.lang.IllegalStateException: Missing system library")
                exc_match = re.match(r'^([a-zA-Z0-9_.]+(?:Exception|Error)):\s*(.*)$', next_line)
                if exc_match and not stack_trace_lines:
                    exception_type = exc_match.group(1).split('.')[-1]
                    exception_message = exc_match.group(2)
                    stack_trace_lines.append(next_line)
                # Check for stack trace line
                elif next_line.startswith('at '):
                    stack_trace_lines.append(next_line)
                # Check for "Caused by:"
                elif next_line.startswith('Caused by:'):
                    stack_trace_lines.append(next_line)
                # Stop if we hit another test or marker
                elif '[ERROR]' in next_line or '[INFO]' in next_line:
                    break
            
            full_trace = '\n'.join(stack_trace_lines) if stack_trace_lines else ""
            frames = parse_java_stack_trace(full_trace) if language == "Java" else parse_python_stack_trace(full_trace)
            
            # Extract short test name
            test_name = full_test_name.split('.')[-1] if '.' in full_test_name else full_test_name
            test_class = '.'.join(full_test_name.split('.')[:-1]) if '.' in full_test_name else ""
            
            failure = FailureInstance(
                build_id=f"bugswarm_{image_tag}",
                failure_id=f"bugswarm_{image_tag}::failure_{failure_idx}",
                test_name=f"{test_class}::{test_name}" if test_class else test_name,
                exception_type=exception_type,
                exception_message=exception_message[:500],
                stack_trace=full_trace[:5000],
                frames=frames,
                stderr="",
                stdout="",
                project=repo.replace("/", "_"),
                bug_id=image_tag,
                timestamp=datetime.now().isoformat(),
                ground_truth={
                    "root_cause_id": image_tag,
                    "changed_files": [],
                    "diff_url": artifact.get("diff_url", "")
                },
                language=language.lower()
            )
            failures.append(failure)
            failure_idx += 1
    
    return failures


def parse_pytest_output(output: str, artifact: Dict) -> List[FailureInstance]:
    """Parse pytest output to extract failures.
    
    Args:
        output: Raw pytest output
        artifact: Artifact metadata
        
    Returns:
        List of FailureInstance objects
    """
    failures = []
    image_tag = artifact["image_tag"]
    repo = artifact["repo"]
    
    # pytest failure patterns
    # FAILED test_file.py::TestClass::test_method - ExceptionType: message
    # Then traceback follows
    
    # Split by FAILED markers
    failure_pattern = r"FAILED\s+([^\s]+)\s+-\s+(\w+(?:Error|Exception|Failure)?):?\s*([^\n]*)"
    stack_pattern = r"(Traceback \(most recent call last\):[\s\S]*?(?=\n\n|\nFAILED|\nPASSED|\n=+|\Z))"
    
    failure_idx = 0
    
    for match in re.finditer(failure_pattern, output):
        test_name = match.group(1)
        exception_type = match.group(2)
        exception_message = match.group(3)
        
        # Find traceback after this failure
        remaining = output[match.end():]
        stack_match = re.search(stack_pattern, remaining)
        
        full_trace = stack_match.group(1) if stack_match else ""
        frames = parse_python_stack_trace(full_trace)
        
        failure = FailureInstance(
            build_id=f"bugswarm_{image_tag}",
            failure_id=f"bugswarm_{image_tag}::failure_{failure_idx}",
            test_name=test_name,
            exception_type=exception_type,
            exception_message=exception_message[:500],
            stack_trace=full_trace[:5000],
            frames=frames,
            stderr="",
            stdout="",
            project=repo.replace("/", "_"),
            bug_id=image_tag,
            timestamp=datetime.now().isoformat(),
            ground_truth={
                "root_cause_id": image_tag,
                "changed_files": [],
                "diff_url": artifact.get("diff_url", "")
            },
            language="python"
        )
        failures.append(failure)
        failure_idx += 1
    
    return failures


def parse_test_output(output: str, artifact: Dict) -> List[FailureInstance]:
    """Parse test output based on language.
    
    Args:
        output: Raw test output
        artifact: Artifact metadata
        
    Returns:
        List of FailureInstance objects
    """
    language = artifact.get("lang", "Java")
    
    if language == "Python":
        failures = parse_pytest_output(output, artifact)
    else:
        failures = parse_junit_output(output, artifact)
    
    # Fallback: simple pattern matching if no failures found
    if not failures:
        failures = parse_generic_failures(output, artifact)
    
    return failures


def parse_generic_failures(output: str, artifact: Dict) -> List[FailureInstance]:
    """Generic fallback parser for test failures.
    
    Looks for common exception patterns across languages.
    """
    failures = []
    image_tag = artifact["image_tag"]
    repo = artifact["repo"]
    language = artifact.get("lang", "Java").lower()
    
    # Generic exception patterns
    if language == "java":
        exc_pattern = r"((?:java\.|org\.)[.\w]+(?:Exception|Error)):\s*([^\n]*)((?:\n\s+at\s+[^\n]+)+)"
    else:
        exc_pattern = r"(\w+(?:Error|Exception)):\s*([^\n]*)((?:\n\s+File\s+[^\n]+)+)?"
    
    failure_idx = 0
    seen_traces = set()
    
    for match in re.finditer(exc_pattern, output):
        exception_type = match.group(1).split(".")[-1]
        exception_message = match.group(2)
        trace_part = match.group(3) or ""
        
        # Deduplicate
        trace_key = f"{exception_type}:{exception_message[:50]}:{trace_part[:100]}"
        if trace_key in seen_traces:
            continue
        seen_traces.add(trace_key)
        
        full_trace = f"{exception_type}: {exception_message}{trace_part}"
        
        if language == "java":
            frames = parse_java_stack_trace(full_trace)
        else:
            frames = parse_python_stack_trace(full_trace)
        
        failure = FailureInstance(
            build_id=f"bugswarm_{image_tag}",
            failure_id=f"bugswarm_{image_tag}::failure_{failure_idx}",
            test_name=f"unknown_test_{failure_idx}",
            exception_type=exception_type,
            exception_message=exception_message[:500],
            stack_trace=full_trace[:5000],
            frames=frames,
            stderr="",
            stdout="",
            project=repo.replace("/", "_"),
            bug_id=image_tag,
            timestamp=datetime.now().isoformat(),
            ground_truth={
                "root_cause_id": image_tag,
                "changed_files": [],
                "diff_url": artifact.get("diff_url", "")
            },
            language=language
        )
        failures.append(failure)
        failure_idx += 1
    
    return failures


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


def collect_artifact_failures(
    artifact: Dict, 
    keep_image: bool = False,
    extract_diffs: bool = True
) -> tuple[List[FailureInstance], Optional[BuildInfo]]:
    """Collect failures and code diffs from a single BugSwarm artifact.
    
    Args:
        artifact: Artifact metadata from API
        keep_image: Whether to keep Docker image after collection
        extract_diffs: Whether to extract code diffs (default True)
        
    Returns:
        Tuple of (List of FailureInstance objects, BuildInfo or None)
    """
    image_tag = artifact["image_tag"]
    print(f"\nProcessing artifact: {image_tag}")
    print(f"  Repo: {artifact['repo']}")
    print(f"  Language: {artifact['lang']}")
    print(f"  Expected failures: {artifact.get('_num_failures', '?')}")
    
    # Pull Docker image
    if not pull_docker_image(image_tag):
        print(f"  Failed to pull image, skipping")
        return [], None
    
    # Extract code diffs FIRST (this is the key addition!)
    code_diff_info = {"changed_files": [], "file_diffs": {}, "additions": 0, "deletions": 0}
    if extract_diffs:
        print(f"  Extracting code diffs...")
        code_diff_info = extract_code_diff(image_tag)
        print(f"    Changed files: {len(code_diff_info['changed_files'])}")
        print(f"    Lines: +{code_diff_info['additions']} -{code_diff_info['deletions']}")
    
    # Run failing tests
    output = run_failing_tests(image_tag, artifact["lang"])
    if not output:
        print(f"  Failed to run tests, skipping")
        # Clean up
        if not keep_image:
            full_image = f"{BUGSWARM_DOCKER_REPO}:{image_tag}"
            subprocess.run(["docker", "rmi", full_image], capture_output=True)
        return [], None
    
    # Parse failures
    failures = parse_test_output(output, artifact)
    print(f"  Extracted {len(failures)} failures")
    
    # Update ground_truth with code diff info for each failure
    for failure in failures:
        failure.ground_truth["changed_files"] = code_diff_info["changed_files"]
        failure.ground_truth["additions"] = code_diff_info["additions"]
        failure.ground_truth["deletions"] = code_diff_info["deletions"]
        # Store file diffs separately to avoid bloating failure instances
        failure.ground_truth["has_diffs"] = len(code_diff_info["file_diffs"]) > 0
    
    # Create build info
    build_info = BuildInfo(
        build_id=f"bugswarm_{image_tag}",
        project=artifact["repo"].replace("/", "_"),
        repo=artifact["repo"],
        language=artifact["lang"].lower(),
        image_tag=image_tag,
        num_failures=len(failures),
        changed_files=code_diff_info["changed_files"],
        file_diffs=code_diff_info["file_diffs"],
        additions=code_diff_info["additions"],
        deletions=code_diff_info["deletions"],
        diff_url=artifact.get("diff_url", ""),
        classification={
            "code": artifact.get("classification", {}).get("code", "NA"),
            "build": artifact.get("classification", {}).get("build", "NA"),
            "test": artifact.get("classification", {}).get("test", "NA"),
        },
        timestamp=datetime.now().isoformat()
    )
    
    # Clean up image if not keeping
    if not keep_image:
        full_image = f"{BUGSWARM_DOCKER_REPO}:{image_tag}"
        subprocess.run(["docker", "rmi", full_image], capture_output=True)
    
    return failures, build_info


def save_failures(failures: List[FailureInstance], output_path: str):
    """Save failures to JSONL file.
    
    Args:
        failures: List of failure instances
        output_path: Path to output file
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "a") as f:
        for failure in failures:
            f.write(json.dumps(asdict(failure)) + "\n")
    
    print(f"Saved {len(failures)} failures to {output_path}")


def save_build_info(build_info: BuildInfo, output_path: str):
    """Save build info (including code diffs) to JSONL file.
    
    Args:
        build_info: Build information with code diffs
        output_path: Path to output file
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "a") as f:
        f.write(json.dumps(asdict(build_info)) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Collect BugSwarm test failures with code diffs")
    parser.add_argument("--list", action="store_true", help="List available artifacts")
    parser.add_argument("--image-tags", nargs="+", help="Specific image tags to collect")
    parser.add_argument("--min-failures", type=int, default=3, help="Minimum test failures per artifact")
    parser.add_argument("--limit", type=int, default=50, help="Maximum artifacts to collect")
    parser.add_argument("--languages", nargs="+", default=["Java", "Python"], help="Languages to collect")
    parser.add_argument("--output", type=str, default="/output", help="Output directory")
    parser.add_argument("--keep-images", action="store_true", help="Keep Docker images after collection")
    parser.add_argument("--no-diffs", action="store_true", help="Skip code diff extraction (faster but no code changes)")
    parser.add_argument("--code-bugs-only", action="store_true", help="Only collect bugs classified as code changes")
    parser.add_argument("--target-successful", type=int, default=None, 
                        help="Keep collecting until this many successful builds (ignores --limit)")
    parser.add_argument("--append", action="store_true", help="Append to existing files instead of overwriting")
    
    args = parser.parse_args()
    
    # Fetch artifacts
    artifacts = fetch_bugswarm_artifacts(args.languages, args.min_failures)
    
    # Filter for code bugs only (most useful for fault localization)
    if args.code_bugs_only:
        artifacts = [
            a for a in artifacts 
            if a.get("classification", {}).get("code") in ["Yes", "Partial"]
        ]
        print(f"Filtered to {len(artifacts)} code-change artifacts")
    
    if args.list:
        print("\n=== Available Artifacts ===")
        print(f"{'Image Tag':<60} {'Repo':<40} {'Lang':<8} {'Failures':<10} {'Code?':<6}")
        print("-" * 130)
        for a in artifacts[:100]:
            code_flag = a.get("classification", {}).get("code", "NA")
            print(f"{a['image_tag']:<60} {a['repo']:<40} {a['lang']:<8} {a.get('_num_failures', '?'):<10} {code_flag:<6}")
        if len(artifacts) > 100:
            print(f"... and {len(artifacts) - 100} more")
        return
    
    # Filter by specific tags if provided
    if args.image_tags:
        tag_set = set(args.image_tags)
        artifacts = [a for a in artifacts if a["image_tag"] in tag_set]
    
    failures_file = os.path.join(args.output, "failure_instances_bugswarm.jsonl")
    builds_file = os.path.join(args.output, "builds_bugswarm.jsonl")
    
    # Load already collected artifacts to skip them
    already_collected = set()
    if args.append or args.target_successful:
        if os.path.exists(builds_file):
            with open(builds_file) as f:
                for line in f:
                    if line.strip():
                        build = json.loads(line)
                        already_collected.add(build.get("image_tag", ""))
            print(f"Already collected: {len(already_collected)} artifacts")
    
    # Filter out already collected
    artifacts = [a for a in artifacts if a["image_tag"] not in already_collected]
    print(f"Remaining artifacts to try: {len(artifacts)}")
    
    # Determine target
    if args.target_successful:
        target = args.target_successful
        print(f"\n=== Collecting until {target} successful builds ===")
    else:
        # Limit number of artifacts
        artifacts = artifacts[:args.limit]
        target = None
        print(f"\n=== Collecting from {len(artifacts)} artifacts ===")
    
    print(f"    Code diffs: {'disabled' if args.no_diffs else 'enabled'}")
    
    # Clear existing files only if not appending
    if not args.append and not args.target_successful:
        for f in [failures_file, builds_file]:
            if os.path.exists(f):
                os.remove(f)
    
    total_failures = 0
    total_changed_files = 0
    successful_artifacts = len(already_collected)
    attempted = 0
    
    for i, artifact in enumerate(artifacts):
        # Check if we've reached target
        if target and successful_artifacts >= target:
            print(f"\n✓ Reached target of {target} successful builds!")
            break
        
        attempted += 1
        if target:
            print(f"\n[{successful_artifacts}/{target} successful, attempt {attempted}]")
        else:
            print(f"\n[{i+1}/{len(artifacts)}]")
        
        try:
            failures, build_info = collect_artifact_failures(
                artifact, 
                keep_image=args.keep_images,
                extract_diffs=not args.no_diffs
            )
            if failures:
                save_failures(failures, failures_file)
                total_failures += len(failures)
                successful_artifacts += 1
            
            if build_info:
                save_build_info(build_info, builds_file)
                total_changed_files += len(build_info.changed_files)
                
        except Exception as e:
            print(f"  Error processing artifact: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print(f"\n{'='*60}")
    print(f"=== Collection Complete ===")
    print(f"{'='*60}")
    print(f"Successful artifacts: {successful_artifacts}")
    print(f"Attempted this run: {attempted}")
    print(f"Total failures collected: {total_failures}")
    print(f"Total changed files tracked: {total_changed_files}")
    print(f"\nOutput files:")
    print(f"  Failures: {failures_file}")
    print(f"  Builds (with diffs): {builds_file}")


if __name__ == "__main__":
    main()

