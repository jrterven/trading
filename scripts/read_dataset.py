#!/usr/bin/env python3
"""Inspect or export either public dataset. Requires only the duckdb package."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="Path to a downloaded .duckdb file.")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="Print table counts and column types.")
    inspect.add_argument(
        "--coverage", action="store_true", help="Also scan bars for coverage by symbol/timeframe."
    )

    export = commands.add_parser("export", help="Export a table or SELECT query to CSV or Parquet.")
    source = export.add_mutually_exclusive_group(required=True)
    source.add_argument("--table", help="Export every column and row of this table.")
    source.add_argument("--sql", help="One SELECT query, quoted for your shell.")
    export.add_argument("--output", required=True, type=Path, help="New .csv or .parquet file.")
    return parser.parse_args()


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def inspect_database(con, coverage: bool) -> None:
    tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
    for table in tables:
        identifier = quote_identifier(table)
        count = con.execute(f"SELECT COUNT(*) FROM {identifier}").fetchone()[0]
        print(f"\n{table}: {count:,} rows")
        for name, data_type, *_ in con.execute(f"DESCRIBE {identifier}").fetchall():
            print(f"  {name}: {data_type}")

    if coverage and "bars" in tables:
        print("\nBar coverage (UTC; first/last timestamps do not imply continuous coverage):")
        print("symbol\ttimeframe\trows\tfirst_timestamp\tlast_timestamp")
        for row in con.execute(
            """
            SELECT symbol, timeframe, COUNT(*), MIN(timestamp), MAX(timestamp)
            FROM bars
            GROUP BY symbol, timeframe
            ORDER BY symbol, timeframe
            """
        ).fetchall():
            print("\t".join(str(value) for value in row))


def export_data(con, args: argparse.Namespace) -> None:
    output = args.output.expanduser().resolve()
    if output == args.db.expanduser().resolve():
        raise ValueError("Output must be different from the input database.")
    if output.exists():
        raise ValueError(f"Output already exists: {output}. Choose a new path.")
    formats = {".csv": "FORMAT CSV, HEADER TRUE", ".parquet": "FORMAT PARQUET, COMPRESSION ZSTD"}
    options = formats.get(output.suffix.lower())
    if options is None:
        raise ValueError("Output must end in .csv or .parquet.")

    if args.table:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if args.table not in tables:
            raise ValueError(f"Unknown table {args.table!r}. Run inspect to list tables.")
        query = f"SELECT * FROM {quote_identifier(args.table)}"
    else:
        statements = con.extract_statements(args.sql)
        if len(statements) != 1 or statements[0].type.name != "SELECT":
            raise ValueError("--sql must contain exactly one SELECT query.")
        # Use the parsed statement so a trailing semicolon is outside the COPY subquery.
        query = statements[0].query.rstrip().removesuffix(";")

    output.parent.mkdir(parents=True, exist_ok=True)
    # COPY writes directly from DuckDB, without loading the full result into Python memory.
    # Newlines also allow a SELECT query ending in a SQL line comment.
    count = con.execute(f"COPY (\n{query}\n) TO ? ({options})", [str(output)]).fetchone()[0]
    print(f"Exported {count:,} rows to {output}")


def main() -> None:
    args = parse_args()
    try:
        import duckdb
    except ImportError as exc:
        raise SystemExit("Install DuckDB first: python -m pip install duckdb==1.5.4") from exc

    database = args.db.expanduser().resolve()
    if not database.is_file():
        raise SystemExit(f"Database not found: {database}")

    try:
        # Connect directly: no backend imports, migrations, API keys, or application setup.
        with duckdb.connect(str(database), read_only=True) as con:
            if args.command == "inspect":
                inspect_database(con, args.coverage)
            else:
                export_data(con, args)
    except (duckdb.Error, OSError, ValueError) as exc:
        raise SystemExit(f"Error: {exc}") from exc


if __name__ == "__main__":
    main()
