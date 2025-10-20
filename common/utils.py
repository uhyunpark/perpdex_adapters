"""
Common utility functions
"""
import time
from typing import Union


def now_ms() -> int:
    """Get current timestamp in milliseconds"""
    return int(time.time() * 1000)


def now_us() -> int:
    """Get current timestamp in microseconds"""
    return int(time.time() * 1_000_000)


def format_price(price: float, decimals: int = 2) -> str:
    """Format price with specified decimal places"""
    return f"{price:.{decimals}f}"


def format_qty(qty: float, decimals: int = 6) -> str:
    """Format quantity with specified decimal places"""
    return f"{qty:.{decimals}f}"


def bps_to_decimal(bps: float) -> float:
    """Convert basis points to decimal"""
    return bps / 10_000.0


def decimal_to_bps(decimal: float) -> float:
    """Convert decimal to basis points"""
    return decimal * 10_000.0


def safe_float(value: Union[str, int, float], default: float = 0.0) -> float:
    """Safely convert value to float"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: Union[str, int, float], default: int = 0) -> int:
    """Safely convert value to int"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value between min and max"""
    return max(min_val, min(max_val, value))