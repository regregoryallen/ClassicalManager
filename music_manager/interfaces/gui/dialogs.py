"""Standalone dialogs: help, settings, logs, import/export.

V3 Phase 3: mechanically split from gui.py — methods are
unchanged; this mixin is mounted on App in app.py.
"""

import json
import io
import logging
import platform
import sys
import threading
import tkinter as tk
from contextlib import contextmanager
from tkinter import messagebox, ttk
from music_manager.interfaces import filedialog
from pathlib import Path

from music_manager.core.config import PROJECT_ROOT
from music_manager.interfaces.gui.common import (
    _PREFS_PATH, _load_prefs, _save_prefs, _ScanCancelled, _GUILogHandler,
)

logger = logging.getLogger(__name__)


class DialogsMixin:
    def _show_help(self, section=None):
        """Open or focus the help window, optionally jumping to a section."""
        if self._help_window and self._help_window.winfo_exists():
            self._help_window.lift()
            self._help_window.focus_force()
            if section:
                self._help_jump(section)
            return

        win = tk.Toplevel(self.root)
        win.title("Help \u2014 Classical Music Playlist Manager")
        win.transient(self.root)
        self._center_on_main(win, 720, 720)
        # Non-modal: no grab_set() so main app stays interactive

        self._help_window = win

        def on_close():
            self._help_window = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)

        ctk = self.ctk

        # Navigation bar
        nav = ctk.CTkFrame(win, fg_color="transparent")
        nav.pack(fill="x", padx=5, pady=(5, 0))

        nav_sections = [
            ("Setup", "setup"),
            ("Getting Started", "getting_started"),
            ("Sidebar", "sidebar"),
            ("Builder", "builder"),
            ("Rules", "rules"),
            ("Cleanup", "cleanup"),
            ("Settings", "settings"),
            ("CLI", "cli"),
            ("Patterns", "patterns"),
            ("Troubleshooting", "troubleshooting"),
        ]
        for label, mark in nav_sections:
            ctk.CTkButton(
                nav, text=label, width=0, height=24,
                font=ctk.CTkFont(size=11),
                fg_color="gray30", hover_color="gray40",
                command=lambda m=mark: self._help_jump(m),
            ).pack(side="left", padx=1, pady=2)

        # Text content
        text = tk.Text(win, bg="#1e1e1e", fg="#cccccc",
                       font=("Segoe UI", 10), wrap="word",
                       state="normal", padx=12, pady=8,
                       relief="flat", borderwidth=0,
                       selectbackground="#3a5a8a")
        text.pack(fill="both", expand=True, padx=5, pady=5)

        scroll = ttk.Scrollbar(text, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")

        # Configure text tags
        text.tag_configure("title", foreground="#ffffff",
                           font=("Segoe UI", 16, "bold"),
                           spacing1=4, spacing3=2)
        text.tag_configure("h1", foreground="#88ccff",
                           font=("Segoe UI", 13, "bold"),
                           spacing1=10, spacing3=1)
        text.tag_configure("h2", foreground="#bbddaa",
                           font=("Segoe UI", 11, "bold"),
                           spacing1=4, spacing3=1)
        text.tag_configure("bold", foreground="#eeeeee",
                           font=("Segoe UI", 10, "bold"))
        text.tag_configure("body", foreground="#cccccc",
                           font=("Segoe UI", 10))
        text.tag_configure("code", foreground="#d4a76a",
                           font=("Consolas", 10))
        text.tag_configure("sep", foreground="#444444")

        from music_manager.interfaces.help_content import build_help_content
        build_help_content(text)

        text.configure(state="disabled")

        # Bottom close button
        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.pack(fill="x", padx=5, pady=5)
        ctk.CTkButton(btn_frame, text="Close", width=80,
                      command=on_close).pack(side="right", padx=3)

        self._help_text = text

        if section:
            win.after(50, lambda: self._help_jump(section))

    def _help_jump(self, section):
        """Scroll the help text widget to a named section mark."""
        try:
            self._help_text.see(section)
        except (tk.TclError, AttributeError):
            pass

    def _show_log_viewer(self):
        """Open a window displaying captured log output."""
        if not self._log_handler:
            messagebox.showinfo("Logs", "No log handler configured.")
            return

        viewer = tk.Toplevel(self.root)
        viewer.title("Application Logs")
        viewer.transient(self.root)
        self._center_on_main(viewer, 800, 500)
        viewer.wait_visibility()
        viewer.grab_set()

        text = tk.Text(viewer, bg="#1e1e1e", fg="#cccccc",
                       font=("Consolas", 10), wrap="word",
                       state="normal")
        text.pack(fill="both", expand=True, padx=5, pady=5)

        scroll = ttk.Scrollbar(text, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")

        text.insert("1.0", self._log_handler.get_text())
        text.configure(state="disabled")
        text.see("end")

        ctk = self.ctk
        btn_frame = ctk.CTkFrame(viewer, fg_color="transparent")
        btn_frame.pack(fill="x", padx=5, pady=5)

        def refresh():
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", self._log_handler.get_text())
            text.configure(state="disabled")
            text.see("end")

        def clear():
            self._log_handler.clear()
            refresh()

        ctk.CTkButton(btn_frame, text="Refresh", width=80,
                      command=refresh).pack(side="left", padx=3)
        ctk.CTkButton(btn_frame, text="Clear", width=80,
                      command=clear).pack(side="left", padx=3)
        ctk.CTkButton(btn_frame, text="Close", width=80,
                      command=viewer.destroy).pack(side="right", padx=3)

    def _show_settings(self):
        """Open the settings dialog for app-wide configuration."""
        ctk = self.ctk

        from music_manager.core.config import load_config, DEFAULT_CONFIG_PATH, ConfigError

        # Load current config (or start with defaults)
        try:
            config = load_config()
        except ConfigError:
            config = {"active_library": 1, "targets": {}}

        plex = config.get("targets", {}).get("plex", {})
        m3u = config.get("targets", {}).get("m3u", {})

        dlg = tk.Toplevel(self.root)
        dlg.title("Settings")
        dlg.transient(self.root)
        self._center_on_main(dlg, 700, 700)
        dlg.wait_visibility()
        dlg.grab_set()

        frame = ctk.CTkScrollableFrame(dlg)
        frame.pack(fill="both", expand=True, padx=5, pady=5)

        row = 0

        def add_section(label):
            nonlocal row
            ctk.CTkLabel(frame, text=label,
                         font=ctk.CTkFont(size=14, weight="bold")).grid(
                row=row, column=0, columnspan=3, sticky="w",
                padx=10, pady=(12, 4))
            row += 1

        def add_field(label, value="", width=400):
            nonlocal row
            ctk.CTkLabel(frame, text=label).grid(
                row=row, column=0, sticky="w", padx=(20, 5), pady=3)
            entry = ctk.CTkEntry(frame, width=width)
            entry.grid(row=row, column=1, columnspan=2, sticky="w",
                       padx=5, pady=3)
            if value:
                entry.insert(0, str(value))
            row += 1
            return entry

        def add_browse_field(label, value="", width=350):
            nonlocal row
            ctk.CTkLabel(frame, text=label).grid(
                row=row, column=0, sticky="w", padx=(20, 5), pady=3)
            entry = ctk.CTkEntry(frame, width=width)
            entry.grid(row=row, column=1, sticky="w", padx=5, pady=3)
            if value:
                entry.insert(0, str(value))

            def browse():
                path = filedialog.asksaveasfilename(
                    title=f"Select {label}", parent=dlg,
                    defaultextension=".db",
                    filetypes=[("SQLite Database", "*.db"),
                               ("All files", "*.*")],
                    confirmoverwrite=False)
                if path:
                    entry.delete(0, "end")
                    entry.insert(0, path)

            ctk.CTkButton(frame, text="...", width=30,
                          command=browse).grid(
                row=row, column=2, padx=5, pady=3)
            row += 1
            return entry

        # -- Database --
        add_section("Database")
        from music_manager.core.config import get_db_path
        # Show the path actually in use. A missing or empty db_path falls
        # back to the bundled default, and showing blank there left you
        # guessing which database was open.
        db_entry = add_browse_field("Database File", str(get_db_path()))

        # -- Plex --
        add_section("Plex")
        plex_url = add_field("Server URL", plex.get("base_url", ""))
        plex_token = add_field("Token", plex.get("token", ""))
        plex_token_env = add_field("Token Env Var",
                                   plex.get("token_env", ""))
        plex_section_default = add_field("Default Section",
                                         plex.get("music_section", ""))
        ctk.CTkLabel(frame, text="(Per-library section in sidebar overrides this)",
                     text_color="gray", font=ctk.CTkFont(size=11)).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=30, pady=0)
        row += 1

        # Plex path rules
        add_section("Plex Path Rules")
        ctk.CTkLabel(frame, text="One per line:  find -> replace",
                     text_color="gray", font=ctk.CTkFont(size=11)).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=20, pady=0)
        row += 1
        plex_rules_text = tk.Text(frame, height=4, width=60,
                                  bg="#343638", fg="#dce4ee",
                                  insertbackground="#dce4ee",
                                  font=("Consolas", 10),
                                  relief="flat")
        plex_rules_text.grid(row=row, column=0, columnspan=3,
                             padx=20, pady=3, sticky="ew")
        for pr in plex.get("path_rules", []):
            plex_rules_text.insert("end",
                                   f"{pr['find']} -> {pr['replace']}\n")
        row += 1

        # -- M3U --
        add_section("M3U Export")
        m3u_style = ctk.CTkComboBox(
            frame, values=["absolute", "relative_to_playlist"], width=200)
        ctk.CTkLabel(frame, text="Path Style").grid(
            row=row, column=0, sticky="w", padx=(20, 5), pady=3)
        m3u_style.grid(row=row, column=1, columnspan=2, sticky="w",
                       padx=5, pady=3)
        m3u_style.set(m3u.get("path_style", "absolute"))
        row += 1
        m3u_base = add_field("Base Path", m3u.get("base_path", ""))

        # M3U path rules
        add_section("M3U Path Rules")
        ctk.CTkLabel(frame, text="One per line:  find -> replace",
                     text_color="gray", font=ctk.CTkFont(size=11)).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=20, pady=0)
        row += 1
        m3u_rules_text = tk.Text(frame, height=4, width=60,
                                 bg="#343638", fg="#dce4ee",
                                 insertbackground="#dce4ee",
                                 font=("Consolas", 10),
                                 relief="flat")
        m3u_rules_text.grid(row=row, column=0, columnspan=3,
                            padx=20, pady=3, sticky="ew")
        for mr in m3u.get("path_rules", []):
            m3u_rules_text.insert("end",
                                  f"{mr['find']} -> {mr['replace']}\n")
        row += 1

        # -- Buttons --
        def parse_rules(text_widget):
            rules = []
            for line in text_widget.get("1.0", "end").strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                if " → " in line:
                    parts = line.split(" → ", 1)
                elif " -> " in line:
                    parts = line.split(" -> ", 1)
                else:
                    continue
                rules.append({"find": parts[0].strip(),
                              "replace": parts[1].strip()})
            return rules

        def save():
            # Build config
            new_config = {"active_library": config.get("active_library", 1),
                          "targets": {}}

            # Plex
            url = plex_url.get().strip()
            tok = plex_token.get().strip()
            tok_env = plex_token_env.get().strip()
            section = plex_section_default.get().strip()
            if url and (tok or tok_env):
                plex_cfg = {"base_url": url}
                if tok:
                    plex_cfg["token"] = tok
                if tok_env:
                    plex_cfg["token_env"] = tok_env
                if section:
                    plex_cfg["music_section"] = section
                plex_cfg["path_rules"] = parse_rules(plex_rules_text)
                new_config["targets"]["plex"] = plex_cfg

            # M3U
            new_config["targets"]["m3u"] = {
                "path_style": m3u_style.get(),
                "base_path": m3u_base.get().strip(),
                "path_rules": parse_rules(m3u_rules_text),
            }

            # Database path (stored in config.json, requires restart).
            # The field shows the effective path, so compare against that
            # — and persist it, turning an implicit fallback into an
            # explicit setting.
            from music_manager.core.config import get_db_path
            new_db = db_entry.get().strip()
            current_db = str(get_db_path())
            db_changed = bool(new_db) and new_db != current_db
            if new_db:
                new_config["db_path"] = new_db
            elif config.get("db_path"):
                new_config["db_path"] = config["db_path"]

            # Write config.json
            from music_manager.core.config import save_config
            save_config(new_config)

            if db_changed:
                messagebox.showinfo(
                    "Restart Required",
                    "Database path changed. Restart the app for it to take effect.",
                    parent=dlg)

            dlg.destroy()
            messagebox.showinfo("Settings", "Settings saved.")

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=8)
        ctk.CTkButton(btn_row, text="Save", width=80,
                      command=save).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="Cancel", width=80,
                      command=dlg.destroy).pack(side="right", padx=5)

    def _show_profile_summary(self):
        """Show a popup summarizing all profiles for the active library."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        from music_manager.core.database import (
            PlaylistProfile, Album, Work, Track, Composer,
        )
        from music_manager.core.selection import resolve_selections

        profiles = list(PlaylistProfile.select().where(
            (PlaylistProfile.library == self.active_library) &
            (~PlaylistProfile.name.startswith("__"))))

        if not profiles:
            messagebox.showinfo("No Profiles",
                                "No saved profiles for this library.")
            return

        with self._busy():
            rows = []
            for prof in profiles:
                # V2 bug: unpacked the old 3-tuple into 2 names (crashed
                # for any profile with selections).
                selected_ids = resolve_selections(prof).track_ids

                albums_set = set()
                works_set = set()
                composers_set = set()
                total_ms = 0

                if selected_ids:
                    tracks = list(
                        Track.select(Track, Work, Album)
                        .join(Work, on=(Track.work == Work.id))
                        .switch(Track)
                        .join(Album, on=(Track.album == Album.id))
                        .where(Track.id.in_(list(selected_ids)))
                    )
                    for t in tracks:
                        albums_set.add(t.album_id)
                        works_set.add(t.work_id)
                        total_ms += t.duration_ms or 0
                        if t.composer_id:
                            composers_set.add(t.composer_id)

                total_s = total_ms // 1000
                dur_str = (f"{total_s // 3600}h {(total_s % 3600) // 60:02d}m"
                           if total_s >= 3600
                           else f"{total_s // 60}m {total_s % 60:02d}s")

                rows.append((prof.name, len(albums_set), len(works_set),
                             len(selected_ids), len(composers_set), dur_str))

        popup = tk.Toplevel(self.root)
        popup.title(f"Profile Summary — {self.active_library.name}")
        popup.transient(self.root)
        self._center_on_main(popup, 750, 350)
        popup.wait_visibility()
        popup.grab_set()

        ctk = self.ctk

        tree = ttk.Treeview(popup,
                            columns=("albums", "works", "tracks",
                                     "composers", "duration"),
                            show="tree headings", selectmode="browse")
        tree.heading("#0", text="Profile")
        tree.heading("albums", text="Albums")
        tree.heading("works", text="Works")
        tree.heading("tracks", text="Tracks")
        tree.heading("composers", text="Composers")
        tree.heading("duration", text="Duration")
        tree.column("#0", width=200)
        tree.column("albums", width=70, anchor="center")
        tree.column("works", width=70, anchor="center")
        tree.column("tracks", width=70, anchor="center")
        tree.column("composers", width=90, anchor="center")
        tree.column("duration", width=100, anchor="center")
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        for name, alb, wrk, trk, comp, dur in rows:
            tree.insert("", "end", text=name,
                        values=(alb, wrk, trk, comp, dur))

        self._setup_tree_sort(tree)

        ctk.CTkButton(popup, text="Close",
                      command=popup.destroy).pack(pady=(0, 10))

    def _export_library(self):
        """Show a library picker, then export selected libraries to JSON files."""
        from music_manager.core.database import Library

        libs = list(Library.select())
        if not libs:
            messagebox.showwarning("No Libraries", "No libraries to export.")
            return

        # If only one library, skip the picker
        if len(libs) == 1:
            self._export_libraries(libs)
            return

        picker = tk.Toplevel(self.root)
        picker.title("Export Libraries")
        picker.transient(self.root)
        self._center_on_main(picker, 350, 320)
        picker.wait_visibility()
        picker.grab_set()

        ctk = self.ctk
        ctk.CTkLabel(picker, text="Select libraries to export:",
                     font=("Segoe UI", 12)).pack(padx=10, pady=(10, 5))

        check_frame = ctk.CTkScrollableFrame(picker, height=180)
        check_frame.pack(fill="both", expand=True, padx=10, pady=5)

        check_vars = []
        for lib in libs:
            var = tk.BooleanVar(value=True)
            check_vars.append((lib, var))
            ctk.CTkCheckBox(check_frame, text=lib.name, variable=var,
                            font=("Segoe UI", 11)).pack(anchor="w", pady=2)

        btn_frame = ctk.CTkFrame(picker, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(0, 5))

        def select_all():
            for _, var in check_vars:
                var.set(True)

        def select_none():
            for _, var in check_vars:
                var.set(False)

        ctk.CTkButton(btn_frame, text="All", width=60,
                      command=select_all).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="None", width=60,
                      command=select_none).pack(side="left", padx=5)

        def on_export():
            selected = [lib for lib, var in check_vars if var.get()]
            if not selected:
                messagebox.showwarning("None Selected",
                                       "Select at least one library.",
                                       parent=picker)
                return
            picker.destroy()
            self._export_libraries(selected)

        ctk.CTkButton(picker, text="Export", width=100,
                      command=on_export).pack(pady=(0, 10))

    def _export_libraries(self, libraries):
        """Export one or more libraries to JSON files in a chosen directory."""
        from music_manager.core.library_io import export_library

        if len(libraries) == 1:
            # Single library — save-as dialog for one file
            lib = libraries[0]
            initial_dir = self._prefs.get("last_export_dir", "")
            default_name = lib.name.replace(" ", "_")
            path = filedialog.asksaveasfilename(
                defaultextension=".json",
                initialfile=f"{default_name}_library.json",
                initialdir=initial_dir or None,
                filetypes=[("JSON", "*.json")],
                title="Export Library",
                parent=self.root,
            )
            if not path:
                return
            self._prefs["last_export_dir"] = str(Path(path).parent)
            _save_prefs(self._prefs)
            with self._busy():
                export_library(lib, Path(path))
            messagebox.showinfo("Export",
                               f"Exported library '{lib.name}' to:\n{path}")
        else:
            # Multiple libraries — pick a directory
            initial_dir = self._prefs.get("last_export_dir", "")
            directory = filedialog.askdirectory(
                initialdir=initial_dir or None,
                title="Choose Export Directory",
                parent=self.root,
            )
            if not directory:
                return
            self._prefs["last_export_dir"] = directory
            _save_prefs(self._prefs)
            exported = []
            with self._busy():
                for lib in libraries:
                    safe_name = lib.name.replace(" ", "_")
                    path = Path(directory) / f"{safe_name}_library.json"
                    export_library(lib, path)
                    exported.append(f"  {lib.name} → {path.name}")
            messagebox.showinfo(
                "Export",
                f"Exported {len(exported)} libraries to:\n{directory}\n\n"
                + "\n".join(exported))

    def _import_library(self):
        """Import a library from a JSON file."""
        initial_dir = self._prefs.get("last_export_dir", "")
        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json")],
            initialdir=initial_dir or None,
            title="Import Library",
            parent=self.root,
        )
        if not path:
            return
        self._prefs["last_export_dir"] = str(Path(path).parent)
        _save_prefs(self._prefs)

        try:
            data = json.loads(Path(path).read_text())
        except Exception as exc:
            messagebox.showerror("Import Error", f"Cannot read file: {exc}")
            return

        from music_manager.core.database import Library
        from music_manager.core.library_io import import_library

        with self._busy():
            lib_name = data.get("library_name", "Imported")
            existing = [l.name for l in Library.select()]
            final_name = lib_name
            n = 2
            while final_name in existing:
                final_name = f"{lib_name} ({n})"
                n += 1

            lib = Library.create(name=final_name,
                                 plex_section=data.get("plex_section", ""))
            result = import_library(lib, data)

            self._refresh_library_list()
            self.lib_combo.set(final_name)
            self._on_library_changed(final_name)

        msg = f"Imported library '{final_name}' from:\n{path}"
        if result.get("old_format_skipped"):
            msg += (f"\n\nNote: {result['old_format_skipped']} old-format rules "
                    f"were skipped. Re-create selections manually.")
        messagebox.showinfo("Import", msg)

    def _import_old_playlists(self):
        """Import old-style playlists (text files with one album directory per line).

        Each file becomes a profile with album-level selections.
        """
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        paths = filedialog.askopenfilenames(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Select Old Playlist Files",
            parent=self.root,
        )
        if not paths:
            return

        self.root.config(cursor="watch")
        self.root.update_idletasks()

        from music_manager.core.database import (
            Album, PlaylistProfile, ProfileSelection,
        )

        albums = list(Album.select().where(Album.library == self.active_library))

        results = []
        for filepath in paths:
            try:
                lines = Path(filepath).read_text().strip().splitlines()
            except Exception as exc:
                results.append(f"Error reading {filepath}: {exc}")
                continue

            # Profile name from filename without extension
            profile_name = Path(filepath).stem

            # Delete existing profile with same name (CASCADE deletes selections)
            for existing in PlaylistProfile.select().where(
                (PlaylistProfile.library == self.active_library) &
                (PlaylistProfile.name == profile_name)
            ):
                existing.delete_instance()

            profile = PlaylistProfile.create(
                library=self.active_library,
                name=profile_name,
                shuffle_mode="album",
                work_integrity="enforce",
                length_mode="all",
                length_value=None,
                seed=None,
                no_repeat_tracks=True,
                separate_composers=False,
                separate_albums=False,
                separate_forms=False,
            )

            matched = 0
            unmatched = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Match by album directory name (last path component)
                dir_name = Path(line).name if "/" in line or "\\" in line else line
                found = False
                for album in albums:
                    # album_key is the folder name relative to source root
                    album_dir = Path(album.album_key).name
                    if album_dir == dir_name or album.title == dir_name:
                        ProfileSelection.create(
                            profile=profile, level="album",
                            key=album.album_key, excluded=False,
                        )
                        matched += 1
                        found = True
                        break
                if not found:
                    unmatched.append(dir_name)

            status = f"'{profile_name}': {matched} matched"
            if unmatched:
                status += f", {len(unmatched)} unmatched"
            results.append(status)

        self.root.config(cursor="")

        summary = "\n".join(results)
        if any("unmatched" in r for r in results):
            summary += "\n\nUnmatched albums won't appear in the playlist. " \
                       "Check album names match your library."
        messagebox.showinfo("Import Results", summary)
