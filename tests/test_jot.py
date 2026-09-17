"""Tests for jot storage, naming, title, sidebar browsing, and markdown rendering."""
from datetime import datetime
import os
from pathlib import Path
import sys
import time
import pytest

from jot import (
    Note,
    NoteInfo,
    get_notes_dir,
    list_notes,
    preview_for,
    relative_time,
    render_html,
    title_for,
)


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


def test_import_does_not_import_gi_or_markdown():
    """Verify jot module does not import gi or markdown at top level."""
    import subprocess
    cmd = [
        sys.executable,
        "-c",
        "import sys, jot; print('gi' in sys.modules, 'markdown' in sys.modules)",
    ]
    res = subprocess.run(
        cmd,
        cwd=Path(__file__).parent.parent,
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == "False False"


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


def test_note_open_saves_to_same_path(tmp_path):
    notes_dir = tmp_path / "Notes"
    notes_dir.mkdir()
    existing_file = notes_dir / "my_note.md"
    existing_file.write_text("Original content", encoding="utf-8")

    note = Note.open(existing_file)
    assert note.path == existing_file
    assert note._last_saved_text == "Original content"

    # Saving identical text does not touch file
    past = 1_000_000.0
    os.utime(existing_file, (past, past))
    mtime_before = os.stat(existing_file).st_mtime_ns
    note.save("Original content")
    assert os.stat(existing_file).st_mtime_ns == mtime_before

    # Saving modified text writes to the same file
    note.save("Updated content")
    assert note.path == existing_file
    assert existing_file.read_text(encoding="utf-8") == "Updated content"


def test_note_open_cleared_does_not_delete_or_write(tmp_path):
    notes_dir = tmp_path / "Notes"
    notes_dir.mkdir()
    existing_file = notes_dir / "preserve.md"
    existing_file.write_text("Keep me", encoding="utf-8")

    past = 1_000_000.0
    os.utime(existing_file, (past, past))
    mtime_before = os.stat(existing_file).st_mtime_ns

    note = Note.open(existing_file)
    # Blank text must not delete the file and must not write it either
    note.save("")
    assert existing_file.exists()
    assert existing_file.read_text(encoding="utf-8") == "Keep me"
    assert os.stat(existing_file).st_mtime_ns == mtime_before

    note.save("   \n\t  ")
    assert existing_file.exists()
    assert existing_file.read_text(encoding="utf-8") == "Keep me"
    assert os.stat(existing_file).st_mtime_ns == mtime_before


def test_preview_for():
    # Empty / None
    assert preview_for("") == ""
    assert preview_for(None) == ""
    assert preview_for("   \n\t  ") == ""

    # Only title
    assert preview_for("# Just Title") == ""
    assert preview_for("# Just Title\n\n   \n") == ""

    # Basic lines after title
    sample = "# Title\nLine one\nLine two"
    assert preview_for(sample) == "Line one · Line two"

    # Leading markdown noise stripped
    noise_sample = """# Main Title
## Subheading
- Bullet
* Star
+ Plus
1. Numbered
> Quote
- [ ] Task
- [x] Done
"""
    expected = "Subheading · Bullet · Star · Plus · Numbered · Quote · Task · Done"
    assert preview_for(noise_sample) == expected

    # Bold, italic, code formatting stripped
    fmt_sample = """# Title
Some **bold text** and __underlined__ with `inline code`
"""
    assert preview_for(fmt_sample) == "Some bold text and underlined with inline code"

    # Truncation to 90 chars with ellipsis
    long_line = "A" * 100
    long_sample = f"# Title\n{long_line}"
    preview = preview_for(long_sample)
    assert len(preview) == 91
    assert preview.endswith("…")
    assert preview.startswith("A" * 90)

    # Blank lines skipped
    blank_lines = "# Title\n\n\nFirst line\n\n\nSecond line\n\n"
    assert preview_for(blank_lines) == "First line · Second line"


def test_relative_time():
    now = datetime(2026, 9, 17, 14, 0, 0)
    now_ts = now.timestamp()

    # < 60 s -> "just now"
    assert relative_time(now_ts - 0, now_ts) == "just now"
    assert relative_time(now_ts - 30, now_ts) == "just now"
    assert relative_time(now_ts - 59, now_ts) == "just now"

    # < 3600 s -> "5 min ago"
    assert relative_time(now_ts - 60, now_ts) == "1 min ago"
    assert relative_time(now_ts - 300, now_ts) == "5 min ago"
    assert relative_time(now_ts - 3599, now_ts) == "59 min ago"

    # Same day >= 3600 s -> "3 h ago"
    assert relative_time(now_ts - 3600, now_ts) == "1 h ago"
    assert relative_time(now_ts - 3 * 3600, now_ts) == "3 h ago"
    assert relative_time(datetime(2026, 9, 17, 8, 0, 0).timestamp(), now_ts) == "6 h ago"

    # Yesterday -> "yesterday"
    yesterday = datetime(2026, 9, 16, 10, 0, 0).timestamp()
    assert relative_time(yesterday, now_ts) == "yesterday"

    # Same year -> "Sep 12"
    older_same_year = datetime(2026, 9, 12, 10, 0, 0).timestamp()
    assert relative_time(older_same_year, now_ts) == "Sep 12"

    # Different year -> "Sep 12, 2025"
    older_diff_year = datetime(2025, 9, 12, 10, 0, 0).timestamp()
    assert relative_time(older_diff_year, now_ts) == "Sep 12, 2025"


def test_list_notes(tmp_path):
    notes_dir = tmp_path / "Notes"
    assert list_notes(notes_dir) == []

    notes_dir.mkdir()
    assert list_notes(notes_dir) == []

    t1 = 1_700_000_000.0
    t2 = 1_700_000_100.0
    t3 = 1_700_000_200.0

    f1 = notes_dir / "note1.md"
    f1.write_text("# Note 1\nBody one", encoding="utf-8")
    os.utime(f1, (t1, t1))

    f2 = notes_dir / "note2.md"
    f2.write_text("# Note 2\nBody two", encoding="utf-8")
    os.utime(f2, (t3, t3))

    f3 = notes_dir / "note3.md"
    f3.write_text("# Note 3\nBody three", encoding="utf-8")
    os.utime(f3, (t2, t2))

    # Files that must be ignored: dotfiles, .tmp, non-.md
    (notes_dir / ".hidden.md").write_text("# Hidden", encoding="utf-8")
    (notes_dir / "note.tmp").write_text("# Temp", encoding="utf-8")
    (notes_dir / "note.md.tmp").write_text("# Temp2", encoding="utf-8")
    (notes_dir / "other.txt").write_text("Text file", encoding="utf-8")
    sub_dir = notes_dir / "subdir"
    sub_dir.mkdir()
    (sub_dir / "subnote.md").write_text("# Sub", encoding="utf-8")

    listed = list_notes(notes_dir)
    assert len(listed) == 3
    # Sorted newest mtime first: note2 (t3), note3 (t2), note1 (t1)
    assert listed[0].path == f2
    assert listed[0].title == "Note 2"
    assert listed[0].preview == "Body two"
    assert listed[0].mtime == t3

    assert listed[1].path == f3
    assert listed[1].title == "Note 3"
    assert listed[1].preview == "Body three"
    assert listed[1].mtime == t2

    assert listed[2].path == f1
    assert listed[2].title == "Note 1"
    assert listed[2].preview == "Body one"
    assert listed[2].mtime == t1


def test_list_notes_unreadable_and_non_utf8(tmp_path):
    notes_dir = tmp_path / "Notes"
    notes_dir.mkdir()

    # Non-UTF8 file should decode with replace or skip without raising
    bad_file = notes_dir / "bad.md"
    bad_file.write_bytes(b"# Bad \xff\xfe\nBody \x80\x81")

    # Read at most first 4 KB
    large_file = notes_dir / "large.md"
    large_file.write_text("# Large Note\n" + "A" * 10000, encoding="utf-8")

    listed = list_notes(notes_dir)
    names = [n.path.name for n in listed]
    assert "large.md" in names
    assert "bad.md" in names
    large_note = next(n for n in listed if n.path.name == "large.md")
    assert large_note.title == "Large Note"


def test_render_html():
    sample = """# Heading 1
A paragraph with **bold**, *italic*, `code`, and a [link](https://example.com).

## List
- Item 1
- Item 2

### Tasks
- [ ] Todo item
- [x] Done item

> A blockquote quote

| A | B |
| - | - |
| 1 | 2 |

```python
x = 1
```
"""
    # 1. Headings, lists, code, table render
    dark_html = render_html(sample, dark=True)
    light_html = render_html(sample, dark=False)

    assert "<h1>Heading 1</h1>" in dark_html
    assert "<ul>" in dark_html
    assert "<li>Item 1</li>" in dark_html
    assert "<table>" in dark_html
    assert "<pre><code" in dark_html

    # 2. <script> in note produces no <script tag in output
    xss_note = "<script>alert(1)</script>\n<img src=x onerror=alert(2)>"
    xss_html = render_html(xss_note, dark=True)
    assert "<script" not in xss_html
    assert "&lt;script" in xss_html
    assert "<img src=x" not in xss_html

    # 3. > quote still becomes <blockquote>
    quote_note = "# Title\n> this is a blockquote"
    quote_html = render_html(quote_note, dark=True)
    assert "<blockquote>" in quote_html
    assert "<p>this is a blockquote</p>" in quote_html

    # 4. CSP meta present
    expected_csp = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data: file: https:">'
    assert expected_csp in dark_html
    assert expected_csp in light_html

    # 5. Dark and light produce different colours
    assert dark_html != light_html
    assert "#ffffffde" in dark_html
    assert "#000000cc" in light_html
    assert "#78aeed" in dark_html
    assert "#1c71d8" in light_html

    # 6. Task list boxes rendered (☐ and ☑)
    assert "☐" in dark_html
    assert "☑" in dark_html
