# FreeAgent Invoice Cache Builder

A Python script for incrementally downloading invoices and credit notes from the FreeAgent API. Designed to run via cron job, processing 50 items at a time to respect rate limits.

## Features

- **Incremental Download**: Processes 50 invoices per run, safe for cron execution
- **Progress Tracking**: Uses Link header pagination to show exact progress
- **Completion Detection**: Automatically detects when catchup is complete and avoids unnecessary API calls
- **Idempotent**: Safe to run multiple times, skips already-downloaded files
- **Resumable**: Can stop and restart without losing progress
- **Rate-Limit Friendly**: Respects API limits by processing in small batches

## Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) package manager
- FreeAgent OAuth token

## Installation

1. **Clone or download this repository**

2. **Install dependencies using uv:**
   ```bash
   uv init
   uv add requests
   ```

3. **Create configuration file:**
   ```bash
   cp config.json.example config.json
   ```

4. **Edit `config.json`** and add your FreeAgent OAuth token:
   ```json
   {
     "api_base_url": "https://api.freeagent.com/v2",
     "oauth_token": "YOUR_OAUTH_TOKEN_HERE",
     "per_page": 50,
     "nested_invoice_items": true
   }
   ```

## Usage

### Initialize State File

Before first run, initialize the state file:

```bash
uv run python download_invoices.py --initialise
```

This creates `state.json` with default values.

### Run Manually

Execute the script to download one page (50 invoices):

```bash
uv run python download_invoices.py
```

The script will:
- Check if catchup is already complete (exit immediately if so)
- Fetch the next page of invoices
- Save each invoice/credit note as individual JSON files
- Update state with progress
- Mark completion when all pages are processed

### Run via Cron Job

For continuous catchup, add to your crontab:

```bash
# Run every 2 minutes
*/2 * * * * cd /path/to/freeagent-invoice-cache-builder && uv run python download_invoices.py >> logs/cron.log 2>&1
```

Create logs directory first:
```bash
mkdir logs
```

### Catchup Duration Estimates

For ~93,000 invoices at 50 per page (~1,860 pages):

- **Every 5 minutes**: ~6.5 days
- **Every 2 minutes**: ~2.6 days (recommended)
- **Every minute**: ~1.3 days

## File Structure

```
.
├── download_invoices.py     # Main script
├── config.json              # API credentials (gitignored)
├── config.json.example      # Configuration template
├── state.json               # Progress tracking (gitignored)
├── data/                    # Downloaded data (gitignored)
│   ├── invoices/            # Invoice JSON files
│   └── credit_notes/        # Credit note JSON files
├── logs/                    # Cron job logs
├── pyproject.toml           # uv dependencies
├── .gitignore              # Git ignore rules
└── README.md               # This file
```

## State File

The `state.json` file tracks progress:

```json
{
  "status": "in_progress",
  "current_page": 150,
  "total_pages": 1860,
  "per_page": 50,
  "last_run": "2026-01-11T18:30:00Z",
  "completed_at": null
}
```

- **status**: Either `"in_progress"` or `"catchup_complete"`
- **current_page**: Last successfully processed page
- **total_pages**: Total pages available (updated on each run)
- **completed_at**: Timestamp when catchup completed

## Monitoring Progress

Check state file to see progress:

```bash
cat state.json
```

Check logs:

```bash
tail -f logs/cron.log
```

Example log output:
```
2026-01-11 18:30:00 - INFO - Processing page 150 of 1860 (8.06% complete)
2026-01-11 18:30:02 - INFO - Found 50 items on page 150
2026-01-11 18:30:03 - INFO - Processing complete. State saved successfully.
```

## After Catchup Complete

Once catchup is complete:

1. **Option 1**: Leave cron job running (safe - script exits immediately without API calls)
2. **Option 2**: Manually disable cron job
3. **Option 3**: Create separate maintenance script for ongoing updates (future work)

To re-run catchup:
```bash
uv run python download_invoices.py --initialise
```

## File Naming

Downloaded files use the following naming convention:

- **Invoices**: `data/invoices/invoice_{ID}.json`
- **Credit Notes**: `data/credit_notes/credit_note_{ID}.json`

Where `{ID}` is extracted from the URL field:
- `https://api.freeagent.com/v2/invoices/694948` → `data/invoices/invoice_694948.json`
- `https://api.freeagent.com/v2/credit_notes/694947` → `data/credit_notes/credit_note_694947.json`

## Error Handling

The script handles common errors gracefully:

- **Rate Limiting (429)**: Exits and retries on next cron run
- **Authentication Errors (401)**: Logs error and exits (manual intervention required)
- **Network Errors**: Exits and retries on next cron run
- **Individual File Errors**: Logs warning but continues with other items

## Troubleshooting

### "State file not found"

Run with `--initialise` flag first:
```bash
uv run python download_invoices.py --initialise
```

### "Configuration file not found"

Copy the example config:
```bash
cp config.json.example config.json
```
Then edit with your OAuth token.

### "Authentication failed (401)"

Check your `oauth_token` in `config.json` is valid.

### Progress seems stuck

Check the logs for errors:
```bash
tail -f logs/cron.log
```

Verify the cron job is running:
```bash
crontab -l
```

## Development

The script follows the KISS principle - it does one thing well (catchup). Future enhancements could include:

- Separate maintenance script for daily updates
- Webhook integration for real-time updates
- Database storage instead of JSON files
- Parallel processing for faster catchup

## License

MIT License

## Contributing

Contributions welcome! Please open an issue or pull request.
