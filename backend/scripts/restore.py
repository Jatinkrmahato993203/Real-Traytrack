"""
restore.py — loads a backup made by backup.py into DB_NAME, and its photos
into UPLOAD_DIR.

    python scripts/restore.py                         # newest backup in BACKUP_DIR
    python scripts/restore.py path/to/traytrack-20261022-020000.sql
    python scripts/restore.py ... --force             # replace a database that has data

Refuses to touch a database that already has tables unless --force. Stop
the app first so nothing writes during the restore. Afterwards, start the
app normally — migrations bring an older backup up to the current schema.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import backups  # noqa: E402
import config  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sql", nargs="?", help="the .sql file (default: newest in BACKUP_DIR)")
    parser.add_argument("--force", action="store_true", help="replace existing tables")
    args = parser.parse_args()
    sql = Path(args.sql) if args.sql else backups.latest_backup()
    if not sql:
        sys.exit(f"No backups found in {backups.backup_dir()}")
    uploads = Path(str(sql).replace(".sql", "-uploads.zip"))
    try:
        backups.restore(sql, uploads if uploads.is_file() else None, force=args.force)
    except RuntimeError as e:
        sys.exit(str(e))
    print(f"Restored {sql.name} into {config.DB_NAME}" + (f" and photos from {uploads.name}" if uploads.is_file() else ""))


if __name__ == "__main__":
    main()
