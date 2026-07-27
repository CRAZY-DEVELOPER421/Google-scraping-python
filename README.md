# Google-Maps-Scrapper
This Python script utilizes the Playwright library to perform web scraping and data extraction from Google Maps. It is particularly designed for obtaining information about businesses, including their name, address, website, phone number, reviews, and more.

## Read Prerequistes
Latest python was not used and is not suggested

<br>
To do a custom web scraping project you can find me on Upwork or on Linkedin<br><br>

<a href="https://www.upwork.com/freelancers/~01dbb4d47d167c2d43" target="_blank">
<img src=https://img.shields.io/badge/Upwork-6FDA44?&style=for-the-badge&logo=medium&logoColor=white alt=medium style="margin-bottom: 5px;" />
</a>

<a href="https://www.linkedin.com/in/zohaibbashir" target="_blank">
<img src="https://img.shields.io/badge/LinkedIn-0077B5?&style=for-the-badge&logo=linkedin&logoColor=white" alt="linkedin" style="margin-bottom: 5px;" />
</a>


## Table of Contents
- [Prerequisites](#prerequisites)
- [Multiple Branches](#multiple-branches)
- [Project Structure](#project-structure)
- [AI Search Feature](#ai-search-feature)
- [Key Features](#key-features)
- [Installation](#installation)
- [Usage](#usage)
- [Example](#example)
- [Notes](#notes)
- [Video Example](#video-example)

## Prerequisites
- Python 3.8 or 3.9 (Python 3.10+ may not be compatible with some dependencies)
- Google Chrome or Chromium browser installed (for Playwright)

## Multiple Branches
The repo currently has 3 branches
- Main
- Latest Libraries (The one that works with latest libraries, can cause issues. Prefer Main)
- Linux ( Linux Support if main branch does not work correctly)


## Project Structure

The project has been cleaned up to keep only essential files. Below is the current file tree:

```
📁 Google-Maps-Scrapper/
├── app.py                 ← Flask web server (UI + API)
├── main.py                ← Google Maps scraper engine (Playwright)
├── ai/                    ← AI Search package (runs alongside scraper)
│   ├── __init__.py
│   ├── routes.py          ← /api/ai-search/* endpoints
│   ├── service.py         ← AI pipeline: web search → DeepSeek → enrichment
│   ├── deepseek_client.py ← DeepSeek / Zaucto AI API client
│   ├── web_search_client.py ← Serper.dev web search client
│   └── usage_tracker.py   ← Monthly API usage tracking
├── database/              ← Saved data
│   ├── __init__.py
│   ├── db_connection.py
│   └── saved_data_service.py
├── static/                ← Frontend assets
│   ├── ai-panel.css
│   └── ai-panel.js
├── templates/
│   └── index.html         ← Main UI (dark/light theme, scraper + AI panel)
├── .env                   ← API keys (not committed)
├── .gitignore             ← Excludes logs, .venv, outputs, debug files
├── requirements.txt
└── README.md
```

### Cleanup Notes

- **13 unused files removed**: debug scripts (`debug_reviews.py`, `diagnose_ai_search.py`, `test_*.py`, `trace_pipeline.py`), old outputs (`result.csv`, `debug_output.json`, `ai/usage_data.json`), and the `public/` directory
- **Logs excluded**: `*.log` pattern added to `.gitignore` — previously tracked logs (`flask_output.log`) also untracked
- **Test artifacts excluded**: `debug_*.py`, `test_*.py`, `diagnose_*.py`, `trace_*.py` all ignored by git
- **.venv recreated**: Fresh virtual environment from `requirements.txt` to avoid cruft

## AI Search Feature

This project includes an **AI-powered business search** feature that runs alongside the Google Maps scraper.
It uses **Zaucto AI** (powered by DeepSeek) to fetch business data directly via AI — no browser needed.

- **Backend AI code**: `ai/` folder (routes, service, clients, tracker)
- **Frontend panel**: `static/ai-panel.js` (dynamic panel injection) + `static/ai-panel.css` (light theme styling)
- **Toggle**: Enable "AI SEARCH" in the header to run AI search in parallel with scraping
- **No separate input**: AI search reads keyword, location, results count, and filter from the main form
- **Mode matching**: AI returns the same fields as the selected scraping mode (Fast/Deep/Ultra Deep)
- **Duplicate results**: Deduplication applied on both scraper and AI search results
- **Non-business queries**: Promptly refused with a Hindi/English message
- **Never fabricates**: System prompt explicitly tells Zaucto AI to return empty strings for unknown fields

## Key Features
- Data Scraping: The script scrapes data from Google Maps listings, extracting valuable information about businesses, such as their name, address, website, and contact details.

- Review Analysis: It extracts review counts and average ratings, providing insights into businesses' online reputation.

- Business Type Detection: The script identifies whether a business offers in-store shopping, in-store pickup, or delivery services.

- Operating Hours: It extracts information about the business's operating hours.

- Introduction Extraction: The script also scrapes introductory information about the businesses when available.

- Data Cleansing: It cleanses and organizes the scraped data, removing redundant or unnecessary columns.

- CSV Export: The cleaned data is exported to a CSV file for further analysis or integration with other tools.

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/zohaibbashir/Google-Maps-Scrapper.git
   cd google-maps-scraper
   ```
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Install Playwright browsers:
   ```bash
   playwright install
   ```

## Usage

Run the script with your desired search term and number of results:

```bash
python main.py -s "Turkish Restaurants in Toronto Canada" -t 20
```

- `-s` or `--search`: Search query for Google Maps (default: "turkish stores in toronto Canada")
- `-t` or `--total`: Number of results to scrape (default: 1)
- `-o` or `--output`: Output CSV file path (default: result.csv)
- `--append`: Append results to the output file instead of overwriting (default: off)

## Example

Append new results to an existing CSV file:
```bash
python main.py -s "Turkish Restaurants in Toronto Canada" -t 20 -o toronto_turkish_restaurants.csv --append
```

The script will launch a browser, perform the search, and start scraping information. Progress will be displayed in the terminal, and results will be saved to the specified CSV file. If `--append` is used, new results will be added to the end of the file without removing previous data.

## Notes
- The script opens a visible browser window (not headless) for scraping.
- Google Maps DOM may change, which can break the script. If you encounter issues, update the XPaths in `main.py`.
- Avoid running too many scrapes in a short period to prevent being blocked by Google.

## Video Example

https://www.linkedin.com/posts/zohaibbashir_python-data-webscraping-activity-7093920891411062784-flEQ

## License
MIT