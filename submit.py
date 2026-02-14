#!/usr/bin/env python3

# Copyright (c) 2026 Pranav Nutalapati (@preyneyv)
# SPDX-License-Identifier: MIT

"""
Utility script to create a submission zip file containing all relevant homework
files. No dependencies beyond the Python standard library, and works on all
platforms.

Compatible with Python 3.6+.

This script parses a `.submit` file in the target directory and selectively
includes matching files in the output zip archive.

.submit syntax:
```
# lines starting with # are comments and ignored
# paths are relative to the .submit file
# syntax is glob patterns (https://docs.python.org/3/library/glob.html)
# if a pattern matches a directory, the entire directory is included recursively

src/**/*.py  # all .py files in src and subdirectories
README.md
```

--------------------------------------------------------------------------------

usage: submit.py [directory] [output_path] [--list|--check] [--force]

Create a submission zip file. By default, tries to archive the nearest directory
containing a `.submit` file.

positional arguments:
  directory    The directory to archive (e.g. hw1)
  output_path  output zip file path (default: <directory>/submit.zip)

options:
  -h, --help   show this help message and exit
  --force, -f  overwrite without confirmation
  --list, -l   list matching files
  --check, -c  check for missing files
"""

import argparse
import contextlib
import glob
import logging
import os
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).parent  # path to the repo root
STREAM = sys.stderr
INTERACTIVE = STREAM.isatty()
MAX_ARCHIVE_SIZE = 100 * 1024 * 1024  # 100 MB

# --------------------
# logging + formatting
# --------------------

# ANSI escape codes for colors and styles
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

LEVEL_STYLES = {
    logging.DEBUG: "\033[2m",  # dim
    logging.INFO: "\033[36m",  # cyan
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[31m",  # red
}

if not INTERACTIVE:
    # disable colors if not in an interactive terminal
    RESET = ""
    BOLD = ""
    DIM = ""
    for k in LEVEL_STYLES:
        LEVEL_STYLES[k] = ""

LEVEL_TAGS = {
    logging.DEBUG: "DBG",
    logging.INFO: "INFO",
    logging.WARNING: "WARN",
    logging.ERROR: "ERR",
    logging.CRITICAL: "CRIT",
}


def _enable_windows_ansi():
    # weird trick to enable ANSI codes in Windows terminals.
    if os.name == "nt":
        os.system("")


def format_line(level: int, text: str) -> str:
    """
    Format a log line with a colored level tag.
    Sample:
    [ INFO ] This is a test message
    [ WARN ] This is a warning
    [ ERR  ] This is an error
    """

    tag = LEVEL_TAGS.get(level, "INFO")
    color = LEVEL_STYLES.get(level, "")

    return f"{color}[{tag:^6}]{RESET} {text}"


class ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return format_line(record.levelno, record.getMessage())


def setup_logger() -> logging.Logger:
    """
    Setup a logger using `ColorFormatter` that logs to stderr.
    (leaving stdout clean for pipeable output)
    """
    logger = logging.getLogger("submit")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.handlers.clear()

    stream = sys.stderr
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    handler.setFormatter(ColorFormatter())
    logger.addHandler(handler)
    return logger


logger = setup_logger()


@contextlib.contextmanager
def hide_cursor():
    """
    Hide the terminal cursor while performing an operation
    (useful for progress bars).
    """
    if not INTERACTIVE:
        yield
        return

    HIDE_CURSOR = "\033[?25l"
    SHOW_CURSOR = "\033[?25h"
    STREAM.write(HIDE_CURSOR)
    STREAM.flush()
    try:
        yield
    finally:
        STREAM.write(SHOW_CURSOR)
        STREAM.flush()


def progress_bar(current, total, width=32):
    total = max(total, 1)
    ratio = current / total
    filled = int(width * ratio)
    bar = "█" * filled + "░" * (width - filled)
    percent = int(ratio * 100)
    return f"{bar} {percent:3d}% ({current}/{total})"


def size_for_humans(num):
    for unit in ["B", "KB", "MB"]:
        if num < 1024:
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}GB"


def _input(prompt):
    """
    Prompt the user for input if in interactive mode, otherwise log a warning
    and return an empty string.
    """
    if INTERACTIVE:
        STREAM.write(prompt)
        STREAM.flush()
        return input()
    else:
        logger.warning(prompt + " [input skipped in non-interactive mode]")
        return ""


def _inline_print(level, text: str):
    if not INTERACTIVE:
        return
    STREAM.write("\r" + format_line(level, text))
    STREAM.flush()


def _inline_clear():
    if not INTERACTIVE:
        return
    # clear the line
    STREAM.write("\r\033[K")
    STREAM.flush()


# --------------
# implementation
# --------------


def find_submit_spec(current_dir: Path):
    """
    Walk up the directory tree from the current directory to find the nearest
    .submit file.
    """
    for d in [current_dir] + list(current_dir.parents):
        submit_spec = d / ".submit"
        if submit_spec.exists():
            return d
    return None


def parse_submit_spec(hw_dir: Path):
    """
    Parse the .submit file in the given homework directory to get the list of
    file patterns to include in the submission.
    """
    submit_spec = hw_dir / ".submit"
    if not submit_spec.exists():
        logger.error(f"No .submit file found in {BOLD}{hw_dir}{RESET}.")
        sys.exit(1)
    patterns = []

    with submit_spec.open() as f:
        for line in f:
            line = line.strip()
            first_hash = line.find("#")
            if first_hash != -1:
                line = line[:first_hash].strip()  # remove comments
            if line:
                patterns.append(line)
    return patterns


def collect_files(base: Path, patterns):
    """
    Match globs against the file system and collect the paths of all matched
    files. If a pattern matches a directory, include the directory recursively.

    :param base: the base directory to resolve patterns against
    :param patterns: list of glob patterns to match (relative to base)
    """
    files = set()
    logger.info("Finding files...")

    max_l = max((len(p) for p in patterns), default=0)

    def pattern_line(pattern, dots, n=6):
        if dots < 0:
            d = ""
        else:
            idx = dots % n
            d = "".join("█" if idx == i else "░" for i in range(n))
        return f"{DIM}>{RESET} {pattern:<{max_l + 3}}{d}"

    missing_patterns = []

    for pattern in patterns:
        matched_files = set()
        dots = 0

        with hide_cursor():
            _inline_print(logging.INFO, pattern_line(pattern, dots))

            for m in glob.iglob(str(base / pattern), recursive=True):
                dots += 1
                _inline_print(logging.INFO, pattern_line(pattern, dots))

                p = Path(m)
                if p.is_file():
                    matched_files.add(p.resolve())
                elif p.is_dir():
                    for f in p.rglob("*"):
                        if f.is_file():
                            dots += 1
                            _inline_print(logging.INFO, pattern_line(pattern, dots))
                            matched_files.add(f.resolve())

        _inline_clear()
        count = len(matched_files)
        logger.info(
            f"{pattern_line(pattern, -1)}{DIM}{count} file{'s' if count != 1 else ''}{RESET}"
        )

        if not matched_files:
            missing_patterns.append(pattern)
        files.update(matched_files)

    logger.info(f"Collected {len(files)} files")

    if missing_patterns:
        logger.warning("The following patterns did not match any files:")
        for p in missing_patterns:
            logger.warning(f"{DIM}>{RESET} {p}")

    return files, bool(missing_patterns)


def create_zip(zip_path: Path, base, files):
    """
    Create a zip archive preserving the directory structure of the source files.
    """
    logger.info(f"Creating {BOLD}{zip_path.name}{RESET}...")

    total = len(files)

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zf, hide_cursor():
        for i, file in enumerate(sorted(files), 1):
            rel = file.relative_to(base)
            zf.write(file, rel)
            _inline_print(logging.INFO, progress_bar(i, total))
        _inline_clear()

    logger.info(f"Created {BOLD}{zip_path.name}{RESET} successfully.")
    total_size = zip_path.stat().st_size
    if total_size > MAX_ARCHIVE_SIZE:
        logger.warning(
            f"Archive size {size_for_humans(total_size)} exceeds the limit of {size_for_humans(MAX_ARCHIVE_SIZE)}."
        )
    logger.info(f"{BOLD}Size:{RESET}   {size_for_humans(total_size)}")
    logger.info(f"{BOLD}Output:{RESET} {zip_path}")


def main():
    _enable_windows_ansi()

    parser = argparse.ArgumentParser(
        description=(
            "Create a submission zip file. By default, tries to archive the "
            "nearest directory containing a `.submit` file."
        ),
        usage="uv run submit.py [directory] [output_path] [--list|--check] [--force]",
    )
    parser.add_argument(
        "directory", nargs="?", help="The directory to archive (e.g. hw1)"
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        help="output zip file path (default: <directory>/submit.zip)",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="overwrite without confirmation",
    )
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="list matching files",
    )
    action_group.add_argument(
        "--check",
        "-c",
        action="store_true",
        help="check for missing files",
    )

    args = parser.parse_args()

    if args.list:
        action = "list"
    elif args.check:
        action = "check"
    else:
        action = "archive"

    if args.directory:
        # use the explicitly provided directory
        base = Path(args.directory).resolve()
    else:
        # find the nearest .submit file in the current directory or its parents
        base = find_submit_spec(Path.cwd())
        if base is None:
            logger.error("No `.submit` file found in any parent directories.")
            parser.print_help()
            sys.exit(1)

    if not base.exists():
        logger.error(f"Directory {BOLD}{base}{RESET} does not exist.")
        sys.exit(1)
    if not base.is_dir():
        logger.error(f"{BOLD}{base}{RESET} is not a directory.")
        sys.exit(1)

    logger.info(f"Archiving {BOLD}{base}{RESET}")
    zip_path = Path(args.output_path) if args.output_path else base / "submit.zip"
    zip_path = zip_path.resolve()

    patterns = parse_submit_spec(base)

    if action == "archive":
        if zip_path.exists():
            logger.warning(f"{BOLD}{zip_path.name}{RESET} already exists.")
            if not args.force and _input("Overwrite? [y/N] ").lower() != "y":
                logger.error("Aborted.")
                sys.exit(1)

    files, has_missing = collect_files(base, patterns)
    if not files:
        logger.error("No files collected. Aborting.")
        sys.exit(1)

    if action == "archive":
        if (
            not args.force
            and has_missing
            and _input("Proceed with missing files? [Y/n] ").lower() == "n"
        ):
            logger.error("Aborted.")
            sys.exit(1)

        create_zip(zip_path, base, files)
    elif action == "list":
        for f in sorted(files):
            try:
                print(f.relative_to(base))
            except ValueError:
                print(f)
    elif action == "check":
        if has_missing:
            logger.error("Some patterns did not match any files.")
            sys.exit(1)
        logger.info("All patterns matched at least one file.")


if __name__ == "__main__":
    main()
