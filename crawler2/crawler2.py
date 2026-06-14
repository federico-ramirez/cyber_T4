#!/usr/bin/env python3

import json
import logging
import os
import re
import sys
import time

from pathlib import Path
from urllib.parse import (
    urljoin,
    urlparse,
    unquote
)

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# CONFIGURATION
# ============================================================

ROOT_URL = "http://xxxxxxxxxxxxxxxx.onion/detail/VICTIM_ID"

VICTIM_ID = "VICTIM_ID"

USE_TOR = True

TOR_PROXIES = {
    "http": "socks5h://127.0.0.1:9050",
    "https": "socks5h://127.0.0.1:9050"
}

OUTPUT_FILE = "filetree_output.txt"
ERROR_FILE = "error_log.txt"
CHECKPOINT_FILE = "crawl_checkpoint.json"

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
SAVE_EVERY = 100

INVALID_WINDOWS_CHARS = '<>:"\\|?*'

# ============================================================
# GLOBALS
# ============================================================

visited_urls = set()
current_stack = []
processed_count = 0

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    filename=ERROR_FILE,
    level=logging.ERROR,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ============================================================
# SESSION
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
    "User-Agent":
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64)"
})

# ============================================================
# HELPERS
# ============================================================

def sanitize_windows_name(name):

    for ch in INVALID_WINDOWS_CHARS:
        name = name.replace(ch, "_")

    return name.strip()


def write_output(line):

    with open(
        OUTPUT_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(line + "\n")

    print(f"[SAVED] {line}")


def log_error(url, error):

    logging.error(
        f"{url} | {error}"
    )

    print(f"[ERROR] {url}")
    print(f"        {error}")


def normalize_url(url):
    return url.rstrip("/")


def build_windows_path(parts, is_folder=False):

    path = "\\" + "\\".join(parts)

    if is_folder:
        path += "\\"

    return path


# ============================================================
# CHECKPOINTS
# ============================================================

def save_checkpoint():

    data = {
        "visited_urls": list(visited_urls),
        "pending_stack": current_stack
    }

    temp_file = CHECKPOINT_FILE + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        temp_file,
        CHECKPOINT_FILE
    )

    print(
        f"[CHECKPOINT] "
        f"Visited={len(visited_urls)} "
        f"Pending={len(current_stack)}"
    )


def load_checkpoint():

    if not Path(
        CHECKPOINT_FILE
    ).exists():

        return set(), None

    try:

        with open(
            CHECKPOINT_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        print(
            f"[RESUME] "
            f"Loaded checkpoint "
            f"(Visited={len(data.get('visited_urls', []))})"
        )

        return (
            set(data.get("visited_urls", [])),
            data.get("pending_stack", [])
        )

    except Exception as e:

        print(
            f"[ERROR] "
            f"Failed to load checkpoint: {e}"
        )

        return set(), None


# ============================================================
# NETWORK
# ============================================================

def get_page(url):

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

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

            time.sleep(attempt * 2)

    return None


# ============================================================
# PARSING
# ============================================================

def extract_sub_value(onclick):

    match = re.search(
        r"sub=([^'\"]+)",
        onclick
    )

    if not match:
        return None

    value = unquote(
        match.group(1)
    )

    return value.strip()


def is_folder_row(onclick):

    return (
        "window.open" not in onclick
    )


def extract_entries(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    entries = []

    rows = soup.select(
        "tr.noselect"
    )

    for row in rows:

        link = row.find("a")

        if not link:
            continue

        text = link.get_text(
            strip=True
        )

        if text.lower() == "back":
            continue

        onclick = (
            link.get("onclick", "")
            or ""
        )

        if not onclick:
            continue

        sub_path = extract_sub_value(
            onclick
        )

        if not sub_path:
            continue

        size_td = row.find(
            "td",
            class_="file-size"
        )

        size = "N/A"

        if size_td:

            size_text = (
                size_td.get_text(
                    strip=True
                )
            )

            if (
                size_text
                and size_text != "-"
            ):
                size = size_text

        entries.append({
            "path": sub_path,
            "size": size,
            "is_folder":
                is_folder_row(
                    onclick
                )
        })

    return entries


# ============================================================
# SCOPE VALIDATION
# ============================================================

def in_scope(url):

    parsed = urlparse(url)

    return (
        f"/detail/{VICTIM_ID}"
        in parsed.path
    )


# ============================================================
# OPTIONAL BREADCRUMB VALIDATION
# ============================================================

def validate_breadcrumb(
    html,
    expected_parts
):

    try:

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        breadcrumb_text = soup.get_text(
            " ",
            strip=True
        )

        expected = " ".join(
            expected_parts
        )

        return expected in breadcrumb_text

    except Exception:
        return True


# ============================================================
# DFS CRAWLER
# ============================================================

def crawl():

    global visited_urls
    global current_stack
    global processed_count

    loaded_visited, loaded_stack = (
        load_checkpoint()
    )

    visited_urls = loaded_visited

    if loaded_stack is None:

        current_stack = [
            (
                ROOT_URL,
                []
            )
        ]

    else:

        current_stack = loaded_stack

    while current_stack:

        current_url, current_parts = (
            current_stack.pop()
        )

        normalized = normalize_url(
            current_url
        )

        if normalized in visited_urls:
            continue

        visited_urls.add(
            normalized
        )

        print(
            f"\n[VISITING] "
            f"{current_url}"
        )

        html = get_page(
            current_url
        )

        if not html:
            continue

        validate_breadcrumb(
            html,
            current_parts
        )

        entries = extract_entries(
            html
        )

        folders = []

        for entry in entries:

            full_parts = []

            for part in (
                entry["path"]
                .split("/")
            ):

                part = unquote(part)

                part = (
                    sanitize_windows_name(
                        part
                    )
                )

                if part:
                    full_parts.append(
                        part
                    )

            if not full_parts:
                continue

            if entry["is_folder"]:

                folder_path = (
                    build_windows_path(
                        full_parts,
                        True
                    )
                )

                write_output(
                    f"[FOLDER] {folder_path}"
                )

                folder_url = (
                    f"{ROOT_URL}"
                    f"?sub="
                    f"{entry['path']}"
                )

                if in_scope(
                    folder_url
                ):

                    folders.append(
                        (
                            folder_url,
                            full_parts
                        )
                    )

            else:

                file_path = (
                    build_windows_path(
                        full_parts,
                        False
                    )
                )

                write_output(
                    f"[FILE]   "
                    f"{file_path} | "
                    f"{entry['size']}"
                )

        #
        # Reverse push
        # to preserve DFS order
        #
        for folder in reversed(
            folders
        ):
            current_stack.append(
                folder
            )

        processed_count += 1

        if (
            processed_count %
            SAVE_EVERY
            == 0
        ):
            save_checkpoint()

    save_checkpoint()

    print(
        "\n[COMPLETE] "
        "Crawl finished."
    )

# ============================================================
# MAIN
# ============================================================

def main():

    if not Path(
        CHECKPOINT_FILE
    ).exists():

        if Path(
            OUTPUT_FILE
        ).exists():

            os.remove(
                OUTPUT_FILE
            )

    try:

        crawl()

    except KeyboardInterrupt:

        print(
            "\n[CTRL+C]"
        )

        save_checkpoint()

        print(
            "[CTRL+C] "
            "Checkpoint saved."
        )

        sys.exit(0)

    except Exception as e:

        save_checkpoint()

        raise e


if __name__ == "__main__":
    main()