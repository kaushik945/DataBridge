# Explicit date formats
Supported formats are YYYY-MM-DD (%Y-%m-%d), DD/MM/YYYY (%d/%m/%Y), MM/DD/YYYY (%m/%d/%Y), and DD-MM-YYYY (%d-%m-%Y). Choose one format per mapped column. A value must match exactly and be a valid calendar date. 03/04/2025 is ambiguous until an operator chooses a format. Agents must not infer slash order. Invalid leap days are rejected.
