"""Consistent SQLite backup. Does not copy credentials or delete the source.
Usage: python scripts/backup_sqlite.py var/riskiq.db PRIVATE_DESTINATION.db
Run against the actual DB file. A Docker named volume is not the host's ./var/.
"""
import argparse
import os
import sqlite3
from pathlib import Path


def backup(source: Path, destination: Path) -> dict:
    source=source.resolve(); destination=destination.resolve()
    if not source.is_file(): raise ValueError("Source database does not exist")
    if source==destination: raise ValueError("Source and destination must differ")
    if not destination.parent.is_dir(): raise ValueError("Create a private destination directory first")
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    os.close(fd)
    try:
        src=sqlite3.connect(source.as_uri()+"?mode=ro",uri=True)
        dst=sqlite3.connect(str(destination))
        try:
            src.backup(dst,pages=100)
            check=dst.execute("PRAGMA integrity_check").fetchone()[0]
            if check!="ok": raise ValueError("Backup integrity check failed")
            tables=dst.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        finally:
            dst.close();src.close()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return {"integrity":"ok","tables":tables,"bytes":destination.stat().st_size}

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('destination',type=Path)
    args=p.parse_args();print(backup(args.source,args.destination))
