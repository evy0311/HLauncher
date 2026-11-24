#!/usr/bin/env python3
"""Publish Shields endpoint data for .img/.img.xz downloads across all releases.

Includes prereleases, excludes drafts, and follows pagination for both releases
and assets. GitHub counts downloads, not unique people. Run with GITHUB_TOKEN
and GITHUB_REPOSITORY set; the output directory is served by GitHub Pages.
"""

import argparse
import json
import os
from pathlib import Path
import re
from urllib.request import Request, urlopen


def api_items(path, token):
    page = 1
    while True:
        request = Request(
            f"https://api.github.com{path}?per_page=100&page={page}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "HLauncher-image-downloads",
            },
        )
        with urlopen(request, timeout=60) as response:
            items = json.load(response)
        yield from items
        if len(items) < 100:
            return
        page += 1


def image_downloads(repository, token):
    total = 0
    for release in api_items(f"/repos/{repository}/releases", token):
        if release["draft"]:
            continue
        for asset in api_items(
            f"/repos/{repository}/releases/{release['id']}/assets", token
        ):
            if asset["name"].lower().endswith((".img", ".img.xz")):
                total += asset["download_count"]
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    repository = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        parser.error("GITHUB_REPOSITORY must be OWNER/REPO")
    total = image_downloads(repository, os.environ["GITHUB_TOKEN"])
    args.output.mkdir(parents=True, exist_ok=True)
    badge = {
        "schemaVersion": 1,
        "label": "Image downloads",
        "message": str(total),
        "color": "blue",
        "cacheSeconds": 3600,
    }
    (args.output / "image-downloads.json").write_text(
        json.dumps(badge, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Image downloads across all published releases: {total}")


if __name__ == "__main__":
    main()
