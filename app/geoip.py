import logging
from pathlib import Path

import maxminddb

from app.config import GEOIP_DATABASE_PATH

logger = logging.getLogger(__name__)

# The location file is opened once, when the app starts.
# If it is missing, the app still works: country and city are simply left empty.
reader = None
if Path(GEOIP_DATABASE_PATH).exists():
    reader = maxminddb.open_database(GEOIP_DATABASE_PATH)
else:
    logger.warning("IP location file not found at %s: country and city will stay empty", GEOIP_DATABASE_PATH)


def find_location(ip_address: str) -> tuple[str | None, str | None]:
    """Return (country, city) for a public IP address, or (None, None) if unknown."""
    if reader is None:
        return None, None

    try:
        record = reader.get(ip_address)
    except ValueError:
        return None, None

    if record is None:
        # private addresses (like Docker's 172.18.0.1) are not in the file
        return None, None

    country = record.get("country", {}).get("names", {}).get("en")
    city = record.get("city", {}).get("names", {}).get("en")
    return country, city
