"""Scanner result caching module.

This module provides caching functionality for scanner results based on
file path and content hash. Cache entries are automatically invalidated
when file content changes.

Requirements: 6.3
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry for scanner results.
    
    Attributes:
        content_hash: Hash of the file content when scanned
        issues: List of scanner issues
        scanner_name: Name of the scanner that produced the results
        timestamp: Unix timestamp when the entry was created
    """
    content_hash: str
    issues: List[Dict[str, Any]]
    scanner_name: str
    timestamp: float = field(default_factory=time.time)


class ScannerCache:
    """Cache for scanner results.
    
    Provides thread-safe caching of scanner results based on file path
    and content hash. Cache entries are automatically invalidated when
    file content changes.
    
    The cache key is a combination of:
    - File path (normalized)
    - Scanner name
    
    Cache entries are validated by comparing the stored content hash
    with the hash of the current content.
    
    Requirements: 6.3
    """
    
    _instance: Optional["ScannerCache"] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "ScannerCache":
        """Singleton pattern for global cache instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize the cache."""
        if getattr(self, "_initialized", False):
            return
        
        self._cache: Dict[str, CacheEntry] = {}
        self._cache_lock = threading.Lock()
        self._max_entries = 1000  # Maximum cache entries
        self._ttl = 3600  # Time-to-live in seconds (1 hour)
        self._initialized = True
        
        logger.debug("ScannerCache initialized")
    
    @staticmethod
    def compute_content_hash(content: str) -> str:
        """Compute hash of file content.
        
        Args:
            content: File content string
            
        Returns:
            SHA-256 hash of the content
            
        Requirements: 6.3
        """
        if not content:
            return hashlib.sha256(b"").hexdigest()
        return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
    
    def _make_cache_key(self, file_path: str, scanner_name: str) -> str:
        """Create cache key from file path and scanner name.
        
        Args:
            file_path: Path to the file
            scanner_name: Name of the scanner
            
        Returns:
            Cache key string
        """
        # Normalize path separators
        normalized_path = file_path.replace("\\", "/")
        return f"{normalized_path}:{scanner_name}"
    
    def get(
        self, 
        file_path: str, 
        scanner_name: str, 
        content: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Get cached scanner results if valid.
        
        Returns cached results only if:
        1. Cache entry exists for the file/scanner combination
        2. Content hash matches (file hasn't changed)
        3. Entry hasn't expired (TTL)
        
        Args:
            file_path: Path to the file
            scanner_name: Name of the scanner
            content: Current file content
            
        Returns:
            List of cached issues if cache hit, None if cache miss
            
        Requirements: 6.3
        """
        cache_key = self._make_cache_key(file_path, scanner_name)
        content_hash = self.compute_content_hash(content)
        
        with self._cache_lock:
            entry = self._cache.get(cache_key)
            
            if entry is None:
                logger.debug(f"Cache miss for {cache_key}: no entry")
                return None
            
            # Check if content has changed (Requirements 6.3)
            if entry.content_hash != content_hash:
                logger.debug(
                    f"Cache invalidated for {cache_key}: content changed "
                    f"(old={entry.content_hash[:8]}..., new={content_hash[:8]}...)"
                )
                # Remove stale entry
                del self._cache[cache_key]
                return None
            
            # Check TTL
            if time.time() - entry.timestamp > self._ttl:
                logger.debug(f"Cache expired for {cache_key}")
                del self._cache[cache_key]
                return None
            
            logger.debug(f"Cache hit for {cache_key}")
            return entry.issues
    
    def set(
        self, 
        file_path: str, 
        scanner_name: str, 
        content: str, 
        issues: List[Dict[str, Any]]
    ) -> None:
        """Store scanner results in cache.
        
        Args:
            file_path: Path to the file
            scanner_name: Name of the scanner
            content: File content (used for hash)
            issues: List of scanner issues to cache
            
        Requirements: 6.3
        """
        cache_key = self._make_cache_key(file_path, scanner_name)
        content_hash = self.compute_content_hash(content)
        
        entry = CacheEntry(
            content_hash=content_hash,
            issues=issues,
            scanner_name=scanner_name
        )
        
        with self._cache_lock:
            # Evict old entries if cache is full
            if len(self._cache) >= self._max_entries:
                self._evict_oldest()
            
            self._cache[cache_key] = entry
            logger.debug(
                f"Cached {len(issues)} issues for {cache_key} "
                f"(hash={content_hash[:8]}...)"
            )
    
    def invalidate(self, file_path: str, scanner_name: Optional[str] = None) -> int:
        """Invalidate cache entries for a file.
        
        Args:
            file_path: Path to the file
            scanner_name: Optional scanner name. If None, invalidates all
                         scanners for the file.
            
        Returns:
            Number of entries invalidated
            
        Requirements: 6.3
        """
        normalized_path = file_path.replace("\\", "/")
        invalidated = 0
        
        with self._cache_lock:
            if scanner_name:
                # Invalidate specific scanner
                cache_key = self._make_cache_key(file_path, scanner_name)
                if cache_key in self._cache:
                    del self._cache[cache_key]
                    invalidated = 1
            else:
                # Invalidate all scanners for this file
                keys_to_remove = [
                    key for key in self._cache.keys()
                    if key.startswith(f"{normalized_path}:")
                ]
                for key in keys_to_remove:
                    del self._cache[key]
                invalidated = len(keys_to_remove)
        
        if invalidated:
            logger.debug(f"Invalidated {invalidated} cache entries for {file_path}")
        
        return invalidated
    
    def invalidate_by_content_change(
        self, 
        file_path: str, 
        new_content: str
    ) -> int:
        """Invalidate cache entries if content has changed.
        
        Checks all cache entries for the file and removes those
        where the content hash doesn't match.
        
        Args:
            file_path: Path to the file
            new_content: New file content
            
        Returns:
            Number of entries invalidated
            
        Requirements: 6.3
        """
        normalized_path = file_path.replace("\\", "/")
        new_hash = self.compute_content_hash(new_content)
        invalidated = 0
        
        with self._cache_lock:
            keys_to_check = [
                key for key in self._cache.keys()
                if key.startswith(f"{normalized_path}:")
            ]
            
            for key in keys_to_check:
                entry = self._cache.get(key)
                if entry and entry.content_hash != new_hash:
                    del self._cache[key]
                    invalidated += 1
        
        if invalidated:
            logger.debug(
                f"Invalidated {invalidated} cache entries for {file_path} "
                f"due to content change"
            )
        
        return invalidated
    
    def _evict_oldest(self) -> None:
        """Evict oldest cache entries to make room for new ones."""
        if not self._cache:
            return
        
        # Sort by timestamp and remove oldest 10%
        sorted_entries = sorted(
            self._cache.items(),
            key=lambda x: x[1].timestamp
        )
        
        num_to_evict = max(1, len(sorted_entries) // 10)
        for key, _ in sorted_entries[:num_to_evict]:
            del self._cache[key]
        
        logger.debug(f"Evicted {num_to_evict} oldest cache entries")
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._cache_lock:
            count = len(self._cache)
            self._cache.clear()
            logger.debug(f"Cleared {count} cache entries")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        with self._cache_lock:
            return {
                "entries": len(self._cache),
                "max_entries": self._max_entries,
                "ttl_seconds": self._ttl,
            }
    
    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance._cache.clear()
            cls._instance = None


# Global cache instance
_scanner_cache: Optional[ScannerCache] = None


def get_scanner_cache() -> ScannerCache:
    """Get the global scanner cache instance.
    
    Returns:
        ScannerCache singleton instance
    """
    global _scanner_cache
    if _scanner_cache is None:
        _scanner_cache = ScannerCache()
    return _scanner_cache


__all__ = [
    "ScannerCache",
    "CacheEntry", 
    "get_scanner_cache",
]
