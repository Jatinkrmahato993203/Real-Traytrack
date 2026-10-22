"""
backups.py — database + photo snapshots, checking that each one is usable,
and restoring them.

Used by scripts/backup.py and scripts/restore.py (by hand / cron) and by the
nightly `backup` job in jobs.py (BACKUPS_ENABLED=1, e.g. in Docker).
"""

import os
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

import config

ESSENTIAL_TABLES = ("schema_migrations", "colleges", "mess_halls", "complaints", "alerts", "staff_users",
                    "inspections", "activity_log")


def backup_dir():
    return Path(os.environ.get("BACKUP_DIR", str(config.BASE_DIR / "backups")))


def _tool(*names):
    """MYSQLDUMP / MYSQL env vars point at the tools when they're not on PATH."""
    for env in ("MYSQLDUMP" if "mysqldump" in names else "MYSQL",):
        if os.environ.get(env):
            return os.environ[env]
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError(f"{names[0]} not found — install the MySQL/MariaDB client tools.")


def _db_args():
    return ["-h", config.DB_HOST, "-P", str(config.DB_PORT), "-u", config.DB_USER]


def _env():
    return {**os.environ, "MYSQL_PWD": config.DB_PASSWORD}  # keeps the password off the command line


def verify_dump(path):
    """Raises if a dump is truncated or missing essential tables."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 1024:
        raise RuntimeError(f"Backup {path.name} is missing or empty")
    with open(path, "rb") as f:
        f.seek(max(0, path.stat().st_size - 4096))
        tail = f.read().decode("utf-8", "replace")
    if "Dump completed" not in tail:
        raise RuntimeError(f"Backup {path.name} is truncated (no 'Dump completed' marker)")
    text = path.read_text("utf-8", "replace")
    missing = [t for t in ESSENTIAL_TABLES if f"CREATE TABLE `{t}`" not in text]
    if missing:
        raise RuntimeError(f"Backup {path.name} is missing tables: {', '.join(missing)}")
    return True


def run_backup(keep=30, out_dir=None):
    """Writes traytrack-<time>.sql (+ -uploads.zip), verifies it, keeps the
    newest `keep`. Returns (sql_path, zip_path or None)."""
    out = Path(out_dir) if out_dir else backup_dir()
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    sql_path = out / f"traytrack-{stamp}.sql"
    with open(sql_path, "wb") as f:
        result = subprocess.run(
            [_tool("mysqldump", "mariadb-dump"), *_db_args(), "--single-transaction", "--routines",
             "--default-character-set=utf8mb4", "--no-tablespaces", config.DB_NAME],
            stdout=f, stderr=subprocess.PIPE, env=_env(),
        )
    if result.returncode != 0:
        sql_path.unlink(missing_ok=True)
        raise RuntimeError(f"mysqldump failed: {result.stderr.decode(errors='replace').strip()}")
    verify_dump(sql_path)

    zip_path = None
    uploads = Path(config.UPLOAD_ROOT)
    if uploads.exists() and any(uploads.rglob("*")):
        zip_path = Path(shutil.make_archive(str(out / f"traytrack-{stamp}-uploads"), "zip", uploads))

    for old in sorted(out.glob("traytrack-*.sql"), reverse=True)[keep:]:
        old.unlink(missing_ok=True)
        Path(str(old).replace(".sql", "-uploads.zip")).unlink(missing_ok=True)
    return sql_path, zip_path


def latest_backup(out_dir=None):
    found = sorted((Path(out_dir) if out_dir else backup_dir()).glob("traytrack-*.sql"), reverse=True)
    return found[0] if found else None


def restore(sql_path, uploads_zip=None, force=False):
    """Loads a backup into DB_NAME (and photos into UPLOAD_DIR). Refuses to
    overwrite a database that already has tables unless force=True."""
    import pymysql
    verify_dump(sql_path)
    conn = pymysql.connect(host=config.DB_HOST, port=config.DB_PORT, user=config.DB_USER,
                           password=config.DB_PASSWORD, database=config.DB_NAME)
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES")
        tables = [r[0] for r in cur.fetchall()]
        if tables and not force:
            conn.close()
            raise RuntimeError(f"{config.DB_NAME} already has {len(tables)} tables — use --force to replace them.")
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        for t in tables:
            cur.execute(f"DROP TABLE `{t}`")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    conn.commit()
    conn.close()
    with open(sql_path, "rb") as f:
        result = subprocess.run([_tool("mysql", "mariadb"), *_db_args(), config.DB_NAME],
                                stdin=f, stderr=subprocess.PIPE, env=_env())
    if result.returncode != 0:
        raise RuntimeError(f"Restore failed: {result.stderr.decode(errors='replace').strip()}")
    if uploads_zip:
        target = Path(config.UPLOAD_ROOT)
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(uploads_zip) as z:
            for name in z.namelist():                     # refuse path tricks in the archive
                if name.startswith("/") or ".." in Path(name).parts:
                    raise RuntimeError(f"Unsafe path in uploads archive: {name}")
            z.extractall(target)
    return True
