"""Standalone dialogs: help, settings, logs, import/export.

V3 Phase 3: mechanically split from gui.py — methods are
unchanged; this mixin is mounted on App in app.py.
"""

import copy
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
    bind_wheel_scroll,
)

logger = logging.getLogger(__name__)

# The backend as config.json spells it, and as the dialog shows it.
BACKEND_LABELS = {
    "sqlite": "SQLite (file)",
    "mysql": "MySQL / MariaDB (server)",
}


def _apply_database_fields(config: dict, fields: dict) -> None:
    """Write the chosen backend into config['database'], in place.

    Settings belonging to the backend that was *not* chosen are left where
    they are, so switching to SQLite for an afternoon and back again does
    not make you retype a server.

    The legacy top-level 'db_path' is dropped once a 'database' section
    exists. resolve_db_settings prefers database.path, so keeping both
    would leave config.json naming one database and the app opening
    another — the exact confusion this dialog is meant to end.
    """
    from music_manager.core.config import DEFAULT_DB_CHARSET, DEFAULT_DB_PORT
    from music_manager.core.database import DATABASE_PATH

    backend = fields["db_backend"]
    db = config.setdefault("database", {})
    db["backend"] = backend

    if backend == "sqlite":
        path = fields["db_path"].strip()
        # The field is prefilled with the path in use, so writing it back
        # unconditionally would freeze the bundled default into config.json
        # and break the app the day the checkout moves. Storing nothing
        # means "wherever the app lives", which is what it already meant.
        if path and Path(path) != DATABASE_PATH:
            db["path"] = path
        else:
            db.pop("path", None)
    else:
        db["host"] = fields["db_host"].strip()
        db["name"] = fields["db_name"].strip()
        db["user"] = fields["db_user"].strip()
        db["charset"] = fields["db_charset"].strip() or DEFAULT_DB_CHARSET

        port = fields["db_port"].strip()
        if not port:
            db["port"] = DEFAULT_DB_PORT
        else:
            # Anything non-numeric is stored as typed so that
            # validate_config rejects it by name. Silently substituting
            # the default would connect somewhere the user did not ask for.
            db["port"] = int(port) if port.isdigit() else port

        for key in ("password", "password_env"):
            value = fields[f"db_{key}"].strip()
            if value:
                db[key] = value
            else:
                db.pop(key, None)

    config.pop("db_path", None)


def apply_settings_fields(config: dict, fields: dict) -> dict:
    """Fold the settings dialog's field values into a loaded config.

    Returns a new dict; `config` is not modified.

    The dialog covers a fraction of config.json — cron, webhook and
    autosave settings have no fields here — so this updates what was
    loaded instead of building a config from the fields. Rebuilding
    deleted every unshown key, which silently dropped a configured MySQL
    server back to SQLite. The same holds within a section: 'strategy' on
    the Plex target has no field and must survive.

    Split out of the dialog so it can be tested without a display.
    """
    new_config = copy.deepcopy(config)
    new_config.setdefault("active_library", 1)
    targets = new_config.setdefault("targets", {})

    # -- Plex --
    url = fields["plex_base_url"]
    token = fields["plex_token"]
    token_env = fields["plex_token_env"]
    if url and (token or token_env):
        plex_cfg = targets.setdefault("plex", {})
        plex_cfg["base_url"] = url
        for key, value in (("token", token), ("token_env", token_env),
                           ("music_section", fields["plex_music_section"])):
            if value:
                plex_cfg[key] = value
            else:
                plex_cfg.pop(key, None)
        plex_cfg["path_rules"] = fields["plex_path_rules"]
    else:
        # Clearing the URL or both token fields removes the target, as it
        # did before.
        targets.pop("plex", None)

    # -- M3U --
    m3u_cfg = targets.setdefault("m3u", {})
    m3u_cfg["path_style"] = fields["m3u_path_style"]
    m3u_cfg["path_rules"] = fields["m3u_path_rules"]

    # -- Database -- (stored in config.json, takes effect on restart)
    _apply_database_fields(new_config, fields)

    return new_config


class DialogsMixin:
    def _show_help(self, section=None):
        """Open or focus the help window, optionally jumping to a section.

        The help window is deliberately non-modal so the app stays usable
        beside it. That works when help is opened from the main window,
        which holds no grab \u2014 but v3.8 added help buttons to the Find
        Similar popup, and that popup *does* grab. A non-modal window
        opened underneath a grab receives no events at all: the help text
        appeared and then refused to scroll, and none of its navigation
        buttons responded.

        So whatever holds the grab gives it up while help is open, and
        takes it back when help closes. Same shape as filedialog releasing
        the caller's grab around an external chooser.
        """
        grabbed = self.root.grab_current()
        if grabbed is not None:
            grabbed.grab_release()

        def restore_grab():
            """Hand the grab back to whoever had it, if it still wants it."""
            try:
                if (grabbed is not None and grabbed.winfo_exists()
                        and grabbed.winfo_viewable()):
                    grabbed.grab_set()
            except tk.TclError:                     # pragma: no cover
                pass

        if self._help_window and self._help_window.winfo_exists():
            self._help_window.lift()
            self._help_window.focus_force()
            if section:
                self._help_jump(section)
            # An already-open help window can still be unreachable: it may
            # have been opened from the main window before the grabbing
            # popup existed. The release above fixes that; hand the grab
            # back when this help window eventually closes, not now.
            self._help_restore_grab = restore_grab
            return

        win = tk.Toplevel(self.root)
        win.title("Help \u2014 Classical Music Playlist Manager")
        win.transient(self.root)
        self._center_on_main(win, 720, 720)
        # Non-modal: no grab_set() so main app stays interactive

        self._help_window = win
        self._help_restore_grab = restore_grab

        def on_close():
            self._help_window = None
            restore = getattr(self, "_help_restore_grab", None)
            self._help_restore_grab = None
            win.destroy()
            if restore:
                restore()

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

        from music_manager.core.config import (load_config, DEFAULT_CONFIG_PATH,
                                               ConfigError)

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
        bind_wheel_scroll(frame)

        row = 0

        # Rows belonging to a backend panel, so they can be hidden when the
        # other backend is chosen. Everything is built in the one grid:
        # a nested frame per backend would have its own column widths, and
        # the labels would not line up with the rest of the dialog.
        panel_rows = None

        def track(*widgets):
            if panel_rows is not None:
                panel_rows.extend(widgets)

        def add_section(label):
            nonlocal row
            ctk.CTkLabel(frame, text=label,
                         font=ctk.CTkFont(size=14, weight="bold")).grid(
                row=row, column=0, columnspan=3, sticky="w",
                padx=10, pady=(12, 4))
            row += 1

        def add_field(label, value="", width=400, show=None):
            nonlocal row
            caption = ctk.CTkLabel(frame, text=label)
            caption.grid(row=row, column=0, sticky="w", padx=(20, 5), pady=3)
            entry = ctk.CTkEntry(frame, width=width,
                                 **({"show": show} if show else {}))
            entry.grid(row=row, column=1, columnspan=2, sticky="w",
                       padx=5, pady=3)
            if value:
                entry.insert(0, str(value))
            track(caption, entry)
            row += 1
            return entry

        def add_note(text, padx=30):
            """A greyed-out line of explanation under the row above it."""
            nonlocal row
            note = ctk.CTkLabel(frame, text=text, text_color="gray",
                                wraplength=560, justify="left",
                                font=ctk.CTkFont(size=11))
            note.grid(row=row, column=0, columnspan=3, sticky="w",
                      padx=padx, pady=(0, 2))
            track(note)
            row += 1
            return note

        def add_browse_field(label, value="", width=310):
            """A text field with a Browse button beside it.

            The entry and the button share one cell, in their own frame.
            Gridding the button into column 2 put it off the right edge:
            the plain add_field rows span columns 1-2 with a 400px entry,
            which stretches column 2 past the visible width of the
            scrollable frame, and there is no horizontal scrollbar to
            reach it.  Nothing here depends on column widths now.
            """
            nonlocal row
            caption = ctk.CTkLabel(frame, text=label)
            caption.grid(row=row, column=0, sticky="w", padx=(20, 5), pady=3)

            holder = ctk.CTkFrame(frame, fg_color="transparent")
            holder.grid(row=row, column=1, columnspan=2, sticky="w",
                        padx=5, pady=3)
            entry = ctk.CTkEntry(holder, width=width)
            entry.pack(side="left")
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

            ctk.CTkButton(holder, text="Browse…", width=80,
                          command=browse).pack(side="left", padx=(6, 0))
            track(caption, holder)
            row += 1
            return entry

        # -- Database --
        add_section("Database")
        from music_manager.core.config import (DEFAULT_DB_CHARSET,
                                               DEFAULT_DB_PORT)
        from music_manager.core.database import DATABASE_PATH

        db_cfg = config.get("database")
        if not isinstance(db_cfg, dict):
            db_cfg = {}
        current_backend = db_cfg.get("backend", "sqlite")
        # The path in use, by the same precedence resolve_db_settings
        # applies. Reading it from the config directly rather than
        # resolving keeps the dialog openable when the settings are the
        # thing that is broken — a password_env naming an unset variable
        # raises, and this is where you would come to fix it.
        current_path = db_cfg.get("path") or config.get("db_path") or DATABASE_PATH

        ctk.CTkLabel(frame, text="Backend").grid(
            row=row, column=0, sticky="w", padx=(20, 5), pady=3)
        backend_box = ctk.CTkComboBox(frame, values=list(BACKEND_LABELS.values()),
                                      width=260, state="readonly")
        backend_box.grid(row=row, column=1, columnspan=2, sticky="w",
                         padx=5, pady=3)
        backend_box.set(BACKEND_LABELS[current_backend])
        row += 1

        sqlite_rows = []
        panel_rows = sqlite_rows
        db_entry = add_browse_field("Database File", current_path)
        default_note = add_note(
            "This is the default, so it is not written to config.json — each "
            "install opens the database beside it. Choose any other path and "
            "it is stored.")

        def refresh_default_note(*_):
            """Say when a save will deliberately store nothing.

            Saving the default path would pin one checkout's location into
            config.json, so it is left out — which looks like the setting
            was ignored unless the dialog says otherwise.
            """
            chosen = db_entry.get().strip()
            if chosen and Path(chosen) != DATABASE_PATH:
                default_note.grid_remove()
            else:
                default_note.grid()

        # A trace rather than a key binding: Browse… fills the field in
        # without the keyboard ever touching it.
        db_path_var = tk.StringVar(value=str(current_path))
        db_entry.configure(textvariable=db_path_var)
        db_path_var.trace_add("write", refresh_default_note)

        mysql_rows = []
        panel_rows = mysql_rows
        db_host = add_field("Host", db_cfg.get("host", ""))
        db_port = add_field("Port", db_cfg.get("port", DEFAULT_DB_PORT),
                            width=100)
        db_name = add_field("Database", db_cfg.get("name", ""))
        db_user = add_field("User", db_cfg.get("user", ""))
        # Only a password written in config.json is shown. One taken from
        # the environment stays there: displaying it would copy the secret
        # into the file on the next save.
        db_password = add_field("Password", db_cfg.get("password", ""),
                                show="•")
        db_password_env = add_field("Password Env Var",
                                    db_cfg.get("password_env", ""))
        add_note("Env var wins when it is set, so a shared config need not "
                 "carry the password.")
        db_charset = add_field("Charset",
                               db_cfg.get("charset", DEFAULT_DB_CHARSET),
                               width=150)

        def test_connection():
            """Try the entered settings without saving them."""
            port = db_port.get().strip()
            if not port.isdigit():
                messagebox.showerror("Database", "Port must be a number.",
                                     parent=dlg)
                return
            name = db_name.get().strip()
            if not name:
                messagebox.showerror("Database",
                                     "Enter the database name first.",
                                     parent=dlg)
                return

            import os
            password = db_password.get()
            env_name = db_password_env.get().strip()
            if env_name and os.environ.get(env_name):
                password = os.environ[env_name]

            params = dict(host=db_host.get().strip() or "localhost",
                          port=int(port), user=db_user.get().strip(),
                          password=password, database=name,
                          charset=db_charset.get().strip() or DEFAULT_DB_CHARSET,
                          connect_timeout=5)
            test_btn.configure(state="disabled", text="Testing…")

            def finished(error):
                if not dlg.winfo_exists():
                    return
                test_btn.configure(state="normal", text="Test Connection")
                if error:
                    messagebox.showerror(
                        "Database", f"Could not connect:\n\n{error}",
                        parent=dlg)
                else:
                    messagebox.showinfo("Database", "Connected successfully.",
                                        parent=dlg)

            def worker():
                # An unreachable host blocks for the whole timeout, so this
                # cannot run on the UI thread.
                error = None
                try:
                    import pymysql
                    pymysql.connect(**params).close()
                except Exception as exc:
                    error = exc
                dlg.after(0, lambda: finished(error))

            threading.Thread(target=worker, daemon=True).start()

        test_btn = ctk.CTkButton(frame, text="Test Connection", width=140,
                                 command=test_connection)
        test_btn.grid(row=row, column=1, sticky="w", padx=5, pady=(6, 3))
        track(test_btn)
        row += 1
        panel_rows = None

        def selected_backend():
            label = backend_box.get()
            for key, text in BACKEND_LABELS.items():
                if text == label:
                    return key
            return "sqlite"

        def show_backend(_=None):
            """Show the chosen backend's rows and hide the other's.

            grid_remove keeps each row's placement, so the rows come back
            where they were, and an emptied row collapses to nothing —
            no gap where the hidden panel used to be.
            """
            mysql = selected_backend() == "mysql"
            for widget in (sqlite_rows if mysql else mysql_rows):
                widget.grid_remove()
            for widget in (mysql_rows if mysql else sqlite_rows):
                widget.grid()
            if not mysql:
                # Restoring the panel re-grids every row, note included.
                refresh_default_note()

        backend_box.configure(command=show_backend)
        show_backend()

        add_note("Changing this opens a different database — it does not copy "
                 "anything across. Use the migrate-db command to move an "
                 "existing library.")

        # -- Plex --
        add_section("Plex")
        plex_url = add_field("Server URL", plex.get("base_url", ""))
        plex_token = add_field("Token", plex.get("token", ""))
        plex_token_env = add_field("Token Env Var",
                                   plex.get("token_env", ""))
        plex_section_default = add_field("Default Section",
                                         plex.get("music_section", ""))
        add_note("(Per-library section in sidebar overrides this)")

        # Plex path rules
        add_section("Plex Path Rules")
        add_note("One per line:  find -> replace", padx=20)
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

        # M3U path rules
        add_section("M3U Path Rules")
        add_note("One per line:  find -> replace", padx=20)
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
            fields = {
                "plex_base_url": plex_url.get().strip(),
                "plex_token": plex_token.get().strip(),
                "plex_token_env": plex_token_env.get().strip(),
                "plex_music_section": plex_section_default.get().strip(),
                "plex_path_rules": parse_rules(plex_rules_text),
                "m3u_path_style": m3u_style.get(),
                "m3u_path_rules": parse_rules(m3u_rules_text),
                "db_backend": selected_backend(),
                "db_path": db_entry.get().strip(),
                "db_host": db_host.get().strip(),
                "db_port": db_port.get().strip(),
                "db_name": db_name.get().strip(),
                "db_user": db_user.get().strip(),
                "db_password": db_password.get(),
                "db_password_env": db_password_env.get().strip(),
                "db_charset": db_charset.get().strip(),
            }
            new_config = apply_settings_fields(config, fields)

            # Compare what the app would connect to, not the raw section:
            # writing 'database' for the first time rewrites keys without
            # changing the database, and a restart prompt for that would be
            # noise. Settings too broken to resolve count as changed.
            from music_manager.core.config import resolve_db_settings
            try:
                db_changed = (resolve_db_settings(new_config)
                              != resolve_db_settings(config))
            except Exception:
                db_changed = True

            # Check it before writing it: an invalid config.json stops the
            # app loading at all, and finding that out on the next start is
            # far worse than a message here.
            from music_manager.core.config import validate_config
            try:
                validate_config(new_config)
            except ConfigError as exc:
                messagebox.showerror(
                    "Settings", f"Not saved — these settings are not valid:"
                                f"\n\n{exc}", parent=dlg)
                return

            # Write config.json
            from music_manager.core.config import save_config
            save_config(new_config)

            if db_changed:
                messagebox.showinfo(
                    "Restart Required",
                    "The database settings changed. Restart the app for them "
                    "to take effect.",
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
        bind_wheel_scroll(check_frame)

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
            data = json.loads(Path(path).read_text(encoding="utf-8"))
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
                lines = Path(filepath).read_text(
                    encoding="utf-8").strip().splitlines()
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
