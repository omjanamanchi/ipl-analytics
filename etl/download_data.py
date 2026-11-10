"""
Download the IPL ball-by-ball JSON from Cricsheet into data/raw/ipl_json/.

    python -m etl.download_data

Cricsheet data is licensed under the Open Data Commons Attribution License (ODC-BY);
see https://cricsheet.org/licensing/ . Credit Cricsheet wherever the data is shown.
If cricsheet.org is unreachable, the same files are mirrored (zip/ipl_json.zip) at
https://github.com/ritesh-ojha/IPL-DATASET .
"""
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

SOURCES = [
    "https://cricsheet.org/downloads/ipl_male_json.zip",
    "https://raw.githubusercontent.com/ritesh-ojha/IPL-DATASET/main/zip/ipl_json.zip",
]
DEST = Path(__file__).resolve().parent.parent / "data" / "raw" / "ipl_json"


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    for url in SOURCES:
        try:
            print(f"Downloading {url}")
            with urllib.request.urlopen(url, timeout=120) as resp:
                blob = resp.read()
            break
        except Exception as exc:  # try the mirror next
            print(f"  failed: {exc}")
    else:
        sys.exit("Could not download IPL data from any source.")

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".json")]
        for n in names:
            (DEST / Path(n).name).write_bytes(zf.read(n))
    print(f"Saved {len(names)} match files to {DEST}")


if __name__ == "__main__":
    main()
