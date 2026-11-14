"""Move files from an input tree into OUTPUT/YYYY/MM, dated by modification time.

Used two ways:
  * imported by service.py, which runs it on a timer and adds the dashboard
  * standalone:  python filesOrganizer.py <input_directory> <output_parent_directory>
"""
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

log = logging.getLogger("organizer")


@dataclass
class Rules:
    # Skip anything whose path contains '@' (Synology @eaDir thumbnails, @SynoResource, ...).
    skip_at: bool = True
    # Skip dot-files and dot-folders. Sync apps upload into hidden temp files such as
    # ".IMG_0980.MP4" and rename them when done; moving one mid-upload strands a partial copy.
    skip_hidden: bool = True
    # Leave files that changed this recently alone: they may still be uploading.
    min_age_seconds: int = 120


@dataclass
class Moved:
    src: Path
    dest: Path
    size: int


@dataclass
class RunResult:
    moved: List[Moved] = field(default_factory=list)
    skipped: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def bytes_moved(self) -> int:
        return sum(m.size for m in self.moved)


def skip_reason(rel: Path, st: os.stat_result, rules: Rules, now: float) -> Optional[str]:
    if rules.skip_at and any("@" in part for part in rel.parts):
        return "contains '@'"
    if rules.skip_hidden and any(part.startswith(".") for part in rel.parts):
        return "hidden"
    # st_ctime moves on every write/rename/utime, so it catches uploads whose mtime is
    # set back to the original capture date.
    last_change = max(st.st_mtime, st.st_ctime)
    if now - last_change < rules.min_age_seconds:
        return "changed too recently"
    return None


def unique_dest(dest: Path) -> Path:
    """Never overwrite: IMG_1234.HEIC (1).HEIC style suffix when the name is taken."""
    if not dest.exists():
        return dest
    n = 1
    while True:
        candidate = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def organize_files_by_date(
    input_path,
    output_parent_path,
    rules: Optional[Rules] = None,
    on_moved: Optional[Callable[[Moved], None]] = None,
) -> RunResult:
    rules = rules or Rules()
    input_path = Path(input_path)
    output_parent_path = Path(output_parent_path)
    result = RunResult()

    if not input_path.exists():
        msg = f"Input path {input_path} does not exist."
        log.error(msg)
        result.errors.append(msg)
        return result
    if not output_parent_path.exists():
        msg = f"Output parent path {output_parent_path} does not exist."
        log.error(msg)
        result.errors.append(msg)
        return result

    now = time.time()
    for file in sorted(input_path.rglob("*")):
        try:
            if not file.is_file():
                continue
            st = file.stat()
            reason = skip_reason(file.relative_to(input_path), st, rules, now)
            if reason:
                log.debug("Skipping %s (%s)", file, reason)
                result.skipped += 1
                continue

            modified_time = datetime.fromtimestamp(st.st_mtime)
            dest_dir = output_parent_path / modified_time.strftime("%Y") / modified_time.strftime("%m")
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = unique_dest(dest_dir / file.name)
            shutil.move(str(file), str(dest_file))
            moved = Moved(src=file, dest=dest_file, size=st.st_size)
            result.moved.append(moved)
            log.info("Moved %s to %s", file, dest_file)
            if on_moved:
                on_moved(moved)
        except Exception as e:  # one bad file must not stop the run
            msg = f"Failed on {file}: {e}"
            log.error(msg)
            result.errors.append(msg)
    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("organizer.log")],
    )
    if len(sys.argv) != 3:
        log.error("Usage: python filesOrganizer.py <input_directory> <output_parent_directory>")
        sys.exit(1)

    while True:
        organize_files_by_date(sys.argv[1], sys.argv[2])
        log.info("Waiting for 1 minute...")
        time.sleep(60)
