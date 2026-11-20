from slowapi import Limiter
from slowapi.util import get_remote_address

# Counts requests per visitor address (the IP the app sees).
# The counts are kept in this process's memory: with several workers, each worker counts separately.
# Module 8 adds Redis; the limiter can then share its counts there (storage_uri="redis://...").
limiter = Limiter(key_func=get_remote_address)
