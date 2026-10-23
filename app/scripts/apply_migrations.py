# -*- coding: utf-8 -*-
"""
Apply migrations/*.sql in filename order.

Run at mcp container boot, before uvicorn starts. Every migration is written to be
idempotent (CREATE ... IF NOT EXISTS), so running this on every boot is safe and an
existing pgdata volume picks up new DDL without being recreated. Each file runs in
its own transaction.
"""

import os
import sys
import glob
import re
import time
import configparser

import psycopg2

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

config = configparser.ConfigParser()
with open(os.path.join(BASE_DIR, "config", "app.ini")) as fh:
    config.read_file(fh)


def connect(attempts=30):
    for i in range(attempts):
        try:
            return psycopg2.connect(
                host=config.get("database", "host"),
                port=config.get("database", "port"),
                dbname=config.get("database", "name"),
                user=config.get("database", "user"),
                password=config.get("database", "password"),
            )
        except psycopg2.OperationalError as e:
            if i == attempts - 1:
                raise
            print("waiting for database: %s" % str(e).strip().splitlines()[0], flush=True)
            time.sleep(2)


def main():
    files = sorted(glob.glob(os.path.join(BASE_DIR, "migrations", "*.sql")))
    conn = connect()
    try:
        for path in files:
            with open(path, encoding="utf-8") as fh:
                sql = fh.read()
            with conn:                       # one transaction per file
                with conn.cursor() as cur:
                    cur.execute(sql)
            # CREATE ... IF NOT EXISTS notices only (ADD COLUMN IF NOT EXISTS says "column ...")
            present = sum(1 for n in conn.notices if "already exists" in n
                          and not n.split(":", 1)[-1].strip().startswith("column"))
            print("applied %s: %d created, %d already present" % (
                os.path.basename(path), _count_creates(sql) - present, present), flush=True)
            del conn.notices[:]
    finally:
        conn.close()
    return 0


def _count_creates(sql):
    return len(re.findall(r"^\s*CREATE\s", sql, re.I | re.M))


if __name__ == "__main__":
    sys.exit(main())
