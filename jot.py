#!/usr/bin/env python3
"""jot — minimal autosaving GTK4 notes editor for Super+Ctrl+C.

Saves notes automatically to $JOT_DIR or ~/Documents/Notes with zero modal prompts.
"""
from datetime import datetime
import os
from pathlib import Path
import sys


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


class Note:
    """Storage manager for a single note.

    Pure logic without GTK dependencies so storage and file handling can be
    tested headlessly.
    """

    def __init__(self, notes_dir=None):
        self._notes_dir = Path(notes_dir).expanduser() if notes_dir else None
        self.path = None
        self._last_saved_text = None

    @property
    def notes_dir(self):
        return self._notes_dir or get_notes_dir()

    def save(self, text):
        """Save text atomically or delete the note file if text is blank."""
        # Blank text removes any file previously written by this note
        if not text or text.isspace():
            if self.path is not None:
                try:
                    if self.path.exists():
                        self.path.unlink()
                except OSError:
                    pass
                self.path = None
                self._last_saved_text = None
            return

        # Skip write if text hasn't changed since last successful save
        if self.path is not None and text == self._last_saved_text:
            return

        directory = self.notes_dir
        # Allocate timestamp-based filename on first non-blank save
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
    from gi.repository import Adw, Gio, GLib, Gtk, GtkSource

    app = Adw.Application(
        application_id="dev.omega.jot",
        flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
    )

    window = None
    tabs = {}

    def get_style_scheme(manager, dark):
        # Fall back to Adwaita-dark/classic-dark or Adwaita/classic if Adw is unavailable
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

    # Window and tab view components
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

    def save_tab(tab_info):
        text = get_buffer_text(tab_info["buffer"])
        tab_info["note"].save(text)
        if tab_view.get_selected_page() == tab_info["page"]:
            update_title_for_selected()

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

    def add_new_tab():
        note = Note()
        buffer = GtkSource.Buffer()
        lang = GtkSource.LanguageManager.get_default().get_language("markdown")
        if lang is not None:
            buffer.set_language(lang)
        buffer.set_enable_undo(True)
        apply_style_scheme(buffer)

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

        page = tab_view.append(scrolled)
        page.set_title(title_for(""))

        tab_info = {
            "note": note,
            "buffer": buffer,
            "view": view,
            "page": page,
            "scrolled": scrolled,
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
            tabs[page]["view"].grab_focus()

    tab_view.connect("notify::selected-page", on_page_selected)

    def on_close_page(view, page):
        tab_info = tabs.pop(page, None)
        if tab_info:
            flush_tab(tab_info)
        view.close_page_finish(page, True)
        if view.get_n_pages() == 0:
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
    style_mgr = Adw.StyleManager.get_default()
    style_mgr.connect(
        "notify::dark",
        lambda *_: [apply_style_scheme(t["buffer"]) for t in tabs.values()],
    )

    def create_window():
        nonlocal window
        window = Adw.ApplicationWindow(application=app, title="jot")
        window.set_default_size(720, 520)

        toolbar_view = Adw.ToolbarView()

        header_bar = Adw.HeaderBar()
        header_bar.add_css_class("flat")
        header_bar.set_title_widget(window_title)

        new_tab_btn = Gtk.Button.new_from_icon_name("tab-new-symbolic")
        new_tab_btn.set_tooltip_text("New note (Ctrl+T)")
        new_tab_btn.connect("clicked", lambda *_: add_new_tab())
        header_bar.pack_start(new_tab_btn)

        open_folder_btn = Gtk.Button.new_from_icon_name("folder-symbolic")
        open_folder_btn.set_tooltip_text("Open notes folder")
        open_folder_btn.connect("clicked", lambda *_: open_notes_folder())
        header_bar.pack_end(open_folder_btn)

        tab_bar = Adw.TabBar()
        tab_bar.set_autohide(True)
        tab_bar.set_view(tab_view)

        toolbar_view.add_top_bar(header_bar)
        toolbar_view.add_top_bar(tab_bar)
        toolbar_view.set_content(tab_view)
        window.set_content(toolbar_view)

        # Global keyboard shortcuts via capture phase so Escape cannot be swallowed
        shortcut_controller = Gtk.ShortcutController.new()
        shortcut_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

        def add_shortcut(trigger_str, callback):
            trigger = Gtk.ShortcutTrigger.parse_string(trigger_str)
            action = Gtk.CallbackAction.new(callback)
            shortcut_controller.add_shortcut(Gtk.Shortcut.new(trigger, action))

        add_shortcut("<Control>t", lambda *_: (add_new_tab(), True)[1])
        add_shortcut("<Control>n", lambda *_: (add_new_tab(), True)[1])

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
