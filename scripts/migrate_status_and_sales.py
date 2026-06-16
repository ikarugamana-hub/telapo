#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import (
    Db,
    LEGACY_ASSIGNED_TO_DEPARTMENT_MIGRATIONS,
    STATUS_MIGRATIONS,
    get_db_connection,
)


def main():
    db = Db(get_db_connection())
    updated = 0

    for old_status, new_status in STATUS_MIGRATIONS.items():
        cur = db.execute("UPDATE companies SET status=? WHERE status=?", (new_status, old_status))
        updated += cur.rowcount

    for old_value, sales_department in LEGACY_ASSIGNED_TO_DEPARTMENT_MIGRATIONS.items():
        cur = db.execute(
            """
            UPDATE companies
            SET sales_department=?, assigned_to=''
            WHERE assigned_to=?
              AND (sales_department IS NULL OR sales_department='')
            """,
            (sales_department, old_value),
        )
        updated += cur.rowcount

    db.commit()
    db.close()
    print(f"updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
