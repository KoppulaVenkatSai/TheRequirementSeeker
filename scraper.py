import time
import random
import re
import requests
import concurrent.futures
from bs4 import BeautifulSoup
import urllib3

# Disable insecure request warnings if user bypasses SSL checks
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import (
    FREE_PROXY_SOURCES,
    LINKEDIN_SEARCH_URL,
    LINKEDIN_JOB_DETAIL_URL,
    DEFAULT_REQUEST_TIMEOUT,
    MIN_REQUEST_DELAY,
    MAX_REQUEST_DELAY,
    MAX_PROXY_FAILURES_BEFORE_RESET
)

class ProxyManager:
    """
    Fetches and rotates open-source public proxies.
    Validates a subset using concurrent threads at startup to guarantee connection success.
    """
    def __init__(self, enabled=True, custom_proxy=None):
        self.enabled = enabled
        self.proxies = []
        self.current_index = 0
        self.consecutive_failures = 0
        self.is_custom = custom_proxy is not None
        
        if self.enabled:
            if self.is_custom:
                self.proxies = [custom_proxy]
                print(f"[+] Using custom proxy: {custom_proxy}")
            else:
                self.fetch_proxies()
            
    @staticmethod
    def _test_proxy(proxy_ip_port):
        """Tests if a proxy can successfully reach Google via HEAD request."""
        proxies = {
            "http": f"http://{proxy_ip_port}",
            "https": f"http://{proxy_ip_port}"
        }
        try:
            response = requests.head(
                "https://www.google.com",
                proxies=proxies,
                timeout=2.5,
                verify=False
            )
            if response.status_code == 200:
                return proxy_ip_port
        except Exception:
            pass
        return None

    def fetch_proxies(self):
        """
        Downloads public proxies from open-source URLs.
        Filters and validates working proxies using a ThreadPoolExecutor.
        """
        print("[*] Fetching fresh list of free public proxies...")
        raw_proxies = set()
        
        for url in FREE_PROXY_SOURCES:
            try:
                response = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                if response.status_code == 200:
                    # Look for IP:Port patterns
                    matches = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}\b', response.text)
                    raw_proxies.update(matches)
                    print(f"    - Found {len(matches)} proxies from {url.split('/')[2]}")
            except Exception as e:
                print(f"    - Failed to fetch proxies from {url}: {e}")
                
        raw_list = list(raw_proxies)
        random.shuffle(raw_list)
        print(f"[+] Loaded {len(raw_list)} unique raw public proxies. Validating subset...")

        verified_proxies = []
        # Test up to 250 proxies to find 20 verified working ones
        test_batch = raw_list[:250]
        
        print("[*] Finding working proxies in background (2.5s timeout)...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=45) as executor:
            future_to_proxy = {executor.submit(self._test_proxy, p): p for p in test_batch}
            for future in concurrent.futures.as_completed(future_to_proxy):
                res = future.result()
                if res:
                    verified_proxies.append(res)
                    if len(verified_proxies) >= 20:
                        break
                        
        self.proxies = verified_proxies
        
        if len(self.proxies) == 0:
            print("[!] Warning: No verified proxies found in the test batch. Using raw list as fallback.")
            self.proxies = raw_list[:100]
        else:
            random.shuffle(self.proxies)
            print(f"[+] Found {len(self.proxies)} validated working proxies.")
            
        self.current_index = 0
        self.consecutive_failures = 0

    def get_proxy(self):
        """Returns the current proxy in dict format, or None if disabled/empty."""
        if not self.enabled or not self.proxies:
            return None
            
        proxy_val = self.proxies[self.current_index]
        # Check if custom proxy already contains protocol prefix
        if proxy_val.startswith(("http://", "https://", "socks5://", "socks4://")):
            return {
                "http": proxy_val,
                "https": proxy_val
            }
        return {
            "http": f"http://{proxy_val}",
            "https": f"http://{proxy_val}"
        }

    def report_failure(self):
        """If a proxy fails, rotate to the next one."""
        if not self.enabled or not self.proxies:
            return
            
        self.consecutive_failures += 1
        failed_proxy = self.proxies[self.current_index]
        print(f"[-] Proxy failed: {failed_proxy} (Consecutive failures: {self.consecutive_failures})")
        
        # Remove the failed proxy so we don't retry it
        self.proxies.pop(self.current_index)
        
        # Adjust index or wrap around
        if len(self.proxies) == 0:
            if self.is_custom:
                print("[!] Custom proxy failed. No fallback proxies available.")
            else:
                print("[!] All proxies exhausted. Re-fetching proxy list...")
                self.fetch_proxies()
        else:
            self.current_index = self.current_index % len(self.proxies)

    def report_success(self):
        """Reset consecutive failure counter on a successful request."""
        self.consecutive_failures = 0

    def rotate(self):
        """Rotate to the next proxy in the list."""
        if not self.enabled or not self.proxies:
            return
        self.current_index = (self.current_index + 1) % len(self.proxies)


class LinkedInScraper:
    """
    Orchestrates search and detail retrieval from LinkedIn's guest portals.
    Rotates proxies dynamically and rate-limits requests to look like human traffic.
    """
    def __init__(self, proxy_manager=None, timeout=DEFAULT_REQUEST_TIMEOUT):
        self.proxy_manager = proxy_manager or ProxyManager(enabled=False)
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/"
        }

    def _sleep_delay(self):
        """Polite sleep delay to prevent rapid-fire blocking."""
        delay = random.uniform(MIN_REQUEST_DELAY, MAX_REQUEST_DELAY)
        time.sleep(delay)

    def request_with_retry(self, url, params=None, max_retries=None):
        """
        Performs an HTTP request with retry logic.
        Attempts direct request first if proxies are disabled,
        otherwise uses and rotates through the proxy list on error.
        """
        if max_retries is None:
            # Try up to 60 proxies if enabled (high success probability),
            # or 3 times if using direct connection.
            max_retries = 60 if self.proxy_manager.enabled else 3

        # Free proxies are either fast or dead; cap timeout to 5s to rotate quickly
        timeout = min(self.timeout, 5) if self.proxy_manager.enabled else self.timeout

        retries = 0
        while retries < max_retries:
            proxy = self.proxy_manager.get_proxy()
            proxy_str = list(proxy.values())[0] if proxy else "Direct Connection"
            
            # Rate limiting sleep
            if self.proxy_manager.enabled:
                # Rotate quickly through free proxies without sleeping too long
                time.sleep(random.uniform(0.1, 0.5))
            else:
                self._sleep_delay()
            
            try:
                # print(f"[*] Fetching: {url} using {proxy_str}...")
                response = requests.get(
                    url,
                    params=params,
                    headers=self.headers,
                    proxies=proxy,
                    timeout=timeout,
                    verify=False  # Avoid SSL errors with some proxies
                )
                
                # Check for rate limiting / blocking (usually HTML with CAPTCHA or 429 status)
                if response.status_code == 429:
                    print(f"[-] Status 429 (Too Many Requests). Rotating proxy...")
                    if self.proxy_manager.enabled:
                        self.proxy_manager.report_failure()
                    retries += 1
                    continue
                    
                if response.status_code == 200:
                    # Check if we were redirected to an authwall/login page or served a login screen.
                    # Also, both guest API endpoints (search & detail) return HTML fragments. 
                    # If we receive a full HTML document (with <html> or <body>), it means we were redirected or blocked.
                    is_full_page = "<html" in response.text.lower() or "<body" in response.text.lower()
                    is_login_wall = "authwall" in response.url or "login" in response.url or "log in or sign up" in response.text.lower()

                    if is_full_page or is_login_wall:
                        print("[-] Redirected to login/authwall or received full HTML page. Rotating proxy...")
                        if self.proxy_manager.enabled:
                            self.proxy_manager.report_failure()
                        retries += 1
                        continue

                    # Safety check: if response is empty or extremely short (like a proxy error page or soft block)
                    if len(response.text.strip()) < 200:
                        print("[-] Received empty or extremely short response. Rotating proxy...")
                        if self.proxy_manager.enabled:
                            self.proxy_manager.report_failure()
                        retries += 1
                        continue

                    # Safety check: if searching and no <li> elements are returned (empty fragment)
                    if "seeMoreJobPostings" in url and "<li>" not in response.text:
                        print("[-] Received empty job list fragment (likely soft blocked/proxy error). Rotating proxy...")
                        if self.proxy_manager.enabled:
                            self.proxy_manager.report_failure()
                        retries += 1
                        continue

                    # Basic sanity check that it's not a captcha wall page
                    if "security challenge" in response.text.lower() or "quick security check" in response.text.lower():
                        print("[-] CAPTCHA challenge detected on page. Rotating proxy...")
                        if self.proxy_manager.enabled:
                            self.proxy_manager.report_failure()
                        retries += 1
                        continue
                    
                    # Successful response!
                    if self.proxy_manager.enabled:
                        self.proxy_manager.report_success()
                    return response.text
                else:
                    print(f"[-] HTTP error code {response.status_code} received. Rotating proxy...")
                    if self.proxy_manager.enabled:
                        self.proxy_manager.report_failure()
                    retries += 1
                    
            except requests.exceptions.RequestException as e:
                # Network failures (timeouts, connection reset, etc.)
                if self.proxy_manager.enabled:
                    self.proxy_manager.report_failure()
                retries += 1
                
        raise Exception("[-] Max retries reached. Could not fetch URL.")

    def search_jobs(self, keywords, location, days_back, max_results=200):
        """
        Queries LinkedIn's guest job search API.
        Paginates until results run out or max_results is reached.
        """
        # LinkedIn guest API accepts f_TPR in seconds
        # e.g., 6 months = 180 days = 15,552,000 seconds
        seconds_back = days_back * 24 * 60 * 60
        f_TPR = f"r{seconds_back}"
        
        job_ids = []
        start = 0
        
        print(f"[*] Starting job search for '{keywords}' in '{location}' (Time period: past {days_back} days)...")
        
        while len(job_ids) < max_results:
            params = {
                "keywords": keywords,
                "location": location,
                "f_TPR": f_TPR,
                "start": start
            }
            
            try:
                html_content = self.request_with_retry(LINKEDIN_SEARCH_URL, params=params)
            except Exception as e:
                print(f"[-] Search failed at page offset {start}: {e}")
                break
                
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find list items for job postings
            listings = soup.find_all('li')
            
            if not listings:
                # No listings found, search complete
                break
                
            page_job_count = 0
            for item in listings:
                # Extract job ID
                # Under the guest API endpoint:
                # 1. The job URN may be in the data-entity-urn attribute of a div/anchor
                # 2. Or the href of a link may contain /jobs/view/some-id
                job_id = None
                
                # Check for full link
                link_tag = item.find('a', class_=lambda c: c and 'full-link' in c)
                if not link_tag:
                    link_tag = item.find('a')
                    
                if link_tag and 'href' in link_tag.attrs:
                    href = link_tag['href']
                    match = re.search(r'/view/(\d+)', href)
                    if match:
                        job_id = match.group(1)
                
                # Alternate method: data-entity-urn attribute
                div_tag = item.find('div', attrs={'data-entity-urn': True})
                if div_tag:
                    urn = div_tag['data-entity-urn']
                    match = re.search(r'urn:li:jobPosting:(\d+)', urn)
                    if match:
                        job_id = match.group(1)
                        
                if job_id and job_id not in job_ids:
                    job_ids.append(job_id)
                    page_job_count += 1
                    if len(job_ids) >= max_results:
                        break
            
            print(f"[+] Found {page_job_count} new jobs at page offset {start}. (Total gathered: {len(job_ids)})")
            
            if page_job_count == 0:
                # If we parsed an entire page and found no new jobs, break to avoid loops
                break
                
            start += 25
            
        return job_ids

    def get_job_detail_html(self, job_id):
        """Fetches the raw HTML detail page of a job posting."""
        url = LINKEDIN_JOB_DETAIL_URL.format(job_id=job_id)
        try:
            return self.request_with_retry(url)
        except Exception as e:
            print(f"[-] Failed to fetch details for job ID {job_id}: {e}")
            return None
