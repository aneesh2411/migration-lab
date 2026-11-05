"""CLI: python run_migration.py CLIENT LIB_OLD LIB_NEW GUIDE"""
import json
import sys
from pathlib import Path

from migrator.agent import migrate

if __name__ == "__main__":
    report = migrate(*(Path(a) for a in sys.argv[1:5]))
    print(json.dumps(report, indent=2, default=str))
