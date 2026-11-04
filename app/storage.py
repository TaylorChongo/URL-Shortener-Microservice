class InMemoryStorage:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def save(self, short_code: str, url: str) -> None:
        self.data[short_code] = url

    def get(self, short_code: str) -> str | None:
        return self.data.get(short_code)

    def exists(self, short_code: str) -> bool:
        return short_code in self.data