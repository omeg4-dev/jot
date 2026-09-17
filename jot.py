#!/usr/bin/env python3
"""jot — minimal autosaving GTK4 notes editor for Super+Ctrl+C.

Saves notes automatically to $JOT_DIR or ~/Documents/Notes with zero modal prompts.
"""
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import sys
import time
import urllib.parse


@dataclass
class NoteInfo:
    """Metadata summary for a single note file."""
    path: Path
    title: str
    preview: str
    mtime: float


def get_notes_dir(custom_dir=None):
    """Return notes directory from custom_dir, $JOT_DIR, or ~/Documents/Notes."""
    if custom_dir:
        return Path(custom_dir).expanduser()
    env_dir = os.environ.get("JOT_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / "Documents" / "Notes"


def title_for(text):
    """Extract tab/window title from the first non-blank line of text.

    Leading markdown heading hashes and whitespace are stripped.
    Titles longer than 30 characters are truncated with an ellipsis.
    """
    if not text:
        return "New note"
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        cleaned = stripped.lstrip("#").strip()
        if not cleaned:
            continue
        if len(cleaned) > 30:
            return cleaned[:30] + "…"
        return cleaned
    return "New note"


def preview_for(text):
    """Extract a preview snippet from the text after the line the title came from.

    Skips blank lines, strips leading markdown noise, drops **, __, and backticks,
    joins remaining lines with ' · ', collapses whitespace, and truncates to 90 chars.
    """
    if not text:
        return ""
    lines = text.splitlines()
    title_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        cleaned = stripped.lstrip("#").strip()
        if cleaned:
            title_idx = i
            break
    if title_idx is None or title_idx + 1 >= len(lines):
        return ""

    cleaned_lines = []
    for line in lines[title_idx + 1:]:
        s = line.strip()
        if not s:
            continue
        while True:
            prev = s
            if s.startswith(("- [ ]", "- [x]", "- [X]", "* [ ]", "* [x]", "* [X]", "+ [ ]", "+ [x]", "+ [X]")):
                s = s[5:].lstrip()
            elif s.startswith(("- ", "* ", "+ ", "> ")):
                s = s[2:].lstrip()
            elif s.startswith(">"):
                s = s[1:].lstrip()
            elif s.startswith("#"):
                s = s.lstrip("#").lstrip()
            elif re.match(r"^\d+\.\s+", s):
                s = re.sub(r"^\d+\.\s+", "", s)
            if s == prev:
                break
        s = s.replace("**", "").replace("__", "").replace("`", "")
        s = " ".join(s.split())
        if s:
            cleaned_lines.append(s)

    if not cleaned_lines:
        return ""

    joined = " · ".join(cleaned_lines)
    joined = " ".join(joined.split())
    if len(joined) > 90:
        return joined[:90] + "…"
    return joined


def list_notes(notes_dir=None):
    """List notes directly in notes_dir sorted newest mtime first."""
    directory = get_notes_dir(notes_dir)
    if not directory.exists() or not directory.is_dir():
        return []

    notes = []
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []

    for entry in entries:
        name = entry.name
        if name.startswith(".") or not name.endswith(".md") or name.endswith(".tmp") or ".tmp." in name:
            continue
        try:
            st = entry.stat()
            if not entry.is_file():
                continue
            mtime = st.st_mtime
            with entry.open("r", encoding="utf-8", errors="replace") as f:
                content = f.read(4096)
            title = title_for(content)
            preview = preview_for(content)
            notes.append(NoteInfo(path=entry, title=title, preview=preview, mtime=mtime))
        except OSError:
            continue

    notes.sort(key=lambda n: n.mtime, reverse=True)
    return notes


def relative_time(mtime, now=None):
    """Format mtime into relative human-readable string."""
    if now is None:
        now = time.time()
    if isinstance(now, (int, float)):
        dt_now = datetime.fromtimestamp(now)
    else:
        dt_now = now
        now = dt_now.timestamp()

    if isinstance(mtime, (int, float)):
        dt_mtime = datetime.fromtimestamp(mtime)
    else:
        dt_mtime = mtime
        mtime = dt_mtime.timestamp()

    diff = now - mtime
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{int(diff // 60)} min ago"

    days = (dt_now.date() - dt_mtime.date()).days
    if days == 0:
        return f"{int(diff // 3600)} h ago"
    if days == 1:
        return "yesterday"
    if dt_mtime.year == dt_now.year:
        return f"{dt_mtime.strftime('%b')} {dt_mtime.day}"
    return f"{dt_mtime.strftime('%b')} {dt_mtime.day}, {dt_mtime.year}"


def render_html(text, dark=False):
    """Render markdown text into a full HTML document string."""
    import markdown

    # Escape HTML tags to neutralise raw HTML while preserving blockquotes and code fences
    escaped_text = text.replace("&", "&amp;").replace("<", "&lt;")

    rendered = markdown.markdown(
        escaped_text,
        extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
    )

    # Render [ ] and [x] at start of list items as ☐ and ☑
    rendered = re.sub(r"(<li\b[^>]*>(?:\s*<p>)?\s*)\[ \]\s*", r"\g<1>☐ ", rendered)
    rendered = re.sub(r"(<li\b[^>]*>(?:\s*<p>)?\s*)\[[xX]\]\s*", r"\g<1>☑ ", rendered)

    text_color = "#ffffffde" if dark else "#000000cc"
    link_color = "#78aeed" if dark else "#1c71d8"

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data: file: https:">
<style>
body {{
  font-family: "Adwaita Sans", "Cantarell", sans-serif;
  font-size: 15px;
  line-height: 1.6;
  margin: 0;
  padding: 16px 24px 32px;
  max-width: 72ch;
  background: transparent;
  color: {text_color};
}}
:first-child {{
  margin-top: 0;
}}
h1, h2, h3, h4, h5, h6 {{
  font-weight: 750;
  margin: 1.2em 0 .4em;
  line-height: 1.25;
}}
h1 {{
  font-size: 1.6em;
  border-bottom: 1px solid color-mix(in srgb, currentColor 15%, transparent);
  padding-bottom: 0.2em;
}}
h2 {{
  font-size: 1.3em;
  border-bottom: 1px solid color-mix(in srgb, currentColor 15%, transparent);
  padding-bottom: 0.2em;
}}
h3 {{
  font-size: 1.1em;
}}
a {{
  color: {link_color};
  text-decoration: underline;
}}
code {{
  font-family: "FiraCode Nerd Font", "Adwaita Mono", monospace;
  font-size: 0.9em;
  background: color-mix(in srgb, currentColor 8%, transparent);
  border-radius: 6px;
  padding: 2px 5px;
}}
pre {{
  font-family: "FiraCode Nerd Font", "Adwaita Mono", monospace;
  font-size: 0.9em;
  background: color-mix(in srgb, currentColor 8%, transparent);
  border-radius: 6px;
  padding: 10px 12px;
  overflow-x: auto;
}}
pre code {{
  padding: 0;
  background: none;
  border-radius: 0;
}}
blockquote {{
  border-left: 3px solid {link_color};
  padding-left: 12px;
  margin: 1em 0;
  color: color-mix(in srgb, currentColor 75%, transparent);
}}
table {{
  border-collapse: collapse;
  margin: 1em 0;
  width: 100%;
}}
th, td {{
  border: 1px solid color-mix(in srgb, currentColor 15%, transparent);
  padding: 4px 10px;
  text-align: left;
}}
th {{
  background: color-mix(in srgb, currentColor 6%, transparent);
}}
hr {{
  border: none;
  border-top: 1px solid color-mix(in srgb, currentColor 15%, transparent);
  margin: 1.5em 0;
}}
img {{
  max-width: 100%;
  height: auto;
}}
p {{
  margin: 0.8em 0;
}}
ul, ol {{
  margin: 0.8em 0;
  padding-left: 1.6em;
}}
li {{
  margin: 0.25em 0;
}}
</style>
</head>
<body>
{rendered}
</body>
</html>"""


class Note:
    """Storage manager for a single note.

    Pure logic without GTK dependencies so storage and file handling can be
    tested headlessly.
    """

    def __init__(self, notes_dir=None, path=None, created=True):
        self._notes_dir = Path(notes_dir).expanduser() if notes_dir else None
        self.path = Path(path).expanduser() if path else None
        self._created = created
        if self.path is not None:
            self._notes_dir = self.path.parent
            try:
                self._last_saved_text = self.path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                self._last_saved_text = None
        else:
            self._last_saved_text = None

    @classmethod
    def open(cls, path):
        """Open a Note bound to an existing file."""
        path = Path(path).expanduser()
        return cls(notes_dir=path.parent, path=path, created=False)

    @property
    def notes_dir(self):
        return self._notes_dir or get_notes_dir()

    def save(self, text):
        """Save text atomically or delete the note file if text is blank."""
        # Blank text handling
        if not text or text.isspace():
            if self._created:
                # Only notes created in this session delete their own file when cleared
                if self.path is not None:
                    try:
                        if self.path.exists():
                            self.path.unlink()
                    except OSError:
                        pass
                    self.path = None
                    self._last_saved_text = None
            # Opened notes: blank text must not delete the file and must not write it either
            return

        # Skip write if text hasn't changed since last successful save
        if self.path is not None and text == self._last_saved_text:
            return

        directory = self.notes_dir
        # Allocate timestamp-based filename on first non-blank save for created notes
        if self.path is None:
            directory.mkdir(parents=True, exist_ok=True)
            base = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
            candidate = directory / f"{base}.md"
            counter = 2
            while candidate.exists():
                candidate = directory / f"{base} {counter}.md"
                counter += 1
            self.path = candidate

        # Atomic write: write to <path>.tmp in the same dir then replace
        tmp_path = self.path.with_name(f"{self.path.name}.tmp")
        try:
            tmp_path.write_text(text, encoding="utf-8")
            os.replace(tmp_path, self.path)
            self._last_saved_text = text
        except Exception:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise


def build_app():
    """Import GTK/Adwaita libraries and configure the Jot application."""
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("GtkSource", "5")
    from gi.repository import Adw, Gio, GLib, GObject, Gtk, GtkSource, Pango

    has_preview = False
    try:
        gi.require_version("Gdk", "4.0")
        gi.require_version("WebKit", "6.0")
        from gi.repository import Gdk, WebKit
        import markdown
        has_preview = True
    except (ValueError, ImportError):
        has_preview = False

    app = Adw.Application(
        application_id="dev.omega.jot",
        flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
    )

    window = None
    tabs = {}
    split_view = None
    notes_list = None
    preview_toggle_btn = None
    updating_preview_toggle = False

    def get_style_scheme(manager, dark):
        names = ("Adw-dark", "Adwaita-dark", "classic-dark") if dark else ("Adw", "Adwaita", "classic")
        for name in names:
            scheme = manager.get_scheme(name)
            if scheme is not None:
                return scheme
        return None

    def apply_style_scheme(buffer):
        scheme_mgr = GtkSource.StyleSchemeManager.get_default()
        style_mgr = Adw.StyleManager.get_default()
        scheme = get_style_scheme(scheme_mgr, style_mgr.get_dark())
        if scheme is not None:
            buffer.set_style_scheme(scheme)

    def get_buffer_text(buffer):
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        return buffer.get_text(start, end, True)

    def open_notes_folder():
        directory = get_notes_dir()
        directory.mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(directory.as_uri(), None)

    # Window title and tab view components
    tab_view = Adw.TabView()
    window_title = Adw.WindowTitle(title="jot", subtitle="Saves automatically")

    def update_title_for_selected():
        page = tab_view.get_selected_page()
        if not page:
            window_title.set_title("jot")
            window_title.set_subtitle("Saves automatically")
            return
        window_title.set_title(page.get_title())
        tab_info = tabs.get(page)
        if tab_info and tab_info["note"].path is not None:
            window_title.set_subtitle(tab_info["note"].path.name)
        else:
            window_title.set_subtitle("Saves automatically")

    def on_decide_policy(_view, decision, decision_type):
        if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            action = decision.get_navigation_action()
            nav_type = action.get_navigation_type()
            is_click = (nav_type == WebKit.NavigationType.LINK_CLICKED) or action.is_user_gesture()
            if is_click:
                req = action.get_request()
                uri = req.get_uri() if req else None
                if uri:
                    parsed = urllib.parse.urlparse(uri)
                    if parsed.scheme.lower() in ("http", "https", "mailto"):
                        Gio.AppInfo.launch_default_for_uri(uri, None)
                decision.ignore()
                return True
        decision.use()
        return True

    def match_editor_background(tab_info):
        # The page itself is transparent; paint the web view with the editor's
        # own background so switching modes doesn't change the colour.
        rgba = Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=0.0)
        scheme = tab_info["buffer"].get_style_scheme()
        style = scheme.get_style("text") if scheme is not None else None
        if style is not None and style.props.background_set:
            rgba.parse(style.props.background)
        tab_info["web_view"].set_background_color(rgba)

    def set_tab_mode(tab_info, mode):
        if not has_preview:
            return
        tab_info["mode"] = mode
        if mode == "preview":
            if tab_info["timeout_id"] is not None:
                GLib.source_remove(tab_info["timeout_id"])
                tab_info["timeout_id"] = None
                save_tab(tab_info)

            if tab_info.get("web_view") is None:
                settings = WebKit.Settings()
                settings.set_enable_javascript(False)
                settings.set_enable_developer_extras(False)
                settings.set_enable_page_cache(False)
                wv = WebKit.WebView(settings=settings)
                wv.connect("decide-policy", on_decide_policy)
                tab_info["web_view"] = wv
                match_editor_background(tab_info)
                tab_info["stack"].add_named(wv, "preview")

            is_dark = Adw.StyleManager.get_default().get_dark()
            text = get_buffer_text(tab_info["buffer"])
            html = render_html(text, is_dark)
            tab_info["web_view"].load_html(html, "file:///")
            tab_info["stack"].set_visible_child_name("preview")
        else:
            tab_info["stack"].set_visible_child_name("edit")
            tab_info["view"].grab_focus()

        if preview_toggle_btn is not None and tab_view.get_selected_page() == tab_info["page"]:
            nonlocal updating_preview_toggle
            updating_preview_toggle = True
            try:
                preview_toggle_btn.set_active(mode == "preview")
            finally:
                updating_preview_toggle = False

    def refresh_sidebar():
        if notes_list is None:
            return
        notes_list.remove_all()
        notes = list_notes()
        for info in notes:
            row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            row_box.set_margin_top(6)
            row_box.set_margin_bottom(6)
            row_box.set_margin_start(10)
            row_box.set_margin_end(10)

            title_lbl = Gtk.Label(label=info.title, xalign=0)
            title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            title_lbl.add_css_class("heading")
            row_box.append(title_lbl)

            if info.preview:
                prev_lbl = Gtk.Label(label=info.preview, xalign=0)
                prev_lbl.set_wrap(True)
                prev_lbl.set_lines(2)
                prev_lbl.set_ellipsize(Pango.EllipsizeMode.END)
                prev_lbl.add_css_class("dim-label")
                prev_lbl.add_css_class("caption")
                row_box.append(prev_lbl)

            time_lbl = Gtk.Label(label=relative_time(info.mtime), xalign=0)
            time_lbl.add_css_class("dim-label")
            time_lbl.add_css_class("caption")
            row_box.append(time_lbl)

            row = Gtk.ListBoxRow()
            row.set_child(row_box)
            row.set_tooltip_text(info.path.name)
            row.note_path = info.path
            notes_list.append(row)

    def save_tab(tab_info):
        old_path = tab_info["note"].path
        old_text = tab_info["note"]._last_saved_text
        text = get_buffer_text(tab_info["buffer"])
        tab_info["note"].save(text)
        if tab_view.get_selected_page() == tab_info["page"]:
            update_title_for_selected()
        if split_view is not None and split_view.get_show_sidebar():
            if tab_info["note"].path != old_path or tab_info["note"]._last_saved_text != old_text:
                refresh_sidebar()

    def flush_tab(tab_info):
        if tab_info["timeout_id"] is not None:
            GLib.source_remove(tab_info["timeout_id"])
            tab_info["timeout_id"] = None
        save_tab(tab_info)

    def on_buffer_changed(buffer, tab_info):
        text = get_buffer_text(buffer)
        tab_info["page"].set_title(title_for(text))
        if tab_view.get_selected_page() == tab_info["page"]:
            window_title.set_title(tab_info["page"].get_title())

        # Debounce autosave with 400ms delay
        if tab_info["timeout_id"] is not None:
            GLib.source_remove(tab_info["timeout_id"])
            tab_info["timeout_id"] = None

        def _on_timeout():
            tab_info["timeout_id"] = None
            save_tab(tab_info)
            return GLib.SOURCE_REMOVE

        tab_info["timeout_id"] = GLib.timeout_add(400, _on_timeout)

    def add_new_tab(note=None):
        if note is None:
            note = Note()
            initial_text = ""
        else:
            initial_text = note._last_saved_text or ""

        buffer = GtkSource.Buffer()
        lang = GtkSource.LanguageManager.get_default().get_language("markdown")
        if lang is not None:
            buffer.set_language(lang)
        buffer.set_enable_undo(True)
        apply_style_scheme(buffer)

        if initial_text:
            buffer.begin_irreversible_action()
            buffer.set_text(initial_text)
            buffer.end_irreversible_action()
            buffer.place_cursor(buffer.get_end_iter())

        view = GtkSource.View.new_with_buffer(buffer)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_left_margin(24)
        view.set_right_margin(24)
        view.set_top_margin(16)
        view.set_bottom_margin(16)
        view.set_show_line_numbers(False)
        view.set_monospace(False)
        view.set_highlight_current_line(False)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(view)

        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        stack.set_transition_duration(120)
        stack.add_named(scrolled, "edit")

        page = tab_view.append(stack)
        page.set_title(title_for(initial_text))

        tab_info = {
            "note": note,
            "buffer": buffer,
            "view": view,
            "page": page,
            "scrolled": scrolled,
            "stack": stack,
            "mode": "edit",
            "web_view": None,
            "timeout_id": None,
        }
        tabs[page] = tab_info

        buffer.connect("changed", lambda buf: on_buffer_changed(buf, tab_info))

        tab_view.set_selected_page(page)
        view.grab_focus()
        update_title_for_selected()
        return page

    def on_page_selected(*_):
        update_title_for_selected()
        page = tab_view.get_selected_page()
        if page and page in tabs:
            tab_info = tabs[page]
            if preview_toggle_btn is not None:
                nonlocal updating_preview_toggle
                updating_preview_toggle = True
                try:
                    preview_toggle_btn.set_active(tab_info["mode"] == "preview")
                finally:
                    updating_preview_toggle = False
            if tab_info["mode"] == "edit":
                tab_info["view"].grab_focus()
            elif tab_info.get("web_view") is not None:
                tab_info["web_view"].grab_focus()

    tab_view.connect("notify::selected-page", on_page_selected)

    def on_close_page(tab_v, page):
        tab_info = tabs.pop(page, None)
        if tab_info:
            flush_tab(tab_info)
        tab_v.close_page_finish(page, True)
        if tab_v.get_n_pages() == 0:
            if window is not None:
                window.close()
        else:
            update_title_for_selected()
        return True

    tab_view.connect("close-page", on_close_page)

    def on_close_request(_win):
        for tab_info in list(tabs.values()):
            flush_tab(tab_info)
        tabs.clear()
        app.quit()
        return False

    def on_shutdown(_app):
        for tab_info in list(tabs.values()):
            flush_tab(tab_info)
        tabs.clear()

    app.connect("shutdown", on_shutdown)

    # Listen for system theme changes
    def on_theme_changed(*_):
        style_mgr = Adw.StyleManager.get_default()
        is_dark = style_mgr.get_dark()
        for t in tabs.values():
            apply_style_scheme(t["buffer"])
            if has_preview and t.get("mode") == "preview" and t.get("web_view") is not None:
                text = get_buffer_text(t["buffer"])
                match_editor_background(t)
                html = render_html(text, is_dark)
                t["web_view"].load_html(html, "file:///")

    style_mgr = Adw.StyleManager.get_default()
    style_mgr.connect("notify::dark", on_theme_changed)

    def on_row_activated(_lb, row):
        path = getattr(row, "note_path", None)
        if not path:
            return

        target_page = None
        for page, tab_info in tabs.items():
            if tab_info["note"].path is not None:
                try:
                    if tab_info["note"].path.resolve() == path.resolve():
                        target_page = page
                        break
                except OSError:
                    if tab_info["note"].path == path:
                        target_page = page
                        break

        if target_page is not None:
            tab_view.set_selected_page(target_page)
            tab_info = tabs[target_page]
            if tab_info["mode"] == "edit":
                tab_info["view"].grab_focus()
            elif tab_info.get("web_view") is not None:
                tab_info["web_view"].grab_focus()
        else:
            cur_page = tab_view.get_selected_page()
            can_reuse = False
            if cur_page and cur_page in tabs:
                cur_info = tabs[cur_page]
                if cur_info["note"].path is None:
                    text = get_buffer_text(cur_info["buffer"])
                    if not text.strip():
                        can_reuse = True

            note = Note.open(path)
            content = note._last_saved_text or ""

            if can_reuse:
                tab_info = tabs[cur_page]
                if tab_info["timeout_id"] is not None:
                    GLib.source_remove(tab_info["timeout_id"])
                    tab_info["timeout_id"] = None
                tab_info["note"] = note
                buf = tab_info["buffer"]
                buf.begin_irreversible_action()
                buf.set_text(content)
                buf.end_irreversible_action()
                buf.place_cursor(buf.get_end_iter())
                tab_info["page"].set_title(title_for(content))
                set_tab_mode(tab_info, "edit")
                tab_info["view"].grab_focus()
                update_title_for_selected()
            else:
                add_new_tab(note=note)

        if split_view.get_collapsed():
            split_view.set_show_sidebar(False)

    def create_window():
        nonlocal window, split_view, notes_list, preview_toggle_btn
        window = Adw.ApplicationWindow(application=app, title="jot")
        window.set_default_size(720, 520)

        toolbar_view = Adw.ToolbarView()

        header_bar = Adw.HeaderBar()
        header_bar.add_css_class("flat")
        header_bar.set_title_widget(window_title)

        split_view = Adw.OverlaySplitView()
        split_view.set_sidebar_position(Gtk.PackType.START)
        split_view.set_show_sidebar(False)
        split_view.set_sidebar_width_fraction(0.36)
        split_view.set_min_sidebar_width(240)
        split_view.set_max_sidebar_width(320)
        split_view.set_content(tab_view)

        sidebar_toggle_btn = Gtk.ToggleButton.new()
        sidebar_toggle_btn.set_icon_name("sidebar-show-symbolic")
        sidebar_toggle_btn.set_tooltip_text("Browse notes (Ctrl+O)")
        sidebar_toggle_btn.bind_property(
            "active",
            split_view,
            "show-sidebar",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )
        header_bar.pack_start(sidebar_toggle_btn)

        new_tab_btn = Gtk.Button.new_from_icon_name("tab-new-symbolic")
        new_tab_btn.set_tooltip_text("New note (Ctrl+T)")
        new_tab_btn.connect("clicked", lambda *_: add_new_tab())
        header_bar.pack_start(new_tab_btn)

        open_folder_btn = Gtk.Button.new_from_icon_name("folder-symbolic")
        open_folder_btn.set_tooltip_text("Open notes folder")
        open_folder_btn.connect("clicked", lambda *_: open_notes_folder())
        header_bar.pack_end(open_folder_btn)

        if has_preview:
            preview_toggle_btn = Gtk.ToggleButton.new()
            preview_toggle_btn.set_icon_name("view-reveal-symbolic")
            preview_toggle_btn.set_tooltip_text("Preview Markdown (Ctrl+E)")

            def on_preview_btn_toggled(btn):
                if updating_preview_toggle:
                    return
                page = tab_view.get_selected_page()
                if page and page in tabs:
                    mode = "preview" if btn.get_active() else "edit"
                    set_tab_mode(tabs[page], mode)

            preview_toggle_btn.connect("toggled", on_preview_btn_toggled)
            header_bar.pack_end(preview_toggle_btn)

        # Sidebar content
        sidebar_toolbar = Adw.ToolbarView()
        sidebar_header = Adw.HeaderBar()
        sidebar_header.add_css_class("flat")
        sidebar_header.set_show_title(True)
        sidebar_header.set_title_widget(Adw.WindowTitle(title="Notes"))
        sidebar_header.set_show_end_title_buttons(False)
        sidebar_header.set_show_start_title_buttons(False)
        sidebar_toolbar.add_top_bar(sidebar_header)

        notes_list = Gtk.ListBox()
        notes_list.add_css_class("navigation-sidebar")
        notes_list.set_selection_mode(Gtk.SelectionMode.NONE)
        notes_list.set_activate_on_single_click(True)
        notes_list.connect("row-activated", on_row_activated)

        empty_page = Adw.StatusPage(
            icon_name="document-edit-symbolic",
            title="No notes yet",
            description="Notes you write appear here.",
        )
        empty_page.add_css_class("compact")
        notes_list.set_placeholder(empty_page)

        sidebar_scrolled = Gtk.ScrolledWindow()
        sidebar_scrolled.set_child(notes_list)
        sidebar_toolbar.set_content(sidebar_scrolled)
        split_view.set_sidebar(sidebar_toolbar)

        split_view.connect(
            "notify::show-sidebar",
            lambda sv, *_: refresh_sidebar() if sv.get_show_sidebar() else None,
        )

        # Collapse breakpoint at 560px
        bp = Adw.Breakpoint.new(Adw.breakpoint_condition_parse("max-width: 560px"))
        bp.add_setter(split_view, "collapsed", True)
        window.add_breakpoint(bp)

        tab_bar = Adw.TabBar()
        tab_bar.set_autohide(True)
        tab_bar.set_view(tab_view)

        toolbar_view.add_top_bar(header_bar)
        toolbar_view.add_top_bar(tab_bar)
        toolbar_view.set_content(split_view)
        window.set_content(toolbar_view)

        # Shortcuts
        shortcut_controller = Gtk.ShortcutController.new()
        shortcut_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

        def add_shortcut(trigger_str, callback):
            trigger = Gtk.ShortcutTrigger.parse_string(trigger_str)
            action = Gtk.CallbackAction.new(callback)
            shortcut_controller.add_shortcut(Gtk.Shortcut.new(trigger, action))

        add_shortcut("<Control>t", lambda *_: (add_new_tab(), True)[1])
        add_shortcut("<Control>n", lambda *_: (add_new_tab(), True)[1])
        add_shortcut("<Control>o", lambda *_: (sidebar_toggle_btn.set_active(not sidebar_toggle_btn.get_active()), True)[1])

        if has_preview:
            def on_ctrl_e(*_):
                page = tab_view.get_selected_page()
                if page and page in tabs:
                    tab_info = tabs[page]
                    new_mode = "edit" if tab_info["mode"] == "preview" else "preview"
                    set_tab_mode(tab_info, new_mode)
                return True

            add_shortcut("<Control>e", on_ctrl_e)

        def on_ctrl_w(*_):
            page = tab_view.get_selected_page()
            if page:
                tab_view.close_page(page)
            return True

        def on_escape(*_):
            window.close()
            return True

        add_shortcut("<Control>w", on_ctrl_w)
        add_shortcut("Escape", on_escape)
        add_shortcut("<Control>q", on_escape)

        window.add_controller(shortcut_controller)
        window.connect("close-request", on_close_request)

    def on_activate(_app):
        if window is None:
            create_window()
            add_new_tab()
            window.present()
        else:
            add_new_tab()
            window.present()

    app.connect("activate", on_activate)
    return app


def main():
    """Main application entry point."""
    app = build_app()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
