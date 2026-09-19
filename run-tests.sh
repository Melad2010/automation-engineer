#!/usr/bin/env bash
# Runs every project's test suite. No arguments; exits non-zero if any fail.
set -uo pipefail

cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
projects=(web-scraper-qa quote-generator kpi-dashboard ai-agent)
failed=()

for project in "${projects[@]}"; do
    printf '\n=== %s ===\n' "$project"
    if ! (cd "projects/$project" && "$PYTHON" -m unittest discover -s tests -t . "$@"); then
        failed+=("$project")
    fi
done

printf '\n========================================\n'
if [ ${#failed[@]} -eq 0 ]; then
    echo "All ${#projects[@]} project suites passed."
    exit 0
fi
echo "Failed: ${failed[*]}"
exit 1
