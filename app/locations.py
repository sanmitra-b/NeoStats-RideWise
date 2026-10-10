"""Explicit city aliases; no fuzzy matching or changes to supplied records."""
import re

ALIASES = {'bangalore', 'bengaluru', 'blr'}

def canonical_city(value):
    value = value.strip()
    return 'Bengaluru' if value.casefold() in ALIASES else value

def city_sql(column):
    # column comes from code-owned SQL identifiers, never request text.
    return f"CASE WHEN lower(trim({column})) IN ('bangalore','bengaluru','blr') THEN 'Bengaluru' ELSE trim({column}) END"

def normalize_question(value):
    return re.sub(r'\b(?:bangalore|bengaluru|blr)\b', 'Bengaluru', value, flags=re.IGNORECASE)
