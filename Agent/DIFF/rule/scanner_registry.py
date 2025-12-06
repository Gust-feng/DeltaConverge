"""Scanner registry for managing code scanner instances.

This module provides a centralized registry for code scanners, supporting
automatic registration via decorators and language-based scanner lookup.

Requirements: 4.1, 4.4, 7.1, 7.2, 7.3, 7.4
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from Agent.DIFF.rule.scanner_base import BaseScanner

logger = logging.getLogger(__name__)


def _load_scanner_config_from_rule_config() -> Dict[str, Dict[str, Any]]:
    """Load scanner configuration from rule_config.py.
    
    Returns:
        Scanner configuration dictionary mapping language to scanner configs
        
    Requirements: 4.1, 4.4
    """
    try:
        from Agent.DIFF.rule.rule_config import get_scanner_config
        return get_scanner_config()
    except ImportError:
        logger.warning("Could not import rule_config, using empty config")
        return {}
    except Exception as e:
        logger.warning(f"Error loading scanner config: {e}")
        return {}


class ScannerRegistry:
    """Registry for managing code scanner classes and instances.
    
    Provides decorator-based registration of scanner classes and methods
    for retrieving scanner instances by language.
    
    Configuration is automatically loaded from rule_config.py when needed.
    
    Attributes:
        _scanners: Mapping of language to list of scanner classes
        _instances: Cache of scanner instances by language
        _configs: Scanner configuration cache
        _config_loaded: Whether configuration has been loaded
        
    Requirements: 4.1, 4.4, 7.1, 7.2, 7.3, 7.4
    """
    
    _scanners: Dict[str, List[Type["BaseScanner"]]] = {}
    _instances: Dict[str, List["BaseScanner"]] = {}
    _configs: Dict[str, Dict[str, Any]] = {}
    _config_loaded: bool = False
    
    @classmethod
    def register(cls, language: str):
        """Decorator to register a scanner class for a language.
        
        Args:
            language: Target language (e.g., "python", "java")
            
        Returns:
            Decorator function that registers the scanner class
            
        Example:
            @ScannerRegistry.register("python")
            class PylintScanner(BaseScanner):
                ...
                
        Requirements: 7.2
        """
        def decorator(scanner_cls: Type["BaseScanner"]):
            if language not in cls._scanners:
                cls._scanners[language] = []
            
            # Avoid duplicate registration
            if scanner_cls not in cls._scanners[language]:
                cls._scanners[language].append(scanner_cls)
                logger.debug(
                    f"Registered scanner {scanner_cls.__name__} for language '{language}'"
                )
            
            return scanner_cls
        
        return decorator
    
    @classmethod
    def set_config(cls, config: Dict[str, Dict[str, Any]]) -> None:
        """Set scanner configuration.
        
        Args:
            config: Configuration dictionary mapping language to scanner configs
                    e.g., {"python": {"pylint": {"enabled": True, "timeout": 30}}}
                    
        Requirements: 4.1, 4.4
        """
        cls._configs = config
        cls._config_loaded = True
        # Clear instance cache when config changes
        cls._instances.clear()
    
    @classmethod
    def load_config(cls, force_reload: bool = False) -> None:
        """Load scanner configuration from rule_config.py.
        
        Args:
            force_reload: If True, reload config even if already loaded
            
        Requirements: 4.1, 4.4
        """
        if cls._config_loaded and not force_reload:
            return
        
        cls._configs = _load_scanner_config_from_rule_config()
        cls._config_loaded = True
        # Clear instance cache when config changes
        cls._instances.clear()
        logger.debug(f"Loaded scanner config for languages: {list(cls._configs.keys())}")
    
    @classmethod
    def get_scanner_config(
        cls, 
        language: str, 
        scanner_name: str
    ) -> Dict[str, Any]:
        """Get configuration for a specific scanner.
        
        Automatically loads configuration from rule_config.py if not already loaded.
        
        Args:
            language: Target language
            scanner_name: Scanner name
            
        Returns:
            Scanner configuration dictionary
            
        Requirements: 4.1, 4.4
        """
        # Auto-load config if not loaded
        if not cls._config_loaded:
            cls.load_config()
        
        lang_config = cls._configs.get(language, {})
        return lang_config.get(scanner_name, {})
    
    @classmethod
    def get_scanners(
        cls, 
        language: str, 
        config: Optional[Dict[str, Any]] = None
    ) -> List["BaseScanner"]:
        """Get all registered scanner instances for a language.
        
        Creates new instances with the provided configuration.
        Configuration is automatically loaded from rule_config.py if not provided.
        
        Args:
            language: Target language (e.g., "python", "java")
            config: Optional configuration dictionary for scanners.
                    If None, loads from rule_config.py.
            
        Returns:
            List of scanner instances for the specified language
            
        Requirements: 4.1, 4.4, 7.3
        """
        # Auto-load config if not loaded and no config provided
        if config is None and not cls._config_loaded:
            cls.load_config()
        
        scanner_classes = cls._scanners.get(language, [])
        instances = []
        
        for scanner_cls in scanner_classes:
            # Get scanner-specific config
            scanner_config = {}
            if config:
                scanner_config = config.get(scanner_cls.name, {})
            else:
                scanner_config = cls.get_scanner_config(language, scanner_cls.name)
            
            try:
                instance = scanner_cls(config=scanner_config)
                instances.append(instance)
                logger.debug(
                    f"Created scanner instance {scanner_cls.name} for {language} "
                    f"with config: {scanner_config}"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to instantiate scanner {scanner_cls.__name__}: {e}"
                )
        
        return instances
    
    @classmethod
    def get_available_scanners(
        cls, 
        language: str,
        config: Optional[Dict[str, Any]] = None
    ) -> List["BaseScanner"]:
        """Get all available (installed) scanner instances for a language.
        
        Only returns scanners that are both enabled and available on the system.
        Logs warnings for unavailable scanners to help with debugging.
        
        Args:
            language: Target language (e.g., "python", "java")
            config: Optional configuration dictionary for scanners
            
        Returns:
            List of available scanner instances
            
        Requirements: 4.2, 7.4
        """
        all_scanners = cls.get_scanners(language, config)
        available = []
        unavailable_reasons = []
        
        for scanner in all_scanners:
            # Check if scanner is enabled
            if not scanner.enabled:
                logger.debug(f"Scanner {scanner.name} is disabled in configuration")
                unavailable_reasons.append(f"{scanner.name}: disabled")
                continue
            
            # Check if scanner is available on the system
            is_avail, reason = scanner.check_availability_with_reason()
            if is_avail:
                available.append(scanner)
                logger.debug(f"Scanner {scanner.name} is available for {language}")
            else:
                # Log warning for unavailable scanner (Requirements 4.2)
                logger.warning(
                    f"Scanner {scanner.name} for {language} is not available: {reason}"
                )
                unavailable_reasons.append(f"{scanner.name}: {reason}")
        
        # Log summary if some scanners are unavailable
        if unavailable_reasons and available:
            logger.info(
                f"Using {len(available)} of {len(all_scanners)} scanners for {language}. "
                f"Unavailable: {', '.join(unavailable_reasons)}"
            )
        elif not available and all_scanners:
            logger.warning(
                f"No scanners available for {language}. "
                f"All {len(all_scanners)} registered scanners are unavailable."
            )
        
        return available
    
    @classmethod
    def get_registered_languages(cls) -> List[str]:
        """Get list of languages with registered scanners.
        
        Returns:
            List of language names
        """
        return list(cls._scanners.keys())
    
    @classmethod
    def get_scanner_classes(cls, language: str) -> List[Type["BaseScanner"]]:
        """Get registered scanner classes for a language.
        
        Args:
            language: Target language
            
        Returns:
            List of scanner classes
        """
        return cls._scanners.get(language, []).copy()
    
    @classmethod
    def clear(cls) -> None:
        """Clear all registered scanners and cached instances.
        
        Useful for testing.
        """
        cls._scanners.clear()
        cls._instances.clear()
        cls._configs.clear()
        cls._config_loaded = False
    
    @classmethod
    def unregister(cls, language: str, scanner_cls: Type["BaseScanner"]) -> bool:
        """Unregister a scanner class.
        
        Args:
            language: Target language
            scanner_cls: Scanner class to unregister
            
        Returns:
            True if scanner was unregistered, False if not found
        """
        if language in cls._scanners:
            if scanner_cls in cls._scanners[language]:
                cls._scanners[language].remove(scanner_cls)
                # Clear instance cache for this language
                if language in cls._instances:
                    del cls._instances[language]
                return True
        return False
    
    @classmethod
    def get_scanner_info(cls, language: str) -> List[Dict[str, Any]]:
        """Get information about all scanners for a language.
        
        Args:
            language: Target language
            
        Returns:
            List of scanner info dictionaries
        """
        scanners = cls.get_scanners(language)
        return [scanner.get_scanner_info() for scanner in scanners]
