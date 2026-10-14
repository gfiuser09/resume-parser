
import os
import sys
from time import perf_counter

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv()

# Fastest Groq-hosted model available; overrides the quality-oriented default
# used elsewhere in the app (only applies if GROQ_MODEL isn't already set).
os.environ.setdefault("GROQ_MODEL", "openai/gpt-oss-20b")

from extractors.case_study_extractor import WORD_LIMITS, ensure_min_words, extract_case_study_data
from utils.errors import GroqError, GroqNotConfigured, InvalidURL, URLFetchError
from utils.url_fetcher import fetch_url_text

URL = "https://uksustainability.co.uk/case-study/sustainability-strategy-refinement-by-a-leading-ppe-supplier/"


def _word_count_line(field, data):
    min_words, max_words = WORD_LIMITS[field]
    count = data["word_counts"][field]
    line = f"{count} / {min_words} words min • max {max_words}"
    if count < min_words:
        line += "  [BELOW MINIMUM]"
    return line


start = perf_counter()

try:
    text = fetch_url_text(URL)
    fetched = perf_counter()

    print(f"Fetch: {(fetched-start)*1000:.1f} ms")

    try:
        extracted = perf_counter()
        data = extract_case_study_data(text)
        data = ensure_min_words(data, text)
        extracted_done = perf_counter()

        print(f"\nTitle *\n{data['title']}")
        print(f"\nClient name\n{data['client_name']}")
        print("\nThe story *")
        print(f"1. Situation - what existed before you came in?\n{data['situation']}")
        print(_word_count_line("situation", data))
        print(f"\n2. Process - what was your approach?\n{data['process']}")
        print(_word_count_line("process", data))
        print(f"\n3. Results - what did you measurably achieve?\n{data['results']}")
        print(_word_count_line("results", data))

        print(f"\nGroq: {(extracted_done-extracted)*1000:.1f} ms")
        print(f"Total: {(extracted_done-start)*1000:.1f} ms")
    except (GroqNotConfigured, GroqError) as e:
        print(f"\nGroq error: {e}")

except (InvalidURL, URLFetchError) as e:
    print(f"Error: {e}")
