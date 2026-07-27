import os

# Search defaults
DEFAULT_KEYWORDS = "AI Developer"
DEFAULT_LOCATION = "United States"
DEFAULT_TIME_PERIOD_DAYS = 180  # Default 6 months (180 days)

# Multi-search configuration variables
SEARCH_ROLES = ["AI engineer", "ML engineer", "AI & ML engineer", "Data scientist"]
SEARCH_LOCATIONS = ["US", "India", "UK", "Australia"]
TOTAL_TARGET_RECORDS = 150

# LinkedIn guest API endpoints
LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LINKEDIN_JOB_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

# Open-source/free public proxy list endpoints (plain text IP:port formats)
FREE_PROXY_SOURCES = [
    "https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/http_elite.txt",
    "https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=elite"
]

# Scraping settings
DEFAULT_REQUEST_TIMEOUT = 10  # Seconds
MIN_REQUEST_DELAY = 1.5       # Seconds
MAX_REQUEST_DELAY = 4.0       # Seconds
MAX_PROXY_FAILURES_BEFORE_RESET = 3
MAX_JOBS_LIMIT = 500          # Stop after fetching this many jobs (safety limit)

# Output paths
DEFAULT_CSV_PATH = "linkedin_jobs.csv"
DEFAULT_JSON_PATH = "linkedin_jobs.json"
DEFAULT_MD_PATH = "linkedin_jobs.md"

# LLM Parsing Configuration
# Uses standard google-genai package
GEMINI_MODEL = "gemini-2.5-flash"  # Standard fast model for JSON extraction
