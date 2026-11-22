"""Command-line entry point. Placeholder until the M1 pipeline lands."""

from __future__ import annotations

import argparse

from sartor import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sartor",
        description=(
            "Privacy-first résumé tailoring: your evidence in, a tailored "
            "résumé out — every claim traceable, nothing invented."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"sartor {__version__}"
    )
    parser.parse_args(argv)
    print(
        f"sartor {__version__} — pre-release placeholder.\n"
        "M1 (ingest, tailor, verify, render) is in development: "
        "https://github.com/michael-borck/sartor"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
