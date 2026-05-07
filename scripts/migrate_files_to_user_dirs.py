#!/usr/bin/env python3
"""Migrate pre-multi-user raw/wiki files into user-scoped subdirectories.

Before multi-user isolation (commit b469efa, April 2026), files were stored at:
    ~/.wikimind/raw/{source_id}.txt
    ~/.wikimind/wiki/{article_slug}.md

After multi-user, they must be at:
    ~/.wikimind/raw/{user_id}/{source_id}.txt
    ~/.wikimind/wiki/{user_id}/{article_slug}.md

This script reads the database to find each source/article's user_id,
then moves the file from the root-level path to the user-scoped path.

Usage:
    python scripts/migrate_files_to_user_dirs.py          # dry run
    python scripts/migrate_files_to_user_dirs.py --apply   # actually move files
"""

import argparse
import os
import shutil
import sqlite3
from pathlib import Path


def get_data_dir() -> Path:
    """Resolve the WikiMind data directory."""
    return Path(os.environ.get("WIKIMIND_DATA_DIR", Path.home() / ".wikimind"))


def _move_file(src: Path, dst: Path, *, apply: bool) -> bool:
    """Move a single file, printing the action. Returns True if moved/would move."""
    if not src.exists() or dst.exists():
        return False
    print(f"  {'MOVE' if apply else 'would move'}: {src} -> {dst}")
    if apply:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    return True


def migrate_raw_files(db: sqlite3.Connection, data_dir: Path, *, apply: bool) -> int:
    """Move root-level raw files into user subdirectories."""
    raw_dir = data_dir / "raw"
    if not raw_dir.exists():
        print(f"  raw dir not found: {raw_dir}")
        return 0

    cursor = db.execute("SELECT id, user_id, file_path FROM source WHERE user_id IS NOT NULL")
    moved = 0
    for _source_id, user_id, file_path in cursor:
        if not file_path:
            continue

        stem = Path(file_path).stem
        user_dir = raw_dir / user_id

        # Move the .txt file
        if _move_file(raw_dir / file_path, user_dir / file_path, apply=apply):
            moved += 1

        # Move siblings (PDF, HTML originals)
        for ext in (".pdf", ".html"):
            name = f"{stem}{ext}"
            if _move_file(raw_dir / name, user_dir / name, apply=apply):
                moved += 1

    return moved


def migrate_wiki_files(db: sqlite3.Connection, data_dir: Path, *, apply: bool) -> int:
    """Move root-level wiki files into user subdirectories."""
    wiki_dir = data_dir / "wiki"
    if not wiki_dir.exists():
        print(f"  wiki dir not found: {wiki_dir}")
        return 0

    cursor = db.execute("SELECT id, user_id, file_path FROM article WHERE user_id IS NOT NULL")
    moved = 0
    for _article_id, user_id, file_path in cursor:
        if not file_path:
            continue
        legacy_path = wiki_dir / file_path
        if not legacy_path.exists():
            continue

        target_path = wiki_dir / user_id / file_path
        if target_path.exists():
            continue

        print(f"  {'MOVE' if apply else 'would move'}: {legacy_path} -> {target_path}")
        if apply:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy_path), str(target_path))
        moved += 1

    return moved


def main() -> None:
    """Run the file migration."""
    parser = argparse.ArgumentParser(description="Migrate files to user-scoped directories")
    parser.add_argument("--apply", action="store_true", help="Actually move files (default: dry run)")
    args = parser.parse_args()

    data_dir = get_data_dir()
    db_path = data_dir / "db" / "wikimind.db"

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    print(f"Data dir: {data_dir}")
    print(f"Database: {db_path}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN (pass --apply to move files)'}")
    print()

    db = sqlite3.connect(str(db_path))

    print("=== Raw source files ===")
    raw_count = migrate_raw_files(db, data_dir, apply=args.apply)
    print(f"  Total: {raw_count} files {'moved' if args.apply else 'to move'}")
    print()

    print("=== Wiki article files ===")
    wiki_count = migrate_wiki_files(db, data_dir, apply=args.apply)
    print(f"  Total: {wiki_count} files {'moved' if args.apply else 'to move'}")
    print()

    total = raw_count + wiki_count
    if total == 0:
        print("Nothing to migrate.")
    elif not args.apply:
        print(f"Run with --apply to move {total} files.")

    db.close()


if __name__ == "__main__":
    main()
