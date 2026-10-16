#!/bin/bash
# Vendored from HyTri scripts/docker/run_docker_defects4j.sh @ 4039de468073f7a81c3eab2f577654880205467f
# Modified: paths adjusted to this repository layout.
# Provided as-is for provenance of data/sources; not re-run for this release.
# Build and run Docker container for Defects4J Java bugs
#
# Usage:
#   ./scripts/docker/run_docker_defects4j.sh [projects] [max_bugs]
#
# Examples:
#   ./scripts/docker/run_docker_defects4j.sh                     # All projects, 100 bugs each
#   ./scripts/docker/run_docker_defects4j.sh "Lang,Math" 50      # Specific projects, 50 bugs each
#   ./scripts/docker/run_docker_defects4j.sh "" 20               # All projects, 20 bugs each

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PROJECTS="${1:-}"
MAX_BUGS="${2:-100}"

echo "============================================================"
echo "Defects4J Docker Collection (v3 - WITH DIFFS)"
echo "============================================================"
echo "Project root: $PROJECT_ROOT"
echo "Projects: ${PROJECTS:-all (17 projects, 835 total bugs)}"
echo "Max bugs per project: $MAX_BUGS"
echo ""

# Create output directory
OUTPUT_DIR="$PROJECT_ROOT/data/sources/defects4j"
mkdir -p "$OUTPUT_DIR"

# Force rebuild Docker image (to pick up changes)
echo "Building Docker image (this may take 10-15 minutes for first build)..."
docker rmi hytri-defects4j 2>/dev/null || true
echo "Pruning Docker build cache..."
docker builder prune -f 2>/dev/null || true
docker build --no-cache \
    -f "$SCRIPT_DIR/Dockerfile.defects4j" \
    -t hytri-defects4j \
    "$PROJECT_ROOT"

echo ""
echo "Running Defects4J collection in Docker container..."
echo "(This will take a while - each bug needs checkout + compile + test)"
echo ""

# Run container
docker run --rm \
    -v "$OUTPUT_DIR:/output" \
    -e "PROJECTS=$PROJECTS" \
    -e "MAX_BUGS=$MAX_BUGS" \
    hytri-defects4j

echo ""
echo "============================================================"
echo "Collection complete!"
echo "Output saved to: $OUTPUT_DIR"
echo "============================================================"

if [ -f "$OUTPUT_DIR/failure_instances_defects4j.jsonl" ]; then
    FAILURES=$(wc -l < "$OUTPUT_DIR/failure_instances_defects4j.jsonl")
    echo "Captured $FAILURES Java test failures"
fi

if [ -f "$OUTPUT_DIR/defects4j_diffs.json" ]; then
    echo "Diffs saved to: $OUTPUT_DIR/defects4j_diffs.json"
    echo ""
    echo "Each failure now includes:"
    echo "  - changed_files: List of files modified to fix the bug"
    echo "  - file_diffs: The actual unified diff"
    echo "  - diff_stats: {additions, deletions}"
fi
