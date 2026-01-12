#!/usr/bin/env bash
#
# download_invoices.sh - Wrapper script for FreeAgent Invoice Cache Builder
#
# Usage:
#   ./download_invoices.sh              # Run normal download
#   ./download_invoices.sh --initialise # Initialize/reset state
#

set -e  # Exit on error

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Change to script directory to ensure relative paths work
cd "$SCRIPT_DIR"

# Set up PATH for cron compatibility
# Add common locations where uv might be installed
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.cargo/bin:$HOME/.local/bin:/usr/bin:/bin:$PATH"

# Verify uv is available
if ! command -v uv &> /dev/null; then
    echo "Error: uv command not found in PATH" >&2
    echo "PATH: $PATH" >&2
    exit 1
fi

# Run the Python script with uv, passing through all arguments
uv run python download_invoices.py "$@"
