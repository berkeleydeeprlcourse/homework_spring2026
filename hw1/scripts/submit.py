import contextlib
import glob
import os
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

PATTERNS = [
    # globs to include in the submission zip
    # if a directory is matched, all files under it are included
    "src/**/*.py",
    "exp/flow",
    "exp/mse",
    "pyproject.toml",
    "uv.lock",
    "README.md",
]

ROOT = Path(__file__).parent.parent  # path to the root directory

# --------------------
# formatting utilities
# --------------------


@contextlib.contextmanager
def hide_cursor():
    """
    hide the terminal cursor while the context is active
    (for things like progress bars)
    """
    HIDE_CURSOR = "\033[?25l"
    SHOW_CURSOR = "\033[?25h"
    print(HIDE_CURSOR, end="", flush=True)
    try:
        yield
    finally:
        print(SHOW_CURSOR, end="", flush=True)


# ANSI escape codes for colors and styles
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
COLORS = {
    "INFO": "\033[36m",  # cyan
    "WARN": "\033[33m",  # yellow
    "ERR": "\033[31m",  # red
    "OK": "\033[32m",  # green
}


def log(level, *msg, **kwargs):
    """
    log a message with a colored level
    """
    color = COLORS.get(level, "")
    print(f"{color}[{level: ^6}]{RESET}", *msg, **kwargs)


def progress_bar(current, total, width=32):
    """
    generate a progress bar string
    """
    ratio = current / total
    filled = int(width * ratio)
    bar = "█" * filled + "░" * (width - filled)
    percent = int(ratio * 100)
    return f"{bar} {percent:3d}% ({current}/{total})"


def size_for_humans(num):
    """
    convert a number of bytes to a human-readable string
    """
    for unit in ["B", "KB", "MB", "GB"]:
        if num < 1024:
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}TB"


# --------------
# implementation
# --------------


def collect_files(patterns):
    """
    match globs against the file system and collect the paths of all matched
    files.

    if a pattern matches a directory, include the directory recursively.
    """
    files = set()

    log("INFO", "Finding files...")
    missing_patterns = []

    max_l = max(len(p) for p in patterns)

    def pattern_line(pattern, dots, overwrite=False, n=6):
        if overwrite:
            print("\r", end="")
        if dots == -1:
            d = ""
        else:
            idx = dots % n
            d = "".join("█" if idx == i else "░" for i in range(n))
        log("INFO", f"{DIM}>{RESET} {pattern:<{max_l + 3}}{d}", flush=True, end="")

    for pattern in patterns:
        with hide_cursor():
            dots = 0
            pattern_line(pattern, dots)
            matched_files = set()
            for m in glob.iglob(pattern, recursive=True):
                dots += 1
                pattern_line(pattern, dots, overwrite=True)
                p = Path(m)
                if p.is_file():
                    matched_files.add(p.resolve())
                elif p.is_dir():
                    for f in p.rglob("*"):
                        dots += 1
                        pattern_line(pattern, dots, overwrite=True)
                        if f.is_file():
                            matched_files.add(f.resolve())
        pattern_line(pattern, -1, overwrite=True)
        count = len(matched_files)
        print(f"{DIM}{count} file{'s' if count != 1 else ''}{RESET}")
        if not matched_files:
            missing_patterns.append(pattern)
        files.update(matched_files)

    if missing_patterns:
        print()
        log("WARN", "The following patterns did not match any files:")
        for p in missing_patterns:
            log("WARN", f"{DIM}>{RESET} {p}")
        if input("Proceed with missing files? [y/N] ").lower() != "y":
            log("ERR", "Aborted.")
            sys.exit(1)

    log("OK", f"Collected {len(files)} files")
    return files


def create_zip(zip_path, files):
    """
    create a zip archive preserving the directory structure of the source files.

    :param zip_path: output zip file path
    :param files: array of file paths to include
    """
    total_size = sum(f.stat().st_size for f in files)

    log("INFO", f"Creating {BOLD}{zip_path.name}{RESET}")

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zf, hide_cursor():
        for i, file in enumerate(sorted(files), 1):
            rel = file.relative_to(ROOT)
            zf.write(file, rel)
            print("\r", end="")
            log("INFO", progress_bar(i, len(files)), end="", flush=True)
        print()

    log("OK", "Ready to submit!")
    log("OK", f"{BOLD}Size:{RESET}   {size_for_humans(total_size)}")
    log("OK", f"{BOLD}Output:{RESET} {zip_path}")


def main():
    zip_path = ROOT / "submit.zip"

    if zip_path.exists():
        log("WARN", f"{BOLD}{zip_path.name}{RESET} already exists.")
        if input("Overwrite? [y/N] ").lower() != "y":
            log("ERR", "Aborted.")
            sys.exit(1)

    log("INFO", f"Root directory: {ROOT}")

    files = collect_files(PATTERNS)

    if not files:
        log("ERR", "No files collected. Aborting.")
        sys.exit(1)

    create_zip(zip_path, files)


if __name__ == "__main__":
    # weird trick to enable ansi colors on windows
    if os.name == "nt":
        os.system("")

    main()
