from calendar import monthrange
from datetime import date


def end_after_months(start, months):
    offset = start.year * 12 + start.month - 1 + months
    year, month = divmod(offset, 12)
    month += 1
    return date(year, month, min(start.day, monthrange(year, month)[1]))
