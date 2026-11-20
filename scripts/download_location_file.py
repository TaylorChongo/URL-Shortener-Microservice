"""Download the free DB-IP "City Lite" IP location file into the data/ folder.

Run it from the project folder (only Python's built-in tools are needed):

    python scripts/download_location_file.py

Run it again later to get the newest monthly edition, then restart the app.

IP Geolocation by DB-IP (https://db-ip.com), licensed under CC BY 4.0.
"""

import gzip
import shutil
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

PROJECT_FOLDER = Path(__file__).resolve().parent.parent
DATA_FOLDER = PROJECT_FOLDER / "data"
TARGET_FILE = DATA_FOLDER / "dbip-city-lite.mmdb"
URL_TEMPLATE = "https://download.db-ip.com/free/dbip-city-lite-{edition}.mmdb.gz"


def recent_editions() -> list[str]:
    # A new edition comes out each month. Try this month first, then last month.
    today = date.today()
    this_month = f"{today.year}-{today.month:02d}"
    if today.month == 1:
        last_month = f"{today.year - 1}-12"
    else:
        last_month = f"{today.year}-{today.month - 1:02d}"
    return [this_month, last_month]


def download(edition: str) -> bool:
    url = URL_TEMPLATE.format(edition=edition)
    compressed_file = DATA_FOLDER / "download.mmdb.gz"
    unpacked_file = DATA_FOLDER / "download.mmdb"

    print(f"Downloading {url} ...")
    # The site refuses Python's default client name, so we send a plain one
    request = urllib.request.Request(url, headers={"User-Agent": "url-shortener-setup-script"})
    try:
        with urllib.request.urlopen(request) as response, open(compressed_file, "wb") as target:
            shutil.copyfileobj(response, target)
    except urllib.error.HTTPError as error:
        print(f"  not downloaded (HTTP {error.code})")
        return False

    print("Unpacking ...")
    with gzip.open(compressed_file, "rb") as source, open(unpacked_file, "wb") as target:
        shutil.copyfileobj(source, target)
    compressed_file.unlink()

    # Replace the old file only once the new one is complete
    unpacked_file.replace(TARGET_FILE)
    return True


def main() -> None:
    DATA_FOLDER.mkdir(exist_ok=True)

    for edition in recent_editions():
        if download(edition):
            size_mb = TARGET_FILE.stat().st_size / 1024 / 1024
            print(f"Saved {TARGET_FILE.relative_to(PROJECT_FOLDER)} ({size_mb:.0f} MB, edition {edition})")
            print("Restart the app to use it: docker compose restart api")
            return

    print("Could not download the location file. Check your internet connection and try again later.")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
