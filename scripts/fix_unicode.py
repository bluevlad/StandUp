"""Fix literal unicode escape sequences in DB work_items"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

UNICODE_ESCAPE_RE = re.compile(r'\\u([0-9a-fA-F]{4})')


def decode_unicode_escapes(text):
    """Replace literal \\uXXXX with actual unicode characters"""
    if not text:
        return text
    return UNICODE_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), text)


def main():
    from app.core.database import SessionLocal
    from app.models.issue import WorkItem

    db = SessionLocal()
    try:
        all_items = db.query(WorkItem).all()
        fixed = 0
        for item in all_items:
            changed = False
            if item.title and "\\u" in item.title:
                old = item.title
                item.title = decode_unicode_escapes(item.title)
                print(f"  title: {old[:60]}")
                print(f"      -> {item.title[:60]}")
                changed = True
            if item.summary and "\\u" in item.summary:
                item.summary = decode_unicode_escapes(item.summary)
                changed = True
            if changed:
                fixed += 1

        db.commit()
        print(f"\nFixed {fixed} items")
    finally:
        db.close()


if __name__ == "__main__":
    main()
