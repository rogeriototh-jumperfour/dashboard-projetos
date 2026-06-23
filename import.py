#!/usr/bin/env python3
"""
Import projects Excel → PostgreSQL (replace-only).
Usage:
    python import.py                          # Scan data/ and import newest .xlsx
    python import.py --file path/to/file.xlsx # Import specific file
"""

import os, sys, glob, json, re
from datetime import datetime
import openpyxl
import psycopg2
from psycopg2.extras import execute_values

# ─── Config ───────────────────────────────────────────────────
DATA_DIR = os.path.expanduser("~/dashboard/data")
DATABASE_URL = "postgresql://postgres@localhost:5432/dashboard_projetos"

# ─── Helpers ──────────────────────────────────────────────────

def parse_tags(tags_raw):
    """Parse 'Plano: Atraso,Prazo: Atrasado,Sist: BMS' into [{cat,val},...]"""
    if not tags_raw or not isinstance(tags_raw, str):
        return []
    parts = [t.strip() for t in tags_raw.split(",") if t.strip()]
    result = []
    for p in parts:
        m = re.match(r'^([^:]+):\s*(.+)$', p)
        if m:
            result.append({"cat": m.group(1).strip(), "val": m.group(2).strip()})
        else:
            result.append({"cat": "Outro", "val": p})
    return result


def do_import(conn, path):
    """Replace all data with contents of a single .xlsx file."""
    basename = os.path.basename(path)

    cur = conn.cursor()

    # Read Excel
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    if len(rows) < 2:
        print(f"  ⚠ Empty file: {basename}")
        cur.close()
        return None

    header = [str(c) if c else "" for c in rows[0]]
    data_rows = rows[1:]

    # Map columns
    col_map = {}
    expected = ["id", "active", "name", "user_id", "stage_id",
                "date_start", "date", "last_update_status", "tag_ids"]
    for col_name in expected:
        try:
            col_map[col_name] = header.index(col_name)
        except ValueError:
            print(f"  ✗ Column '{col_name}' not found in {basename}")
            cur.close()
            return None

    # Prepare project rows
    projetos = []
    for row in data_rows:
        external_id = str(row[col_map["id"]]) if row[col_map["id"]] else None
        active = bool(row[col_map["active"]]) if row[col_map["active"]] is not None else True
        nome = str(row[col_map["name"]]) if row[col_map["name"]] else None
        responsavel = str(row[col_map["user_id"]]) if row[col_map["user_id"]] else None
        estagio = str(row[col_map["stage_id"]]) if row[col_map["stage_id"]] else None

        ds = row[col_map["date_start"]]
        data_inicio = ds.isoformat() if hasattr(ds, "isoformat") else ds

        df = row[col_map["date"]]
        data_fim = df.isoformat() if hasattr(df, "isoformat") else df

        status = str(row[col_map["last_update_status"]]) if row[col_map["last_update_status"]] else None
        tags_raw = str(row[col_map["tag_ids"]]) if row[col_map["tag_ids"]] else ""
        tags_jsonb = json.dumps(parse_tags(tags_raw), ensure_ascii=False)

        projetos.append((external_id, active, nome, responsavel,
                         estagio, data_inicio, data_fim, status, tags_raw, tags_jsonb))

    if not projetos:
        print(f"  ⚠ No data rows in {basename}")
        cur.close()
        return None

    # ── UPSERT: update existing + insert new (keep unmatched) ──
    upsert_sql = """
        INSERT INTO dash_projetos
            (external_id, active, nome, responsavel,
             estagio, data_inicio, data_fim, status_atualizacao, tags_raw, tags_jsonb)
        VALUES %s
        ON CONFLICT (external_id) DO UPDATE SET
            active = EXCLUDED.active,
            nome = EXCLUDED.nome,
            responsavel = EXCLUDED.responsavel,
            estagio = EXCLUDED.estagio,
            data_inicio = EXCLUDED.data_inicio,
            data_fim = EXCLUDED.data_fim,
            status_atualizacao = EXCLUDED.status_atualizacao,
            tags_raw = EXCLUDED.tags_raw,
            tags_jsonb = EXCLUDED.tags_jsonb
    """

    # Count before
    cur.execute("SELECT COUNT(*) FROM dash_projetos")
    count_before = cur.fetchone()[0]

    execute_values(cur, upsert_sql, projetos)

    # Count after
    cur.execute("SELECT COUNT(*) FROM dash_projetos")
    count_after = cur.fetchone()[0]

    inserted = count_after - count_before
    updated = len(projetos) - inserted

    # File metadata
    fstat = os.stat(path)
    file_mtime = datetime.fromtimestamp(fstat.st_mtime)
    file_size = fstat.st_size

    cur.execute(
        """INSERT INTO dash_extracoes
            (filename, file_mtime, file_size, row_count, updated_count, inserted_count)
            VALUES (%s, %s, %s, %s, %s, %s)""",
        (basename, file_mtime, file_size, len(projetos), updated, inserted)
    )

    conn.commit()
    cur.close()
    print(f"  ✓ Imported: {basename} ({len(projetos)} rows: {updated} updated, {inserted} inserted)")
    return (basename, len(projetos))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Import .xlsx → dashboard_projetos (replace)")
    parser.add_argument("--file", "-f", help="Import specific file")
    parser.add_argument("--list", action="store_true", help="List files in data dir")
    args = parser.parse_args()

    conn = psycopg2.connect(DATABASE_URL)

    if args.list:
        files = sorted(glob.glob(os.path.join(DATA_DIR, "*.xlsx")))
        if not files:
            print("No .xlsx files found in ~/dashboard/data/")
        else:
            print(f"Files in {DATA_DIR}:")
            for f in files:
                size = os.path.getsize(f)
                mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%d/%m/%Y %H:%M")
                print(f"  {os.path.basename(f)} ({size:,} bytes, {mtime})")
        conn.close()
        return

    if args.file:
        path = args.file
        if not os.path.exists(path):
            print(f"File not found: {path}")
            sys.exit(1)
        do_import(conn, path)
    else:
        files = sorted(glob.glob(os.path.join(DATA_DIR, "*.xlsx")))
        if not files:
            print(f"No .xlsx files found. Copy your file to: {DATA_DIR}")
        else:
            # Import the newest file
            newest = max(files, key=os.path.getmtime)
            print(f"Newest file: {os.path.basename(newest)}")
            do_import(conn, newest)

    conn.close()


if __name__ == "__main__":
    main()
