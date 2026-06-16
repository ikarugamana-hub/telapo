#!/usr/bin/env python3
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import Db, get_db_connection
from collector import MAX_INDUSTRY_CHARS, summarize_industry_with_claude


BATCH_SIZE = int(os.environ.get("INDUSTRY_SUMMARY_BATCH_SIZE", "200"))


def main():
    db = Db(get_db_connection())
    rows = db.execute(
        """
        SELECT id, industry, memo
        FROM companies
        WHERE industry IS NOT NULL
          AND industry != ''
          AND char_length(industry) > ?
        ORDER BY id
        LIMIT ?
        """,
        (MAX_INDUSTRY_CHARS, BATCH_SIZE),
    ).fetchall()

    updated = 0
    for row in rows:
        original = row["industry"]
        summarized = summarize_industry_with_claude(original)
        memo = row["memo"] or ""
        if f"元業種:{original}" not in memo:
            memo = f"{memo} / 元業種:{original}" if memo else f"元業種:{original}"
        db.execute(
            "UPDATE companies SET industry=?, memo=? WHERE id=?",
            (summarized, memo, row["id"]),
        )
        updated += 1

    db.commit()
    db.close()
    print(f"updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
