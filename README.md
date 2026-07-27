# LinkedIn Job Qualification Scraper (No Login)

This is a robust, modular, command-line utility written in Python to search for job posts on LinkedIn, retrieve their descriptions, and parse out their **Required** and **Preferred** qualifications. 

The scraper operates **completely without user credentials** (does not require login or OAuth) by fetching job lists and details from LinkedIn's guest endpoints.

---

## Features

1. **No Login Required:** Never logs into your LinkedIn account, avoiding account flags or restriction risks.
2. **Rotating Open-Source Proxies:** Automatically fetches a list of hundreds of public HTTP proxies and rotates them on demand when requests fail or get rate-limited.
3. **Double-layer Time Period Filter:** Uses LinkedIn's API-level recency filter (`f_TPR`) combined with client-side exact date checks to strictly respect the time range.
4. **Hybrid Qualification Parsers:**
   - **Rule-Based Parser (Local Heuristics):** Analyzes heading hierarchy and bullet formatting to extract requirements locally without external API dependencies.
   - **LLM-Based Parser (Gemini API):** Standard integration with Google's new `google-genai` SDK to extract and structure requirements perfectly.
5. **Multiple Export Formats:** Outputs results to a primary **CSV** file, with alternate exports to **JSON** and formatted **Markdown** reports.

---

## Setup

1. **Clone or copy this directory** to your workspace.
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **(Optional) LLM Setup:**
   If you wish to use the high-accuracy LLM-based parser, obtain a free-tier Gemini API key, and set it as an environment variable or create a `.env` file in the root directory:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

---

## How to Run

### 1. Basic Run
Search for the default role (`AI Developer`) in the `United States` within the last `6` months, limit the scrape to 50 jobs, using local rule-based parsing:
```bash
python main.py
```

### 2. Custom Role & Time period
Search for "Data Scientist" roles in "United Kingdom" posted in the last **2 months** with a limit of 20 postings:
```bash
python main.py --keywords "Data Scientist" --location "United Kingdom" --months 2 --limit 20
```

### 3. LLM-Based Qualification Extraction
To enable the Gemini parser (requires `GEMINI_API_KEY` set in env):
```bash
python main.py --use-llm
```

### 4. Direct Run (No Proxy)
If you want to run direct requests without public rotating proxies (much faster, but risk of local IP rate limits if you run it many times):
```bash
python main.py --no-proxy
```

### 5. Custom Output Filenames
By default, the script generates:
- `linkedin_jobs.csv` (Primary)
- `linkedin_jobs.json` (Alternate)
- `linkedin_jobs.md` (Alternate Markdown report)

You can customize these output paths:
```bash
python main.py --csv-out custom.csv --json-out custom.json --md-out custom.md
```

---

## Under the Hood

- **Proxy Management (`scraper.py`):** Programmatically fetches live list updates from multiple public repos. It filters out non-functioning servers lazily during scraping to speed up start times.
- **Client-Side Validation (`parser.py`):** Handles parsing relative dates (e.g., "3 weeks ago") and dynamically checking them against your `--months` parameter to filter out out-of-date entries.
- **Rule Parser (`parser.py`):** Searches for logical qualification section headers (like "Basic Requirements", "Preferred Qualifications") and gathers the bulleted text items beneath them.
