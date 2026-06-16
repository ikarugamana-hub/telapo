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
        SELECT industry, COUNT(*) AS cnt
        FROM companies
        WHERE industry IS NOT NULL
          AND industry != ''
          AND char_length(industry) > ?
        GROUP BY industry
        ORDER BY COUNT(*) DESC
        LIMIT ?
        """,
        (MAX_INDUSTRY_CHARS, BATCH_SIZE),
    ).fetchall()

    updated = 0
    for row in rows:
        original = row["industry"]
        summarized = summarize_industry_with_claude(original)
        db.execute(
            """
            UPDATE companies
            SET industry=?,
                memo = CASE
                    WHEN memo IS NULL OR memo = '' THEN ?
                    WHEN memo NOT LIKE ? THEN memo || ?
                    ELSE memo
                END
            WHERE industry=?
            """,
            (
                summarized,
                f"元業種:{original}",
                f"%元業種:{original}%",
                f" / 元業種:{original}",
                original,
            ),
        )
        updated += int(row["cnt"])

    db.commit()
    db.close()
    print(f"updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
