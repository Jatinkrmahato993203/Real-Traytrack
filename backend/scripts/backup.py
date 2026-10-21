"""
backup.py — one consistent snapshot of everything TrayTrack needs to be
restored: the database (mysqldump) and the uploaded photos.

    python scripts/backup.py                 # writes to BACKUP_DIR (default backend/backups)
    python scripts/backup.py --keep 14       # and keeps only the newest 14

Schedule it daily (cron / Windows Task Scheduler) and copy BACKUP_DIR
somewhere off this machine — a backup on the same disk isn't a backup.

Restore:
    mysql -u USER -p DB_NAME < traytrack-YYYYmmdd-HHMMSS.sql
    unzip traytrack-YYYYmmdd-HHMMSS-uploads.zip -d <UPLOAD_DIR>
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default=os.environ.get("BACKUP_DIR", str(config.BASE_DIR / "backups")))
    parser.add_argument("--keep", type=int, default=30, help="how many backups to keep (default 30)")
    args = parser.parse_args()

    out_dir = Path(args.dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    sql_path = out_dir / f"traytrack-{stamp}.sql"

    # MYSQLDUMP lets you point at the tool when it isn't on PATH (common on Windows).
    mysqldump = os.environ.get("MYSQLDUMP") or shutil.which("mysqldump") or shutil.which("mariadb-dump")
    if not mysqldump:
        sys.exit("mysqldump not found on PATH — install the MySQL/MariaDB client tools.")
    env = {**os.environ, "MYSQL_PWD": config.DB_PASSWORD}  # keeps the password off the command line
    with open(sql_path, "wb") as f:
        result = subprocess.run(
            [mysqldump, "-h", config.DB_HOST, "-P", str(config.DB_PORT), "-u", config.DB_USER,
             "--single-transaction", "--routines", "--default-character-set=utf8mb4", config.DB_NAME],
            stdout=f, stderr=subprocess.PIPE, env=env,
        )
    if result.returncode != 0:
        sql_path.unlink(missing_ok=True)
        sys.exit(f"mysqldump failed: {result.stderr.decode(errors='replace').strip()}")

    uploads = Path(config.UPLOAD_ROOT)
    archive = None
    if uploads.exists():
        archive = shutil.make_archive(str(out_dir / f"traytrack-{stamp}-uploads"), "zip", uploads)

    # Rotate: keep the newest N snapshots.
    snapshots = sorted(out_dir.glob("traytrack-*.sql"), reverse=True)
    for old in snapshots[args.keep:]:
        old.unlink(missing_ok=True)
        Path(str(old).replace(".sql", "-uploads.zip")).unlink(missing_ok=True)

    print(f"Database: {sql_path} ({sql_path.stat().st_size // 1024} KB)")
    if archive:
        print(f"Uploads:  {archive}")


if __name__ == "__main__":
    main()
