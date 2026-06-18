#!/usr/bin/env python3
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import Db, get_db_connection


def is_dry_run():
    return os.environ.get("DRY_RUN", "1").lower() not in {"0", "false", "no"}


def main():
    db = Db(get_db_connection())
    dry_run = is_dry_run()

    total = db.execute(
        "SELECT COUNT(*) AS cnt FROM companies WHERE municipality LIKE ?",
        ("%村",),
    ).fetchone()["cnt"]

    print(f"dry_run={dry_run}")
    print(f"target_rows={total}")

    rows = db.execute(
        """
        SELECT prefecture, municipality, COUNT(*) AS cnt
        FROM companies
        WHERE municipality LIKE ?
        GROUP BY prefecture, municipality
        ORDER BY cnt DESC, prefecture, municipality
        LIMIT 50
        """,
        ("%村",),
    ).fetchall()
    for row in rows:
        print(f"{row['prefecture']}/{row['municipality']}: {row['cnt']}")

    if total == 0:
        db.close()
        return 0

    deleted = db.execute(
        "DELETE FROM companies WHERE municipality LIKE ?",
        ("%村",),
    ).rowcount

    if dry_run:
        db.conn.rollback()
        print(f"would_delete={deleted}")
    else:
        db.commit()
        print(f"deleted={deleted}")

    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
