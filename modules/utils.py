import pandas as pd
import numpy as np
from typing import Any, Dict, List, Optional, Union
import re

def clean_column_name(name: str) -> str:
    """
    Cleans a column name by removing special characters and converting to snake_case.
    """
    # Remove accents and special chars
    name = re.sub(r'[^\w\s]', '', name)
    # Convert to snake_case
    name = name.lower().strip().replace(' ', '_')
    return name

def validate_dataframe(df: pd.DataFrame) -> bool:
    """
    Validates if the dataframe is not empty and has columns.
    """
    if df is None or df.empty:
        return False
    return True

def safe_float_conversion(value: Any) -> Optional[float]:
    """
    Safely converts a value to float. Returns None if conversion fails.
    """
    try:
        if pd.isna(value):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # Handle Brazilian currency format
            value = value.replace('R$', '').replace('.', '').replace(',', '.')
            return float(value)
        return float(value)
    except (ValueError, TypeError):
        return None

def format_currency(value: float) -> str:
    """
    Formats a float value as Brazilian currency.
    """
    try:
        return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return str(value)
