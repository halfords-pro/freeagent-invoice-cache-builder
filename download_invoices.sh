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

# Run the Python script with uv, passing through all arguments
uv run python download_invoices.py "$@"
