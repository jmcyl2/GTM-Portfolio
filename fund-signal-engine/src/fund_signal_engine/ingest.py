"""Pull SEC Form ADV (fund-level history + current roster) and Form D into DuckDB.

Sources (all public, no key):
  - Form ADV bulk filing data, 2011-11 to 2024-12: Schedule D 7.B.(1) private
    fund rows (fund type, gross assets, audit, administrator Y/N) per filing.
  - Monthly SEC adviser roster: which firms are registered/exempt *today*,
    plus website.
  - Form D quarterly data sets: new private offerings (freshness signal).
"""

import argparse
import zipfile
from pathlib import Path

import duckdb

from . import sec

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "fse.duckdb"

ADV_PAGE = f"{sec.SEC}/foia-services/frequently-requested-documents/form-adv-data"
ROSTER_PAGE = f"{sec.SEC}/data-research/sec-markets-data/information-about-registered-investment-advisers-exempt-reporting-advisers"
FORMD_PAGE = f"{sec.SEC}/data-research/sec-markets-data/form-d-data-sets"

# table name -> member-name prefix inside the ADV bulk zips
ADV_TABLES = {
    "era_base": "ERA_ADV_Base_2011",
    "ia_base": "IA_ADV_Base_A_2011",
    "era_funds": "ERA_Schedule_D_7B1_2011",
    "ia_funds": "IA_Schedule_D_7B1_2011",
    "era_admins": "ERA_Schedule_D_7B1A26_2011",
    "ia_admins": "IA_Schedule_D_7B1A26_2011",
    "era_contacts": "ERA_ADV_1J_1K_2011",
    "ia_contacts": "IA_ADV_1J_1K_2011",
    "era_owners": "ERA_Schedule_A_B_2011",   # Schedule A/B: executive officers and owners, with titles
    "ia_owners": "IA_Schedule_A_B_2011",
}
FORMD_TABLES = ["FORMDSUBMISSION", "ISSUERS", "OFFERING", "RELATEDPERSONS"]


def _csv(path: Path, delim: str = ",") -> str:
    return (f"read_csv('{path}', header=true, all_varchar=true, delim='{delim}', "
            "quote='\"', escape='\"', strict_mode=false, ignore_errors=true, max_line_size=10000000)")


def ingest_adv(con) -> None:
    print("Form ADV bulk filing data")
    urls = sec.links(ADV_PAGE, r"adv-filing-data-2011\d+-\d+.*\.zip$")
    if not urls:
        raise SystemExit("No ADV bulk filing data links found; the SEC page layout may have changed.")
    dest = RAW / "adv"
    for url in urls:
        sec.extract_remote(url, list(ADV_TABLES.values()), dest)
    for table, prefix in ADV_TABLES.items():
        [path] = sorted(dest.glob(f"{prefix}*.csv"))
        con.execute(f"CREATE OR REPLACE TABLE raw_{table} AS SELECT * FROM {_csv(path)}")
        print(f"  raw_{table}: {con.execute(f'SELECT count(*) FROM raw_{table}').fetchone()[0]:,} rows")


def ingest_roster(con) -> None:
    print("Current SEC adviser roster")
    zips = sec.links(ROSTER_PAGE, r"/ia\d+.*\.zip$")
    exempt = next(u for u in zips if "exempt" in Path(u).name)
    # File naming drifts month to month (ia09012026-registered.zip, ia100226.zip),
    # so pair the registered file with the exempt one by its date token.
    month = Path(exempt).name.split("-")[0]
    registered = next(u for u in zips if "exempt" not in Path(u).name and Path(u).name.startswith(month))
    for kind, url in (("exempt", exempt), ("registered", registered)):
        archive = sec.download(url, RAW / "roster" / Path(url).name)
        with zipfile.ZipFile(archive) as z:
            [member] = [n for n in z.namelist() if n.lower().endswith(".csv")]
            out = RAW / "roster" / f"{kind}.csv"
            out.write_text(z.read(member).decode("latin-1"), encoding="utf-8")
        con.execute(f"CREATE OR REPLACE TABLE raw_roster_{kind} AS SELECT *, '{Path(url).name}' AS source_file FROM {_csv(out)}")
        print(f"  raw_roster_{kind}: {con.execute(f'SELECT count(*) FROM raw_roster_{kind}').fetchone()[0]:,} rows ({Path(url).name})")


def ingest_formd(con, quarters: int) -> None:
    print(f"Form D, last {quarters} quarters")
    urls = sec.links(FORMD_PAGE, r"_d\.zip$")[:quarters]
    frames = {t: [] for t in FORMD_TABLES}
    for url in urls:
        archive = sec.download(url, RAW / "formd" / Path(url).name)
        qdir = RAW / "formd" / Path(url).stem
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                table = Path(name).stem
                if table in FORMD_TABLES:
                    out = qdir / f"{table}.tsv"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(z.read(name).decode("latin-1"), encoding="utf-8")
                    frames[table].append(out)
    for table, paths in frames.items():
        union = " UNION ALL BY NAME ".join(f"SELECT * FROM {_csv(p, chr(9))}" for p in paths)
        con.execute(f"CREATE OR REPLACE TABLE raw_formd_{table.lower()} AS {union}")
        print(f"  raw_formd_{table.lower()}: {con.execute(f'SELECT count(*) FROM raw_formd_{table.lower()}').fetchone()[0]:,} rows")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-adv", action="store_true", help="reuse existing ADV tables (the slow part)")
    parser.add_argument("--formd-quarters", type=int, default=4)
    args = parser.parse_args()
    DB.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(DB)) as con:
        if not args.skip_adv:
            ingest_adv(con)
        ingest_roster(con)
        ingest_formd(con, args.formd_quarters)


if __name__ == "__main__":
    main()
