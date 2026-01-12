#!/usr/bin/env python3
"""
FreeAgent Invoice Cache Builder - Catchup Script

Downloads all historical invoices from FreeAgent API incrementally.
Designed to run via cron job every few minutes, processing 50 invoices at a time.
"""

import argparse
import json
import logging
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Constants
CONFIG_FILE = "config.json"
STATE_FILE = "state.json"
INVOICES_DIR = "data/invoices"
CREDIT_NOTES_DIR = "data/credit_notes"


def load_config() -> Dict:
    """Load API configuration from config.json"""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"Configuration file '{CONFIG_FILE}' not found")
        logger.error(f"Please copy 'config.json.example' to '{CONFIG_FILE}' and add your credentials")
        sys.exit(1)

    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)

        # Validate required fields
        required_fields = ['api_base_url', 'access_token', 'refresh_token', 'client_id', 'client_secret', 'per_page', 'nested_invoice_items']
        missing_fields = [field for field in required_fields if field not in config]
        if missing_fields:
            logger.error(f"Missing required fields in config: {', '.join(missing_fields)}")
            sys.exit(1)

        return config
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in configuration file: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        sys.exit(1)


def refresh_access_token(config: Dict) -> bool:
    """
    Refresh expired access token using refresh token

    Updates config dict in-place with new tokens.
    Returns True on success, False on failure.
    """
    token_endpoint = "https://api.freeagent.com/v2/token_endpoint"

    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': config['refresh_token'],
        'client_id': config['client_id'],
        'client_secret': config['client_secret']
    }

    try:
        logger.info("Refreshing expired access token...")
        response = requests.post(token_endpoint, data=payload, timeout=30)

        if response.status_code != 200:
            logger.error(f"Token refresh failed: {response.status_code} - {response.text}")
            return False

        data = response.json()

        # Update config with new tokens
        config['access_token'] = data['access_token']
        config['refresh_token'] = data['refresh_token']

        logger.info("Access token refreshed successfully")
        return True

    except Exception as e:
        logger.error(f"Error refreshing token: {e}")
        return False


def save_config(config: Dict) -> None:
    """Persist updated config (including refreshed tokens) to config.json"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        logger.debug("Config saved successfully")
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        # Don't exit - script can continue with in-memory tokens


def load_state() -> Dict:
    """Load execution state from state.json or create default"""
    if not os.path.exists(STATE_FILE):
        logger.warning(f"State file '{STATE_FILE}' not found. Run with --initialise first.")
        sys.exit(1)

    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
        return state
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in state file: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error loading state: {e}")
        sys.exit(1)


def save_state(state: Dict) -> None:
    """Persist state to state.json"""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
        logger.debug(f"State saved successfully")
    except Exception as e:
        logger.error(f"Error saving state: {e}")
        sys.exit(1)


def initialise_state(config: Dict) -> None:
    """Create fresh state.json with --initialise flag"""
    default_state = {
        "status": "in_progress",
        "current_page": 0,
        "total_pages": None,
        "per_page": config['per_page'],
        "last_run": None,
        "completed_at": None
    }

    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(default_state, f, indent=2)
        logger.info("State initialized successfully")
        logger.info(f"Created '{STATE_FILE}' with current_page=0 and status='in_progress'")
    except Exception as e:
        logger.error(f"Error initializing state: {e}")
        sys.exit(1)


def build_api_url(base_url: str, page: int, per_page: int, nested: bool) -> str:
    """Construct API URL with pagination parameters"""
    nested_param = "true" if nested else "false"
    url = f"{base_url}/invoices?nested_invoice_items={nested_param}&per_page={per_page}&page={page}"
    return url


def fetch_invoices(url: str, config: Dict) -> Tuple[Dict, Dict, Dict]:
    """
    Make API call to fetch invoices, with automatic token refresh on 401

    Returns:
        Tuple of (response_data, response_headers, updated_config)
    """
    headers = {
        'Authorization': f'Bearer {config["access_token"]}',
        'Accept': 'application/json',
        'User-Agent': 'FreeAgent-Invoice-Cache-Builder/0.1.0'
    }

    try:
        logger.debug(f"Fetching: {url}")
        response = requests.get(url, headers=headers, timeout=30)

        # Handle rate limiting
        if response.status_code == 429:
            logger.warning("Rate limit exceeded (429). Will retry on next cron run.")
            sys.exit(0)

        # Handle authentication errors
        if response.status_code == 401:
            logger.warning("Authentication failed (401). Attempting to refresh token...")

            # Try to refresh token
            if refresh_access_token(config):
                # Save updated tokens to disk
                save_config(config)

                # Retry request with new access token
                headers['Authorization'] = f'Bearer {config["access_token"]}'
                response = requests.get(url, headers=headers, timeout=30)

                # Check if retry succeeded
                if response.status_code == 200:
                    data = response.json()
                    return data, dict(response.headers), config
                else:
                    logger.error(f"Request failed even after token refresh: {response.status_code}")
                    sys.exit(1)
            else:
                logger.error("Token refresh failed. Check your refresh_token and client credentials.")
                sys.exit(1)

        # Handle other errors
        if response.status_code != 200:
            logger.error(f"API request failed with status {response.status_code}: {response.text}")
            sys.exit(1)

        data = response.json()
        return data, dict(response.headers), config

    except requests.exceptions.Timeout:
        logger.error("API request timed out. Will retry on next cron run.")
        sys.exit(0)
    except requests.exceptions.ConnectionError:
        logger.error("Connection error. Will retry on next cron run.")
        sys.exit(0)
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error during API call: {e}")
        sys.exit(1)


def get_header_case_insensitive(headers: Dict, header_name: str) -> Optional[str]:
    """
    Get header value using case-insensitive lookup

    HTTP headers are case-insensitive, but dict.get() is case-sensitive.
    This helper finds the header regardless of case.

    Args:
        headers: Dictionary of HTTP headers
        header_name: Header name to search for (e.g., 'Link', 'X-Total-Count')

    Returns:
        Header value if found, None otherwise
    """
    header_name_lower = header_name.lower()
    for key, value in headers.items():
        if key.lower() == header_name_lower:
            return value
    return None


def calculate_pages_from_count(total_count: int, per_page: int) -> int:
    """
    Calculate total pages from X-Total-Count header

    FreeAgent API documentation recommends using X-Total-Count to determine
    the number of pages: divide total count by per_page and round up.

    Args:
        total_count: Total number of records (from X-Total-Count header)
        per_page: Number of items per page

    Returns:
        Total number of pages (at least 1)
    """
    if per_page <= 0:
        logger.warning(f"Invalid per_page value: {per_page}, defaulting to 1 page")
        return 1

    if total_count <= 0:
        return 1

    return math.ceil(total_count / per_page)


def parse_link_header(headers: Dict) -> Optional[int]:
    """
    Parse RFC 5988 Link header to extract total pages

    Uses case-insensitive header lookup to find the Link header,
    then extracts the page number from rel="last" link.

    Example Link header:
    <https://api.freeagent.com/v2/invoices?page=2>; rel="next",
    <https://api.freeagent.com/v2/invoices?page=1860>; rel="last"

    Args:
        headers: Dictionary of HTTP response headers

    Returns:
        Total number of pages, or None if not found
    """
    # Use case-insensitive lookup for Link header
    link_header = get_header_case_insensitive(headers, 'Link')

    if not link_header:
        logger.debug("No Link header found in response")
        return None

    logger.debug(f"Link header: {link_header}")

    try:
        # Parse link header for rel="last"
        # Format: <URL>; rel="last"
        pattern = r'<([^>]+)>;\s*rel="last"'
        match = re.search(pattern, link_header)

        if not match:
            logger.debug("No rel='last' found in Link header")
            return None

        last_url = match.group(1)
        logger.debug(f"Found last page URL: {last_url}")

        # Extract page parameter from URL
        parsed = urlparse(last_url)
        params = parse_qs(parsed.query)

        if 'page' not in params:
            logger.warning("Link header found but no 'page' parameter in URL")
            return None

        total_pages = int(params['page'][0])
        logger.info(f"Determined total_pages from Link header: {total_pages}")
        return total_pages

    except Exception as e:
        logger.error(f"Error parsing Link header: {e}")
        return None


def determine_total_pages(headers: Dict, per_page: int, has_data: bool) -> Optional[int]:
    """
    Determine total pages using multiple methods with fallback logic

    This function tries multiple approaches to determine pagination:
    1. Parse Link header for rel="last" (primary method)
    2. Calculate from X-Total-Count header (fallback)
    3. Return None if all methods fail

    Args:
        headers: Dictionary of HTTP response headers
        per_page: Number of items per page
        has_data: Whether the response contains any data

    Returns:
        Total number of pages, or None if it cannot be determined
    """
    # Layer 1: Try Link header (RFC 5988 standard)
    logger.debug("Attempting to determine total pages from Link header...")
    total_pages = parse_link_header(headers)

    if total_pages and total_pages > 0:
        logger.info(f"Total pages determined from Link header: {total_pages}")
        return total_pages

    # Layer 2: Try X-Total-Count header (FreeAgent recommended method)
    logger.debug("Link header method failed, trying X-Total-Count header...")
    total_count_str = get_header_case_insensitive(headers, 'X-Total-Count')

    if total_count_str:
        try:
            total_count = int(total_count_str)
            logger.debug(f"X-Total-Count header: {total_count}")
            total_pages = calculate_pages_from_count(total_count, per_page)
            logger.info(f"Total pages calculated from X-Total-Count: {total_pages} (count={total_count}, per_page={per_page})")
            return total_pages
        except ValueError as e:
            logger.warning(f"Invalid X-Total-Count value '{total_count_str}': {e}")

    # Layer 3: No pagination info found
    if has_data:
        logger.warning("Could not determine total pages from headers. Defaulting to 1 page.")
        logger.warning("Available headers: " + ", ".join(headers.keys()))
        return 1
    else:
        logger.debug("No data in response, assuming single empty page")
        return 1


def extract_id_from_url(url: str) -> str:
    """
    Extract ID from invoice/credit note URL

    Examples:
        "https://api.freeagent.com/v2/invoices/694948" -> "694948"
        "https://api.freeagent.com/v2/credit_notes/694947" -> "694947"
    """
    parts = url.rstrip('/').split('/')
    return parts[-1]


def determine_type(url: str) -> str:
    """
    Determine if item is invoice or credit_note from URL

    Returns:
        "invoice" or "credit_note"
    """
    if '/credit_notes/' in url:
        return 'credit_note'
    elif '/invoices/' in url:
        return 'invoice'
    else:
        logger.warning(f"Unknown URL type: {url}")
        return 'unknown'


def save_item(data: Dict, item_type: str, item_id: str) -> None:
    """Write JSON file to appropriate directory"""
    # Determine directory and filename
    if item_type == 'invoice':
        directory = INVOICES_DIR
        filename = f"invoice_{item_id}.json"
    elif item_type == 'credit_note':
        directory = CREDIT_NOTES_DIR
        filename = f"credit_note_{item_id}.json"
    else:
        logger.warning(f"Unknown item type '{item_type}', skipping")
        return

    # Create directory if it doesn't exist
    Path(directory).mkdir(parents=True, exist_ok=True)

    # Full path
    filepath = os.path.join(directory, filename)

    # Check if file already exists (skip re-download)
    if os.path.exists(filepath):
        logger.debug(f"Skipping {filename} (already exists)")
        return

    # Write file
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Saved {filename}")
    except Exception as e:
        logger.error(f"Error saving {filename}: {e}")
        # Continue with other items


def calculate_progress(current: int, total: int) -> str:
    """Return progress percentage string"""
    if total == 0:
        return "0.0%"
    percentage = (current / total) * 100
    return f"{percentage:.2f}%"


def main():
    """Main execution flow"""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='Download invoices from FreeAgent API (catchup mode)'
    )
    parser.add_argument(
        '--initialise', '--initialize',
        action='store_true',
        help='Initialize/reset state file'
    )
    args = parser.parse_args()

    # Handle --initialise flag
    if args.initialise:
        config = load_config()
        initialise_state(config)
        return

    # Load configuration and state
    config = load_config()
    state = load_state()

    # Ensure per_page exists in state (backward compatibility)
    if 'per_page' not in state:
        logger.warning("State missing per_page, using value from config")
        state['per_page'] = config['per_page']
        save_state(state)

    # Warn if config per_page differs from state per_page
    if state['per_page'] != config['per_page']:
        logger.warning(
            f"Config per_page ({config['per_page']}) differs from state per_page "
            f"({state['per_page']}). Using state value for consistency. "
            f"To change, re-initialize with --initialise"
        )

    # Check completion status
    if state.get("status") == "catchup_complete":
        completed_at = state.get("completed_at", "unknown time")
        logger.info(f"Catchup already complete at {completed_at}. Exiting.")
        return

    # Calculate next page to fetch
    current_page = state.get("current_page", 0)
    next_page = current_page + 1

    logger.info(f"Starting to process page {next_page}")

    # Build and execute API request
    url = build_api_url(
        config['api_base_url'],
        next_page,
        state['per_page'],
        config['nested_invoice_items']
    )

    data, headers, config = fetch_invoices(url, config)

    # Process items to check if there's data
    invoices = data.get('invoices', [])
    has_data = len(invoices) > 0

    # Determine total pages using multiple methods with fallback
    total_pages = determine_total_pages(headers, state['per_page'], has_data)

    if total_pages is None:
        logger.error("Failed to determine total pages from any method. Cannot continue. Exiting.")
        sys.exit(1)

    # Update total_pages in state (moving target)
    state['total_pages'] = total_pages

    # Log progress
    progress = calculate_progress(next_page, total_pages)
    logger.info(f"Processing page {next_page} of {total_pages} ({progress} complete)")

    # Process items (already extracted above for pagination check)

    if not invoices:
        logger.info(f"No invoices found on page {next_page}")
    else:
        logger.info(f"Found {len(invoices)} items on page {next_page}")

        for item in invoices:
            url_field = item.get('url')
            if not url_field:
                logger.warning("Item missing 'url' field, skipping")
                continue

            item_id = extract_id_from_url(url_field)
            item_type = determine_type(url_field)

            save_item(item, item_type, item_id)

    # Update state after successful processing
    state['current_page'] = next_page
    state['last_run'] = datetime.utcnow().isoformat() + 'Z'

    # Check if catchup is complete
    if next_page >= total_pages:
        state['status'] = 'catchup_complete'
        state['completed_at'] = datetime.utcnow().isoformat() + 'Z'
        logger.info(f"Catchup complete! Processed {next_page} pages.")
    else:
        state['status'] = 'in_progress'

    # Save state
    save_state(state)

    logger.info("Processing complete. State saved successfully.")


if __name__ == "__main__":
    main()
