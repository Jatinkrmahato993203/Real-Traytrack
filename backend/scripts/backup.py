"""
backup.py — one consistent snapshot of everything TrayTrack needs to be
restored: the database (mysqldump) and the uploaded photos. Each dump is
checked (complete, essential tables present) before it counts.

    python scripts/backup.py                 # writes to BACKUP_DIR (default backend/backups)
    python scripts/backup.py --keep 14       # and keeps only the newest 14

In Docker the nightly `backup` job does this automatically (BACKUPS_ENABLED=1).
Copy BACKUP_DIR somewhere off this machine — a backup on the same disk
isn't a backup. Restore with scripts/restore.py.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import backups  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default=None, help="where to write (default BACKUP_DIR)")
    parser.add_argument("--keep", type=int, default=30, help="how many backups to keep (default 30)")
    args = parser.parse_args()
    try:
        sql_path, zip_path = backups.run_backup(keep=args.keep, out_dir=args.dir)
    except RuntimeError as e:
        sys.exit(str(e))
    print(f"Database: {sql_path} ({sql_path.stat().st_size // 1024} KB, verified)")
    if zip_path:
        print(f"Uploads:  {zip_path}")


if __name__ == "__main__":
    main()
