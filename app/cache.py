import hashlib
import time
from typing import Optional


class ResponseCache:
    """
    In Memory response cache with TTL (time to live)

    In production, replace this with redis for:
    - presistance accross restarts
    - shared cache across multiple instances
    - built it TTL management
    """

    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._cache: dict[str, dict] = {}
        self._hits = 0
        self._misses = 0

    def _make_key(self, query: str) -> str:
        """Create a cache key from the normalized query."""
        normalized = query.lower().strip()
        return hashlib.sha256(normalized.encode()).hexdigest()
        # 'What is python?' and 'what is python?' mapped in the same cache key

    def get(self, query: str) -> Optional[str]:  # noqa: UP045
        """
        Get cached response if it exits and hasn't expired.
        Return None on the cache miss.
        """
        key = self._make_key(query)
        if key in self._cache:
            entry = self._cache[key]
            # Check TTL
            if time.time() - entry["timestamp"] < self.ttl:
                self._hits += 1
                return entry["response"]
            else:
                # Expired
                del self._cache[key]
        self._misses += 1
        return None

    def set(self, query: str, response: str) -> None:
        """Cache a response."""
        key = self._make_key(query)
        self._cache[key] = {
            "response": response,
            "timestamp": time.time(),
            "query": query,
        }

    @property
    def stats(self) -> dict:
        """Cache performance statistic"""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{hit_rate:.1%}",
            "cached_entries": len(self._cache),
        }


"""

uv run python - <<'PY'
import time
from app.cache import ResponseCache

cache = ResponseCache(ttl_seconds=2)

def show_stats():
    print(f"Stats: {cache.stats}")

print("=" * 60)
print("TEST 1: CACHE MISS")
print("=" * 60)

result = cache.get("What is Python?")
print(f"Expected: None")
print(f"Actual:   {result}")
assert result is None, "Expected a cache miss"
show_stats()

print("\n" + "=" * 60)
print("TEST 2: CACHE SET AND HIT")
print("=" * 60)

cache.set("What is Python?", "Python is a programming language.")
result = cache.get("What is Python?")
print(f"Expected: Python is a programming language.")
print(f"Actual:   {result}")
assert result == "Python is a programming language.", "Cache hit failed"
show_stats()

print("\n" + "=" * 60)
print("TEST 3: CASE-INSENSITIVE KEY")
print("=" * 60)

result = cache.get("WHAT IS PYTHON?")
print(f"Expected: Python is a programming language.")
print(f"Actual:   {result}")
assert result == "Python is a programming language.", "Case-insensitive lookup failed"
show_stats()

print("\n" + "=" * 60)
print("TEST 4: WHITESPACE NORMALIZATION")
print("=" * 60)

result = cache.get("  what is python?  ")
print(f"Expected: Python is a programming language.")
print(f"Actual:   {result}")
assert result == "Python is a programming language.", "Whitespace normalization failed"
show_stats()

print("\n" + "=" * 60)
print("TEST 5: TTL EXPIRATION")
print("=" * 60)

cache.set("Temporary query", "Temporary response")
print("Waiting 4 seconds for the cache entry to expire...")
time.sleep(4)

result = cache.get("Temporary query")
print(f"Expected: None")
print(f"Actual:   {result}")
assert result is None, "Expired cache entry was returned"
show_stats()

print("\n" + "=" * 60)
print("TEST 6: CACHE STATISTICS")
print("=" * 60)

stats = cache.stats
print(stats)

assert stats["hits"] == 3, f"Expected 3 hits, got {stats['hits']}"
assert stats["misses"] == 2, f"Expected 2 misses, got {stats['misses']}"
assert stats["cached_entries"] == 1, (
    f"Expected 1 cached entry, got {stats['cached_entries']}"
)

print("\nAll tests passed!")
PY

"""
