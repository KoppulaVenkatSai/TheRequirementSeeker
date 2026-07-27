import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# Pydantic is used for structured outputs in LLM mode if installed
try:
    from pydantic import BaseModel, Field
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False

# Google GenAI SDK for LLM-based parsing
try:
    from google import genai
    from google.genai import types
    HAS_GEMINI_SDK = True
except ImportError:
    HAS_GEMINI_SDK = False


class QualificationModel:
    """Fallback validation schema structure if Pydantic is not used directly."""
    pass

if HAS_PYDANTIC:
    class JobQualifications(BaseModel):
        required_qualifications: list[str] = Field(
            description="Detailed list of mandatory skills, degree requirements, and minimum years of experience."
        )
        preferred_qualifications: list[str] = Field(
            description="Detailed list of optional, desired, nice-to-have skills, preferred degrees, or certifications."
        )


def parse_relative_date(date_str):
    """
    Parses LinkedIn relative dates (e.g., '3 weeks ago', '5 months ago')
    into an approximate datetime.date object.
    Returns datetime.date.min if parsing fails.
    """
    if not date_str:
        return datetime.min.date()
        
    date_str = date_str.lower().strip()
    # Strip prefixes like 'posted' or 'advertised'
    date_str = re.sub(r'^(posted|advertised|active)\s+', '', date_str)
    
    today = datetime.now().date()
    
    # Match hours
    match = re.search(r'(\d+)\s+hour', date_str)
    if match:
        return today
        
    # Match days
    match = re.search(r'(\d+)\s+day', date_str)
    if match:
        days = int(match.group(1))
        return today - timedelta(days=days)
        
    # Match weeks
    match = re.search(r'(\d+)\s+week', date_str)
    if match:
        weeks = int(match.group(1))
        return today - timedelta(weeks=weeks)
        
    # Match months
    match = re.search(r'(\d+)\s+month', date_str)
    if match:
        months = int(match.group(1))
        # Approximate 30 days per month
        return today - timedelta(days=months * 30)
        
    # Match years
    match = re.search(r'(\d+)\s+year', date_str)
    if match:
        years = int(match.group(1))
        return today - timedelta(days=years * 365)
        
    # Default case if string matches "just now" or "today"
    if "today" in date_str or "just now" in date_str or "yesterday" in date_str:
        if "yesterday" in date_str:
            return today - timedelta(days=1)
        return today
        
    return datetime.min.date()


def parse_job_html(html_content, job_id):
    """
    Parses the guest job posting HTML.
    Extracts Title, Company, Location, Date Posted, and Description.
    """
    if not html_content:
        return None
        
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Job Title
    title_tag = soup.find(class_=lambda x: x and ('top-card-layout__title' in x or 'topcard__title' in x or 'job-title' in x))
    title = title_tag.text.strip() if title_tag else "N/A"
    
    if title == "N/A":
        # Fallback to HTML Title
        html_title = soup.find('title')
        if html_title:
            title_text = html_title.text.strip()
            # Title is often "Company hiring Title in Location"
            title = title_text.split(" hiring ")[-1].split(" in ")[0] if " hiring " in title_text else title_text

    # 2. Company Name
    company_tag = soup.find(class_=lambda x: x and ('topcard__org-name-link' in x or 'top-card-layout__subtitle-sec' in x or 'company-name' in x))
    if company_tag:
        # Might contain internal links or sub-tags
        company = company_tag.text.strip()
        # Clean extra whitespace
        company = re.sub(r'\s+', ' ', company)
    else:
        # Fallback check
        sub_tag = soup.find(class_=lambda x: x and 'topcard__flavor' in x and 'org-name' in x)
        company = sub_tag.text.strip() if sub_tag else "N/A"

    # 3. Location
    location_tag = soup.find(class_=lambda x: x and ('topcard__flavor--bullet' in x or 'top-card-layout__first-subline' in x or 'location' in x))
    if location_tag:
        location = location_tag.text.strip()
        location = re.sub(r'\s+', ' ', location).replace('•', '').strip()
    else:
        location = "N/A"

    # 4. Posted Date
    date_tag = soup.find(class_=lambda x: x and ('posted-time-ago__text' in x or 'topcard__flavor--metadata' in x))
    date_text = date_tag.text.strip() if date_tag else "N/A"
    date_posted = parse_relative_date(date_text)

    # 5. Job Description
    desc_tag = soup.find(class_=lambda x: x and ('description__text' in x or 'show-more-less-html__markup' in x or 'job-description' in x))
    description_html = str(desc_tag) if desc_tag else ""
    description_text = desc_tag.get_text(separator='\n').strip() if desc_tag else ""
    
    # Format description text a bit nicer (remove redundant whitespace/newlines)
    description_text = re.sub(r'\n+', '\n', description_text)

    # Safety check: If we hit a login/signup wall or description is empty, discard it
    if "log in" in title.lower() or "sign up" in title.lower() or not description_text:
        return None

    return {
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": location,
        "date_posted_str": date_text,
        "date_posted": date_posted,
        "description_html": description_html,
        "description_text": description_text,
        "url": f"https://www.linkedin.com/jobs/view/{job_id}"
    }


class RuleBasedParser:
    """
    Parses job descriptions using regular expressions, heading matches,
    and text chunk boundaries.
    """
    @staticmethod
    def extract_qualifications(description_text):
        """
        Parses text to segment required vs preferred qualifications.
        """
        required = []
        preferred = []
        
        # Split description into lines
        lines = [line.strip() for line in description_text.split('\n') if line.strip()]
        
        # Categorized heading markers
        required_headers = [
            r'required\s+(qualifications|skills|requirements|experience)',
            r'basic\s+(qualifications|skills|requirements|experience)',
            r'minimum\s+(qualifications|skills|requirements|experience)',
            r'what\s+you(\'ll|\s+will)\s+need',
            r'what\s+you\s+(should\s+)?bring',
            r'what\s+we\s+look\s+for',
            r'^requirements$',
            r'^qualifications$',
            r'^key\s+requirements$',
            r'^about\s+you$',
            r'^must-haves?$',
            r'^must\s+have$',
            r'minimum\s+criteria'
        ]
        
        preferred_headers = [
            r'preferred\s+(qualifications|skills|requirements|experience)',
            r'desired\s+(qualifications|skills|requirements|experience)',
            r'highly\s+desired',
            r'nice-to-haves?',
            r'nice\s+to\s+have',
            r'bonus\s+points',
            r'preferred\s+skills',
            r'plus\s+points',
            r'what\s+would\s+make\s+you\s+stand\s+out',
            r'stand\s+out\s+with',
            r'^preferences?$'
        ]
        
        # Check if line looks like a qualification heading
        def get_section_type(line):
            line_clean = line.lower().strip(':').strip().strip('.').strip()
            for pattern in required_headers:
                if re.search(pattern, line_clean):
                    return "required"
            for pattern in preferred_headers:
                if re.search(pattern, line_clean):
                    return "preferred"
            return None

        current_section = None
        
        for line in lines:
            sec_type = get_section_type(line)
            if sec_type:
                current_section = sec_type
                continue
                
            # If we hit another major section heading that is NOT qualifications (e.g. "Benefits", "About us", "Equal Opportunity")
            # we should stop parsing qualifications.
            lower_line = line.lower()
            if any(term in lower_line for term in ["benefits", "perks", "what we offer", "compensation", "about company", "equal opportunity", "how to apply"]):
                current_section = None
                
            # Check if line looks like a bullet point or list item
            # e.g., starting with -, *, •, or numbers
            is_numbered = re.match(r'^\d+[\.\)]\s+', line) is not None
            is_bullet = line.startswith(('-', '*', '•', '▪', '◦', '▪')) or is_numbered
            
            # Clean bullet symbol
            if is_numbered:
                clean_item = re.sub(r'^\d+[\.\)]\s*', '', line).strip()
            else:
                clean_item = re.sub(r'^[\-\*•▪◦▪\s]+', '', line).strip()
            
            if current_section == "required":
                if is_bullet or len(clean_item) > 15:  # capture sentences too
                    required.append(clean_item)
            elif current_section == "preferred":
                if is_bullet or len(clean_item) > 15:
                    preferred.append(clean_item)
                    
        # If we failed to find any matching sections, let's look for bullet points
        # throughout the whole description and use a simple keyword classifier per bullet
        if not required and not preferred:
            for line in lines:
                is_numbered = re.match(r'^\d+[\.\)]\s+', line) is not None
                is_bullet = line.startswith(('-', '*', '•', '▪', '◦', '▪')) or is_numbered
                if is_bullet:
                    if is_numbered:
                        clean_item = re.sub(r'^\d+[\.\)]\s*', '', line).strip()
                    else:
                        clean_item = re.sub(r'^[\-\*•▪◦▪\s]+', '', line).strip()
                    lower_item = clean_item.lower()
                    
                    # Heuristics for classifying individual bullet points
                    preferred_words = ["preferred", "desired", "plus", "nice to", "bonus", "optional", "strongly preferred"]
                    if any(pw in lower_item for pw in preferred_words):
                        preferred.append(clean_item)
                    else:
                        required.append(clean_item)
                        
        return {
            "required_qualifications": required[:15],  # limit size to prevent massive dumps
            "preferred_qualifications": preferred[:15]
        }


class LLMParser:
    """
    Parses job descriptions using the official Google GenAI SDK.
    Requires GEMINI_API_KEY environment variable.
    """
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.client = None
        if HAS_GEMINI_SDK:
            # The client automatically picks up GEMINI_API_KEY from environment if api_key is None
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                print(f"[-] Failed to initialize Gemini Client: {e}")

    def extract_qualifications(self, description_text):
        """
        Calls Gemini to extract required and preferred qualifications.
        Falls back to Rule-Based parser if LLM fails or SDK is not available.
        """
        if not self.client or not HAS_PYDANTIC:
            # Fall back silently to rule-based
            return RuleBasedParser.extract_qualifications(description_text)
            
        prompt = (
            "You are an expert HR parser. Your task is to extract job qualifications from the provided "
            "job description. Group them into two categories:\n"
            "1. required_qualifications: Mandatory skills, degree requirements, or minimum experience needed.\n"
            "2. preferred_qualifications: Desirable, optional, or plus factors.\n\n"
            f"Job Description:\n{description_text}"
        )
        
        from config import GEMINI_MODEL
        try:
            response = self.client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=JobQualifications,
                    temperature=0.1
                )
            )
            
            # Response is JSON string adhering to JobQualifications schema
            import json
            data = json.loads(response.text)
            return {
                "required_qualifications": data.get("required_qualifications", []),
                "preferred_qualifications": data.get("preferred_qualifications", [])
            }
        except Exception as e:
            print(f"[-] Gemini extraction failed ({e}). Falling back to rule-based parser.")
            return RuleBasedParser.extract_qualifications(description_text)
