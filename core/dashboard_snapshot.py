"""Render each report from one transactionally consistent MySQL snapshot."""
from functools import wraps
from django.db import connection, transaction


def consistent_dashboard(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if connection.vendor == 'mysql' and not connection.in_atomic_block:
            # Applies to the next transaction only, without changing pooled
            # connection defaults or transactions owned by the caller.
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        with transaction.atomic():
            return view(*args, **kwargs)
    return wrapped
