"""Tests for jot storage, naming, and title logic."""
import os
import sys
import time
from pathlib import Path
import pytest

from jot import Note, title_for, get_notes_dir


def test_import_does_not_import_gi():
    """Verify jot module does not import gi at top level."""
    import subprocess
    cmd = [
        sys.executable,
        "-c",
        "import ast, sys; ast.parse(open('jot.py').read()); import jot; print('gi' in sys.modules)",
    ]
    res = subprocess.run(
        cmd,
        cwd=Path(__file__).parent.parent,
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == "False"


def test_blank_note_writes_nothing_and_creates_no_dir(tmp_path):
    notes_dir = tmp_path / "Notes"
    note = Note(notes_dir)
    note.save("")
    assert not notes_dir.exists()
    assert note.path is None

    note.save("   \n\t  ")
    assert not notes_dir.exists()
    assert note.path is None


def test_first_save_creates_timestamp_file(tmp_path):
    notes_dir = tmp_path / "Notes"
    note = Note(notes_dir)
    content = "Hello, world!\nSecond line."
    note.save(content)

    assert notes_dir.exists()
    assert note.path is not None
    assert note.path.exists()
    assert note.path.name.endswith(".md")
    stem = note.path.stem
    parts = stem.split(" ")
    assert len(parts) == 2
    date_part, time_part = parts
    assert len(date_part.split("-")) == 3
    assert len(time_part.split("-")) == 3
    assert note.path.read_text(encoding="utf-8") == content


def test_later_saves_keep_same_path(tmp_path):
    notes_dir = tmp_path / "Notes"
    note = Note(notes_dir)
    note.save("Initial text")
    first_path = note.path
    assert first_path is not None

    time.sleep(0.01)
    note.save("Modified text")
    assert note.path == first_path
    assert note.path.read_text(encoding="utf-8") == "Modified text"


def test_identical_text_not_rewritten(tmp_path):
    notes_dir = tmp_path / "Notes"
    note = Note(notes_dir)
    note.save("Fixed content")
    path = note.path
    assert path is not None

    # Set mtime to a known past timestamp
    past_time = 1_000_000.0
    os.utime(path, (past_time, past_time))
    mtime_ns_before = os.stat(path).st_mtime_ns

    # Save identical text
    note.save("Fixed content")
    mtime_ns_after = os.stat(path).st_mtime_ns

    assert mtime_ns_before == mtime_ns_after


def test_clearing_saved_note_deletes_file(tmp_path):
    notes_dir = tmp_path / "Notes"
    note = Note(notes_dir)
    note.save("Temporary content")
    saved_path = note.path
    assert saved_path is not None
    assert saved_path.exists()

    # Clearing text deletes the file and forgets the path
    note.save("")
    assert not saved_path.exists()
    assert note.path is None

    # Saving again afterwards creates a new note
    note.save("Fresh note")
    assert note.path is not None
    assert note.path.exists()
    assert note.path.read_text(encoding="utf-8") == "Fresh note"


def test_name_collision_gets_suffix(tmp_path):
    notes_dir = tmp_path / "Notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    # Pre-create a file that matches the expected timestamp
    now_str = time.strftime("%Y-%m-%d %H-%M-%S")
    collision_file = notes_dir / f"{now_str}.md"
    collision_file.write_text("Existing note", encoding="utf-8")

    note = Note(notes_dir)
    note.save("New colliding note")

    assert note.path != collision_file
    assert note.path.name == f"{now_str} 2.md"
    assert note.path.read_text(encoding="utf-8") == "New colliding note"
    assert collision_file.read_text(encoding="utf-8") == "Existing note"


def test_pre_existing_unrelated_file_never_touched(tmp_path):
    notes_dir = tmp_path / "Notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    unrelated = notes_dir / "unrelated.txt"
    unrelated.write_text("Important data", encoding="utf-8")

    note = Note(notes_dir)
    note.save("Note content")
    note.save("")  # Clear note

    assert unrelated.exists()
    assert unrelated.read_text(encoding="utf-8") == "Important data"


def test_no_tmp_files_remain(tmp_path):
    notes_dir = tmp_path / "Notes"
    note = Note(notes_dir)
    note.save("Some text")

    tmp_files = list(notes_dir.glob("*.tmp"))
    assert tmp_files == []


def test_jot_dir_env_var(monkeypatch, tmp_path):
    env_dir = tmp_path / "CustomEnvNotes"
    monkeypatch.setenv("JOT_DIR", str(env_dir))

    assert get_notes_dir() == env_dir

    note = Note()
    note.save("Stored in env dir")
    assert env_dir.exists()
    assert note.path.parent == env_dir


def test_title_for():
    # blank cases
    assert title_for("") == "New note"
    assert title_for(None) == "New note"
    assert title_for("   \n\t  ") == "New note"
    assert title_for("###") == "New note"

    # # Heading cases
    assert title_for("# Heading") == "Heading"
    assert title_for("###   Heading with spaces   ") == "Heading with spaces"
    assert title_for("#HeadingNoSpace") == "HeadingNoSpace"

    # leading blank lines
    assert title_for("\n\n\n# Actual Title\nSecond line") == "Actual Title"
    assert title_for("\n   \nFirst non-blank line") == "First non-blank line"

    # long line cut to 30 chars with …
    short_line = "A" * 30
    assert title_for(short_line) == short_line
    long_line = "A" * 31
    assert title_for(long_line) == "A" * 30 + "…"

    long_heading = "# " + "B" * 50
    assert title_for(long_heading) == "B" * 30 + "…"
