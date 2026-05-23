#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@Time    : 2026-03-12
@Author  : Levi Fang 000592
@File    : retry_util.py
@Desc    : Retry utility with exponential backoff decorator for handling transient failures
"""
import os
import sys
import time
import traceback
import random
from typing import Callable, Any, TypeVar, Optional, Union, Type, Tuple
from functools import wraps

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.klogger_util import logger

T = TypeVar('T')


def retry_with_backoff(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = (Exception,)
) -> Callable:
    """
    Decorator for retry with exponential backoff
    
    Implements exponential backoff retry logic for handling transient failures
    in network operations, database connections, and API calls.
    
    :param max_retries: Maximum number of retry attempts (default: 3)
    :param backoff_factor: Multiplier for delay between retries (default: 2.0)
    :param initial_delay: Initial delay in seconds (default: 1.0)
    :param max_delay: Maximum delay between retries in seconds (default: 60.0)
    :param jitter: Add random jitter to prevent thundering herd (default: True)
    :param exceptions: Exception types to catch and retry on
    :return: Decorated function
    """
    # Normalize exceptions to tuple
    if not isinstance(exceptions, tuple):
        exceptions = (exceptions,)
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            retry_count = 0
            delay = initial_delay
            
            # Handle zero retries case
            if max_retries <= 0:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    logger.error(
                        f"Function {func.__name__} failed with no retries allowed, "
                        f"args={args}, kwargs={kwargs}, "
                        f"error: {traceback.format_exc()}"
                    )
                    raise
            
            while retry_count < max_retries:
                try:
                    result = func(*args, **kwargs)
                    if retry_count > 0:
                        logger.info(
                            f"Function {func.__name__} succeeded after {retry_count} retries"
                        )
                    return result
                    
                except exceptions as e:
                    retry_count += 1
                    
                    if retry_count >= max_retries:
                        logger.error(
                            f"Function {func.__name__} failed after {max_retries} retries, "
                            f"args={args}, kwargs={kwargs}, "
                            f"error: {traceback.format_exc()}"
                        )
                        raise
                    
                    # Calculate next delay with exponential backoff
                    next_delay = delay * backoff_factor
                    capped_delay = min(next_delay, max_delay)
                    
                    # Add jitter to prevent thundering herd
                    if jitter:
                        jitter_delay = capped_delay * (0.5 + random.random() * 0.5)
                    else:
                        jitter_delay = capped_delay
                    
                    logger.warning(
                        f"Function {func.__name__} failed, "
                        f"attempt {retry_count}/{max_retries}, "
                        f"retrying in {jitter_delay:.2f}s, "
                        f"error: {str(e)}"
                    )
                    
                    time.sleep(jitter_delay)
                    delay = next_delay  # Keep uncapped delay for next calculation
            
            # This should never be reached, but for type safety
            raise RuntimeError(f"Unexpected state in retry logic for {func.__name__}")
        
        return wrapper
    return decorator


def retry_api_call(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    initial_delay: float = 1.0,
    max_delay: float = 30.0
) -> Callable:
    """
    Specialized retry decorator for API calls
    
    Handles common API failure scenarios including network timeouts,
    connection errors, and temporary server errors.
    
    :param max_retries: Maximum number of retry attempts (default: 3)
    :param backoff_factor: Multiplier for delay between retries (default: 2.0)
    :param initial_delay: Initial delay in seconds (default: 1.0)
    :param max_delay: Maximum delay between retries in seconds (default: 30.0)
    :return: Decorated function
    """
    # Import here to avoid circular dependencies
    try:
        import requests
        api_exceptions = (
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.HTTPError,
            ConnectionError,
            TimeoutError
        )
    except ImportError:
        # Fallback if requests not available
        api_exceptions = (ConnectionError, TimeoutError, OSError)
    
    return retry_with_backoff(
        max_retries=max_retries,
        backoff_factor=backoff_factor,
        initial_delay=initial_delay,
        max_delay=max_delay,
        exceptions=api_exceptions
    )


def retry_webhook_call(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    initial_delay: float = 2.0,
    max_delay: float = 60.0
) -> Callable:
    """
    Specialized retry decorator for webhook calls
    
    Handles webhook delivery failures with appropriate backoff timing
    for external service integration.
    
    :param max_retries: Maximum number of retry attempts (default: 3)
    :param backoff_factor: Multiplier for delay between retries (default: 2.0)
    :param initial_delay: Initial delay in seconds (default: 2.0)
    :param max_delay: Maximum delay between retries in seconds (default: 60.0)
    :return: Decorated function
    """
    # Import here to avoid circular dependencies
    try:
        import requests
        webhook_exceptions = (
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.HTTPError,
            ConnectionError,
            TimeoutError
        )
    except ImportError:
        # Fallback if requests not available
        webhook_exceptions = (ConnectionError, TimeoutError, OSError)
    
    return retry_with_backoff(
        max_retries=max_retries,
        backoff_factor=backoff_factor,
        initial_delay=initial_delay,
        max_delay=max_delay,
        exceptions=webhook_exceptions
    )


def retry_database_operation(
    max_retries: int = 3,
    backoff_factor: float = 1.5,
    initial_delay: float = 0.5,
    max_delay: float = 10.0
) -> Callable:
    """
    Specialized retry decorator for database operations
    
    Handles database connection failures and temporary lock issues
    with shorter delays appropriate for database operations.
    
    :param max_retries: Maximum number of retry attempts (default: 3)
    :param backoff_factor: Multiplier for delay between retries (default: 1.5)
    :param initial_delay: Initial delay in seconds (default: 0.5)
    :param max_delay: Maximum delay between retries in seconds (default: 10.0)
    :return: Decorated function
    """
    # Import here to avoid circular dependencies
    try:
        from sqlalchemy.exc import OperationalError, DisconnectionError
        db_exceptions = (
            OperationalError,
            DisconnectionError,
            ConnectionError,
            TimeoutError
        )
    except ImportError:
        # Fallback if SQLAlchemy not available
        db_exceptions = (ConnectionError, TimeoutError, OSError)
    
    return retry_with_backoff(
        max_retries=max_retries,
        backoff_factor=backoff_factor,
        initial_delay=initial_delay,
        max_delay=max_delay,
        jitter=False,  # Database operations prefer consistent timing
        exceptions=db_exceptions
    )


class RetryConfig:
    """
    Configuration class for retry behavior
    
    Provides centralized configuration for retry parameters
    across different components of the system.
    """
    
    # Default retry configurations for different operation types
    CRAWLER_CONFIG = {
        'max_retries': 3,
        'backoff_factor': 2.0,
        'initial_delay': 1.0,
        'max_delay': 30.0
    }
    
    API_CONFIG = {
        'max_retries': 3,
        'backoff_factor': 2.0,
        'initial_delay': 1.0,
        'max_delay': 30.0
    }
    
    WEBHOOK_CONFIG = {
        'max_retries': 3,
        'backoff_factor': 2.0,
        'initial_delay': 2.0,
        'max_delay': 60.0
    }
    
    DATABASE_CONFIG = {
        'max_retries': 3,
        'backoff_factor': 1.5,
        'initial_delay': 0.5,
        'max_delay': 10.0
    }
    
    @classmethod
    def get_crawler_retry(cls) -> Callable:
        """
        Get retry decorator configured for crawler operations
        
        :return: Configured retry decorator
        """
        return retry_with_backoff(**cls.CRAWLER_CONFIG)
    
    @classmethod
    def get_api_retry(cls) -> Callable:
        """
        Get retry decorator configured for API operations
        
        :return: Configured retry decorator
        """
        return retry_api_call(**cls.API_CONFIG)
    
    @classmethod
    def get_webhook_retry(cls) -> Callable:
        """
        Get retry decorator configured for webhook operations
        
        :return: Configured retry decorator
        """
        return retry_webhook_call(**cls.WEBHOOK_CONFIG)
    
    @classmethod
    def get_database_retry(cls) -> Callable:
        """
        Get retry decorator configured for database operations
        
        :return: Configured retry decorator
        """
        return retry_database_operation(**cls.DATABASE_CONFIG)


def execute_with_retry(
    func: Callable[..., T],
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    initial_delay: float = 1.0,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = (Exception,),
    *args: Any,
    **kwargs: Any
) -> T:
    """
    Execute a function with retry logic without using decorator
    
    Useful for one-off retry operations or when decorator syntax is not suitable.
    
    :param func: Function to execute
    :param max_retries: Maximum number of retry attempts
    :param backoff_factor: Multiplier for delay between retries
    :param initial_delay: Initial delay in seconds
    :param exceptions: Exception types to catch and retry on
    :param args: Positional arguments for the function
    :param kwargs: Keyword arguments for the function
    :return: Function result
    """
    # Normalize exceptions to tuple
    if not isinstance(exceptions, tuple):
        exceptions = (exceptions,)
    
    retry_count = 0
    delay = initial_delay
    
    while retry_count < max_retries:
        try:
            result = func(*args, **kwargs)
            if retry_count > 0:
                logger.info(
                    f"Function {func.__name__} succeeded after {retry_count} retries"
                )
            return result
            
        except exceptions as e:
            retry_count += 1
            
            if retry_count >= max_retries:
                logger.error(
                    f"Function {func.__name__} failed after {max_retries} retries, "
                    f"args={args}, kwargs={kwargs}, "
                    f"error: {traceback.format_exc()}"
                )
                raise
            
            # Calculate next delay with exponential backoff
            next_delay = delay * backoff_factor
            
            logger.warning(
                f"Function {func.__name__} failed, "
                f"attempt {retry_count}/{max_retries}, "
                f"retrying in {next_delay:.2f}s, "
                f"error: {str(e)}"
            )
            
            time.sleep(next_delay)
            delay = next_delay
    
    # This should never be reached, but for type safety
    raise RuntimeError(f"Unexpected state in retry logic for {func.__name__}")
