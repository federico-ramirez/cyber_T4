#!/usr/bin/env python3

import os
import time
import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# CONFIGURATION
# ============================================================

ROOT_URL = "http://xxx.onion/airespring/"
ROOT_PATH_NAME = "airespring"

OUTPUT_FILE = "filetree_output.txt"
ERROR_LOG_FILE = "error_log.txt"
CHECKPOINT_FILE = "crawl_checkpoint.json"

USE_TOR = True

TOR_PROXIES = {
    "http": "socks5h://127.0.0.1:9050",
    "https": "socks5h://127.0.0.1:9050",
}

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3

SAVE_EVERY = 100

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    filename=ERROR_LOG_FILE,
    level=logging.ERROR,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ============================================================
# SESSION SETUP
# ============================================================

session = requests.Session()

if USE_TOR:
    session.proxies.update(TOR_PROXIES)

retry_strategy = Retry(
    total=3,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)

adapter = HTTPAdapter(max_retries=retry_strategy)

session.mount("http://", adapter)
session.mount("https://", adapter)

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    )
})

# ============================================================
# GLOBALS
# ============================================================

visited_urls = set()
processed_count = 0
current_stack = []

# ============================================================
# OUTPUT HELPERS
# ============================================================

def write_output(line):
    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    print(f"[SAVED] {line}")


def log_error(url, error):
    logging.error(f"{url} | {error}")

    print(f"[ERROR] {url}")
    print(f"        {error}")


# ============================================================
# CHECKPOINT FUNCTIONS
# ============================================================

def save_checkpoint():
    global visited_urls
    global current_stack

    data = {
        "visited_urls": list(visited_urls),
        "pending_stack": current_stack
    }

    temp_file = CHECKPOINT_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    os.replace(temp_file, CHECKPOINT_FILE)

    print(
        f"[CHECKPOINT] "
        f"Visited={len(visited_urls)} "
        f"Pending={len(current_stack)}"
    )


def load_checkpoint():
    if not Path(CHECKPOINT_FILE).exists():
        return set(), None

    try:

        with open(
            CHECKPOINT_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        loaded_visited = set(
            data.get("visited_urls", [])
        )

        loaded_stack = data.get(
            "pending_stack",
            []
        )

        print(
            f"[RESUME] "
            f"Loaded checkpoint. "
            f"Visited={len(loaded_visited)} "
            f"Pending={len(loaded_stack)}"
        )

        return loaded_visited, loaded_stack

    except Exception as e:

        print(f"[ERROR] Failed loading checkpoint: {e}")

        return set(), None


# ============================================================
# URL HELPERS
# ============================================================

def normalize_url(url):
    return url.rstrip("/")


def is_within_scope(url):
    parsed = urlparse(url)

    root_parsed = urlparse(ROOT_URL)

    if parsed.netloc != root_parsed.netloc:
        return False

    if not parsed.path.startswith(f"/{ROOT_PATH_NAME}"):
        return False

    return True


def build_windows_path(parts, is_folder=False):

    if not parts:
        return "\\"

    path = "\\" + "\\".join(parts)

    if is_folder:
        path += "\\"

    return path


# ============================================================
# REQUESTS
# ============================================================

def get_page(url):

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            return response.text

        except Exception as e:

            if attempt == MAX_RETRIES:

                log_error(url, e)

                return None

            wait_time = attempt * 2

            print(
                f"[RETRY] "
                f"{url} "
                f"(attempt {attempt}/{MAX_RETRIES})"
            )

            time.sleep(wait_time)

    return None


# ============================================================
# DIRECTORY PARSING
# ============================================================

def parse_directory_listing(html):

    soup = BeautifulSoup(html, "html.parser")

    pre = soup.find("pre")

    if not pre:
        return []

    entries = []

    for link in pre.find_all("a"):

        href = link.get("href", "").strip()
        name = link.get_text(strip=True)

        if href in ("../", "./"):
            continue

        if name in ("../", "./"):
            continue

        is_folder = href.endswith("/")

        size = "N/A"

        sibling_text = str(link.next_sibling or "").strip()

        if sibling_text:

            tokens = sibling_text.split()

            for token in reversed(tokens):

                if any(c.isdigit() for c in token):
                    size = token
                    break

        entries.append({
            "name": name.rstrip("/"),
            "href": href,
            "is_folder": is_folder,
            "size": size
        })

    return entries


# ============================================================
# DFS CRAWLER
# ============================================================

def crawl():

    global visited_urls
    global processed_count
    global current_stack

    loaded_visited, loaded_stack = load_checkpoint()

    visited_urls = loaded_visited

    if loaded_stack is not None:
        current_stack = loaded_stack
    else:
        current_stack = [
            (
                ROOT_URL,
                []
            )
        ]

    while current_stack:

        current_url, current_path_parts = current_stack.pop()

        normalized = normalize_url(current_url)

        if normalized in visited_urls:
            continue

        visited_urls.add(normalized)

        print(f"\n[VISITING] {current_url}")

        html = get_page(current_url)

        if not html:
            continue

        entries = parse_directory_listing(html)

        folders_to_visit = []

        #
        # Store results exactly in displayed order
        #
        for entry in entries:

            child_url = urljoin(
                current_url,
                entry["href"]
            )

            if not is_within_scope(child_url):
                continue

            if entry["is_folder"]:

                folder_parts = (
                    current_path_parts +
                    [entry["name"]]
                )

                folder_path = build_windows_path(
                    folder_parts,
                    is_folder=True
                )

                write_output(
                    f"[FOLDER] {folder_path}"
                )

                folders_to_visit.append(
                    (
                        child_url,
                        folder_parts
                    )
                )

            else:

                file_parts = (
                    current_path_parts +
                    [entry["name"]]
                )

                file_path = build_windows_path(
                    file_parts
                )

                write_output(
                    f"[FILE]   {file_path} | {entry['size']}"
                )

        #
        # Reverse push for proper DFS order
        #
        for folder in reversed(folders_to_visit):
            current_stack.append(folder)

        processed_count += 1

        if processed_count % SAVE_EVERY == 0:
            save_checkpoint()

    save_checkpoint()

    print("\n[COMPLETE] Crawl finished.")

    try:

        os.rename(
            CHECKPOINT_FILE,
            "crawl_completed.json"
        )

        print(
            "[COMPLETE] Final checkpoint "
            "saved as crawl_completed.json"
        )

    except Exception:
        pass


# ============================================================
# MAIN
# ============================================================

def main():

    if not Path(CHECKPOINT_FILE).exists():

        if Path(OUTPUT_FILE).exists():
            os.remove(OUTPUT_FILE)

    try:

        print("=" * 60)
        print("Directory Tree Crawler")
        print("=" * 60)
        print(f"Root URL: {ROOT_URL}")
        print()

        crawl()

    except KeyboardInterrupt:

        print("\n[CTRL+C] Interrupt received")

        save_checkpoint()

        print(
            "[CTRL+C] Checkpoint saved. "
            "Run the script again to resume."
        )

        sys.exit(0)

    except Exception as e:

        print(f"\n[FATAL] {e}")

        save_checkpoint()

        raise


if __name__ == "__main__":
    main()