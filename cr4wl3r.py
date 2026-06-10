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

MAX_RETRIES = 3
REQUEST_TIMEOUT = 30

# Set to True if using Tor
USE_TOR = True

TOR_PROXIES = {
    "http": "socks5h://127.0.0.1:9050",
    "https": "socks5h://127.0.0.1:9050",
}

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    filename=ERROR_LOG_FILE,
    level=logging.ERROR,
    format="%(asctime)s | %(levelname)s | %(message)s",
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
    allowed_methods=["GET", "HEAD"]
)

adapter = HTTPAdapter(max_retries=retry_strategy)

session.mount("http://", adapter)
session.mount("https://", adapter)

session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

# ============================================================
# GLOBALS
# ============================================================

visited_urls = set()

# ============================================================
# HELPERS
# ============================================================

def write_output(line):
    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_error(url, error):
    logging.error(f"{url} | {error}")


def normalize_url(url):
    return url.rstrip("/")


def is_within_scope(url):
    parsed = urlparse(url)

    if parsed.netloc != urlparse(ROOT_URL).netloc:
        return False

    return parsed.path.startswith(f"/{ROOT_PATH_NAME}")


def build_windows_path(parts, is_folder=False):
    path = "\\" + "\\".join(parts)

    if is_folder:
        path += "\\"

    return path


# ============================================================
# DIRECTORY PARSER
# ============================================================

def parse_directory_listing(html):
    """
    Returns entries in EXACT order shown on page.

    Entry format:
    {
        "name": "...",
        "href": "...",
        "is_folder": True/False,
        "size": "753K"
    }
    """

    soup = BeautifulSoup(html, "html.parser")

    pre = soup.find("pre")

    if not pre:
        return []

    entries = []

    for link in pre.find_all("a"):

        href = link.get("href", "").strip()
        name = link.get_text(strip=True)

        # Skip navigation links
        if href in ("../", "./"):
            continue

        if name in ("../", "./"):
            continue

        line_text = str(link.next_sibling or "")

        size = "N/A"

        tokens = line_text.split()

        if tokens:
            candidate = tokens[-1]

            if any(ch.isdigit() for ch in candidate):
                size = candidate

        entries.append({
            "name": name.rstrip("/"),
            "href": href,
            "is_folder": href.endswith("/"),
            "size": size
        })

    return entries


# ============================================================
# HTTP FETCH
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

            time.sleep(2 * attempt)

    return None


# ============================================================
# DFS CRAWLER
# ============================================================

def crawl_directory(current_url, current_path_parts):

    normalized = normalize_url(current_url)

    if normalized in visited_urls:
        return

    visited_urls.add(normalized)

    html = get_page(current_url)

    if not html:
        return

    entries = parse_directory_listing(html)

    folders = []
    files = []

    #
    # First pass:
    # Record everything in displayed order
    #
    for entry in entries:

        child_url = urljoin(current_url, entry["href"])

        if not is_within_scope(child_url):
            continue

        if entry["is_folder"]:

            folder_parts = current_path_parts + [entry["name"]]

            folder_path = build_windows_path(
                folder_parts,
                is_folder=True
            )

            write_output(
                f"[FOLDER] {folder_path}"
            )

            folders.append(
                (child_url, folder_parts)
            )

        else:

            file_parts = current_path_parts + [entry["name"]]

            file_path = build_windows_path(
                file_parts,
                is_folder=False
            )

            write_output(
                f"[FILE]   {file_path} | {entry['size']}"
            )

            files.append(file_path)

    #
    # Second pass:
    # DFS into folders in displayed order
    #
    for folder_url, folder_parts in folders:
        crawl_directory(folder_url, folder_parts)


# ============================================================
# MAIN
# ============================================================

def main():

    open(OUTPUT_FILE, "w", encoding="utf-8").close()

    print(f"Starting crawl: {ROOT_URL}")

    crawl_directory(
        ROOT_URL,
        []
    )

    print("Finished.")
    print(f"Results written to {OUTPUT_FILE}")
    print(f"Errors written to {ERROR_LOG_FILE}")


if __name__ == "__main__":
    main()