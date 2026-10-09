#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# ///
"""memlog — an append-only memory log: LLM-optimal working memory for a skill.

A memlog is the dense, chronological record of everything that mattered in a piece of
work — every item the user generated or accepted — kept minimal like human memory: only
what's important, never bloated. It persists ACROSS sessions, so a fresh session can
load it and continue. It is NOT a deliverable; downstream artifacts (a brief, a PRD, a
deck, a report) are *derived* from it on demand. The host skill supplies the vocabulary
by how it calls `append` — the tool stays neutral.

It is a FLAT log: there are no sections or grouping. Every entry is one line, recorded
at the END in the order it happened. The chronology itself is the structure — an event
like "started technique X" is just another entry, same as an idea or an insight.

Three invariants make it trustworthy:

  1. Append-only, chronological. Entries land at the end, in the order they happen.
     Nothing is ever inserted backward, reordered, edited, or removed. There is no
     edit or delete subcommand by design; history is never rewritten.
  2. Write-only / blind. Every command is an atomic, context-free write and echoes the
     new state as one line of JSON, so the caller never re-reads the file mid-session.
     The one time the file is read is on resume — and the caller reads it itself, not
     via this script.
  3. No lifecycle status. A memory log has no "complete" flag. Whether the work is done,
     blocked, or paused is itself a fact that happened, so it is recorded as an entry
     (e.g. `append --type event --text "session complete"`), never as frontmatter the
     log would have to mutate. The chronology stays the single source of truth, and a
     resume learns the state by reading the last entries — the same way it learns
     everything else.

Atomicity: every write goes to a temp file, is flushed and fsync'd, then atomically
renamed over the target (and the directory fsync'd), so a crash never leaves a
half-written entry.

Concurrency (one writer at a time): every command holds an exclusive `fcntl.flock`
on a lock file for its whole read-modify-write, so two agents appending to one memlog
at the same moment can neither cut a line nor lose one. The lock file never sits in
the work tree, so it can never be staged into a shared git index: for a memlog inside
a git work tree it is `<git dir>/bmad-memlog-locks/<name>.lock`, keyed by the memlog's
path inside the work tree (the same lock for every process that sees the clone, whatever
its environment or mount point); outside git, or when the git dir is not writable, it is
`<temp dir>/bmad-memlog-locks/<name>.lock`, keyed by the memlog's absolute path (the temp
dir is `tempfile.gettempdir()`, i.e. $TMPDIR else /tmp, so two fallback writers with a
different TMPDIR do not exclude each other - the known split; the git-dir lock has none).
A dangling `.git` file (its gitdir gone) counts as no git. A writer
waits up to 10 s for the lock, then refuses with exit code 75 and a JSON line
`{"ok": false, "error": "locked", ..., "entry": "<the line>"}` - nothing was written, and
the caller re-runs the same command. Platforms without `fcntl` (Windows) write unlocked.

Committing (F-MEMLOG-NOCOMMIT): no command commits, stages or pushes anything. A memlog
kept in git is the caller's to `git add` + commit + push after each entry.

The file shape (.memlog.md):

    ---
    topic: Onboarding flow for a budgeting app
    goal: lift week-1 retention
    updated: 2026-06-07T14:22
    ---

    - (note) user picked techniques: SCAMPER, then Six Thinking Hats
    - (technique) started SCAMPER
    - (idea) skip the signup wall: let people try with sample data first
    - (idea) auto-import one bank account so the first screen shows real numbers
    - (question) is open-banking consent too heavy for step one?
    - (insight) the "scary numbers" risk and the "real numbers" idea are one lever: show real data, pre-categorized
    - (direction) optimize for the anxious first-timer, not the power user
    - (decision) lead with one pre-categorized account; defer multi-account import
    - (event) session complete

Each entry may carry an optional `--type` — what KIND it is (idea, insight, question,
decision, direction, assumption, gap, note, event, …) — and an optional `--by` naming
who it came from (e.g. `user`, `coach`), for sessions where authorship matters. Both
render into one short inline tag: `(idea)`, `(idea by user)`, `(by coach)`. Omit them
for a plain note. The host skill names the vocabulary; the script does not enforce one.

Commands:
  init   (--workspace DIR | --path FILE) [--field k=v ...]    create the memlog (errors if it exists)
  append (--workspace DIR | --path FILE) --text STR [--type T] [--by W]  append one entry at the end
  set    (--workspace DIR | --path FILE) --key K --value V    set/replace a descriptive frontmatter field

Addressing: `--workspace` is the run folder, and the memlog is always {workspace}/.memlog.md.
`--path` points straight at the memlog file instead, for callers that already hold the path.
"""
from __future__ import annotations  # keep type-hint syntax lazy so the script runs on 3.8+

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: no flock, so writes there stay unserialized
    fcntl = None  # type: ignore[assignment]

MEMLOG = ".memlog.md"
LOCK_DIR = "bmad-memlog-locks"
LOCK_WAIT_S = 10.0  # bounded wait for another writer, then refuse (EXIT_LOCKED)
LOCK_POLL_S = 0.02
EXIT_LOCKED = 75  # EX_TEMPFAIL: busy, nothing written, re-run the same command


def now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def resolve(args) -> Path:
    """The memlog file, from either addressing mode: {workspace}/.memlog.md or an explicit --path."""
    return Path(args.path) if args.path else Path(args.workspace) / MEMLOG


def split(text: str) -> tuple[dict, str]:
    """Return (frontmatter dict in source order, body str). Frontmatter is plain key: value.

    The closing fence is the first line that is *exactly* `---`, so a `---` inside a
    field value (topic/goal are free user text) never truncates the frontmatter.
    """
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(".memlog.md has no frontmatter")
    end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if end is None:
        raise ValueError(".memlog.md frontmatter is not terminated")
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, "\n".join(lines[end + 1:]).lstrip("\n")


def render(meta: dict, body: str) -> str:
    # Neutralize newlines in values so a multi-line field can't break the fence on re-read.
    fm = "\n".join(f"{k}: {' '.join(str(v).splitlines())}" for k, v in meta.items())
    return "---\n" + fm + "\n---\n\n" + body.rstrip("\n") + "\n"


def touch(meta: dict) -> None:
    """Stamp `updated` and keep it last so the field order stays predictable."""
    meta.pop("updated", None)
    meta["updated"] = now()


def write_atomic(path: Path, text: str) -> None:
    """Temp + flush + fsync + atomic rename, so a crash never half-writes an entry.

    Callers hold `locked(path)`, so the fixed temp name is never shared by two writers.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fsync_dir(path.parent)


def fsync_dir(directory: Path) -> None:
    """Make the rename itself durable; a no-op where a directory cannot be opened."""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def git_dir(top: Path) -> Path | None:
    """The git dir of a work tree top: `.git` itself, or where a linked worktree's `.git` file points.

    A `.git` file naming a gitdir that does not exist (a pruned or moved worktree) counts as
    no git at all: the lock must never `mkdir -p` a stray tree where that dangling path points.
    """
    dot = top / ".git"
    try:
        if dot.is_dir():
            return dot
        if dot.is_file():
            first = dot.read_text(encoding="utf-8").strip()
            if first.startswith("gitdir:"):
                gd = (top / first[len("gitdir:"):].strip()).resolve()
                return gd if gd.is_dir() else None
    except OSError:
        return None
    return None


def lock_name(memlog_dir: str, key: str) -> str:
    return f"{memlog_dir or 'root'}-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]}.lock"


def temp_lock_path(path: Path) -> Path:
    """The fallback lock: `tempfile.gettempdir()` (TMPDIR, else /tmp; computed once per process).

    The known split: two writers outside git (or with an unwritable git dir) whose TMPDIR
    differs take two different locks. The git-dir lock, the path every seat's memlog takes,
    does not depend on the environment.
    """
    target = path.resolve()
    return Path(tempfile.gettempdir()) / LOCK_DIR / lock_name(target.parent.name, str(target))


def lock_path(path: Path) -> Path:
    """Where the memlog's lock lives: in the git dir of its work tree, else in the temp dir.

    Never next to the memlog: a lock file in the work tree would be staged into the
    shared index by the next `git add -A`.
    """
    target = path.resolve()
    for top in target.parents:
        gd = git_dir(top)
        if gd is not None:
            key = target.relative_to(top).as_posix()
            return gd / LOCK_DIR / lock_name(target.parent.name, key)
    return temp_lock_path(path)


class Locked(Exception):
    """Another writer held the memlog's lock for the whole bounded wait."""

    def __init__(self, lock: Path) -> None:
        super().__init__(str(lock))
        self.lock = lock


def open_lock(path: Path) -> tuple[int, Path]:
    for lock in (lock_path(path), temp_lock_path(path)):
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
            return os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o666), lock
        except OSError:
            continue  # an unwritable git dir: fall back to the temp dir
    raise OSError(f"cannot create a lock file for {path}")


@contextmanager
def locked(path: Path) -> Iterator[Path | None]:
    """Hold the memlog's exclusive lock for one read-modify-write; wait LOCK_WAIT_S, then raise Locked."""
    if fcntl is None:
        yield None
        return
    fd, lock = open_lock(path)
    try:
        deadline = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise Locked(lock) from None
                time.sleep(LOCK_POLL_S)
        try:
            yield lock
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def refuse(path: Path, lock: Path, **retry: str) -> int:
    """The bounded wait ran out: nothing was written; echo what to re-run so no line is lost."""
    print(json.dumps({
        "ok": False,
        "error": "locked",
        "memlog": str(path),
        "lock": str(lock),
        "waited_s": LOCK_WAIT_S,
        **retry,
    }))
    print(
        f"error: {path} stayed locked by another writer for {LOCK_WAIT_S:g} s ({lock}); "
        "nothing was written - re-run the same command",
        file=sys.stderr,
    )
    return EXIT_LOCKED


def entry_count(body: str) -> int:
    return sum(1 for ln in body.splitlines() if ln.startswith("- "))


def ack(path: Path, body: str) -> None:
    """Echo new state so the caller never re-reads the file to know where it stands."""
    print(json.dumps({
        "ok": True,
        "memlog": str(path),
        "entries": entry_count(body),
    }))


def cmd_init(args) -> int:
    path = resolve(args)
    if path.exists():
        print(f"error: {path} already exists; use append/set to update it", file=sys.stderr)
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    meta: dict[str, str] = {}
    for pair in args.field or []:
        if "=" not in pair:
            print(f"error: --field expects key=value, got {pair!r}", file=sys.stderr)
            return 2
        k, v = pair.split("=", 1)
        meta[k.strip()] = v.strip()
    try:
        with locked(path):
            if path.exists():  # another writer created it while this one waited
                print(f"error: {path} already exists; use append/set to update it", file=sys.stderr)
                return 2
            touch(meta)
            write_atomic(path, render(meta, ""))
    except Locked as e:
        return refuse(path, e.lock)
    ack(path, "")
    return 0


def cmd_append(args) -> int:
    path = resolve(args)
    text = " ".join(args.text.split())  # collapse newlines/runs → one-line entry, no prose bloat
    label = args.type or ""
    if args.by:
        label = f"{label} by {args.by}".strip()  # attribution: "(idea by user)" / "(by coach)"
    tag = f"({label}) " if label else ""
    entry = f"- {tag}{text}"
    try:
        with locked(path):  # the read, the append and the write are one step for other writers
            meta, body = split(path.read_text(encoding="utf-8"))
            body = (body.rstrip("\n") + "\n" + entry) if body.strip() else entry  # always at the end
            touch(meta)
            write_atomic(path, render(meta, body))
    except Locked as e:
        return refuse(path, e.lock, entry=entry)
    ack(path, body)
    return 0


def cmd_set(args) -> int:
    path = resolve(args)
    try:
        with locked(path):
            meta, body = split(path.read_text(encoding="utf-8"))
            meta[args.key] = args.value
            touch(meta)
            write_atomic(path, render(meta, body))
    except Locked as e:
        return refuse(path, e.lock, key=args.key, value=args.value)
    ack(path, body)
    return 0


APPEND_HELP = """append one entry at the end of the memlog, then print one JSON line:
{"ok": true, "memlog": "<file>", "entries": <count>}.

Lock: the read, the append and the write run under an exclusive fcntl.flock on
<git dir>/bmad-memlog-locks/<name>.lock (outside git, or with an unwritable git dir:
<temp dir>/bmad-memlog-locks/, the temp dir being $TMPDIR else /tmp - writers with a
different TMPDIR take different fallback locks), never in the work tree. Another
writer holding it is waited for up to 10 s; then the command refuses with exit code
75 and {"ok": false, "error": "locked", ..., "entry": "<the line>"} - nothing was
written; re-run the same command.

F-MEMLOG-NOCOMMIT: append does NOT commit, stage or push. A memlog kept in git is the
caller's to git add + commit + push after each entry.
"""


def add_target(sp) -> None:
    """Every command addresses the memlog the same way: a run folder or an explicit path."""
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--workspace", help="run folder; the memlog is {workspace}/.memlog.md")
    g.add_argument("--path", help="explicit memlog file path (alternative to --workspace)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="create the memlog")
    add_target(pi)
    pi.add_argument("--field", action="append", metavar="KEY=VALUE", help="frontmatter field (repeatable)")
    pi.set_defaults(func=cmd_init)

    pa = sub.add_parser(
        "append",
        help="append one entry at the end",
        description=APPEND_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_target(pa)
    pa.add_argument("--text", required=True)
    pa.add_argument("--type", help="entry kind, rendered as an inline tag")
    pa.add_argument("--by", help="who the entry came from (e.g. user, coach); rendered into the tag")
    pa.set_defaults(func=cmd_append)

    pset = sub.add_parser("set", help="set a descriptive frontmatter field")
    add_target(pset)
    pset.add_argument("--key", required=True)
    pset.add_argument("--value", required=True)
    pset.set_defaults(func=cmd_set)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
