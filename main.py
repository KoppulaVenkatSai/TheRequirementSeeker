import os
import csv
import json
import math
import argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables from a .env file if present
load_dotenv()

from config import (
    DEFAULT_TIME_PERIOD_DAYS,
    DEFAULT_CSV_PATH,
    DEFAULT_JSON_PATH,
    DEFAULT_MD_PATH,
    SEARCH_ROLES,
    SEARCH_LOCATIONS,
    TOTAL_TARGET_RECORDS
)
from scraper import ProxyManager, LinkedInScraper
from parser import parse_job_html, RuleBasedParser, LLMParser, HAS_GEMINI_SDK


def load_existing_job_ids(csv_out, json_out):
    """
    Reads existing CSV and JSON output files to collect previously scraped job IDs.
    Ensures that duplicates are skipped across multiple runs of the script.
    """
    existing_ids = set()
    
    # 1. Load from CSV
    if os.path.exists(csv_out) and os.path.getsize(csv_out) > 0:
        try:
            with open(csv_out, mode='r', encoding='utf-8') as f:
                reader = csv.reader(f)
                # Skip header
                next(reader, None)
                for row in reader:
                    if row and len(row) > 0:
                        existing_ids.add(row[0].strip())
        except Exception as e:
            print(f"[*] Warning: Could not read existing CSV {csv_out}: {e}")
            
    # 2. Load from JSON
    if os.path.exists(json_out) and os.path.getsize(json_out) > 0:
        try:
            with open(json_out, mode='r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "job_id" in item:
                            existing_ids.add(str(item["job_id"]).strip())
        except Exception as e:
            print(f"[*] Warning: Could not read existing JSON {json_out}: {e}")
            
    return existing_ids


def append_to_csv(job, filename):
    """Appends a single job record incrementally to the CSV file."""
    headers = [
        "Job ID", 
        "Title", 
        "Company", 
        "Location", 
        "URL", 
        "Date Posted", 
        "Required Qualifications", 
        "Preferred Qualifications"
    ]
    
    write_header = not os.path.exists(filename) or os.path.getsize(filename) == 0
    
    try:
        with open(filename, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(headers)
                
            req_str = "\n".join([f"- {q}" for q in job["required_qualifications"]])
            pref_str = "\n".join([f"- {q}" for q in job["preferred_qualifications"]])
            
            writer.writerow([
                job["job_id"],
                job["title"],
                job["company"],
                job["location"],
                job["url"],
                job["date_posted_str"],
                req_str,
                pref_str
            ])
    except Exception as e:
        print(f"[-] Failed to write CSV row incrementally: {e}")


def append_to_json(job, filename):
    """Appends a single job record incrementally to the JSON file."""
    existing_data = []
    
    # Read existing data if file exists
    if os.path.exists(filename) and os.path.getsize(filename) > 0:
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
                if not isinstance(existing_data, list):
                    existing_data = []
        except Exception as e:
            print(f"[*] Warning: Failed to parse existing JSON file {filename} ({e}). Starting fresh list.")
            
    # Copy and clean job data
    job_copy = job.copy()
    if isinstance(job_copy.get("date_posted"), (datetime, timedelta)):
        job_copy["date_posted"] = str(job_copy["date_posted"])
    elif hasattr(job_copy.get("date_posted"), 'isoformat'):
        job_copy["date_posted"] = job_copy["date_posted"].isoformat()
        
    if "description_html" in job_copy:
        del job_copy["description_html"]
        
    existing_data.append(job_copy)
    
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[-] Failed to write JSON record incrementally: {e}")


def append_to_markdown(job, filename, search_roles, search_locations, days_back, idx):
    """Appends a single job record incrementally to the Markdown report."""
    write_header = not os.path.exists(filename) or os.path.getsize(filename) == 0
    
    try:
        with open(filename, 'a', encoding='utf-8') as f:
            if write_header:
                f.write(f"# LinkedIn Job Qualifications Report\n\n")
                f.write(f"- **Target Roles**: `{', '.join(search_roles)}`\n")
                f.write(f"- **Target Locations**: `{', '.join(search_locations)}`\n")
                f.write(f"- **Search Window**: Past {days_back} days (approx. {days_back // 30} months)\n")
                f.write(f"- **Initial Export Began**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"- **CSV Data Sheet**: [linkedin_jobs.csv](file:///Users/venkat/Desktop/Other/Projects/TheRequirementSeeker/linkedin_jobs.csv)\n\n")
                f.write("---\n\n")
                
            f.write(f"## {idx}. {job['title']} — *{job['company']}*\n\n")
            f.write(f"- **Location**: {job['location']}\n")
            f.write(f"- **Posted**: {job['date_posted_str']}\n")
            f.write(f"- **Link**: [View Job Posting]({job['url']})\n\n")
            
            f.write("### Required Qualifications\n")
            if job["required_qualifications"]:
                for req in job["required_qualifications"]:
                    f.write(f"- {req}\n")
            else:
                f.write("*None explicitly detected by rule-based heuristics.*\n")
            f.write("\n")
            
            f.write("### Preferred Qualifications\n")
            if job["preferred_qualifications"]:
                for pref in job["preferred_qualifications"]:
                    f.write(f"- {pref}\n")
            else:
                f.write("*None explicitly detected by rule-based heuristics.*\n")
            f.write("\n---\n\n")
    except Exception as e:
        print(f"[-] Failed to write Markdown row incrementally: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Scrapes LinkedIn Job Qualifications (Required & Preferred) across multiple roles and locations without credentials."
    )
    parser.add_argument("-m", "--months", type=float, default=6.0,
                        help="Time period back in months to search (default: 6.0)")
    parser.add_argument("--no-proxy", action="store_true",
                        help="Disable free proxy rotation and run direct requests (faster but higher block rate)")
    parser.add_argument("--proxy", type=str, default=None,
                        help="Specify a custom proxy URL (e.g. 'http://user:pass@host:port' or 'socks5://host:port')")
    parser.add_argument("--use-llm", action="store_true",
                        help="Use Gemini API to extract qualifications (requires GEMINI_API_KEY env var)")
    parser.add_argument("--csv-out", type=str, default=DEFAULT_CSV_PATH,
                        help=f"Output path for primary CSV file (default: {DEFAULT_CSV_PATH})")
    parser.add_argument("--json-out", type=str, default=DEFAULT_JSON_PATH,
                        help=f"Output path for JSON file (default: {DEFAULT_JSON_PATH})")
    parser.add_argument("--md-out", type=str, default=DEFAULT_MD_PATH,
                        help=f"Output path for Markdown file (default: {DEFAULT_MD_PATH})")
                        
    args = parser.parse_args()

    # Calculate days back and cutoff dates
    days_back = int(args.months * 30)
    cutoff_date = datetime.now().date() - timedelta(days=days_back)
    
    # Format proxy status log
    if args.no_proxy:
        proxy_status = "Disabled"
    elif args.proxy:
        proxy_status = f"Custom Proxy ({args.proxy})"
    else:
        proxy_status = "Enabled (Rotating Open-Source)"
        
    print("=" * 60)
    print("      LINKEDIN JOB QUALIFICATION SCRAPER (NO LOGIN)")
    print("=" * 60)
    print(f"[*] Target Roles:     {SEARCH_ROLES}")
    print(f"[*] Locations:        {SEARCH_LOCATIONS}")
    print(f"[*] Search Window:    Past {args.months} months (~{days_back} days, cutoff: {cutoff_date})")
    print(f"[*] Total Target:     {TOTAL_TARGET_RECORDS} new unique records")
    print(f"[*] Proxies:          {proxy_status}")
    
    # 1. Load existing data for duplicate prevention across runs
    scraped_job_ids = load_existing_job_ids(args.csv_out, args.json_out)
    initial_records_count = len(scraped_job_ids)
    print(f"[+] Loaded {initial_records_count} existing job IDs. Scrapes will skip these to prevent duplicates.")
    
    # Initialize components
    proxy_manager = ProxyManager(enabled=not args.no_proxy, custom_proxy=args.proxy)
    scraper = LinkedInScraper(proxy_manager=proxy_manager)
    
    # Selection of Qualification Parser
    if args.use_llm:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("[!] Warning: --use-llm specified, but GEMINI_API_KEY environment variable is not set.")
            print("[!] Falling back to local Rule-Based Heuristic Parser.")
            parser_engine = RuleBasedParser()
        elif not HAS_GEMINI_SDK:
            print("[!] Warning: --use-llm specified, but 'google-genai' SDK is not installed.")
            print("[!] Falling back to local Rule-Based Heuristic Parser.")
            parser_engine = RuleBasedParser()
        else:
            print("[+] Using Gemini API for high-accuracy qualification extraction.")
            parser_engine = LLMParser(api_key=api_key)
    else:
        print("[+] Using Local Rule-Based Heuristic Parser.")
        parser_engine = RuleBasedParser()

    # Generate all Role-Location search pairs
    search_pairs = []
    for role in SEARCH_ROLES:
        for loc in SEARCH_LOCATIONS:
            search_pairs.append((role, loc))
            
    num_pairs = len(search_pairs)
    new_jobs_scraped_this_run = 0
    
    print(f"[*] Generated {num_pairs} search combinations. Distributing targets...")
    print("-" * 60)

    # Iterate over combinations
    for pair_idx, (role, loc) in enumerate(search_pairs):
        if new_jobs_scraped_this_run >= TOTAL_TARGET_RECORDS:
            break
            
        remaining_target = TOTAL_TARGET_RECORDS - new_jobs_scraped_this_run
        remaining_pairs = num_pairs - pair_idx
        
        # Calculate dynamic limit per search pair to distribute equally and hit total target
        pair_limit = math.ceil(remaining_target / remaining_pairs)
        
        print(f"\n[*] Pair [{pair_idx+1}/{num_pairs}]: Searching '{role}' in '{loc}'...")
        print(f"[*] Sub-Target: Retrieve {pair_limit} new unique jobs (Remaining total: {remaining_target})")
        
        # Query search endpoint
        job_ids = scraper.search_jobs(
            keywords=role, 
            location=loc, 
            days_back=days_back, 
            max_results=pair_limit * 3  # Fetch slightly more IDs to account for date skips/duplicates
        )
        
        if not job_ids:
            print("[-] No job listings returned for this pair search.")
            continue
            
        new_jobs_for_pair = 0
        
        for job_id in job_ids:
            # Check limits first
            if new_jobs_scraped_this_run >= TOTAL_TARGET_RECORDS:
                break
            if new_jobs_for_pair >= pair_limit:
                break
                
            # Duplicate prevention check (cross-run and current run)
            if job_id in scraped_job_ids:
                # print(f"    [-] Job ID {job_id} already exists in records. Skipping duplicate.")
                continue
                
            print(f"[*] Fetching details for Job ID: {job_id}...")
            detail_html = scraper.get_job_detail_html(job_id)
            if not detail_html:
                continue
                
            # Parse basic info
            job_info = parse_job_html(detail_html, job_id)
            if not job_info:
                print(f"    [-] Failed to parse HTML for Job ID {job_id}.")
                continue
                
            # Client-Side Date Filter: Filter out older postings
            if job_info["date_posted"] < cutoff_date and job_info["date_posted"] != datetime.min.date():
                print(f"    [-] Skipping: Posted on {job_info['date_posted']}, which is older than cutoff {cutoff_date}.")
                continue
                
            # Add location normalization marker so user knows which search pair it came from
            print(f"    [+] Title: {job_info['title']} | Company: {job_info['company']}")
            
            # Parse qualifications
            quals = parser_engine.extract_qualifications(job_info["description_text"])
            job_info["required_qualifications"] = quals.get("required_qualifications", [])
            job_info["preferred_qualifications"] = quals.get("preferred_qualifications", [])
            
            print(f"    [+] Required Quals: {len(job_info['required_qualifications'])} | Preferred: {len(job_info['preferred_qualifications'])}")
            
            # Incremental writing to files
            append_to_csv(job_info, args.csv_out)
            append_to_json(job_info, args.json_out)
            
            current_markdown_index = initial_records_count + new_jobs_scraped_this_run + 1
            append_to_markdown(
                job_info, 
                args.md_out, 
                SEARCH_ROLES, 
                SEARCH_LOCATIONS, 
                days_back, 
                current_markdown_index
            )
            
            # Track counts
            scraped_job_ids.add(job_id)
            new_jobs_for_pair += 1
            new_jobs_scraped_this_run += 1
            
        print(f"[+] Pair complete. Added {new_jobs_for_pair} new unique records.")
        print("-" * 60)
        
    print("\n" + "=" * 60)
    print(f"[+] Run Complete! Scraped {new_jobs_scraped_this_run} new jobs.")
    print(f"[+] Total records in database: {len(scraped_job_ids)}")
    print(f"[+] CSV:      {args.csv_out}")
    print(f"[+] JSON:     {args.json_out}")
    print(f"[+] Markdown: {args.md_out}")
    print("=" * 60)
    print("Done!")


if __name__ == "__main__":
    main()
