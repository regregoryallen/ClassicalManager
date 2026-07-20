"""GUI interface using customtkinter (§10).

Provides the main application window with:
  - Sidebar: library selector, metrics, rescan button
  - Tab 1: Explorer & Rules (albums, works, include/exclude)
  - Tab 2: Playlist Builder (modes, preview, export, push)
  - Tab 3: Cleanup / Overlay (work review, overrides, import/export)

Treeview note: customtkinter has no native tree widget.  Uses styled
ttk.Treeview themed to approximate the customtkinter palette.
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

logger = logging.getLogger(__name__)

_PREFS_PATH = Path(__file__).resolve().parent.parent.parent / "gui_prefs.json"


def _load_prefs() -> dict:
    """Load GUI preferences from disk."""
    try:
        return json.loads(_PREFS_PATH.read_text())
    except Exception:
        return {}


def _save_prefs(prefs: dict) -> None:
    """Persist GUI preferences to disk."""
    try:
        _PREFS_PATH.write_text(json.dumps(prefs, indent=2))
    except Exception:
        logger.debug("Could not save GUI prefs", exc_info=True)


class _ScanCancelled(Exception):
    """Raised inside the scan progress callback to abort a running scan."""


class _GUILogHandler(logging.Handler):
    """Logging handler that writes to a StringIO buffer for GUI display."""

    def __init__(self):
        super().__init__()
        self.buffer = io.StringIO()

    def emit(self, record):
        try:
            self.buffer.write(self.format(record) + "\n")
        except Exception:
            self.handleError(record)

    def get_text(self):
        return self.buffer.getvalue()

    def clear(self):
        self.buffer = io.StringIO()


def launch_gui():
    """Launch the main GUI window."""
    try:
        import customtkinter as ctk
    except ImportError:
        print("Error: customtkinter is required for the GUI. "
              "Install it with: pip install customtkinter")
        return

    from music_manager.core.database import initialize_database
    from music_manager.core.config import get_db_path
    prefs = _load_prefs()

    # Migrate db_path from gui_prefs.json to config.json (one-time)
    if "db_path" in prefs:
        try:
            from music_manager.core.config import load_config, save_config
            cfg = load_config()
            if "db_path" not in cfg:
                cfg["db_path"] = prefs["db_path"]
                save_config(cfg)
            del prefs["db_path"]
            _save_prefs(prefs)
        except Exception:
            pass

    db_path = get_db_path()
    try:
        initialize_database(db_path)
    except Exception as exc:
        import tkinter as _tk
        _tk.Tk().withdraw()
        from tkinter import messagebox as _mb
        from music_manager.core.database import DATABASE_PATH
        msg = (f"Cannot open database:\n{db_path}\n\n"
               f"Error: {exc}\n\n"
               f"Possible causes:\n"
               f"  - The app is open on another machine (database locked)\n"
               f"  - The network share or drive is not mounted\n"
               f"  - The path in config.json is incorrect\n\n"
               f"Close the app on other machines and ensure the path is "
               f"accessible, or update db_path in config.json.\n\n"
               f"Fall back to the local default database?")
        if _mb.askyesno("Database Error", msg):
            initialize_database(DATABASE_PATH)
        else:
            return

    # Set up logging to capture output for the GUI log viewer
    log_handler = _GUILogHandler()
    log_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S"))
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    log_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(log_handler)


    app = App(ctk, log_handler=log_handler)
    app.mainloop()


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class App:
    """Main application window."""

    def __init__(self, ctk, log_handler=None):
        self.ctk = ctk
        self._log_handler = log_handler
        self.root = ctk.CTk(className="classical-manager")
        self.root.title("Classical Music Playlist Manager")

        # Set window / taskbar icon (platform-specific)
        self._setup_app_icon()

        self._prefs = _load_prefs()
        self.root.geometry(self._prefs.get("window_geometry", "1280x800"))

        self.active_library = None
        self._current_selections = []  # in-memory selections: [{level, key, excluded, pin_position, track_paths, display}]
        self._profile_picker_open = False
        self._lib_tree_snapshot = []  # snapshot for filter/detach
        self._pl_tree_snapshot = []
        self._lib_search_meta = {}   # iid → searchable text for builder lib tree
        self._pl_search_meta = {}    # iid → searchable text for builder pl tree
        self._tree_sort_state = {}     # tree id → (column, reverse)
        self._help_window = None       # singleton help window
        self._autosave_after_id = None # repeating timer for autosave

        self._setup_theme()
        self._build_layout()
        self.root.update_idletasks()  # ensure all widgets render before loading data
        self._refresh_library_list()
        self._start_autosave_timer()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_app_icon(self):
        """Set the app icon for the window titlebar and taskbar.

        Linux/X11: wm_iconphoto sets the titlebar icon; a .desktop file is
        installed to ~/.local/share/applications/ so that GNOME/KDE show the
        correct icon and tooltip in the taskbar.
        Windows: Sets AppUserModelID so the taskbar shows our icon instead of
        the generic Python icon, then uses wm_iconbitmap if an .ico exists
        or falls back to wm_iconphoto.
        """
        icon_path = Path(__file__).resolve().parent.parent.parent / "app_icon.png"
        if not icon_path.exists():
            return

        _sys = platform.system()

        if _sys == "Windows":
            # Give the app its own taskbar identity (not grouped with python.exe)
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "ClassicalManager.App")
            except Exception:
                pass
            # Prefer .ico for Windows taskbar; fall back to wm_iconphoto
            ico_path = icon_path.with_suffix(".ico")
            if ico_path.exists():
                self.root.iconbitmap(str(ico_path))
            else:
                self._icon_img = tk.PhotoImage(file=str(icon_path))
                self.root.wm_iconphoto(True, self._icon_img)
        else:
            # Linux / macOS: wm_iconphoto for the titlebar
            self._icon_img = tk.PhotoImage(file=str(icon_path))
            self.root.wm_iconphoto(True, self._icon_img)

        if _sys == "Linux":
            self._install_desktop_entry(icon_path)

    def _install_desktop_entry(self, icon_path):
        """Create/update a .desktop file for taskbar icon and tooltip on Linux."""
        desktop_dir = Path.home() / ".local" / "share" / "applications"
        desktop_file = desktop_dir / "classical-manager.desktop"
        main_py = Path(__file__).resolve().parent.parent.parent / "main.py"
        venv_python = Path(sys.executable)

        entry = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Classical Manager\n"
            "Comment=Classical-aware music playlist manager\n"
            f"Exec={venv_python} {main_py}\n"
            f"Icon={icon_path}\n"
            "Terminal=false\n"
            "Categories=AudioVideo;Audio;Music;\n"
            "StartupWMClass=classical-manager\n"
        )

        try:
            desktop_dir.mkdir(parents=True, exist_ok=True)
            # Only write if content changed
            if desktop_file.exists() and desktop_file.read_text() == entry:
                return
            desktop_file.write_text(entry)
        except OSError as exc:
            logger.debug("Could not install .desktop file: %s", exc)

    def _on_close(self):
        """Save window state, autosave, and exit."""
        self._autosave()
        self._prefs["window_geometry"] = self.root.geometry()
        _save_prefs(self._prefs)
        self.root.destroy()

    # ------------------------------------------------------------------
    # Autosave (§2a)
    # ------------------------------------------------------------------

    def _start_autosave_timer(self):
        """Start the repeating autosave timer based on config interval."""
        from music_manager.core.config import load_config, ConfigError
        try:
            config = load_config()
        except ConfigError:
            config = {}
        interval = config.get("autosave_interval", 60)
        if not interval or interval <= 0:
            return
        interval_ms = int(interval) * 1000

        def tick():
            self._autosave()
            self._autosave_after_id = self.root.after(interval_ms, tick)

        self._autosave_after_id = self.root.after(interval_ms, tick)

    def _autosave(self):
        """Silently save current builder state as an __autosave__ profile."""
        if not self.active_library:
            return
        from music_manager.core.database import PlaylistProfile, ProfileSelection

        # Delete existing autosave for this library (CASCADE deletes selections)
        for existing in PlaylistProfile.select().where(
            (PlaylistProfile.library == self.active_library) &
            (PlaylistProfile.name == "__autosave__")
        ):
            existing.delete_instance()

        # Capture current UI state
        length_val = self.length_value.get().strip()
        seed_val = self.seed_entry.get().strip()
        profile_name = self.profile_name_entry.get().strip()

        profile = PlaylistProfile.create(
            library=self.active_library,
            name="__autosave__",
            shuffle_mode=self.shuffle_mode.get(),
            work_integrity=self.work_integrity.get(),
            length_mode=self.length_mode.get(),
            length_value=self._parse_length_value(length_val),
            seed=int(seed_val) if seed_val else None,
            no_repeat_tracks=self.no_repeat_var.get() == 1,
            separate_composers=self.sep_composer_var.get() == 1,
            separate_albums=self.sep_album_var.get() == 1,
            separate_forms=self.sep_form_var.get() == 1,
        )

        for sel in self._current_selections:
            ProfileSelection.create(
                profile=profile,
                level=sel["level"],
                key=sel["key"],
                excluded=sel["excluded"],
                pin_position=sel.get("pin_position"),
                track_paths=sel.get("track_paths"),
            )

        # Remember the profile name entry text separately
        self._prefs["autosave_profile_name"] = profile_name
        _save_prefs(self._prefs)
        logger.debug("Autosaved builder state for library %s",
                     self.active_library.name)

    def _restore_autosave(self):
        """Silently restore an autosaved profile if one exists."""
        if not self.active_library:
            return
        from music_manager.core.database import PlaylistProfile
        autosave = PlaylistProfile.select().where(
            (PlaylistProfile.library == self.active_library) &
            (PlaylistProfile.name == "__autosave__")
        ).first()
        if not autosave:
            return
        self._apply_profile("__autosave__")
        # Restore the user's actual profile name (not "__autosave__")
        saved_name = self._prefs.get("autosave_profile_name", "")
        self.profile_name_entry.delete(0, "end")
        if saved_name:
            self.profile_name_entry.insert(0, saved_name)
        logger.debug("Restored autosave for library %s",
                     self.active_library.name)

    def _clear_autosave(self):
        """Delete the autosave profile for the active library."""
        if not self.active_library:
            return
        from music_manager.core.database import PlaylistProfile
        for existing in PlaylistProfile.select().where(
            (PlaylistProfile.library == self.active_library) &
            (PlaylistProfile.name == "__autosave__")
        ):
            existing.delete_instance()  # CASCADE deletes selections

    def mainloop(self):
        """Start the Tk event loop."""
        self.root.mainloop()

    def _center_on_main(self, window, width=400, height=300):
        """Position a toplevel window centered on the main window."""
        self.root.update_idletasks()
        mx = self.root.winfo_x() + self.root.winfo_width() // 2
        my = self.root.winfo_y() + self.root.winfo_height() // 2
        x = mx - width // 2
        y = my - height // 2
        window.geometry(f"{width}x{height}+{x}+{y}")

    def _play_track(self, track_id):
        """Open a track's audio file in the system default player."""
        import subprocess
        from music_manager.core.database import Track
        try:
            track = Track.get_by_id(track_id)
            file_path = Path(track.folder.root_path) / track.relative_path
            if not file_path.exists():
                messagebox.showerror("File Not Found", f"File not found:\n{file_path}")
                return
            _sys = platform.system()
            if _sys == "Windows":
                import os
                os.startfile(str(file_path))
            elif _sys == "Darwin":
                subprocess.Popen(["open", str(file_path)])
            else:
                subprocess.Popen(["xdg-open", str(file_path)])
        except Exception as exc:
            messagebox.showerror("Playback Error", str(exc))

    @contextmanager
    def _busy(self):
        """Show a wait/watch cursor while a blocking operation runs.

        On Windows, Tk doesn't propagate the cursor from the root to child
        widgets, so we set it on every widget in the tree.
        """
        cursor = "wait" if platform.system() == "Windows" else "watch"
        self._set_cursor(cursor)
        self.root.update()
        try:
            yield
        finally:
            self._set_cursor("")
            self.root.update_idletasks()

    def _set_cursor(self, cursor):
        """Set cursor on all widgets (needed for Windows propagation)."""
        def _apply(widget):
            try:
                widget.configure(cursor=cursor)
            except Exception:
                pass
            for child in widget.winfo_children():
                _apply(child)
        _apply(self.root)

    def _setup_theme(self):
        """Configure ttk.Treeview style to blend with customtkinter."""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        background="#2b2b2b", foreground="white",
                        fieldbackground="#2b2b2b", rowheight=25,
                        font=("Segoe UI", 11))
        style.configure("Treeview.Heading",
                        background="#3b3b3b", foreground="white",
                        font=("Segoe UI", 11, "bold"))
        style.map("Treeview",
                  background=[("selected", "#1f6aa5")],
                  foreground=[("selected", "white")])

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self):
        """Build the main window layout: sidebar + tabbed content."""
        ctk = self.ctk

        # Sidebar
        self.sidebar = ctk.CTkFrame(self.root, width=260, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self._build_sidebar()

        # Content area with tabs
        self.tabview = ctk.CTkTabview(self.root)
        self.tabview.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        self.tab_builder = self.tabview.add("Playlist Builder")
        self.tab_explorer = self.tabview.add("Explorer & Rules")
        self.tab_cleanup = self.tabview.add("Cleanup / Overlay")

        self._build_builder_tab()
        self._build_explorer_tab()
        self._build_cleanup_tab()

    # ------------------------------------------------------------------
    # Sidebar (§10)
    # ------------------------------------------------------------------

    def _build_sidebar(self):
        """Build sidebar: library selector, metrics, rescan, manage."""
        ctk = self.ctk

        ctk.CTkLabel(self.sidebar, text="Library",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
            padx=15, pady=(15, 5), anchor="w")

        self.lib_combo = ctk.CTkComboBox(self.sidebar, values=["(none)"],
                                         command=self._on_library_changed,
                                         width=230)
        self.lib_combo.pack(padx=15, pady=5)

        # Library management buttons — row 1
        btn_frame1 = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        btn_frame1.pack(padx=15, pady=(5, 2), fill="x")
        ctk.CTkButton(btn_frame1, text="New", width=72,
                      command=self._new_library).pack(side="left", padx=(0, 3))
        ctk.CTkButton(btn_frame1, text="Rename", width=72,
                      command=self._rename_library).pack(side="left", padx=(0, 3))
        ctk.CTkButton(btn_frame1, text="Delete", width=72,
                      fg_color="#7d2d2d",
                      command=self._delete_library).pack(side="left")

        # Library management buttons — row 2
        btn_frame2 = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        btn_frame2.pack(padx=15, pady=2, fill="x")
        ctk.CTkButton(btn_frame2, text="Export Lib", width=110,
                      command=self._export_library).pack(side="left", padx=(0, 5))
        ctk.CTkButton(btn_frame2, text="Import Lib", width=110,
                      command=self._import_library).pack(side="left")

        # Metrics
        ctk.CTkLabel(self.sidebar, text="Metrics",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=15, pady=(12, 3), anchor="w")

        self.lbl_albums = ctk.CTkLabel(self.sidebar, text="Albums: -")
        self.lbl_albums.pack(padx=20, anchor="w")
        self.lbl_works = ctk.CTkLabel(self.sidebar, text="Works: -")
        self.lbl_works.pack(padx=20, anchor="w")
        self.lbl_tracks = ctk.CTkLabel(self.sidebar, text="Tracks: -")
        self.lbl_tracks.pack(padx=20, anchor="w")
        self.lbl_composers = ctk.CTkLabel(self.sidebar, text="Composers: -")
        self.lbl_composers.pack(padx=20, anchor="w")

        # Scan button + progress
        self.scan_btn = ctk.CTkButton(self.sidebar, text="Rescan Library",
                                      command=self._start_scan)
        self.scan_btn.pack(padx=15, pady=(12, 3), fill="x")

        self.scan_progress = ctk.CTkProgressBar(self.sidebar, width=230)
        self.scan_progress.pack(padx=15, pady=3)
        self.scan_progress.set(0)

        self.scan_status = ctk.CTkLabel(self.sidebar, text="")
        self.scan_status.pack(padx=15, anchor="w")

        ctk.CTkButton(self.sidebar, text="Scan Changes",
                      command=self._scan_changes).pack(
            padx=15, pady=(3, 0), fill="x")

        ctk.CTkButton(self.sidebar, text="Re-detect Works",
                      command=self._redetect_works).pack(
            padx=15, pady=(3, 0), fill="x")

        ctk.CTkButton(self.sidebar, text="Library Integrity Check",
                      command=self._run_integrity_check).pack(
            padx=15, pady=(3, 0), fill="x")

        ctk.CTkButton(self.sidebar, text="Profile Summary",
                      command=self._show_profile_summary).pack(
            padx=15, pady=(3, 0), fill="x")

        ctk.CTkButton(self.sidebar, text="Track Similarity",
                      command=self._show_similarity).pack(
            padx=15, pady=(3, 0), fill="x")

        # Source folders
        folder_hdr = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        folder_hdr.pack(padx=15, pady=(12, 3), fill="x")
        ctk.CTkLabel(folder_hdr, text="Source Folders",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            side="left")

        folder_btns = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        folder_btns.pack(padx=15, pady=2, fill="x")
        ctk.CTkButton(folder_btns, text="Add Folder", width=110,
                      command=self._add_source_folder).pack(side="left", padx=(0, 5))
        ctk.CTkButton(folder_btns, text="Remove Folder", width=110,
                      command=self._remove_source_folder).pack(side="left")

        self.folders_listbox = tk.Listbox(self.sidebar, height=5,
                                          bg="#2b2b2b", fg="white",
                                          selectbackground="#1f6aa5",
                                          font=("Segoe UI", 9))
        self.folders_listbox.pack(padx=15, pady=3, fill="x")

        # Plex section mapping
        plex_hdr = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        plex_hdr.pack(padx=15, pady=(12, 2), fill="x")
        ctk.CTkLabel(plex_hdr, text="Plex Section",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            side="left")
        self.plex_section_entry = ctk.CTkEntry(
            self.sidebar, width=230,
            placeholder_text="e.g. MainMusic")
        self.plex_section_entry.pack(padx=15, pady=2)
        self.plex_section_entry.bind("<FocusOut>", self._save_plex_section)
        self.plex_section_entry.bind("<Return>", self._save_plex_section)

        # Import old playlists
        ctk.CTkButton(self.sidebar, text="Import Old Playlists...",
                      width=230, command=self._import_old_playlists).pack(
            padx=15, pady=(12, 5))

        # Spacer to push bottom buttons down
        ctk.CTkLabel(self.sidebar, text="").pack(expand=True)

        # Bottom buttons
        bottom_btns = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        bottom_btns.pack(fill="x", padx=15, pady=(5, 15))
        ctk.CTkButton(bottom_btns, text="Settings", width=72,
                      fg_color="gray30", hover_color="gray40",
                      command=self._show_settings).pack(side="left", padx=(0, 4))
        ctk.CTkButton(bottom_btns, text="View Logs", width=72,
                      fg_color="gray30", hover_color="gray40",
                      command=self._show_log_viewer).pack(side="left", padx=(0, 4))
        ctk.CTkButton(bottom_btns, text="Help", width=72,
                      fg_color="gray30", hover_color="gray40",
                      command=self._show_help).pack(side="left")

    def _refresh_library_list(self):
        """Reload the library dropdown from the database."""
        from music_manager.core.database import Library, PlaylistProfile
        # Clean up any leftover temp profiles (CASCADE deletes selections)
        for temp in PlaylistProfile.select().where(
                PlaylistProfile.name.startswith("__")):
            temp.delete_instance()
        libs = list(Library.select())
        names = [lib.name for lib in libs]
        self.lib_combo.configure(values=names if names else ["(none)"])
        if libs:
            last = self._prefs.get("last_library")
            default = last if last in names else libs[0].name
            self.lib_combo.set(default)
            self._on_library_changed(default)
        else:
            self.lib_combo.set("(none)")
            self.active_library = None

    def _on_library_changed(self, name):
        """Handle library selection change."""
        from music_manager.core.database import Library
        if name == "(none)":
            self.active_library = None
            self.plex_section_entry.delete(0, "end")
            return
        try:
            self.active_library = Library.get(Library.name == name)
        except Library.DoesNotExist:
            self.active_library = None
            self.plex_section_entry.delete(0, "end")
            return
        # Remember last-used library
        self._prefs["last_library"] = name
        _save_prefs(self._prefs)
        self._save_active_library_to_config()
        # Populate plex section from library
        self.plex_section_entry.delete(0, "end")
        if self.active_library.plex_section:
            self.plex_section_entry.insert(0, self.active_library.plex_section)
        with self._busy():
            self._new_profile()
            self._refresh_metrics()
            self._refresh_source_folders()
            self._refresh_explorer()
            self._refresh_builder_tree()
            self._refresh_cleanup()
            self._restore_autosave()

    def _save_active_library_to_config(self):
        """Persist the current active_library ID to config.json."""
        try:
            from music_manager.core.config import load_config, save_config
            config = load_config()
            config["active_library"] = self.active_library.id if self.active_library else 0
            save_config(config)
        except Exception:
            pass  # non-critical — GUI still works

    def _refresh_metrics(self):
        """Update sidebar metric counts."""
        if not self.active_library:
            for lbl in (self.lbl_albums, self.lbl_works, self.lbl_tracks, self.lbl_composers):
                lbl.configure(text=lbl.cget("text").split(":")[0] + ": -")
            return

        from music_manager.core.database import Album, Work, Track, Composer
        lib = self.active_library

        album_count = Album.select().where(Album.library == lib).count()
        work_count = Work.select().join(Album).where(Album.library == lib).count()
        track_count = Track.select().where(Track.library == lib).count()
        composer_count = Composer.select().where(Composer.library == lib).count()

        self.lbl_albums.configure(text=f"Albums: {album_count}")
        self.lbl_works.configure(text=f"Works: {work_count}")
        self.lbl_tracks.configure(text=f"Tracks: {track_count}")
        self.lbl_composers.configure(text=f"Composers: {composer_count}")

    def _refresh_source_folders(self):
        """Update the source folders display."""
        self.folders_listbox.delete(0, "end")
        self._folder_ids = []
        if self.active_library:
            from music_manager.core.database import SourceFolder
            for sf in SourceFolder.select().where(
                SourceFolder.library == self.active_library
            ):
                self.folders_listbox.insert("end", sf.root_path)
                self._folder_ids.append(sf.id)

    def _save_plex_section(self, event=None):
        """Persist the Plex section name to the active library."""
        if not self.active_library:
            return
        value = self.plex_section_entry.get().strip()
        self.active_library.plex_section = value or ""
        self.active_library.save()

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
            ("Explorer", "explorer"),
            ("Builder", "builder"),
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
        from music_manager.core.database import DATABASE_PATH
        db_entry = add_browse_field("Database File",
                                    config.get("db_path",
                                               str(DATABASE_PATH)))

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

            # Database path (stored in config.json, requires restart)
            new_db = db_entry.get().strip()
            current_db = config.get("db_path", str(DATABASE_PATH))
            if new_db and new_db != current_db:
                new_config["db_path"] = new_db
                db_changed = True
            elif config.get("db_path"):
                new_config["db_path"] = config["db_path"]
                db_changed = False
            else:
                db_changed = False

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

    def _new_library(self):
        """Create a new library via dialog."""
        ctk = self.ctk
        dialog = ctk.CTkInputDialog(text="Library name:", title="New Library")
        # Center the dialog on the main window
        dialog.after(10, lambda: self._center_on_main(dialog, 300, 200))
        name = dialog.get_input()
        if not name or not name.strip():
            return
        from music_manager.core.database import Library
        lib = Library.create(name=name.strip())
        self._refresh_library_list()
        # Auto-select the newly created library
        self.lib_combo.set(lib.name)
        self._on_library_changed(lib.name)

    def _rename_library(self):
        """Rename the active library."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return
        ctk = self.ctk
        dialog = ctk.CTkInputDialog(
            text=f"Rename '{self.active_library.name}' to:",
            title="Rename Library")
        dialog.after(10, lambda: self._center_on_main(dialog, 300, 200))
        name = dialog.get_input()
        if not name or not name.strip():
            return
        self.active_library.name = name.strip()
        self.active_library.save()
        self._refresh_library_list()
        self.lib_combo.set(name.strip())
        self._on_library_changed(name.strip())

    def _delete_library(self):
        """Delete the active library after confirmation."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return
        ok = messagebox.askyesno(
            "Delete Library",
            f"Delete library '{self.active_library.name}' and all its data?\n"
            f"This cannot be undone.",
            parent=self.root)
        if not ok:
            return
        from music_manager.core.database import (
            SourceFolder, Album, Work, Track, Composer, Override,
            PlaylistProfile,
        )
        lib = self.active_library
        # Delete child records (CASCADE deletes selections)
        PlaylistProfile.delete().where(PlaylistProfile.library == lib).execute()
        Override.delete().where(Override.library == lib).execute()
        Track.delete().where(Track.library == lib).execute()
        Work.select().join(Album).where(Album.library == lib)
        for album in Album.select().where(Album.library == lib):
            Work.delete().where(Work.album == album).execute()
        Album.delete().where(Album.library == lib).execute()
        Composer.delete().where(Composer.library == lib).execute()
        SourceFolder.delete().where(SourceFolder.library == lib).execute()
        lib.delete_instance()
        self.active_library = None
        self._refresh_library_list()
        # Update active_library in config so CLI/webhook don't reference deleted ID
        self._save_active_library_to_config()

    def _add_source_folder(self):
        """Add a source folder to the active library."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select or create a library first.")
            return
        folder = filedialog.askdirectory(title="Select Source Folder",
                                         parent=self.root)
        if not folder:
            return
        from music_manager.core.database import SourceFolder
        posix = folder.replace("\\", "/")
        SourceFolder.create(library=self.active_library, root_path=posix)
        self._refresh_source_folders()

    def _remove_source_folder(self):
        """Remove the selected source folder."""
        sel = self.folders_listbox.curselection()
        if not sel:
            messagebox.showinfo("Select", "Select a folder to remove.")
            return
        idx = sel[0]
        if idx >= len(self._folder_ids):
            return
        folder_id = self._folder_ids[idx]
        folder_path = self.folders_listbox.get(idx)
        ok = messagebox.askyesno(
            "Remove Folder",
            f"Remove '{folder_path}' from the library?\n"
            f"Tracks from this folder will be removed on next rescan.",
            parent=self.root)
        if not ok:
            return
        from music_manager.core.database import SourceFolder
        SourceFolder.delete_by_id(folder_id)
        self._refresh_source_folders()

    def _check_folders_before_scan(self):
        """Check source folders and warn if any are missing. Returns True to proceed."""
        from music_manager.core.scanner import check_source_folders
        result = check_source_folders(self.active_library)

        if result["total"] == 0:
            messagebox.showwarning("No Folders",
                                   "This library has no source folders.\n"
                                   "Add source folders before scanning.")
            return False

        if result["all_ok"]:
            return True

        missing = result["missing"]
        msg = f"{len(missing)} of {result['total']} source folder(s) not found:\n\n"
        for p in missing[:5]:
            msg += f"  {p}\n"
        if len(missing) > 5:
            msg += f"  ... and {len(missing) - 5} more\n"

        if result["wrong_os"]:
            msg += ("\nThese paths appear to be from a different operating system.\n"
                    "Scanning should be done from the machine where the files "
                    "are accessible.")

        if len(missing) == result["total"]:
            messagebox.showerror("All Folders Missing", msg)
            return False

        msg += "\nOnly accessible folders will be scanned. Continue?"
        return messagebox.askyesno("Missing Folders", msg)

    def _start_scan(self):
        """Start a library scan on a background thread."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select or create a library first.")
            return

        if not self._check_folders_before_scan():
            return

        if not messagebox.askyesno(
                "Full Scan",
                f"Run a full scan of '{self.active_library.name}'?\n\n"
                "This re-reads all audio files and may take a while\n"
                "for large libraries."):
            return

        self._scan_cancel = threading.Event()
        self.scan_btn.configure(state="normal", text="Cancel Scan",
                                command=self._cancel_scan)
        self.scan_progress.set(0)
        self.scan_status.configure(text="Starting scan...")

        lib = self.active_library
        thread = threading.Thread(target=self._run_scan, args=(lib,), daemon=True)
        thread.start()

    def _cancel_scan(self):
        """Signal the running scan to stop."""
        self._scan_cancel.set()
        self.scan_btn.configure(state="disabled", text="Cancelling...")

    def _run_scan(self, library):
        """Run the scan in a background thread."""
        from music_manager.core.scanner import scan_library
        from music_manager.core.overrides import apply_overrides

        def progress(current, total, message):
            if self._scan_cancel.is_set():
                raise _ScanCancelled()
            frac = current / total if total else 0
            self.root.after(0, lambda: self.scan_progress.set(frac))
            self.root.after(0, lambda: self.scan_status.configure(
                text=f"[{current}/{total}] {message}"))

        try:
            stats = scan_library(library, progress_callback=progress)
            apply_overrides(library)
            msg = (f"Done: {stats.tracks_created} tracks, "
                   f"{stats.albums_created} albums, "
                   f"{stats.works_created} works")
            if stats.files_failed:
                msg += f", {len(stats.files_failed)} failed"
        except _ScanCancelled:
            msg = "Scan cancelled"
            logger.info("Scan cancelled by user")
        except Exception as exc:
            msg = f"Scan error: {exc}"
            logger.exception("Scan failed")

        def finish():
            self.scan_status.configure(text=msg)
            self.scan_progress.set(1 if not self._scan_cancel.is_set() else 0)
            self.scan_btn.configure(state="normal", text="Rescan Library",
                                    command=self._start_scan)
            self._refresh_metrics()
            self._refresh_explorer()
            self._refresh_builder_tree()
            self._refresh_cleanup()

        self.root.after(0, finish)

    def _scan_changes(self):
        """Run an incremental scan (only new/changed/deleted files)."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        if not self._check_folders_before_scan():
            return

        if not messagebox.askyesno(
                "Incremental Scan",
                f"Scan '{self.active_library.name}' for new, changed,\n"
                "or deleted files?"):
            return

        self._scan_cancel = threading.Event()
        self.scan_btn.configure(state="normal", text="Cancel Scan",
                                command=self._cancel_scan)
        self.scan_progress.set(0)
        self.scan_status.configure(text="Checking for changes...")

        lib = self.active_library
        thread = threading.Thread(target=self._run_scan_changes,
                                  args=(lib,), daemon=True)
        thread.start()

    def _run_scan_changes(self, library):
        """Run incremental scan in a background thread."""
        from music_manager.core.scanner import scan_incremental
        from music_manager.core.overrides import apply_overrides

        def progress(current, total, message):
            if self._scan_cancel.is_set():
                raise _ScanCancelled()
            frac = current / total if total else 0
            self.root.after(0, lambda: self.scan_progress.set(frac))
            self.root.after(0, lambda: self.scan_status.configure(
                text=f"[{current}/{total}] {message}"))

        try:
            stats = scan_incremental(library, progress_callback=progress)
            if stats.files_added or stats.files_updated or stats.files_removed:
                apply_overrides(library)
            msg = (f"Done: +{stats.files_added} added, "
                   f"~{stats.files_updated} updated, "
                   f"-{stats.files_removed} removed, "
                   f"{stats.files_unchanged} unchanged")
            if stats.files_failed:
                msg += f", {len(stats.files_failed)} failed"
        except _ScanCancelled:
            msg = "Scan cancelled"
        except Exception as exc:
            msg = f"Scan error: {exc}"
            logger.exception("Incremental scan failed")

        def finish():
            self.scan_status.configure(text=msg)
            self.scan_progress.set(1 if not self._scan_cancel.is_set() else 0)
            self.scan_btn.configure(state="normal", text="Rescan Library",
                                    command=self._start_scan)
            self._refresh_metrics()
            self._refresh_explorer()
            self._refresh_builder_tree()
            self._refresh_cleanup()

        self.root.after(0, finish)

    def _redetect_works(self):
        """Re-run all work detection steps using tag data in the database."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        if not messagebox.askyesno(
                "Re-detect Works",
                f"Re-run work detection for '{self.active_library.name}'?\n\n"
                "This will regroup tracks into works based on\n"
                "current tag data and detection rules."):
            return

        from music_manager.core.scanner import redetect_works
        with self._busy():
            result = redetect_works(self.active_library)
            self._refresh_metrics()
            self._refresh_cleanup()
            self._refresh_explorer()
        messagebox.showinfo(
            "Re-detect Complete",
            f"Albums processed: {result['albums_processed']}\n"
            f"Override: {result['override']}  |  "
            f"MB Work ID: {result['mb_workid']}  |  "
            f"Work Tag: {result['work_tag']}\n"
            f"Heuristic: {result['heuristic']}  |  "
            f"Standalone: {result['standalone']}")

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
                selected_ids, _ = resolve_selections(prof)

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

    def _show_similarity(self):
        """Open the Track Similarity Finder popup."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return
        from music_manager.interfaces.similarity_popup import SimilarityPopup
        SimilarityPopup(self.root, self.active_library, self.ctk,
                        self._center_on_main)

    def _run_integrity_check(self):
        """Run integrity checks and show results in a popup."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        from music_manager.core.integrity import run_integrity_checks
        with self._busy():
            report = run_integrity_checks(self.active_library)

        popup = tk.Toplevel(self.root)
        popup.title(f"Integrity Report — {self.active_library.name}")
        popup.transient(self.root)
        self._center_on_main(popup, 800, 500)
        popup.wait_visibility()
        popup.grab_set()

        ctk = self.ctk

        # Summary bar
        summary = ctk.CTkFrame(popup, fg_color="transparent")
        summary.pack(fill="x", padx=10, pady=(10, 5))
        categories = [
            ("Orphaned Tracks", report.orphans),
            ("Unscanned Files", report.unscanned),
            ("Duplicates", report.duplicates),
            ("Cross-Folder Works", report.cross_folder_works),
        ]
        for label, items in categories:
            color = "#4da6ff" if not items else "#e74c3c"
            ctk.CTkLabel(summary, text=f"{label}: {len(items)}",
                         text_color=color,
                         font=ctk.CTkFont(size=12)).pack(side="left", padx=10)

        # Detail tabs
        notebook = ctk.CTkTabview(popup)
        notebook.pack(fill="both", expand=True, padx=10, pady=5)

        for label, items in categories:
            tab = notebook.add(label)
            text = tk.Text(tab, bg="#1e1e1e", fg="#cccccc",
                           font=("Consolas", 10), wrap="word",
                           state="normal")
            text.pack(fill="both", expand=True, padx=5, pady=5)
            scroll = ttk.Scrollbar(text, orient="vertical", command=text.yview)
            text.configure(yscrollcommand=scroll.set)
            scroll.pack(side="right", fill="y")
            if items:
                text.insert("1.0", "\n".join(items))
            else:
                text.insert("1.0", "No issues found.")
            text.configure(state="disabled")

        ctk.CTkButton(popup, text="Close", width=80,
                      command=popup.destroy).pack(pady=(0, 10))

    # ------------------------------------------------------------------
    # Library Import / Export
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Tab 1: Explorer & Rules (§10)
    # ------------------------------------------------------------------

    def _build_explorer_tab(self):
        """Build the Explorer & Rules tab with album/work treeviews."""
        ctk = self.ctk
        tab = self.tab_explorer

        # Search bar
        search_frame = ctk.CTkFrame(tab, fg_color="transparent")
        search_frame.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(search_frame, text="Filter:").pack(side="left", padx=5)
        self._explorer_search_var = tk.StringVar()
        self._explorer_search_var.trace_add("write", lambda *_: self._debounce_explorer_search())
        self.explorer_search = ctk.CTkEntry(search_frame, width=300,
                                            placeholder_text="Filter albums and works...",
                                            textvariable=self._explorer_search_var)
        self.explorer_search.pack(side="left", padx=5)
        ctk.CTkButton(search_frame, text="?", width=28, height=28,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color="gray30", hover_color="gray40",
                      command=lambda: self._show_help("explorer"),
                      ).pack(side="right", padx=5)
        self._explorer_search_after = None

        # Paned view: albums left, works/tracks right
        pane = ctk.CTkFrame(tab, fg_color="transparent")
        pane.pack(fill="both", expand=True, padx=5, pady=5)

        # Albums tree
        left = ctk.CTkFrame(pane)
        left.pack(side="left", fill="both", expand=True, padx=(0, 5))
        ctk.CTkLabel(left, text="Albums",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=5)
        self.album_tree = ttk.Treeview(left, columns=("artist", "genre", "year", "tracks"),
                                       show="headings", selectmode="browse")
        self.album_tree.heading("artist", text="Album")
        self.album_tree.heading("genre", text="Genre")
        self.album_tree.heading("year", text="Year")
        self.album_tree.heading("tracks", text="Tracks")
        self.album_tree.column("artist", width=260)
        self.album_tree.column("genre", width=100)
        self.album_tree.column("year", width=60, anchor="center")
        self.album_tree.column("tracks", width=60, anchor="center")
        self.album_tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.album_tree.bind("<<TreeviewSelect>>", self._on_album_selected)
        self.album_tree.bind("<Button-3>", self._album_context_menu)
        self._setup_tree_sort(self.album_tree)

        # Works/Tracks tree
        right = ctk.CTkFrame(pane)
        right.pack(side="right", fill="both", expand=True, padx=(5, 0))
        ctk.CTkLabel(right, text="Works & Tracks",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=5)
        self.work_tree = ttk.Treeview(right, columns=("source", "composer", "movements"),
                                      show="tree headings", selectmode="browse")
        self.work_tree.heading("#0", text="Name")
        self.work_tree.heading("source", text="Source")
        self.work_tree.heading("composer", text="Composer")
        self.work_tree.heading("movements", text="Tracks")
        self.work_tree.column("#0", width=300)
        self.work_tree.column("source", width=80)
        self.work_tree.column("composer", width=150)
        self.work_tree.column("movements", width=60, anchor="center")
        self.work_tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.work_tree.bind("<Button-3>", self._work_context_menu)
        self._setup_tree_sort(self.work_tree)

        # Rules display
        rules_frame = ctk.CTkFrame(tab)
        rules_frame.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(rules_frame, text="Active Rules",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left", padx=10)
        self.rules_listbox = tk.Listbox(rules_frame, height=4,
                                        bg="#2b2b2b", fg="white",
                                        selectbackground="#1f6aa5",
                                        font=("Segoe UI", 10))
        self.rules_listbox.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        ctk.CTkButton(rules_frame, text="Remove", width=80,
                      command=self._remove_selection).pack(side="right", padx=5)

        # Store album_id map for treeview items
        self._album_iid_map = {}
        self._work_iid_map = {}

    def _refresh_explorer(self):
        """Reload album and work treeviews from the database."""
        self._clear_tree_sort(self.album_tree)
        self._clear_tree_sort(self.work_tree)
        self.album_tree.delete(*self.album_tree.get_children())
        self._album_iid_map.clear()

        if not self.active_library:
            return

        from music_manager.core.database import Album, Track

        search = self.explorer_search.get().strip().lower() if hasattr(self, 'explorer_search') else ""

        # Pre-compute per-album metadata for genre display and search
        album_genres = {}    # album_id → first non-empty genre
        album_search = {}    # album_id → set of lowercase searchable strings
        for t in Track.select().where(Track.library == self.active_library):
            aid = t.album_id
            if aid not in album_genres and t.genre:
                album_genres[aid] = t.genre
            meta = album_search.setdefault(aid, set())
            for val in (t.genre, t.performer, t.conductor, t.ensemble,
                        t.composer.name if t.composer_id else None):
                if val:
                    meta.add(val.lower())

        albums = Album.select().where(Album.library == self.active_library).order_by(Album.title)
        for album in albums:
            if search:
                if (search not in album.title.lower()
                        and search not in (album.album_artist or "").lower()
                        and not any(search in m for m in album_search.get(album.id, ()))):
                    continue
            track_count = Track.select().where(Track.album == album).count()
            genre = album_genres.get(album.id, "")
            iid = self.album_tree.insert("", "end", values=(
                album.title,
                genre,
                album.year or "",
                track_count,
            ))
            self._album_iid_map[iid] = album.id

        # Clear works tree
        self.work_tree.delete(*self.work_tree.get_children())
        self._work_iid_map.clear()

    def _on_album_selected(self, event):
        """When an album is selected, show its works and tracks."""
        sel = self.album_tree.selection()
        if not sel:
            return
        album_id = self._album_iid_map.get(sel[0])
        if not album_id:
            return

        self._clear_tree_sort(self.work_tree)
        self.work_tree.delete(*self.work_tree.get_children())
        self._work_iid_map.clear()

        from music_manager.core.database import Work, Track

        works = Work.select().where(Work.album == album_id).order_by(Work.work_sequence)
        for work in works:
            tracks = list(Track.select().where(Track.work == work).order_by(
                Track.disc_number, Track.track_number))
            composer_name = tracks[0].composer.name if tracks and tracks[0].composer_id else ""

            work_iid = self.work_tree.insert("", "end", text=work.work_name, values=(
                work.work_source,
                composer_name,
                len(tracks),
            ))
            self._work_iid_map[work_iid] = ("work", work.id)

            for t in tracks:
                t_iid = self.work_tree.insert(work_iid, "end", text=f"  {t.disc_number}-{t.track_number:02d}: {t.title}", values=(
                    "", t.composer.name if t.composer_id else "", ""
                ))
                self._work_iid_map[t_iid] = ("track", t.id)

    def _album_context_menu(self, event):
        """Right-click context menu on albums."""
        iid = self.album_tree.identify_row(event.y)
        if not iid:
            return
        self.album_tree.selection_set(iid)
        album_id = self._album_iid_map.get(iid)
        if not album_id:
            return

        from music_manager.core.database import Album
        from music_manager.core.selection import key_for_album
        album = Album.get_by_id(album_id)
        album_key = key_for_album(album)

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Include Album",
                         command=lambda: self._add_selection("album", album_key))
        menu.add_command(label="Exclude Album",
                         command=lambda: self._add_selection("album", album_key, excluded=True))
        menu.tk_popup(event.x_root, event.y_root)

    def _work_context_menu(self, event):
        """Right-click context menu on works/tracks."""
        iid = self.work_tree.identify_row(event.y)
        if not iid:
            return
        self.work_tree.selection_set(iid)
        entry = self._work_iid_map.get(iid)
        if not entry:
            return

        level, entity_id = entry
        from music_manager.core.selection import key_for_entity
        from music_manager.core.database import Work, Track
        menu = tk.Menu(self.root, tearoff=0)

        if level == "work":
            work = Work.get_by_id(entity_id)
            work_key = key_for_entity("work", work)
            menu.add_command(label="Include Work",
                             command=lambda: self._add_selection("work", work_key))
            menu.add_command(label="Exclude Work",
                             command=lambda: self._add_selection("work", work_key, excluded=True))
        elif level == "track":
            track = Track.get_by_id(entity_id)
            track_key = key_for_entity("track", track)
            menu.add_command(label="Play",
                             command=lambda: self._play_track(entity_id))
            menu.add_separator()
            menu.add_command(label="Include Track",
                             command=lambda: self._add_selection("track", track_key))
            menu.add_command(label="Exclude Track",
                             command=lambda: self._add_selection("track", track_key, excluded=True))

        menu.tk_popup(event.x_root, event.y_root)

    def _add_selection(self, level, key, excluded=False, pin_position=None,
                       track_paths=None, refresh=True):
        """Add a selection to the in-memory list."""
        # At most one selection may exist per (level, key). Skip if this
        # exact state already exists; otherwise remove the stale opposite-
        # state entry so it doesn't linger and get picked up ahead of this
        # one by _find_selection or disagree with resolve_selections.
        existing = self._find_selection(level, key)
        if existing is not None:
            if existing["excluded"] == excluded:
                return
            self._current_selections.remove(existing)

        from music_manager.core.selection import display_name_for_selection
        display_name = display_name_for_selection(self.active_library, level, key)
        prefix = "EXCEPT" if excluded else "ADD"
        pin_str = f"[#{pin_position}] " if pin_position else ""

        sel = {
            "level": level,
            "key": key,
            "excluded": excluded,
            "pin_position": pin_position,
            "track_paths": track_paths,
            "display": f"{pin_str}{prefix}: {level} — {display_name}",
        }
        self._current_selections.append(sel)
        if refresh:
            self._refresh_rules_display()

    def _find_selection(self, level, key):
        """Find an existing selection by level and key."""
        return next((s for s in self._current_selections
                     if s["level"] == level and s["key"] == key), None)

    def _is_item_selected(self, level, key):
        """Check if item is selected (directly or via parent, respecting specificity)."""
        from music_manager.core.selection import parse_work_key, COMPOSITE_SEP
        sel = self._find_selection(level, key)
        if sel is not None:
            return not sel["excluded"]
        # Walk up hierarchy
        if level == "track":
            # Find the work and album this track belongs to
            from music_manager.core.database import Track
            track = Track.select(Track.work, Track.album).where(
                (Track.library == self.active_library) &
                (Track.relative_path == key)
            ).first()
            if track and track.work_id:
                from music_manager.core.selection import key_for_work
                from music_manager.core.database import Work
                work = Work.get_by_id(track.work_id)
                work_key = key_for_work(work)
                work_sel = self._find_selection("work", work_key)
                if work_sel is not None:
                    return not work_sel["excluded"]
                # Check album level
                album_sel = self._find_selection("album", work.album.album_key)
                if album_sel is not None:
                    return not album_sel["excluded"]
            elif track:
                from music_manager.core.database import Album
                album = Album.get_by_id(track.album_id)
                album_sel = self._find_selection("album", album.album_key)
                if album_sel is not None:
                    return not album_sel["excluded"]
        elif level == "work":
            # Extract album_key from work key
            parsed = parse_work_key(key)
            if parsed:
                album_key = parsed[0]
                album_sel = self._find_selection("album", album_key)
                if album_sel is not None:
                    return not album_sel["excluded"]
        return False

    def _remove_selection(self):
        """Remove selected selection from the in-memory list."""
        sel = self.rules_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._current_selections):
            self._current_selections.pop(idx)
            self._refresh_rules_display()

    def _refresh_rules_display(self):
        """Update the rules listbox on the Explorer tab and builder trees."""
        self.rules_listbox.delete(0, "end")
        for sel in self._current_selections:
            self.rules_listbox.insert("end", sel["display"])
        # Refresh builder panes if they exist
        if hasattr(self, "builder_lib_tree"):
            self._rebuild_library_tree()
            self._rebuild_playlist_tree()

    # ------------------------------------------------------------------
    # Tab 2: Playlist Builder (§10)
    # ------------------------------------------------------------------

    def _build_builder_tab(self):
        """Build the Playlist Builder tab.

        Layout: top (profile + compact settings) | middle (library | buttons | playlist) | bottom (actions).
        """
        ctk = self.ctk
        tab = self.tab_builder

        # -- Row 0: Profile name + load/save --
        row0 = ctk.CTkFrame(tab, fg_color="transparent")
        row0.pack(fill="x", padx=10, pady=(5, 2))
        ctk.CTkLabel(row0, text="Profile:").pack(side="left", padx=(0, 3))
        self.profile_name_entry = ctk.CTkEntry(row0, width=200,
                                               placeholder_text="e.g. Sunday Classical")
        self.profile_name_entry.pack(side="left", padx=3)
        ctk.CTkButton(row0, text="New", width=60,
                      command=self._new_profile).pack(side="left", padx=3)
        ctk.CTkButton(row0, text="Load", width=60,
                      command=self._load_profile).pack(side="left", padx=3)
        ctk.CTkButton(row0, text="Save", width=60,
                      command=self._save_profile).pack(side="left", padx=3)
        ctk.CTkButton(row0, text="Delete", width=60,
                      command=self._delete_profile).pack(side="left", padx=3)
        ctk.CTkButton(row0, text="?", width=28, height=28,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color="gray30", hover_color="gray40",
                      command=lambda: self._show_help("builder"),
                      ).pack(side="right", padx=5)

        # -- Row 1: Compact settings (all in one line) --
        row1 = ctk.CTkFrame(tab, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=2)

        ctk.CTkLabel(row1, text="Shuffle:").pack(side="left", padx=(0, 2))
        self.shuffle_mode = ctk.CTkComboBox(row1, values=["track", "work", "album"],
                                            width=90)
        self.shuffle_mode.pack(side="left", padx=(0, 8))
        self.shuffle_mode.set("work")

        ctk.CTkLabel(row1, text="Integrity:").pack(side="left", padx=(0, 2))
        self.work_integrity = ctk.CTkComboBox(
            row1, values=["enforce", "respect_selection"], width=140)
        self.work_integrity.pack(side="left", padx=(0, 8))
        self.work_integrity.set("enforce")

        ctk.CTkLabel(row1, text="Length:").pack(side="left", padx=(0, 2))
        self.length_mode = ctk.CTkComboBox(row1, values=["all", "count", "duration"],
                                           width=90)
        self.length_mode.pack(side="left", padx=(0, 2))
        self.length_mode.set("all")
        self.length_value = ctk.CTkEntry(row1, width=55, placeholder_text="H:MM")
        self.length_value.pack(side="left", padx=(0, 8))

        ctk.CTkLabel(row1, text="Seed:").pack(side="left", padx=(0, 2))
        self.seed_entry = ctk.CTkEntry(row1, width=55, placeholder_text="rnd")
        self.seed_entry.pack(side="left", padx=(0, 8))

        self.no_repeat_var = ctk.CTkCheckBox(row1, text="No repeats", width=30)
        self.no_repeat_var.pack(side="left", padx=(0, 4))
        self.no_repeat_var.select()

        # -- Row 1b: Separation constraints --
        row1b = ctk.CTkFrame(tab, fg_color="transparent")
        row1b.pack(fill="x", padx=10, pady=0)

        ctk.CTkLabel(row1b, text="Avoid adjacent:").pack(side="left", padx=(0, 2))
        self.sep_composer_var = ctk.CTkCheckBox(row1b, text="Same Composer", width=30)
        self.sep_composer_var.pack(side="left", padx=(0, 8))
        self.sep_album_var = ctk.CTkCheckBox(row1b, text="Same Album", width=30)
        self.sep_album_var.pack(side="left", padx=(0, 8))
        self.sep_form_var = ctk.CTkCheckBox(row1b, text="Same Form", width=30)
        self.sep_form_var.pack(side="left", padx=(0, 8))

        # -- Main area: library pane | buttons | playlist pane --
        main_pane = ctk.CTkFrame(tab, fg_color="transparent")
        main_pane.pack(fill="both", expand=True, padx=5, pady=5)
        main_pane.columnconfigure(0, weight=1)
        main_pane.columnconfigure(1, weight=0)
        main_pane.columnconfigure(2, weight=1)
        main_pane.rowconfigure(0, weight=1)

        # ---- Left: Library pane ----
        left_frame = ctk.CTkFrame(main_pane)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 3))

        lib_header = ctk.CTkFrame(left_frame, fg_color="transparent")
        lib_header.pack(fill="x", padx=5, pady=(5, 2))
        ctk.CTkLabel(lib_header, text="Library",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left")
        ctk.CTkButton(lib_header, text="+", width=24, height=24,
                      fg_color="transparent", hover_color="gray40",
                      text_color="gray70", font=ctk.CTkFont(size=14),
                      command=lambda: self._toggle_tree(self.builder_lib_tree, True)
                      ).pack(side="left", padx=(6, 0))
        ctk.CTkButton(lib_header, text="\u2013", width=24, height=24,
                      fg_color="transparent", hover_color="gray40",
                      text_color="gray70", font=ctk.CTkFont(size=14),
                      command=lambda: self._toggle_tree(self.builder_lib_tree, False)
                      ).pack(side="left")
        self._lib_filter_var = tk.StringVar()
        self._lib_filter_var.trace_add("write", lambda *_: self._apply_tree_filter("lib"))
        lib_filter = ctk.CTkEntry(lib_header, width=150,
                                  placeholder_text="Filter...",
                                  textvariable=self._lib_filter_var)
        lib_filter.pack(side="right")
        ctk.CTkLabel(lib_header, text="Filter:",
                     text_color="gray70").pack(side="right", padx=(0, 3))

        self.builder_hide_single = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(lib_header, text="Hide 1-track",
                        variable=self.builder_hide_single,
                        command=self._on_hide_single_changed,
                        width=20).pack(side="right", padx=5)

        self.builder_lib_tree = ttk.Treeview(
            left_frame, columns=("composer", "genre", "info"),
            show="tree headings", selectmode="extended")
        self.builder_lib_tree.heading("#0", text="Name")
        self.builder_lib_tree.heading("composer", text="Composer")
        self.builder_lib_tree.heading("genre", text="Genre")
        self.builder_lib_tree.heading("info", text="Info")
        self.builder_lib_tree.column("#0", width=220)
        self.builder_lib_tree.column("composer", width=120)
        self.builder_lib_tree.column("genre", width=90)
        self.builder_lib_tree.column("info", width=70, anchor="center")
        self.builder_lib_tree.pack(fill="both", expand=True, padx=5, pady=2)

        lib_scroll = ttk.Scrollbar(left_frame, orient="vertical",
                                   command=self.builder_lib_tree.yview)
        self.builder_lib_tree.configure(yscrollcommand=lib_scroll.set)
        # Place scrollbar on top of tree's right edge
        lib_scroll.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne",
                         in_=self.builder_lib_tree)

        self._setup_tree_sort(self.builder_lib_tree,
                              row_dbl_click=self._builder_toggle_include)
        self.builder_lib_tree.bind("<Button-3>", lambda e: self._builder_context_menu(e, "lib"))
        self._builder_lib_iid_map = {}  # iid → (level, entity_id, key)

        # Tag styles for visual state (colorblind-friendly)
        self.builder_lib_tree.tag_configure("included", foreground="#4da6ff")   # blue
        self.builder_lib_tree.tag_configure("excluded", foreground="#666666")   # gray
        self.builder_lib_tree.tag_configure("partial", foreground="#e6a332")    # amber

        # ---- Center: action buttons ----
        center_frame = ctk.CTkFrame(main_pane, fg_color="transparent", width=90)
        center_frame.grid(row=0, column=1, sticky="ns", padx=4)

        # Spacer to vertically center buttons
        ctk.CTkLabel(center_frame, text="").pack(expand=True)
        ctk.CTkButton(center_frame, text="Add >>", width=80,
                      fg_color="#2d7d46",
                      command=self._builder_include_selected).pack(pady=3)
        ctk.CTkButton(center_frame, text="<< Remove", width=80,
                      fg_color="#7d2d2d",
                      command=self._builder_exclude_selected).pack(pady=3)
        ctk.CTkLabel(center_frame, text="Double-click\nor multi-select\n+ buttons",
                     text_color="gray", font=ctk.CTkFont(size=10),
                     justify="center").pack(pady=6)
        ctk.CTkLabel(center_frame, text="").pack(expand=True)

        # ---- Right: Playlist pane ----
        right_frame = ctk.CTkFrame(main_pane)
        right_frame.grid(row=0, column=2, sticky="nsew", padx=(3, 0))

        pl_header = ctk.CTkFrame(right_frame, fg_color="transparent")
        pl_header.pack(fill="x", padx=5, pady=(5, 2))
        ctk.CTkLabel(pl_header, text="Playlist",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left")
        ctk.CTkButton(pl_header, text="+", width=24, height=24,
                      fg_color="transparent", hover_color="gray40",
                      text_color="gray70", font=ctk.CTkFont(size=14),
                      command=lambda: self._toggle_tree(self.builder_pl_tree, True)
                      ).pack(side="left", padx=(6, 0))
        ctk.CTkButton(pl_header, text="\u2013", width=24, height=24,
                      fg_color="transparent", hover_color="gray40",
                      text_color="gray70", font=ctk.CTkFont(size=14),
                      command=lambda: self._toggle_tree(self.builder_pl_tree, False)
                      ).pack(side="left")
        self._pl_filter_var = tk.StringVar()
        self._pl_filter_var.trace_add("write", lambda *_: self._apply_tree_filter("pl"))
        pl_filter = ctk.CTkEntry(pl_header, width=150,
                                 placeholder_text="Filter...",
                                 textvariable=self._pl_filter_var)
        pl_filter.pack(side="right")
        ctk.CTkLabel(pl_header, text="Filter:",
                     text_color="gray70").pack(side="right", padx=(0, 3))

        self._pl_hide_warning = ctk.CTkLabel(
            pl_header, text="  (filter may hide items)",
            text_color="#b08830", font=ctk.CTkFont(size=11))

        self.builder_pl_tree = ttk.Treeview(
            right_frame, columns=("composer", "genre", "info"),
            show="tree headings", selectmode="extended")
        self.builder_pl_tree.heading("#0", text="Name")
        self.builder_pl_tree.heading("composer", text="Composer")
        self.builder_pl_tree.heading("genre", text="Genre")
        self.builder_pl_tree.heading("info", text="Info")
        self.builder_pl_tree.column("#0", width=220)
        self.builder_pl_tree.column("composer", width=120)
        self.builder_pl_tree.column("genre", width=90)
        self.builder_pl_tree.column("info", width=70, anchor="center")
        self.builder_pl_tree.pack(fill="both", expand=True, padx=5, pady=2)

        pl_scroll = ttk.Scrollbar(right_frame, orient="vertical",
                                  command=self.builder_pl_tree.yview)
        self.builder_pl_tree.configure(yscrollcommand=pl_scroll.set)
        pl_scroll.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne",
                        in_=self.builder_pl_tree)

        self._setup_tree_sort(self.builder_pl_tree,
                              row_dbl_click=self._builder_exclude_selected)
        self.builder_pl_tree.bind("<Button-3>", lambda e: self._builder_context_menu(e, "pl"))
        self.builder_pl_tree.tag_configure("pinned", foreground="#e680ff")  # orchid
        self._builder_pl_iid_map = {}  # iid → (level, entity_id, key)

        # -- Bottom: action buttons --
        bot = ctk.CTkFrame(tab, fg_color="transparent")
        bot.pack(fill="x", padx=10, pady=(2, 5))

        ctk.CTkButton(bot, text="Preview", width=110,
                      command=self._preview_playlist).pack(side="left", padx=4)
        ctk.CTkButton(bot, text="Export M3U", width=110,
                      command=self._export_m3u).pack(side="left", padx=4)
        ctk.CTkButton(bot, text="Export JSON", width=110,
                      command=self._export_json).pack(side="left", padx=4)
        ctk.CTkButton(bot, text="Push to Plex", width=110,
                      command=self._push_plex).pack(side="left", padx=4)
        ctk.CTkButton(bot, text="Find Unused", width=110,
                      command=self._find_unused).pack(side="left", padx=4)
        ctk.CTkButton(bot, text="Find Similar", width=110,
                      command=self._find_similar_tracks).pack(side="left", padx=4)

        info = ctk.CTkLabel(bot, text="(empty = all tracks)",
                            text_color="gray")
        info.pack(side="right", padx=10)

    # ------------------------------------------------------------------
    # Builder: data & interaction
    # ------------------------------------------------------------------

    def _toggle_tree(self, tree, expand):
        """Expand or collapse all nodes in a treeview.

        When expanding, opens down to the work level only — albums are
        opened to reveal works, but works stay closed so individual tracks
        remain hidden.  When collapsing, closes everything.
        """
        for iid in tree.get_children():
            tree.item(iid, open=expand)
            for child in tree.get_children(iid):
                tree.item(child, open=False)

    # ------------------------------------------------------------------
    # Treeview column sorting
    # ------------------------------------------------------------------

    def _setup_tree_sort(self, tree, row_dbl_click=None):
        """Bind double-click on column headers to sort the treeview.

        If *row_dbl_click* is given it will be called when the double-click
        lands on a row instead of a heading.
        """
        # Store original heading texts so indicators can be toggled
        show = str(tree.cget("show"))
        cols = (["#0"] if "tree" in show else []) + list(tree["columns"])
        tree._sort_orig_headings = {c: tree.heading(c, "text") for c in cols}

        def on_dbl(event):
            region = tree.identify_region(event.x, event.y)
            if region == "heading":
                col_id = tree.identify_column(event.x)
                if col_id == "#0":
                    col = "#0"
                else:
                    idx = int(col_id.lstrip("#")) - 1
                    col = list(tree["columns"])[idx]
                self._sort_treeview_column(tree, col)
                return "break"
            if row_dbl_click:
                # Ignore double-clicks on the disclosure arrow so fast
                # expand/collapse clicks don't trigger add/remove — but
                # only for nodes that actually have children (the indicator
                # element exists at every indent level, even for leaves).
                element = tree.identify_element(event.x, event.y)
                if element == "Treeitem.indicator":
                    iid = tree.identify_row(event.y)
                    if iid and tree.get_children(iid):
                        return
                return row_dbl_click(event)

        tree.bind("<Double-1>", on_dbl)

    def _sort_treeview_column(self, tree, col):
        """Sort top-level items of *tree* by *col*, toggling direction."""
        tid = id(tree)
        prev_col, prev_rev = self._tree_sort_state.get(tid, (None, False))
        reverse = not prev_rev if col == prev_col else False
        self._tree_sort_state[tid] = (col, reverse)

        # Collect (sort_key, iid) for each top-level item
        items = []
        for iid in tree.get_children():
            if col == "#0":
                val = tree.item(iid, "text")
            else:
                val = tree.set(iid, col)
            items.append((val, iid))

        # Try numeric sort when all values look like numbers
        def numeric_key(val):
            v = val.strip()
            # Handle "N trk" style values
            if v.endswith(" trk"):
                v = v[:-4]
            # Handle "M:SS" durations
            if ":" in v:
                parts = v.split(":")
                try:
                    return sum(float(p) * (60 ** i) for i, p in enumerate(reversed(parts)))
                except ValueError:
                    return None
            try:
                return float(v)
            except ValueError:
                return None

        numeric_vals = [numeric_key(v) for v, _ in items]
        if items and all(n is not None for n in numeric_vals):
            decorated = sorted(zip(numeric_vals, [iid for _, iid in items]),
                               reverse=reverse)
            sorted_iids = [iid for _, iid in decorated]
        else:
            items.sort(key=lambda x: x[0].lower(), reverse=reverse)
            sorted_iids = [iid for _, iid in items]

        for idx, iid in enumerate(sorted_iids):
            tree.move(iid, "", idx)

        # Update heading indicators
        orig = getattr(tree, "_sort_orig_headings", {})
        for c, txt in orig.items():
            tree.heading(c, text=txt)
        arrow = " \u25b2" if not reverse else " \u25bc"
        base = orig.get(col, col)
        tree.heading(col, text=base + arrow)

        # Update snapshot if this is a builder tree (so filter still works)
        if tree is getattr(self, "builder_lib_tree", None):
            self._lib_tree_snapshot = self._snapshot_tree(tree)
        elif tree is getattr(self, "builder_pl_tree", None):
            self._pl_tree_snapshot = self._snapshot_tree(tree)

    def _clear_tree_sort(self, tree):
        """Reset sort state and heading indicators for a tree."""
        tid = id(tree)
        self._tree_sort_state.pop(tid, None)
        orig = getattr(tree, "_sort_orig_headings", {})
        for c, txt in orig.items():
            tree.heading(c, text=txt)

    def _save_builder_view_state(self):
        """Capture expansion, sort, and scroll state for both builder trees."""
        state = {}
        for key, tree, iid_map in [
            ("lib", self.builder_lib_tree, self._builder_lib_iid_map),
            ("pl", self.builder_pl_tree, self._builder_pl_iid_map),
        ]:
            # Which entity keys are expanded
            open_keys = set()
            for iid in self._all_tree_iids(tree):
                if tree.item(iid, "open"):
                    entity = iid_map.get(iid)
                    if entity:
                        open_keys.add(entity)
            # Sort state
            sort = self._tree_sort_state.get(id(tree))
            # Scroll position
            scroll = tree.yview()
            state[key] = {"open": open_keys, "sort": sort, "scroll": scroll}
        return state

    def _restore_builder_view_state(self, state):
        """Re-apply expansion, sort, and scroll state after a rebuild."""
        for key, tree, iid_map in [
            ("lib", self.builder_lib_tree, self._builder_lib_iid_map),
            ("pl", self.builder_pl_tree, self._builder_pl_iid_map),
        ]:
            s = state.get(key)
            if not s:
                continue
            # Close everything first (rebuild may auto-expand albums)
            for iid in self._all_tree_iids(tree):
                try:
                    tree.item(iid, open=False)
                except tk.TclError:
                    pass
            # Invert iid_map: entity_key → iid
            entity_to_iid = {v: k for k, v in iid_map.items()}
            # Restore only what was previously open
            for entity_key in s["open"]:
                iid = entity_to_iid.get(entity_key)
                if iid:
                    try:
                        tree.item(iid, open=True)
                    except tk.TclError:
                        pass
            # Restore sort
            if s["sort"]:
                col, reverse = s["sort"]
                # Apply sort twice if we need descending (first call = asc)
                self._sort_treeview_column(tree, col)
                if reverse:
                    self._sort_treeview_column(tree, col)
            # Restore scroll
            if s["scroll"]:
                tree.yview_moveto(s["scroll"][0])

    def _all_tree_iids(self, tree):
        """Yield all iids in a tree (recursive)."""
        def walk(parent=""):
            for iid in tree.get_children(parent):
                yield iid
                yield from walk(iid)
        yield from walk()

    def _snapshot_tree(self, tree):
        """Capture tree structure as list of (iid, parent, index, text, open)."""
        snapshot = []
        def walk(parent=""):
            for i, iid in enumerate(tree.get_children(parent)):
                snapshot.append((iid, parent, i,
                                 tree.item(iid, "text"),
                                 tree.item(iid, "open")))
                walk(iid)
        walk()
        return snapshot

    def _apply_tree_filter(self, which):
        """Filter library or playlist tree by search text, using detach/reattach."""
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        try:
            self._apply_tree_filter_inner(which)
        finally:
            self.root.config(cursor="")

    def _apply_tree_filter_inner(self, which):
        """Inner implementation of tree filter."""
        if which == "lib":
            tree = self.builder_lib_tree
            snapshot = self._lib_tree_snapshot
            query = self._lib_filter_var.get().strip().lower()
            search_meta = self._lib_search_meta
        else:
            tree = self.builder_pl_tree
            snapshot = self._pl_tree_snapshot
            query = self._pl_filter_var.get().strip().lower()
            search_meta = self._pl_search_meta

        if not snapshot:
            return

        # Reattach everything first
        for iid, parent, index, text, was_open in snapshot:
            try:
                tree.reattach(iid, parent, index)
                tree.item(iid, open=was_open)
            except tk.TclError:
                pass

        if not query:
            return

        # Build a set of iids whose text or metadata matches (case-insensitive)
        matching = set()
        for iid, parent, index, text, was_open in snapshot:
            search_text = search_meta.get(iid, text).lower()
            if query in search_text:
                matching.add(iid)

        # Also keep all ancestors of matching items visible
        visible = set(matching)
        parent_map = {iid: parent for iid, parent, index, text, was_open in snapshot}
        for iid in matching:
            p = parent_map.get(iid, "")
            while p:
                visible.add(p)
                p = parent_map.get(p, "")

        # Also keep all descendants of matching items visible
        children_map = {}
        for iid, parent, index, text, was_open in snapshot:
            children_map.setdefault(parent, []).append(iid)

        def add_descendants(iid):
            for child in children_map.get(iid, []):
                visible.add(child)
                add_descendants(child)

        for iid in matching:
            add_descendants(iid)

        # Detach non-visible items (children before parents)
        for iid, parent, index, text, was_open in reversed(snapshot):
            if iid not in visible:
                tree.detach(iid)

        # Auto-expand ancestors of matches so results are visible
        for iid in matching:
            p = parent_map.get(iid, "")
            while p:
                try:
                    tree.item(p, open=True)
                except tk.TclError:
                    pass
                p = parent_map.get(p, "")

    def _on_hide_single_changed(self):
        """Toggle the 1-track filter and show/hide the playlist warning."""
        if self.builder_hide_single.get():
            self._pl_hide_warning.pack(side="left", padx=(4, 0))
        else:
            self._pl_hide_warning.pack_forget()
        with self._busy():
            self._refresh_builder_tree()

    def _refresh_builder_tree(self):
        """Populate the library tree and refresh the playlist tree."""
        self._builder_lib_data = {}   # entity_id → {level, album_id, work_id, ...}
        self._rebuild_library_tree()
        self._rebuild_playlist_tree()

    def _rebuild_library_tree(self):
        """Rebuild the left (library) tree with visual clues for included/excluded."""
        self._clear_tree_sort(self.builder_lib_tree)
        # Reattach any filter-detached items so delete catches everything
        for iid, parent, idx, txt, opn in self._lib_tree_snapshot:
            try:
                self.builder_lib_tree.reattach(iid, "", "end")
            except tk.TclError:
                pass
        self._lib_tree_snapshot = []
        self.builder_lib_tree.delete(*self.builder_lib_tree.get_children())
        self._builder_lib_iid_map.clear()
        self._lib_search_meta = {}

        if not self.active_library:
            return

        from music_manager.core.database import Album, Work, Track
        from music_manager.core.selection import (
            key_for_album, key_for_work, key_for_track, COMPOSITE_SEP,
        )

        # Build selection lookup dicts for quick matching
        sel_by_key = {}  # (level, key) → selection dict
        for s in self._current_selections:
            sel_by_key[(s["level"], s["key"])] = s

        hide_single = self.builder_hide_single.get()

        albums = (Album.select()
                  .where(Album.library == self.active_library)
                  .order_by(Album.title))

        for album in albums:
            a_key = key_for_album(album)
            album_sel = sel_by_key.get(("album", a_key))
            album_is_add = album_sel is not None and not album_sel["excluded"]
            album_is_except = album_sel is not None and album_sel["excluded"]

            works = list(Work.select()
                         .where(Work.album == album)
                         .order_by(Work.work_sequence))

            # Pre-load track counts per work for hide-single filtering
            work_track_counts = {}
            for work in works:
                work_track_counts[work.id] = Track.select().where(
                    Track.work == work).count()

            # Pre-scan children to detect partial state.
            # album_has_child_exception: a child is explicitly excluded
            #   → album is "partial" when it's added (not everything included)
            # album_has_child_add: a child is explicitly added
            #   → album is "partial" when it's NOT added, UNLESS every track is
            #     effectively included (then it's fully "included", not partial)
            album_has_child_exception = False
            album_has_child_add = False
            album_all_tracks_included = True
            for work in works:
                w_key = key_for_work(work)
                w_sel = sel_by_key.get(("work", w_key))
                work_add = w_sel is not None and not w_sel["excluded"]
                if w_sel:
                    if w_sel["excluded"]:
                        album_has_child_exception = True
                    else:
                        album_has_child_add = True
                tracks_for_work = list(Track.select(Track.relative_path).where(
                    Track.work == work))
                for t in tracks_for_work:
                    t_sel = sel_by_key.get(("track", t.relative_path))
                    t_add = t_sel is not None and not t_sel["excluded"]
                    t_exc = t_sel is not None and t_sel["excluded"]
                    if t_sel:
                        if t_exc:
                            album_has_child_exception = True
                        else:
                            album_has_child_add = True
                    # Effectively included (album itself not directly added here)
                    if not (t_add or (work_add and not t_exc)):
                        album_all_tracks_included = False

            # Filter works for display when hiding single-track works
            visible_works = works
            if hide_single:
                visible_works = [w for w in works if work_track_counts[w.id] > 1]
                if not visible_works:
                    continue

            # Determine album tag
            if album_is_except:
                album_tag = "excluded"
            elif album_is_add and album_has_child_exception:
                album_tag = "partial"  # added but some children excluded
            elif album_is_add:
                album_tag = "included"
            elif album_has_child_add:
                # Every track covered by child adds → fully included, else partial
                album_tag = ("included" if album_all_tracks_included
                             else "partial")
            else:
                album_tag = ""

            track_count = Track.select().where(Track.album == album).count()
            album_artist = album.album_artist or ""
            # Get representative genre from first track with one
            album_genre = ""
            first_genre_track = (Track.select(Track.genre)
                                 .where((Track.album == album) & Track.genre.is_null(False))
                                 .limit(1).first())
            if first_genre_track:
                album_genre = first_genre_track.genre or ""
            album_iid = self.builder_lib_tree.insert(
                "", "end", text=album.title,
                values=(album_artist, album_genre, f"{track_count} trk"),
                tags=(album_tag,) if album_tag else ())
            self._builder_lib_iid_map[album_iid] = ("album", album.id, a_key)
            self._lib_search_meta[album_iid] = " ".join(filter(None, [
                album.title, album_artist, album_genre]))

            for work in visible_works:
                w_key = key_for_work(work)
                tracks = list(Track.select().where(Track.work == work)
                              .order_by(Track.disc_number, Track.track_number))

                work_sel = sel_by_key.get(("work", w_key))
                work_is_add = work_sel is not None and not work_sel["excluded"]
                work_is_except = work_sel is not None and work_sel["excluded"]
                work_effectively_included = (
                    (work_is_add or album_is_add) and not work_is_except
                )

                # Check if any child track has an exception or add, and whether
                # every track is directly added (→ fully included, not partial)
                work_has_child_exception = False
                work_has_child_add = False
                work_all_tracks_added = bool(tracks)
                for t in tracks:
                    t_sel = sel_by_key.get(("track", t.relative_path))
                    if t_sel:
                        if t_sel["excluded"]:
                            work_has_child_exception = True
                        else:
                            work_has_child_add = True
                    if not (t_sel is not None and not t_sel["excluded"]):
                        work_all_tracks_added = False

                if work_is_except:
                    if work_has_child_add:
                        work_tag = "partial"  # excluded but some tracks added back
                    else:
                        work_tag = "excluded"
                elif work_effectively_included and work_has_child_exception:
                    work_tag = "partial"  # included but some tracks excluded
                elif work_effectively_included:
                    work_tag = "included"
                elif work_is_add:
                    work_tag = "included"
                elif work_has_child_add:
                    # All tracks added → fully included, otherwise partial
                    work_tag = "included" if work_all_tracks_added else "partial"
                else:
                    work_tag = ""

                work_composer = work.composer.name if work.composer_id else ""
                work_genre = tracks[0].genre if tracks and tracks[0].genre else ""
                work_iid = self.builder_lib_tree.insert(
                    album_iid, "end", text=work.work_name,
                    values=(work_composer, work_genre, f"{len(tracks)} trk"),
                    tags=(work_tag,) if work_tag else ())
                self._builder_lib_iid_map[work_iid] = ("work", work.id, w_key)
                self._lib_search_meta[work_iid] = " ".join(filter(None, [
                    work.work_name, work_composer, work_genre]))

                for t in tracks:
                    t_key = key_for_track(t)
                    dur_s = (t.duration_ms or 0) // 1000
                    dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"

                    track_sel = sel_by_key.get(("track", t_key))
                    track_is_except = track_sel is not None and track_sel["excluded"]
                    track_is_add = track_sel is not None and not track_sel["excluded"]

                    if track_is_except:
                        t_tag = "excluded"
                    elif track_is_add or work_effectively_included:
                        t_tag = "included"
                    else:
                        t_tag = ""

                    t_composer = t.composer.name if t.composer_id else ""
                    t_genre = t.genre or ""
                    t_iid = self.builder_lib_tree.insert(
                        work_iid, "end",
                        text=f"{t.disc_number}-{t.track_number:02d}: {t.title}",
                        values=(t_composer, t_genre, dur_str),
                        tags=(t_tag,) if t_tag else ())
                    self._builder_lib_iid_map[t_iid] = ("track", t.id, t_key)
                    self._lib_search_meta[t_iid] = " ".join(filter(None, [
                        t.title, t_composer, t_genre,
                        t.performer or "", t.conductor or "", t.ensemble or ""]))

        self._lib_tree_snapshot = self._snapshot_tree(self.builder_lib_tree)
        # Re-apply active filter if any
        if self._lib_filter_var.get().strip():
            self._apply_tree_filter("lib")

    def _rebuild_playlist_tree(self):
        """Rebuild the right (playlist) tree showing effectively-included items."""
        self._clear_tree_sort(self.builder_pl_tree)
        # Reattach any filter-detached items so delete catches everything
        for iid, parent, idx, txt, opn in self._pl_tree_snapshot:
            try:
                self.builder_pl_tree.reattach(iid, "", "end")
            except tk.TclError:
                pass
        self._pl_tree_snapshot = []
        self.builder_pl_tree.delete(*self.builder_pl_tree.get_children())
        self._builder_pl_iid_map.clear()
        self._pl_search_meta = {}

        if not self.active_library:
            return
        if not self._current_selections:
            return  # empty selections = all tracks (shown via label)

        from music_manager.core.database import Album, Work, Track
        from music_manager.core.selection import (
            key_for_album, key_for_work, key_for_track, COMPOSITE_SEP,
        )

        hide_single = self.builder_hide_single.get()

        # Build selection lookup dicts
        sel_by_key = {}
        for s in self._current_selections:
            sel_by_key[(s["level"], s["key"])] = s

        albums = (Album.select()
                  .where(Album.library == self.active_library)
                  .order_by(Album.title))

        for album in albums:
            a_key = key_for_album(album)
            album_sel = sel_by_key.get(("album", a_key))
            album_is_add = album_sel is not None and not album_sel["excluded"]
            album_is_except = album_sel is not None and album_sel["excluded"]
            if album_is_except:
                continue

            works = list(Work.select()
                         .where(Work.album == album)
                         .order_by(Work.work_sequence))

            # Collect works that should appear
            album_has_content = False
            work_entries = []
            for work in works:
                w_key = key_for_work(work)
                work_sel = sel_by_key.get(("work", w_key))
                work_is_add = work_sel is not None and not work_sel["excluded"]
                work_is_except = work_sel is not None and work_sel["excluded"]
                # Don't skip excluded works entirely — track-level adds
                # within them must still appear (specificity model).
                if work_is_except:
                    work_included = False
                else:
                    work_included = work_is_add or album_is_add

                tracks = list(Track.select().where(Track.work == work)
                              .order_by(Track.disc_number, Track.track_number))

                visible_tracks = []
                for t in tracks:
                    t_key = key_for_track(t)
                    track_sel = sel_by_key.get(("track", t_key))
                    track_is_except = track_sel is not None and track_sel["excluded"]
                    track_is_add = track_sel is not None and not track_sel["excluded"]
                    if track_is_except:
                        continue
                    if track_is_add or work_included:
                        visible_tracks.append(t)

                if visible_tracks:
                    if hide_single and len(visible_tracks) <= 1:
                        continue
                    work_entries.append((work, visible_tracks))
                    album_has_content = True

            if not album_has_content:
                continue

            total_tracks = sum(len(ts) for _, ts in work_entries)
            album_artist = album.album_artist or ""
            # Get representative genre from first track
            album_genre = ""
            for _, vts in work_entries:
                for vt in vts:
                    if vt.genre:
                        album_genre = vt.genre
                        break
                if album_genre:
                    break
            album_iid = self.builder_pl_tree.insert(
                "", "end", text=album.title,
                values=(album_artist, album_genre, f"{total_tracks} trk"))
            self._builder_pl_iid_map[album_iid] = ("album", album.id, a_key)
            self._pl_search_meta[album_iid] = " ".join(filter(None, [
                album.title, album_artist, album_genre]))

            for work, vis_tracks in work_entries:
                w_key = key_for_work(work)
                work_composer = work.composer.name if work.composer_id else ""
                work_genre = vis_tracks[0].genre if vis_tracks and vis_tracks[0].genre else ""
                # Check if this work is pinned (via selection pin_position)
                work_sel = sel_by_key.get(("work", w_key))
                pin_pos = work_sel.get("pin_position") if work_sel else None
                work_text = (f"[#{pin_pos}] {work.work_name}"
                             if pin_pos else work.work_name)
                work_iid = self.builder_pl_tree.insert(
                    album_iid, "end", text=work_text,
                    values=(work_composer, work_genre, f"{len(vis_tracks)} trk"),
                    tags=("pinned",) if pin_pos else ())
                self._builder_pl_iid_map[work_iid] = ("work", work.id, w_key)
                self._pl_search_meta[work_iid] = " ".join(filter(None, [
                    work.work_name, work_composer, work_genre]))

                for t in vis_tracks:
                    t_key = key_for_track(t)
                    dur_s = (t.duration_ms or 0) // 1000
                    dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
                    t_composer = t.composer.name if t.composer_id else ""
                    t_genre = t.genre or ""
                    t_iid = self.builder_pl_tree.insert(
                        work_iid, "end",
                        text=f"{t.disc_number}-{t.track_number:02d}: {t.title}",
                        values=(t_composer, t_genre, dur_str))
                    self._builder_pl_iid_map[t_iid] = ("track", t.id, t_key)
                    self._pl_search_meta[t_iid] = " ".join(filter(None, [
                        t.title, t_composer, t_genre,
                        t.performer or "", t.conductor or "", t.ensemble or ""]))

            # Auto-expand albums in playlist view
            self.builder_pl_tree.item(album_iid, open=True)

        self._pl_tree_snapshot = self._snapshot_tree(self.builder_pl_tree)
        # Re-apply active filter if any
        if self._pl_filter_var.get().strip():
            self._apply_tree_filter("pl")

    def _builder_context_menu(self, event, pane):
        """Right-click context menu on playlist builder trees."""
        tree = self.builder_lib_tree if pane == "lib" else self.builder_pl_tree
        iid_map = self._builder_lib_iid_map if pane == "lib" else self._builder_pl_iid_map

        iid = tree.identify_row(event.y)
        if not iid:
            return
        if iid not in tree.selection():
            tree.selection_set(iid)

        entry = iid_map.get(iid)
        if not entry:
            return
        level, entity_id, key = entry

        menu = tk.Menu(self.root, tearoff=0)

        try:
            if level == "work":
                from music_manager.core.database import Work
                work = Work.get_by_id(entity_id)
                menu.add_command(label="Details...",
                                 command=lambda: self._show_work_details(entity_id))
                menu.add_command(label="Show Album",
                                 command=lambda: self._show_album_popup(work.album_id))
            elif level == "track":
                from music_manager.core.database import Track
                track = Track.get_by_id(entity_id)
                menu.add_command(label="Play",
                                 command=lambda: self._play_track(entity_id))
                if track.work_id:
                    menu.add_command(label="Details...",
                                     command=lambda: self._show_work_details(track.work_id))
                menu.add_command(label="Show Album",
                                 command=lambda: self._show_album_popup(track.album_id))
            elif level == "album":
                menu.add_command(label="Show Album",
                                 command=lambda: self._show_album_popup(entity_id))
        except Exception:
            messagebox.showinfo("Stale Data", "Data has changed. Please refresh the view.")
            return

        menu.add_separator()
        if pane == "lib":
            menu.add_command(label="Add >>",
                             command=self._builder_include_selected)
            menu.add_command(label="<< Remove",
                             command=self._builder_exclude_selected)
            menu.add_separator()
            menu.add_command(
                label="Show in profiles...",
                command=lambda lv=level, eid=entity_id, k=key: self._show_in_profiles(lv, eid, k))
        else:
            menu.add_command(label="<< Remove",
                             command=self._builder_exclude_selected)
            if level == "work":
                pin_menu = tk.Menu(menu, tearoff=0)
                for pos in range(1, 6):
                    pin_menu.add_command(
                        label=f"Position {pos}",
                        command=lambda p=pos, wid=entity_id, wk=key: self._pin_work(wid, p, wk),
                    )
                pin_menu.add_separator()
                pin_menu.add_command(
                    label="Remove pin",
                    command=lambda wk=key: self._unpin_work(wk),
                )
                menu.add_cascade(label="Pin to position...", menu=pin_menu)

        menu.tk_popup(event.x_root, event.y_root)

    def _pin_work(self, work_id, position, work_key):
        """Pin a work to a position (1-5). Replaces any existing pin at that position."""
        from music_manager.core.database import Work, Track
        from music_manager.core.selection import display_name_for_selection
        try:
            work = Work.get_by_id(work_id)
        except Work.DoesNotExist:
            return

        # Remove any existing pin at this position from other selections
        for s in self._current_selections:
            if s.get("pin_position") == position and s["key"] != work_key:
                s["pin_position"] = None
                # Rebuild display text without pin prefix
                prefix = "EXCEPT" if s["excluded"] else "ADD"
                dn = display_name_for_selection(self.active_library, s["level"], s["key"])
                s["display"] = f"{prefix}: {s['level']} — {dn}"

        # Find or create selection for this work
        sel = self._find_selection("work", work_key)
        if sel is not None:
            sel["pin_position"] = position
            # Rebuild display text with pin prefix
            prefix = "EXCEPT" if sel["excluded"] else "ADD"
            dn = display_name_for_selection(self.active_library, "work", work_key)
            sel["display"] = f"[#{position}] {prefix}: work — {dn}"
        else:
            # Create a new add selection with pin and track_paths breadcrumbs
            track_paths = json.dumps([
                t.relative_path for t in
                Track.select(Track.relative_path).where(Track.work == work)
            ])
            self._add_selection("work", work_key, excluded=False,
                                pin_position=position, track_paths=track_paths,
                                refresh=False)

        self._refresh_rules_display()

    def _unpin_work(self, work_key):
        """Remove a pin for a work."""
        from music_manager.core.selection import display_name_for_selection
        sel = self._find_selection("work", work_key)
        if sel and sel.get("pin_position"):
            sel["pin_position"] = None
            prefix = "EXCEPT" if sel["excluded"] else "ADD"
            dn = display_name_for_selection(self.active_library, "work", work_key)
            sel["display"] = f"{prefix}: work — {dn}"
        self._refresh_rules_display()

    def _show_in_profiles(self, level, entity_id, key):
        """Show a popup listing all profiles that include this item."""
        from music_manager.core.database import (
            PlaylistProfile, ProfileSelection, Album, Work, Track,
        )
        from music_manager.core.selection import parse_work_key

        # Get display name for the item
        if level == "album":
            name = Album.get_by_id(entity_id).title
        elif level == "work":
            name = Work.get_by_id(entity_id).work_name
        elif level == "track":
            name = Track.get_by_id(entity_id).title
        else:
            name = str(entity_id)

        # Find all profiles (non-internal) that have a matching add selection
        # Direct match at this level
        direct_sels = list(ProfileSelection.select().where(
            (ProfileSelection.excluded == False) &
            (ProfileSelection.level == level) &
            (ProfileSelection.key == key)
        ))
        profile_ids = {s.profile_id for s in direct_sels}

        # Also check parent-level adds (album add covers work/track)
        if level == "work":
            parsed = parse_work_key(key)
            if parsed:
                album_key = parsed[0]
                album_sels = list(ProfileSelection.select().where(
                    (ProfileSelection.excluded == False) &
                    (ProfileSelection.level == "album") &
                    (ProfileSelection.key == album_key)
                ))
                profile_ids.update(s.profile_id for s in album_sels)
        elif level == "track":
            track = Track.get_by_id(entity_id)
            if track.work_id:
                from music_manager.core.selection import key_for_work
                work = Work.get_by_id(track.work_id)
                work_key = key_for_work(work)
                work_sels = list(ProfileSelection.select().where(
                    (ProfileSelection.excluded == False) &
                    (ProfileSelection.level == "work") &
                    (ProfileSelection.key == work_key)
                ))
                profile_ids.update(s.profile_id for s in work_sels)
            album = Album.get_by_id(track.album_id)
            album_sels = list(ProfileSelection.select().where(
                (ProfileSelection.excluded == False) &
                (ProfileSelection.level == "album") &
                (ProfileSelection.key == album.album_key)
            ))
            profile_ids.update(s.profile_id for s in album_sels)

        # Also include profiles with NO selections (they include everything)
        all_profiles = list(PlaylistProfile.select().where(
            ~PlaylistProfile.name.startswith("__")))
        profiles_with_no_selections = []
        for prof in all_profiles:
            if prof.id in profile_ids:
                continue
            has_adds = ProfileSelection.select().where(
                (ProfileSelection.profile == prof) &
                (ProfileSelection.excluded == False)
            ).exists()
            if not has_adds:
                profiles_with_no_selections.append(prof)

        # Gather matching profile objects
        matching = [p for p in all_profiles if p.id in profile_ids]
        matching.sort(key=lambda p: p.name)

        # Build popup
        popup = tk.Toplevel(self.root)
        popup.title(f"Profiles including: {name}")
        popup.transient(self.root)
        self._center_on_main(popup, 450, 300)
        popup.wait_visibility()
        popup.grab_set()

        ctk = self.ctk
        frame = ctk.CTkFrame(popup)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        lb = tk.Listbox(frame, bg="#2b2b2b", fg="white",
                        selectbackground="#1f6aa5",
                        font=("Segoe UI", 10))
        lb.pack(fill="both", expand=True)

        if matching:
            for p in matching:
                lb.insert("end", f"{p.name}  ({p.library.name})")
        if profiles_with_no_selections:
            lb.insert("end", "")
            lb.insert("end", "— Profiles with no selections (all tracks) —")
            for p in sorted(profiles_with_no_selections, key=lambda p: p.name):
                lb.insert("end", f"{p.name}  ({p.library.name})")

        if not matching and not profiles_with_no_selections:
            lb.insert("end", "(not included in any profile)")

        ctk.CTkButton(popup, text="Close", width=80,
                      command=popup.destroy).pack(pady=(0, 10))

    def _builder_toggle_include(self, event=None):
        """Toggle selection state of library items on double-click.

        Simple 3-state toggle:
          - Has direct add → remove it (and clean up children)
          - Has direct exception → remove the exception
          - Not selected → add it
          - Selected via parent → add exception
        """
        sel = self.builder_lib_tree.selection()
        if not sel:
            return "break"

        entries = []
        for iid in sel:
            entry = self._builder_lib_iid_map.get(iid)
            if entry:
                entries.append(entry)

        for level, entity_id, key in entries:
            existing = self._find_selection(level, key)
            if existing is not None:
                if existing["excluded"]:
                    # Exception → remove it (re-includes via parent)
                    # Also clean up child selections that were workarounds
                    self._current_selections.remove(existing)
                    self._cascade_remove_children(level, key)
                else:
                    # Direct add → remove it and clean up children
                    self._current_selections.remove(existing)
                    self._cascade_remove_children(level, key)
                    # If still covered by a broader parent selection, one
                    # toggle should hide it — add an exclusion rather than
                    # leaving it visible via the parent (which would take a
                    # second toggle to clear).
                    if self._is_item_selected(level, key):
                        self._add_selection(level, key, excluded=True,
                                            refresh=False)
            elif self._is_item_selected(level, key):
                # Included via parent — add exception
                self._add_selection(level, key, excluded=True, refresh=False)
            else:
                # Not selected — add it
                self.__add_with_breadcrumbs(level, key, entity_id)

        with self._busy():
            view_state = self._save_builder_view_state()
            self._refresh_rules_display()
            self._restore_builder_view_state(view_state)
        return "break"

    def _builder_include_selected(self, event=None):
        """Add selected library items as selections."""
        sel = self.builder_lib_tree.selection()
        if not sel:
            if event is None:
                messagebox.showinfo("Select", "Select items in the Library pane first.")
            return "break"

        entries = []
        for iid in sel:
            entry = self._builder_lib_iid_map.get(iid)
            if entry:
                entries.append(entry)

        for level, entity_id, key in entries:
            existing = self._find_selection(level, key)
            if existing and not existing["excluded"]:
                continue  # already added
            if existing and existing["excluded"]:
                # Has exception — remove it to re-include via parent
                # Also clean up child selections that are now redundant
                self._current_selections.remove(existing)
                self._cascade_remove_children(level, key)
            else:
                self.__add_with_breadcrumbs(level, key, entity_id)

        with self._busy():
            view_state = self._save_builder_view_state()
            self._refresh_rules_display()
            self._restore_builder_view_state(view_state)
        return "break"

    def _builder_exclude_selected(self, event=None):
        """Remove selected items (remove direct adds or add exceptions)."""
        # Try playlist tree first, then library tree
        sel = self.builder_pl_tree.selection()
        iid_map = self._builder_pl_iid_map
        if not sel:
            sel = self.builder_lib_tree.selection()
            iid_map = self._builder_lib_iid_map
        if not sel:
            if event is None:
                messagebox.showinfo("Select", "Select items to remove.")
            return "break"

        entries = []
        for iid in sel:
            entry = iid_map.get(iid)
            if entry:
                entries.append(entry)

        for level, entity_id, key in entries:
            existing = self._find_selection(level, key)
            if existing and not existing["excluded"]:
                # Direct add — remove it and clean up children
                self._current_selections.remove(existing)
                self._cascade_remove_children(level, key)
            # After dropping any direct add, the item may still be covered by
            # a broader parent selection (e.g. its album was added). Removing
            # only the direct add would leave it visible via the parent, so
            # add an explicit exclusion to actually take it out.
            if self._is_item_selected(level, key):
                self._add_selection(level, key, excluded=True, refresh=False)

        with self._busy():
            view_state = self._save_builder_view_state()
            self._refresh_rules_display()
            self._restore_builder_view_state(view_state)
        return "break"

    def _cascade_remove_children(self, level, key):
        """Remove all child selections when a parent selection is removed."""
        from music_manager.core.selection import COMPOSITE_SEP

        if level == "album":
            album_key = key
            self._current_selections = [
                s for s in self._current_selections
                if not (
                    (s["level"] == "work" and s["key"].startswith(album_key + COMPOSITE_SEP))
                    or (s["level"] == "track" and s["key"].startswith(album_key + "/"))
                )
            ]
        elif level == "work":
            # Remove track-level selections for tracks belonging to this work
            from music_manager.core.selection import parse_work_key
            from music_manager.core.database import Work, Track, Album
            parsed = parse_work_key(key)
            if parsed:
                album_key, work_name, work_seq = parsed
                album = Album.select().where(
                    (Album.library == self.active_library) &
                    (Album.album_key == album_key)
                ).first()
                if album:
                    query = Work.select().where(
                        (Work.album == album) & (Work.work_name == work_name)
                    )
                    if work_seq is not None:
                        query = query.where(Work.work_sequence == work_seq)
                    work = query.first()
                    if work:
                        track_paths = {
                            t.relative_path for t in
                            Track.select(Track.relative_path).where(Track.work == work)
                        }
                        self._current_selections = [
                            s for s in self._current_selections
                            if not (s["level"] == "track" and s["key"] in track_paths)
                        ]

    def __add_with_breadcrumbs(self, level, key, entity_id):
        """Add a selection, including track_paths breadcrumbs for work-level."""
        import json
        track_paths = None
        if level == "work":
            from music_manager.core.database import Track
            track_paths = json.dumps([
                t.relative_path for t in
                Track.select(Track.relative_path).where(Track.work == entity_id)
            ])
        self._add_selection(level, key, excluded=False,
                            track_paths=track_paths, refresh=False)

    def _build_temp_profile(self):
        """Build a temporary PlaylistProfile from current UI settings."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return None

        from music_manager.core.database import PlaylistProfile, ProfileSelection

        # Use a temp name that won't collide with user-saved profiles
        name = "__temp_preview__"
        # Clean up any leftover temp profiles (CASCADE deletes selections)
        for old in PlaylistProfile.select().where(PlaylistProfile.name == name):
            old.delete_instance()

        length_val = self.length_value.get().strip()
        seed_val = self.seed_entry.get().strip()

        profile = PlaylistProfile.create(
            library=self.active_library,
            name=name,
            shuffle_mode=self.shuffle_mode.get(),
            work_integrity=self.work_integrity.get(),
            length_mode=self.length_mode.get(),
            length_value=self._parse_length_value(length_val),
            seed=int(seed_val) if seed_val else None,
            no_repeat_tracks=self.no_repeat_var.get() == 1,
            separate_composers=self.sep_composer_var.get() == 1,
            separate_albums=self.sep_album_var.get() == 1,
            separate_forms=self.sep_form_var.get() == 1,
        )

        for sel in self._current_selections:
            ProfileSelection.create(
                profile=profile,
                level=sel["level"],
                key=sel["key"],
                excluded=sel["excluded"],
                pin_position=sel.get("pin_position"),
                track_paths=sel.get("track_paths"),
            )

        return profile

    @staticmethod
    def _parse_length_value(text):
        """Parse a length value that may be an integer, or H:MM / M:SS duration.

        Returns seconds (int) or None if empty.  Raises ValueError on bad input.
        """
        text = text.strip()
        if not text:
            return None
        if ":" in text:
            parts = text.split(":")
            if len(parts) == 2:
                h_or_m, m_or_s = int(parts[0]), int(parts[1])
                return h_or_m * 3600 + m_or_s * 60  # treat as H:MM
            elif len(parts) == 3:
                h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                return h * 3600 + m * 60 + s
            else:
                raise ValueError(f"Invalid duration format: {text}")
        return int(text)

    def _delete_temp_profile(self, profile):
        """Delete a temporarily-created profile."""
        if profile:
            profile.delete_instance()  # CASCADE deletes selections

    def _preview_playlist(self):
        """Preview the playlist in a popup window (dry-run)."""
        display_name = self.profile_name_entry.get().strip() or "Untitled"
        profile = self._build_temp_profile()
        if not profile:
            return

        with self._busy():
            try:
                from music_manager.core.engine import generate_playlist
                result = generate_playlist(profile)
            except Exception as exc:
                self._delete_temp_profile(profile)
                messagebox.showerror("Preview Error", str(exc))
                return

        self._delete_temp_profile(profile)

        # Build popup
        popup = tk.Toplevel(self.root)
        popup.title(f"Preview — {display_name}")
        popup.transient(self.root)
        self._center_on_main(popup, 900, 550)
        popup.wait_visibility()
        popup.grab_set()

        # Bottom bar (pack first so tree gets remaining space)
        total_s = result.total_duration_ms // 1000
        status_text = (f"{result.track_count} tracks, "
                       f"{total_s // 3600}h {(total_s % 3600) // 60}m "
                       f"{total_s % 60}s total")

        bot = tk.Frame(popup, bg="#2b2b2b")
        bot.pack(side="bottom", fill="x", padx=10, pady=5)
        tk.Label(bot, text=status_text, bg="#2b2b2b", fg="white",
                 font=("Segoe UI", 11)).pack(side="left", padx=5)
        tk.Button(bot, text="Close", command=popup.destroy,
                  bg="#3b3b3b", fg="white").pack(side="right", padx=5)

        # Tree + scrollbar in a frame
        tree_frame = tk.Frame(popup)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        tree = ttk.Treeview(tree_frame,
                            columns=("order", "composer", "work", "title", "dur"),
                            show="headings", selectmode="browse")
        tree.heading("order", text="#")
        tree.heading("composer", text="Composer")
        tree.heading("work", text="Work")
        tree.heading("title", text="Title")
        tree.heading("dur", text="Duration")
        tree.column("order", width=40, anchor="center")
        tree.column("composer", width=150)
        tree.column("work", width=220)
        tree.column("title", width=280)
        tree.column("dur", width=70, anchor="center")

        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        if not result.playlist:
            tree.insert("", "end", values=(
                "", "", "", "(no tracks matched current rules)", ""))
        else:
            for rt in result.playlist:
                dur_s = rt.duration_ms // 1000
                dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
                tree.insert("", "end", values=(
                    rt.order_key,
                    rt.composer_name or "",
                    rt.work_name or "",
                    rt.title,
                    dur_str,
                ))

    def _find_unused(self):
        """Populate the builder with tracks not included in any saved profile."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        self._save_before_export()

        with self._busy():
            try:
                from music_manager.core.engine import find_unused_tracks
                albums, works, tracks = find_unused_tracks(self.active_library)
            except Exception as exc:
                messagebox.showerror("Find Unused Error", str(exc))
                return

        if not albums and not works and not tracks:
            messagebox.showinfo(
                "Find Unused",
                "All tracks are used by at least one profile.")
            return

        # Clear builder and populate with unused items
        self._new_profile()
        from music_manager.core.database import Album, Work, Track
        from music_manager.core.selection import key_for_album, key_for_work, key_for_track
        for target_id, name in albums:
            album = Album.get_by_id(target_id)
            self._add_selection("album", key_for_album(album), refresh=False)
        for target_id, name in works:
            work = Work.get_by_id(target_id)
            self.__add_with_breadcrumbs("work", key_for_work(work), target_id)
        for target_id, name in tracks:
            track = Track.get_by_id(target_id)
            self._add_selection("track", key_for_track(track), refresh=False)
        self._refresh_rules_display()

    # ------------------------------------------------------------------
    # Builder: Find Similar Tracks
    # ------------------------------------------------------------------

    def _find_similar_tracks(self):
        """Find tracks similar to the current profile selections."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return
        if not self._current_selections:
            messagebox.showinfo(
                "No Selections",
                "Add some tracks first — all selections are used as seeds "
                "for the similarity search.")
            return

        # Resolve current selections to track IDs
        seed_ids = self._resolve_current_to_track_ids()
        if not seed_ids:
            messagebox.showinfo(
                "No Tracks",
                "Current selections don't match any tracks.")
            return

        # Check for unanalyzed or stale-version tracks
        from music_manager.core.similarity import TrackAnalysis, FEATURE_VERSION
        from music_manager.core.database import Track
        current = set(
            ta.track_id for ta in
            TrackAnalysis.select(TrackAnalysis.track)
            .join(Track)
            .where((Track.library == self.active_library) &
                   (TrackAnalysis.feature_version == FEATURE_VERSION))
        )
        total_tracks = Track.select().where(
            Track.library == self.active_library).count()
        unanalyzed = total_tracks - len(current)

        if unanalyzed > 0:
            if not messagebox.askyesno(
                "Analysis Required",
                f"{unanalyzed} tracks need analysis before similarity "
                f"search.\nThis may take a while. Proceed?"):
                return
            self._run_sim_analysis(seed_ids)
        else:
            self._show_sim_results(seed_ids)

    def _resolve_current_to_track_ids(self):
        """Resolve _current_selections to a set of track IDs."""
        from music_manager.core.selection import resolve_selections
        from music_manager.core.database import PlaylistProfile, ProfileSelection

        profile = self._build_temp_profile()
        if not profile:
            return set()
        try:
            track_ids, _, _ = resolve_selections(profile)
        finally:
            profile.delete_instance(recursive=True)
        return track_ids

    def _run_sim_analysis(self, seed_ids):
        """Run library analysis with progress, then show results."""
        import threading
        self._sim_cancel_flag = False

        popup = tk.Toplevel(self.root)
        popup.title("Analyzing Library")
        popup.transient(self.root)
        popup.resizable(False, False)
        self._center_on_main(popup, 400, 120)
        popup.wait_visibility()
        popup.grab_set()

        ctk = self.ctk
        status = ctk.CTkLabel(popup, text="Analyzing...")
        status.pack(padx=20, pady=(15, 5))
        progress = ctk.CTkProgressBar(popup, width=300)
        progress.pack(padx=20, pady=5)
        progress.set(0)
        cancel_btn = ctk.CTkButton(
            popup, text="Cancel", width=80,
            command=lambda: setattr(self, '_sim_cancel_flag', True))
        cancel_btn.pack(pady=(5, 10))

        def worker():
            from music_manager.core.similarity import (
                analyze_library, AnalysisCancelled)
            try:
                def prog(current, total, msg):
                    if self._sim_cancel_flag:
                        raise AnalysisCancelled()
                    title = (msg[:35] + "...") if len(msg) > 35 else msg
                    self.root.after(0, lambda c=current, t=total, m=title:
                                   _update(c, t, m))

                stats = analyze_library(self.active_library,
                                        progress_callback=prog)
                self.root.after(0, lambda: _done(stats))
            except AnalysisCancelled:
                self.root.after(0, _cancelled)
            except Exception as exc:
                self.root.after(0, lambda e=exc: _error(e))

        def _update(current, total, msg):
            if total > 0:
                progress.set(current / total)
            status.configure(text=f"Analyzing {current}/{total}: {msg}")

        def _done(stats):
            popup.destroy()
            self._show_sim_results(seed_ids)

        def _cancelled():
            popup.destroy()

        def _error(exc):
            popup.destroy()
            messagebox.showerror("Analysis Error", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _show_sim_results(self, seed_ids):
        """Show similarity results in a Toplevel window."""
        popup = tk.Toplevel(self.root)
        popup.title("Find Similar Tracks")
        popup.transient(self.root)
        self._center_on_main(popup, 900, 560)
        popup.wait_visibility()
        popup.grab_set()

        ctk = self.ctk

        # -- Parameter controls --
        param_frame = ctk.CTkFrame(popup, fg_color="transparent")
        param_frame.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(param_frame, text="Max results:").pack(
            side="left", padx=(0, 4))
        limit_var = tk.StringVar(value="50")
        ctk.CTkEntry(param_frame, textvariable=limit_var, width=55).pack(
            side="left", padx=(0, 12))

        ctk.CTkLabel(param_frame, text="Volatility max:").pack(
            side="left", padx=(0, 4))
        vol_var = tk.DoubleVar(value=1.0)
        vol_slider = ctk.CTkSlider(
            param_frame, from_=0.0, to=1.0, variable=vol_var, width=110,
            command=lambda v: vol_label.configure(
                text=f"{float(v):.2f}" if vol_enabled.get() else "Off"))
        vol_slider.pack(side="left", padx=(0, 2))
        vol_label = ctk.CTkLabel(param_frame, text="Off", width=30)
        vol_label.pack(side="left", padx=(0, 2))
        vol_enabled = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            param_frame, text="", variable=vol_enabled, width=20,
            command=lambda: vol_label.configure(
                text=f"{vol_var.get():.2f}" if vol_enabled.get() else "Off")
        ).pack(side="left", padx=(0, 12))

        ctk.CTkLabel(param_frame, text="Blend:").pack(
            side="left", padx=(0, 4))
        blend_var = tk.DoubleVar(value=0.5)
        ctk.CTkSlider(param_frame, from_=0.0, to=1.0,
                      variable=blend_var, width=110).pack(
            side="left", padx=(0, 4))
        ctk.CTkLabel(param_frame, text="nearest ↔ consensus",
                     font=ctk.CTkFont(size=10)).pack(side="left", padx=(0, 12))

        search_btn = ctk.CTkButton(param_frame, text="Search", width=70)
        search_btn.pack(side="left")

        # -- Results Treeview --
        tree_frame = ctk.CTkFrame(popup, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=12, pady=4)

        result_tree = ttk.Treeview(
            tree_frame,
            columns=("composer", "album", "match", "agreement", "volatility"),
            show="tree headings", selectmode="extended")
        result_tree.heading("#0", text="Title")
        result_tree.heading("composer", text="Composer")
        result_tree.heading("album", text="Album")
        result_tree.heading("match", text="Match")
        result_tree.heading("agreement", text="Agreement")
        result_tree.heading("volatility", text="Volatility")
        result_tree.column("#0", width=220)
        result_tree.column("composer", width=140)
        result_tree.column("album", width=160)
        result_tree.column("match", width=60)
        result_tree.column("agreement", width=70)
        result_tree.column("volatility", width=70)
        result_tree.pack(fill="both", expand=True)
        result_tree.tag_configure("match_close", foreground="#2d7d46")
        result_tree.tag_configure("match_loose", foreground="#c98a1f")
        result_tree.tag_configure("match_weak", foreground="#a03a3a")

        scroll = ttk.Scrollbar(tree_frame, orient="vertical",
                               command=result_tree.yview)
        result_tree.configure(yscrollcommand=scroll.set)
        scroll.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne",
                     in_=result_tree)

        result_tree.bind("<Button-3>", lambda e: self._sim_result_context_menu(
            e, result_tree, sim_state))

        # -- Bottom: action buttons + status --
        bot_frame = ctk.CTkFrame(popup, fg_color="transparent")
        bot_frame.pack(fill="x", padx=12, pady=(4, 10))

        ctk.CTkButton(
            bot_frame, text="Accept Selected", width=120,
            fg_color="#2d7d46",
            command=lambda: self._accept_sim_tracks(
                result_tree, sim_state, selected_only=True)
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            bot_frame, text="Accept All", width=100,
            fg_color="#2d7d46",
            command=lambda: self._accept_sim_tracks(
                result_tree, sim_state, selected_only=False)
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            bot_frame, text="Re-search (include accepted)", width=200,
            command=lambda: self._sim_re_search(
                result_tree, sim_state, limit_var, vol_var,
                vol_enabled, blend_var)
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            bot_frame, text="Close", width=70,
            command=popup.destroy).pack(side="left", padx=(0, 4))

        status_label = ctk.CTkLabel(bot_frame, text="", text_color="gray")
        status_label.pack(side="right", padx=10)

        # Shared state dict for the results window
        sim_state = {
            "seed_ids": seed_ids,
            "result_map": {},       # iid → result dict
            "status_label": status_label,
            "popup": popup,
        }

        # Wire up search button
        search_btn.configure(command=lambda: self._do_sim_search(
            result_tree, sim_state, limit_var, vol_var,
            vol_enabled, blend_var))

        # Run initial search
        self._do_sim_search(result_tree, sim_state, limit_var, vol_var,
                            vol_enabled, blend_var)

    def _do_sim_search(self, result_tree, sim_state, limit_var, vol_var,
                       vol_enabled, blend_var):
        """Execute similarity search and populate the results Treeview."""
        from music_manager.core.similarity import find_similar

        try:
            limit = int(limit_var.get())
        except ValueError:
            limit = 50
        vol_max = vol_var.get() if vol_enabled.get() else None
        blend = blend_var.get()
        seed_ids = sim_state["seed_ids"]

        results = find_similar(
            list(seed_ids), limit=limit,
            volatility_max=vol_max, blend=blend)

        # Filter out tracks already in the profile
        selected_track_ids = self._resolve_current_to_track_ids()
        results = [r for r in results if r["track_id"] not in selected_track_ids]

        # Populate tree
        result_tree.delete(*result_tree.get_children())
        sim_state["result_map"].clear()
        for r in results:
            match_pct = r.get("match_pct")
            if match_pct is None:
                tag = "match_loose"
            elif match_pct >= 70:
                tag = "match_close"
            elif match_pct >= 40:
                tag = "match_loose"
            else:
                tag = "match_weak"
            iid = result_tree.insert(
                "", "end", text=r["title"],
                tags=(tag,),
                values=(
                    r["composer"],
                    r["album"],
                    f"{match_pct:.0f}%" if match_pct is not None else "",
                    f"{r['agreement']}/{r['seed_count']}",
                    f"{r['volatility']:.3f}" if r["volatility"] is not None else "",
                ))
            sim_state["result_map"][iid] = r

        sim_state["status_label"].configure(
            text=f"{len(results)} similar tracks found")

    def _accept_sim_tracks(self, result_tree, sim_state, selected_only=True):
        """Add result tracks as track-level selections in the profile."""
        if selected_only:
            iids = result_tree.selection()
            if not iids:
                messagebox.showinfo("Select", "Select tracks to accept.",
                                    parent=sim_state["popup"])
                return
        else:
            iids = result_tree.get_children()
            if not iids:
                return

        from music_manager.core.database import Track

        added = 0
        for iid in iids:
            r = sim_state["result_map"].get(iid)
            if not r:
                continue
            track = Track.get_by_id(r["track_id"])
            self._add_selection("track", track.relative_path, refresh=False)
            added += 1

        if added:
            with self._busy():
                view_state = self._save_builder_view_state()
                self._refresh_rules_display()
                self._restore_builder_view_state(view_state)

        # Remove accepted items from the tree
        for iid in list(iids):
            if iid in sim_state["result_map"]:
                del sim_state["result_map"][iid]
            result_tree.delete(iid)

        remaining = len(result_tree.get_children())
        sim_state["status_label"].configure(
            text=f"{added} accepted, {remaining} remaining")

    def _sim_result_context_menu(self, event, result_tree, sim_state):
        """Right-click context menu on the Find Similar results tree."""
        iid = result_tree.identify_row(event.y)
        if not iid:
            return
        if iid not in result_tree.selection():
            result_tree.selection_set(iid)

        r = sim_state["result_map"].get(iid)
        if not r:
            return

        from music_manager.core.database import Track
        track = Track.get_by_id(r["track_id"])

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Play",
                         command=lambda: self._play_track(track.id))
        if track.work_id:
            menu.add_command(label="Details...",
                             command=lambda: self._show_work_details(track.work_id))
        menu.tk_popup(event.x_root, event.y_root)

    def _sim_re_search(self, result_tree, sim_state, limit_var, vol_var,
                       vol_enabled, blend_var):
        """Re-resolve selections (including accepted tracks) and re-search."""
        new_seed_ids = self._resolve_current_to_track_ids()
        if not new_seed_ids:
            messagebox.showinfo(
                "No Seeds", "No tracks to use as seeds.",
                parent=sim_state["popup"])
            return
        sim_state["seed_ids"] = new_seed_ids
        self._do_sim_search(result_tree, sim_state, limit_var, vol_var,
                            vol_enabled, blend_var)

    def _save_before_export(self):
        """Silently save profile settings before an export operation.

        Only updates an existing profile's settings (shuffle mode, length,
        etc.) in place — never deletes/recreates the profile or touches its
        rules.  If no profile with this name exists yet, creates a new one
        with the current UI rules.
        """
        name = self.profile_name_entry.get().strip()
        if name and self.active_library:
            from music_manager.core.database import PlaylistProfile, ProfileSelection

            # Skip if there's a cross-library name conflict
            conflict = PlaylistProfile.select().where(
                (PlaylistProfile.name == name) &
                (PlaylistProfile.library != self.active_library) &
                (~PlaylistProfile.name.startswith("__"))
            ).first()
            if conflict:
                return

            length_val = self.length_value.get().strip()
            seed_val = self.seed_entry.get().strip()

            existing = PlaylistProfile.select().where(
                (PlaylistProfile.library == self.active_library) &
                (PlaylistProfile.name == name)
            ).first()

            if existing:
                existing.shuffle_mode = self.shuffle_mode.get()
                existing.work_integrity = self.work_integrity.get()
                existing.length_mode = self.length_mode.get()
                existing.length_value = self._parse_length_value(length_val)
                existing.seed = int(seed_val) if seed_val else None
                existing.no_repeat_tracks = self.no_repeat_var.get() == 1
                existing.separate_composers = self.sep_composer_var.get() == 1
                existing.separate_albums = self.sep_album_var.get() == 1
                existing.separate_forms = self.sep_form_var.get() == 1
                existing.save()
                # Sync selections from current UI state
                ProfileSelection.delete().where(
                    ProfileSelection.profile == existing).execute()
                for sel in self._current_selections:
                    ProfileSelection.create(
                        profile=existing,
                        level=sel["level"],
                        key=sel["key"],
                        excluded=sel["excluded"],
                        pin_position=sel.get("pin_position"),
                        track_paths=sel.get("track_paths"),
                    )
            else:
                profile = PlaylistProfile.create(
                    library=self.active_library,
                    name=name,
                    shuffle_mode=self.shuffle_mode.get(),
                    work_integrity=self.work_integrity.get(),
                    length_mode=self.length_mode.get(),
                    length_value=self._parse_length_value(length_val),
                    seed=int(seed_val) if seed_val else None,
                    no_repeat_tracks=self.no_repeat_var.get() == 1,
                    separate_composers=self.sep_composer_var.get() == 1,
                    separate_albums=self.sep_album_var.get() == 1,
                    separate_forms=self.sep_form_var.get() == 1,
                )
                for sel in self._current_selections:
                    ProfileSelection.create(
                        profile=profile,
                        level=sel["level"],
                        key=sel["key"],
                        excluded=sel["excluded"],
                        pin_position=sel.get("pin_position"),
                        track_paths=sel.get("track_paths"),
                    )

            self._clear_autosave()
        else:
            self._autosave()

    def _export_m3u(self):
        """Export the playlist to an M3U file."""
        self._save_before_export()
        default_name = self.profile_name_entry.get().strip() or "playlist"
        initial_dir = self._prefs.get("last_export_dir", "")
        path = filedialog.asksaveasfilename(
            defaultextension=".m3u",
            initialfile=f"{default_name}.m3u",
            initialdir=initial_dir or None,
            filetypes=[("M3U Playlist", "*.m3u"), ("All files", "*.*")],
            title="Export M3U",
            parent=self.root,
        )
        if not path:
            return
        self._prefs["last_export_dir"] = str(Path(path).parent)
        _save_prefs(self._prefs)

        profile = self._build_temp_profile()
        if not profile:
            return

        try:
            from music_manager.core.engine import generate_playlist
            from music_manager.core.serializers.m3u import M3USerializer
            from music_manager.core.config import load_config

            result = generate_playlist(profile)
            config = load_config()
            m3u_config = config.get("targets", {}).get("m3u", {})
            m3u_config["output_path"] = path

            serializer = M3USerializer()
            serializer.serialize(result.playlist, m3u_config)
            messagebox.showinfo("Export", f"Wrote {result.track_count} tracks to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))
        finally:
            self._delete_temp_profile(profile)

    def _export_json(self):
        """Export the playlist to a JSON file."""
        self._save_before_export()
        default_name = self.profile_name_entry.get().strip() or "playlist"
        initial_dir = self._prefs.get("last_export_dir", "")
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile=f"{default_name}.json",
            initialdir=initial_dir or None,
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            title="Export JSON",
            parent=self.root,
        )
        if not path:
            return
        self._prefs["last_export_dir"] = str(Path(path).parent)
        _save_prefs(self._prefs)

        profile = self._build_temp_profile()
        if not profile:
            return

        try:
            from music_manager.core.engine import generate_playlist
            from music_manager.core.serializers.json_dump import serialize_engine_result

            result = generate_playlist(profile)
            serialize_engine_result(result, output_path=Path(path))
            messagebox.showinfo("Export", f"Wrote {result.track_count} tracks to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))
        finally:
            self._delete_temp_profile(profile)

    def _push_plex(self):
        """Push the playlist to Plex."""
        self._save_before_export()
        profile = self._build_temp_profile()
        if not profile:
            return

        with self._busy():
            try:
                from music_manager.core.engine import generate_playlist
                from music_manager.core.serializers.plex import PlexSerializer, PlexConnectionError, PlexPushError
                from music_manager.core.config import load_config

                result = generate_playlist(profile)
                config = load_config()
                plex_config = config.get("targets", {}).get("plex", {})
                plex_config["playlist_name"] = self.profile_name_entry.get().strip() or "Untitled"

                # Use per-library Plex section if set, otherwise fall back to config
                lib_section = (self.active_library.plex_section
                               if self.active_library and self.active_library.plex_section
                               else None)
                if lib_section:
                    plex_config["music_section"] = lib_section

                serializer = PlexSerializer()
                serializer.serialize(result.playlist, plex_config)
                display_name = plex_config["playlist_name"]
                messagebox.showinfo("Plex", f"Pushed '{display_name}' to Plex "
                                   f"({result.track_count} tracks)")
            except (PlexConnectionError, PlexPushError) as exc:
                messagebox.showerror("Plex Error", str(exc))
            except Exception as exc:
                messagebox.showerror("Error", str(exc))
            finally:
                self._delete_temp_profile(profile)

    def _new_profile(self):
        """Clear the builder to start a fresh playlist profile."""
        self.profile_name_entry.delete(0, "end")
        self.shuffle_mode.set("work")
        self.work_integrity.set("enforce")
        self.length_mode.set("all")
        self.length_value.delete(0, "end")
        self.seed_entry.delete(0, "end")
        self.no_repeat_var.select()
        self.sep_composer_var.deselect()
        self.sep_album_var.deselect()
        self.sep_form_var.deselect()
        self._current_selections.clear()
        self._refresh_rules_display()
        self._refresh_builder_tree()

    def _save_profile(self):
        """Save current settings as a named profile in the DB."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        name = self.profile_name_entry.get().strip()
        if not name:
            messagebox.showwarning("No Name", "Enter a profile name.")
            return

        from music_manager.core.database import PlaylistProfile, ProfileSelection

        # Enforce unique profile names across all libraries
        conflict = PlaylistProfile.select().where(
            (PlaylistProfile.name == name) &
            (PlaylistProfile.library != self.active_library) &
            (~PlaylistProfile.name.startswith("__"))
        ).first()
        if conflict:
            messagebox.showwarning(
                "Name Conflict",
                f"A profile named '{name}' already exists in library "
                f"'{conflict.library.name}'. Profile names must be unique "
                f"across all libraries.")
            return

        # Delete existing profile with same name in this library (CASCADE handles selections)
        for existing in PlaylistProfile.select().where(
            (PlaylistProfile.library == self.active_library) &
            (PlaylistProfile.name == name)
        ):
            existing.delete_instance()

        length_val = self.length_value.get().strip()
        seed_val = self.seed_entry.get().strip()

        profile = PlaylistProfile.create(
            library=self.active_library,
            name=name,
            shuffle_mode=self.shuffle_mode.get(),
            work_integrity=self.work_integrity.get(),
            length_mode=self.length_mode.get(),
            length_value=self._parse_length_value(length_val),
            seed=int(seed_val) if seed_val else None,
            no_repeat_tracks=self.no_repeat_var.get() == 1,
            separate_composers=self.sep_composer_var.get() == 1,
            separate_albums=self.sep_album_var.get() == 1,
            separate_forms=self.sep_form_var.get() == 1,
        )

        for sel in self._current_selections:
            ProfileSelection.create(
                profile=profile,
                level=sel["level"],
                key=sel["key"],
                excluded=sel.get("excluded", False),
                pin_position=sel.get("pin_position"),
                track_paths=sel.get("track_paths"),
            )

        self._clear_autosave()
        messagebox.showinfo("Saved", f"Profile '{name}' saved.")

    def _delete_profile(self):
        """Show a profile picker, then delete the selected profile after confirmation."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return
        if self._profile_picker_open:
            return
        self._profile_picker_open = True

        from music_manager.core.database import PlaylistProfile

        profiles = list(PlaylistProfile.select().where(
            (PlaylistProfile.library == self.active_library) &
            (~PlaylistProfile.name.startswith("__"))))
        if not profiles:
            self._profile_picker_open = False
            messagebox.showinfo("No Profiles", "No saved profiles found.")
            return

        # Deduplicate names (keep latest)
        seen = set()
        names = []
        for p in reversed(profiles):
            if p.name not in seen:
                seen.add(p.name)
                names.append(p.name)
        names.reverse()

        picker = tk.Toplevel(self.root)
        picker.title("Delete Profile")
        picker.transient(self.root)
        self._center_on_main(picker, 300, 300)
        picker.wait_visibility()
        picker.grab_set()

        lb = tk.Listbox(picker, bg="#2b2b2b", fg="white",
                        selectbackground="#1f6aa5", font=("Segoe UI", 11),
                        selectmode="extended")
        for n in names:
            lb.insert("end", n)
        lb.pack(fill="both", expand=True, padx=10, pady=10)

        def on_delete():
            sel = lb.curselection()
            if not sel:
                return
            selected_names = [names[i] for i in sel]
            count = len(selected_names)
            label = selected_names[0] if count == 1 else f"{count} profiles"
            if not messagebox.askyesno("Confirm Delete",
                                       f"Delete {label}?", parent=picker):
                return
            for sname in selected_names:
                for existing in PlaylistProfile.select().where(
                    (PlaylistProfile.library == self.active_library) &
                    (PlaylistProfile.name == sname)
                ):
                    existing.delete_instance()  # CASCADE deletes selections
            picker.destroy()
            self._profile_picker_open = False
            # Clear the profile name if it was one of the deleted profiles
            current_name = self.profile_name_entry.get().strip()
            if current_name in selected_names:
                self.profile_name_entry.delete(0, "end")
                self._current_selections.clear()
                self._refresh_rules_display()
            messagebox.showinfo("Deleted", f"Deleted {label}.")

        def on_close():
            picker.destroy()
            self._profile_picker_open = False

        picker.protocol("WM_DELETE_WINDOW", on_close)
        ctk = self.ctk
        ctk.CTkButton(picker, text="Delete", command=on_delete,
                      fg_color="#c0392b", hover_color="#e74c3c").pack(pady=5)

    def _load_profile(self):
        """Always show a profile picker dialog, then load the selected profile."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return
        if self._profile_picker_open:
            return
        self._profile_picker_open = True

        from music_manager.core.database import PlaylistProfile
        profiles = list(PlaylistProfile.select().where(
            (PlaylistProfile.library == self.active_library) &
            (~PlaylistProfile.name.startswith("__"))))
        if not profiles:
            self._profile_picker_open = False
            messagebox.showinfo("No Profiles", "No saved profiles found.")
            return

        # Deduplicate names (keep latest)
        seen = set()
        names = []
        for p in reversed(profiles):
            if p.name not in seen:
                seen.add(p.name)
                names.append(p.name)
        names.reverse()

        picker = tk.Toplevel(self.root)
        picker.title("Select Profile")
        picker.transient(self.root)
        self._center_on_main(picker, 300, 300)
        picker.wait_visibility()
        picker.grab_set()

        lb = tk.Listbox(picker, bg="#2b2b2b", fg="white",
                       selectbackground="#1f6aa5", font=("Segoe UI", 11))
        for n in names:
            lb.insert("end", n)
        lb.pack(fill="both", expand=True, padx=10, pady=10)

        def on_select():
            sel = lb.curselection()
            if not sel:
                return
            chosen = names[sel[0]]
            picker.destroy()
            self._profile_picker_open = False
            self._apply_profile(chosen)

        def on_close():
            picker.destroy()
            self._profile_picker_open = False

        picker.protocol("WM_DELETE_WINDOW", on_close)
        ctk = self.ctk
        ctk.CTkButton(picker, text="Load", command=on_select).pack(pady=5)
        lb.bind("<Double-1>", lambda e: on_select())

    def _apply_profile(self, name):
        """Load a named profile's settings and selections into the UI."""
        from music_manager.core.database import PlaylistProfile, ProfileSelection
        from music_manager.core.selection import display_name_for_selection

        try:
            profile = PlaylistProfile.get(
                (PlaylistProfile.library == self.active_library) &
                (PlaylistProfile.name == name)
            )
        except PlaylistProfile.DoesNotExist:
            messagebox.showwarning("Not Found", f"Profile '{name}' not found.")
            return
        self.root.config(cursor="watch")
        self.root.update_idletasks()

        # Populate UI
        self.profile_name_entry.delete(0, "end")
        self.profile_name_entry.insert(0, name)
        self.shuffle_mode.set(profile.shuffle_mode)
        self.work_integrity.set(profile.work_integrity)
        self.length_mode.set(profile.length_mode)
        self.length_value.delete(0, "end")
        if profile.length_value is not None:
            self.length_value.insert(0, str(profile.length_value))
        self.seed_entry.delete(0, "end")
        if profile.seed is not None:
            self.seed_entry.insert(0, str(profile.seed))
        if profile.no_repeat_tracks:
            self.no_repeat_var.select()
        else:
            self.no_repeat_var.deselect()
        if profile.separate_composers:
            self.sep_composer_var.select()
        else:
            self.sep_composer_var.deselect()
        if profile.separate_albums:
            self.sep_album_var.select()
        else:
            self.sep_album_var.deselect()
        if profile.separate_forms:
            self.sep_form_var.select()
        else:
            self.sep_form_var.deselect()

        # Load selections
        self._current_selections.clear()
        for sel in ProfileSelection.select().where(
            ProfileSelection.profile == profile
        ):
            display_name = display_name_for_selection(
                self.active_library, sel.level, sel.key
            )
            prefix = "EXCLUDE" if sel.excluded else "ADD"
            pin_str = f" [PIN #{sel.pin_position}]" if sel.pin_position else ""
            self._current_selections.append({
                "level": sel.level,
                "key": sel.key,
                "excluded": sel.excluded,
                "pin_position": sel.pin_position,
                "track_paths": sel.track_paths,
                "display": f"{prefix}: {sel.level} — {display_name}{pin_str}",
            })

        self._refresh_rules_display()
        self.root.config(cursor="")

    # ------------------------------------------------------------------
    # Tab 3: Cleanup / Overlay (§10)
    # ------------------------------------------------------------------

    def _build_cleanup_tab(self):
        """Build the Cleanup / Overlay tab."""
        ctk = self.ctk
        tab = self.tab_cleanup

        # Top bar: export/import overrides
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(top, text="Export Overrides JSON", width=180,
                      command=self._export_overrides).pack(side="left", padx=5)
        ctk.CTkButton(top, text="Import Overrides JSON", width=180,
                      command=self._import_overrides).pack(side="left", padx=5)
        ctk.CTkButton(top, text="?", width=28, height=28,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color="gray30", hover_color="gray40",
                      command=lambda: self._show_help("cleanup"),
                      ).pack(side="right", padx=5)

        # Works browser with source filter + search
        filter_frame = ctk.CTkFrame(tab, fg_color="transparent")
        filter_frame.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(filter_frame, text="Works Browser",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            side="left", padx=5)
        ctk.CTkButton(filter_frame, text="+", width=24, height=24,
                      fg_color="transparent", hover_color="gray40",
                      text_color="gray70", font=ctk.CTkFont(size=14),
                      command=lambda: self._toggle_tree(self.works_tree, True)
                      ).pack(side="left", padx=(6, 0))
        ctk.CTkButton(filter_frame, text="\u2013", width=24, height=24,
                      fg_color="transparent", hover_color="gray40",
                      text_color="gray70", font=ctk.CTkFont(size=14),
                      command=lambda: self._toggle_tree(self.works_tree, False)
                      ).pack(side="left")

        self._cleanup_search_var = tk.StringVar()
        self._cleanup_search_var.trace_add("write", lambda *_: self._debounce_cleanup_search())
        self.cleanup_search = ctk.CTkEntry(filter_frame, width=200,
                                           placeholder_text="Search works...",
                                           textvariable=self._cleanup_search_var)
        self.cleanup_search.pack(side="right", padx=5)
        self._cleanup_search_after = None

        self.cleanup_hide_single = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(filter_frame, text="Hide 1-track",
                        variable=self.cleanup_hide_single,
                        command=self._refresh_works_list,
                        width=20).pack(side="right", padx=5)

        _SOURCE_OPTIONS = ["Heuristic", "Standalone", "All Works",
                           "Override", "MB Work ID", "Work Tag"]
        self.cleanup_source_var = tk.StringVar(value="Heuristic")
        self.cleanup_source_menu = ctk.CTkOptionMenu(
            filter_frame, variable=self.cleanup_source_var,
            values=_SOURCE_OPTIONS, width=140,
            command=lambda _: self._refresh_works_list())
        self.cleanup_source_menu.pack(side="right", padx=5)
        ctk.CTkLabel(filter_frame, text="Source:").pack(side="right", padx=(5, 0))

        self.works_tree = ttk.Treeview(
            tab, columns=("source", "album", "tracks", "composer"),
            show="tree headings", selectmode="extended", height=10)
        self.works_tree.heading("#0", text="Name")
        self.works_tree.heading("source", text="Source")
        self.works_tree.heading("album", text="Album")
        self.works_tree.heading("tracks", text="Tracks")
        self.works_tree.heading("composer", text="Composer")
        self.works_tree.column("#0", width=300)
        self.works_tree.column("source", width=80)
        self.works_tree.column("album", width=200)
        self.works_tree.column("tracks", width=60, anchor="center")
        self.works_tree.column("composer", width=150)
        self.works_tree.pack(fill="both", expand=True, padx=10, pady=5)

        w_scroll = ttk.Scrollbar(self.works_tree, orient="vertical",
                                 command=self.works_tree.yview)
        self.works_tree.configure(yscrollcommand=w_scroll.set)
        w_scroll.pack(side="right", fill="y")
        self.works_tree.bind("<Button-3>", self._cleanup_work_context_menu)
        self._setup_tree_sort(self.works_tree)

        self._cleanup_work_map = {}  # iid → work.id (work-level items only)
        self._cleanup_track_map = {}  # iid → track.id (track-level children)

        # Edit section
        edit_frame = ctk.CTkFrame(tab)
        edit_frame.pack(fill="x", padx=10, pady=10)

        edit_top = ctk.CTkFrame(edit_frame, fg_color="transparent")
        edit_top.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(edit_top, text="Edit Selected Work",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left", padx=0)
        ctk.CTkButton(edit_top, text="Show Album", width=110,
                      command=self._show_album_for_selected).pack(
            side="right", padx=5)

        row_e1 = ctk.CTkFrame(edit_frame, fg_color="transparent")
        row_e1.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row_e1, text="Work Name:").pack(side="left", padx=5)
        self.edit_work_name = ctk.CTkEntry(row_e1, width=300)
        self.edit_work_name.pack(side="left", padx=5)
        ctk.CTkButton(row_e1, text="Set Work Name", width=120,
                      command=self._set_work_name_override).pack(side="left", padx=5)

        row_e2 = ctk.CTkFrame(edit_frame, fg_color="transparent")
        row_e2.pack(fill="x", padx=10, pady=3)
        ctk.CTkButton(row_e2, text="Make Standalone", width=120,
                      command=self._make_work_standalone).pack(side="left", padx=5)

        row_e3 = ctk.CTkFrame(edit_frame, fg_color="transparent")
        row_e3.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row_e3, text="Composer:").pack(side="left", padx=5)
        self.edit_composer = ctk.CTkEntry(row_e3, width=300)
        self.edit_composer.pack(side="left", padx=5)
        ctk.CTkButton(row_e3, text="Set Composer", width=120,
                      command=self._set_composer_override).pack(side="left", padx=5)

        # Overrides list
        ov_header = ctk.CTkFrame(tab, fg_color="transparent")
        ov_header.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(ov_header, text="Current Overrides",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            side="left", padx=5)
        self._overrides_search_var = tk.StringVar()
        self._overrides_search_var.trace_add("write", lambda *_: self._debounce_overrides_search())
        self.overrides_search = ctk.CTkEntry(ov_header, width=200,
                                             placeholder_text="Filter overrides...",
                                             textvariable=self._overrides_search_var)
        self.overrides_search.pack(side="right", padx=5)
        self._overrides_search_after = None

        self.overrides_tree = ttk.Treeview(
            tab, columns=("scope", "field", "value", "match"),
            show="headings", selectmode="browse", height=6)
        self.overrides_tree.heading("scope", text="Scope")
        self.overrides_tree.heading("field", text="Field")
        self.overrides_tree.heading("value", text="Value")
        self.overrides_tree.heading("match", text="Match")
        self.overrides_tree.column("scope", width=60)
        self.overrides_tree.column("field", width=130)
        self.overrides_tree.column("value", width=300)
        self.overrides_tree.column("match", width=300)
        self.overrides_tree.pack(fill="both", expand=True, padx=10, pady=5)
        self._setup_tree_sort(self.overrides_tree)
        self._override_id_map = {}

        del_btn_frame = ctk.CTkFrame(tab, fg_color="transparent")
        del_btn_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(del_btn_frame, text="Delete Override", width=140,
                      command=self._delete_override).pack(side="left", padx=5)

    def _debounce_cleanup_search(self):
        """Debounce live search on the cleanup works tree."""
        if self._cleanup_search_after:
            self.root.after_cancel(self._cleanup_search_after)
        self._cleanup_search_after = self.root.after(250, self._refresh_works_list)

    def _debounce_overrides_search(self):
        """Debounce live search on the overrides list."""
        if self._overrides_search_after:
            self.root.after_cancel(self._overrides_search_after)
        self._overrides_search_after = self.root.after(250, self._refresh_overrides_list)

    def _debounce_explorer_search(self):
        """Debounce live search on the explorer album list."""
        if self._explorer_search_after:
            self.root.after_cancel(self._explorer_search_after)
        self._explorer_search_after = self.root.after(250, self._refresh_explorer)

    def _refresh_cleanup(self):
        """Reload works list and overrides."""
        self._refresh_works_list()
        self._refresh_overrides_list()

    def _refresh_works_list(self):
        """Reload the works treeview based on source filter and search."""
        self._clear_tree_sort(self.works_tree)
        self.works_tree.delete(*self.works_tree.get_children())
        self._cleanup_work_map.clear()
        self._cleanup_track_map.clear()

        if not self.active_library:
            return

        from music_manager.core.database import Work, Album, Track

        source_label = self.cleanup_source_var.get()
        source_map = {
            "Heuristic": "heuristic",
            "Standalone": "standalone",
            "Override": "override",
            "MB Work ID": "mb_workid",
            "Work Tag": "work_tag",
        }

        query = (Work.select(Work, Album)
                 .join(Album)
                 .where(Album.library == self.active_library))

        if source_label in source_map:
            query = query.where(Work.work_source == source_map[source_label])

        query = query.order_by(Album.title, Work.work_name)

        search = self.cleanup_search.get().strip().lower()
        hide_single = self.cleanup_hide_single.get()

        for work in query:
            tracks = list(Track.select().where(Track.work == work)
                          .order_by(Track.disc_number, Track.track_number))

            if hide_single and len(tracks) <= 1:
                continue

            composer = tracks[0].composer.name if tracks and tracks[0].composer_id else ""

            if search:
                haystack = f"{work.work_name} {work.album.title} {composer}".lower()
                if search not in haystack:
                    continue

            work_iid = self.works_tree.insert(
                "", "end", text=work.work_name,
                values=(work.work_source, work.album.title, len(tracks), composer))
            self._cleanup_work_map[work_iid] = work.id

            for t in tracks:
                dur_s = (t.duration_ms or 0) // 1000
                dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
                track_iid = self.works_tree.insert(
                    work_iid, "end",
                    text=f"{t.disc_number}-{t.track_number:02d}: {t.title}",
                    values=("", "", dur_str, ""))
                self._cleanup_track_map[track_iid] = t.id

    def _refresh_overrides_list(self):
        """Reload the overrides treeview with optional search filter."""
        self._clear_tree_sort(self.overrides_tree)
        self.overrides_tree.delete(*self.overrides_tree.get_children())
        self._override_id_map.clear()

        if not self.active_library:
            return

        from music_manager.core.database import Override

        search = self.overrides_search.get().strip().lower() if hasattr(self, "overrides_search") else ""

        for ov in Override.select().where(Override.library == self.active_library):
            match = ov.match_mb_id or ov.match_relative_path or ""
            if search:
                haystack = f"{ov.scope} {ov.field} {ov.value} {match}".lower()
                if search not in haystack:
                    continue
            iid = self.overrides_tree.insert("", "end", values=(
                ov.scope, ov.field, ov.value, match
            ))
            self._override_id_map[iid] = ov.id

    def _get_selected_cleanup_work(self):
        """Get the work ID of the first selected work (or its parent if a track is selected)."""
        sel = self.works_tree.selection()
        if not sel:
            messagebox.showinfo("Select", "Select a work first.")
            return None
        iid = sel[0]
        if iid not in self._cleanup_work_map:
            parent = self.works_tree.parent(iid)
            if parent:
                iid = parent
        return self._cleanup_work_map.get(iid)

    def _get_selected_cleanup_works(self):
        """Get work IDs for all selected items (resolving tracks to their parent works)."""
        sel = self.works_tree.selection()
        if not sel:
            messagebox.showinfo("Select", "Select one or more works first.")
            return []
        work_ids = []
        seen = set()
        for iid in sel:
            if iid not in self._cleanup_work_map:
                parent = self.works_tree.parent(iid)
                if parent:
                    iid = parent
            wid = self._cleanup_work_map.get(iid)
            if wid and wid not in seen:
                work_ids.append(wid)
                seen.add(wid)
        return work_ids

    def _cleanup_work_context_menu(self, event):
        """Right-click context menu on the works tree."""
        iid = self.works_tree.identify_row(event.y)
        if not iid:
            return
        # Add to selection if not already selected (preserve multi-select)
        if iid not in self.works_tree.selection():
            self.works_tree.selection_set(iid)

        # Check if clicked item is a track child
        track_id = self._cleanup_track_map.get(iid)

        # Resolve clicked item to work level
        click_iid = iid
        if click_iid not in self._cleanup_work_map:
            parent = self.works_tree.parent(click_iid)
            if parent:
                click_iid = parent
        work_id = self._cleanup_work_map.get(click_iid)
        if not work_id:
            return

        from music_manager.core.database import Work
        work = Work.get_by_id(work_id)

        menu = tk.Menu(self.root, tearoff=0)
        if track_id:
            menu.add_command(label="Play",
                             command=lambda: self._play_track(track_id))
            menu.add_separator()
        menu.add_command(label="Details...",
                         command=lambda: self._show_work_details(work_id))
        menu.add_command(label="Show Album",
                         command=lambda: self._show_album_popup(work.album_id))
        menu.add_separator()
        menu.add_command(label="Set Work Name...",
                         command=lambda: self.edit_work_name.focus_set())
        menu.add_command(label="Set Group Key...",
                         command=lambda: self.edit_group_key.focus_set())
        menu.add_command(label="Set Composer...",
                         command=lambda: self.edit_composer.focus_set())
        menu.add_separator()
        menu.add_command(label="Make Standalone",
                         command=self._make_work_standalone)
        menu.tk_popup(event.x_root, event.y_root)

    def _show_album_for_selected(self):
        """Open the Show Album popup for the album containing the selected work."""
        work_id = self._get_selected_cleanup_work()
        if not work_id:
            return
        from music_manager.core.database import Work
        work = Work.get_by_id(work_id)
        self._show_album_popup(work.album_id)

    def _show_work_details(self, work_id):
        """Show a details popup for a work and its tracks."""
        from music_manager.core.database import Work, Track, Album
        ctk = self.ctk

        work = Work.get_by_id(work_id)
        album = work.album
        tracks = list(Track.select().where(Track.work == work)
                      .order_by(Track.disc_number, Track.track_number))
        composer_name = work.composer.name if work.composer_id else ""

        from music_manager.core.similarity import TrackAnalysis
        volatility_by_track = {
            ta.track_id: ta.volatility for ta in
            TrackAnalysis.select(TrackAnalysis.track, TrackAnalysis.volatility)
            .where(TrackAnalysis.track.in_([t.id for t in tracks]))
        }

        popup = tk.Toplevel(self.root)
        popup.title(f"Details: {work.work_name}")
        popup.transient(self.root)
        self._center_on_main(popup, 750, 500)
        popup.wait_visibility()
        popup.grab_set()

        # Scrollable text widget with all details
        text = tk.Text(popup, wrap="word", font=("monospace", 10),
                       bg="#2b2b2b", fg="#dcdcdc", insertbackground="#dcdcdc",
                       selectbackground="#4a6984", padx=10, pady=10)
        text.pack(fill="both", expand=True, padx=10, pady=(10, 5))
        scroll = ttk.Scrollbar(text, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")

        def _add(label, value):
            text.insert("end", f"{label}: ", "label")
            text.insert("end", f"{value}\n")

        text.tag_configure("label", foreground="#88aacc", font=("monospace", 10, "bold"))
        text.tag_configure("heading", foreground="#ccddaa", font=("monospace", 11, "bold"))
        text.tag_configure("sep", foreground="#555555")

        text.insert("end", "WORK\n", "heading")
        _add("  Name", work.work_name)
        _add("  Source", work.work_source)
        _add("  Composer", composer_name)
        _add("  Sequence", work.work_sequence)
        _add("  MB Work ID", work.musicbrainz_work_id or "")
        _add("  Album", album.title)
        _add("  Album Artist", album.album_artist or "")
        _add("  Album Key", album.album_key)

        text.insert("end", f"\nTRACKS ({len(tracks)})\n", "heading")
        for t in tracks:
            dur_s = (t.duration_ms or 0) // 1000
            dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
            t_composer = t.composer.name if t.composer_id else ""
            text.insert("end", "-" * 60 + "\n", "sep")
            _add(f"  {t.disc_number}-{t.track_number:02d}", t.title)
            _add("    Composer", t_composer)
            _add("    Duration", dur_str)
            _add("    Path", t.relative_path)
            _add("    MB Recording", t.musicbrainz_recording_id or "")
            if t.movement_number is not None:
                _add("    Movement #", t.movement_number)
            volatility = volatility_by_track.get(t.id)
            _add("    Volatility", f"{volatility:.3f}" if volatility is not None
                 else "not analyzed")

        text.configure(state="disabled")

        # Bottom buttons
        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(btn_frame, text="Copy Work Name", width=130,
                      command=lambda: (self.root.clipboard_clear(),
                                       self.root.clipboard_append(work.work_name))
                      ).pack(side="left", padx=5)
        if work.musicbrainz_work_id:
            ctk.CTkButton(btn_frame, text="Copy MB Work ID", width=130,
                          command=lambda: (self.root.clipboard_clear(),
                                           self.root.clipboard_append(
                                               work.musicbrainz_work_id))
                          ).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Close", width=80,
                      command=popup.destroy).pack(side="right", padx=5)

    def _show_album_popup(self, album_id):
        """Open a popup showing all works and tracks in an album for editing."""
        from music_manager.core.database import Album, Work, Track
        from music_manager.core.overrides import set_override

        album = Album.get_by_id(album_id)
        ctk = self.ctk

        popup = tk.Toplevel(self.root)
        popup.title(f"Album: {album.title}")
        popup.transient(self.root)
        self._center_on_main(popup, 1100, 750)
        popup.wait_visibility()
        popup.grab_set()

        # --- Album header edit fields ---
        header = ctk.CTkFrame(popup)
        header.pack(fill="x", padx=10, pady=(10, 5))

        for row_idx, (label, field, current_val, scope_field) in enumerate([
            ("Album Title:", "album_title", album.title, "album_title"),
            ("Album Artist:", "album_artist", album.album_artist or "", "album_artist"),
            ("Year:", "year", str(album.year) if album.year else "", "year"),
        ]):
            row = ctk.CTkFrame(header, fg_color="transparent")
            row.pack(fill="x", padx=5, pady=2)
            ctk.CTkLabel(row, text=label, width=100, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(row, width=350)
            entry.insert(0, current_val)
            entry.pack(side="left", padx=5)

            def _make_album_setter(ent, sf, alb):
                def _set():
                    val = ent.get().strip()
                    if not val:
                        return
                    set_override(
                        library=self.active_library, scope="album",
                        field=sf, value=val,
                        match_relative_path=alb.album_key,
                        match_mb_id=alb.musicbrainz_album_id,
                    )
                    if sf == "album_title":
                        alb.title = val
                    elif sf == "album_artist":
                        alb.album_artist = val
                    elif sf == "year":
                        alb.year = int(val) if val.isdigit() else None
                    alb.save()
                    messagebox.showinfo("Done", f"Set {sf} to '{val}'.",
                                        parent=popup)
                    self._refresh_overrides_list()
                return _set

            ctk.CTkButton(row, text="Set", width=60,
                          command=_make_album_setter(entry, scope_field, album)
                          ).pack(side="left", padx=5)

        # --- Works/Tracks treeview ---
        tree_frame = ctk.CTkFrame(popup, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=10, pady=5)

        album_tree = ttk.Treeview(
            tree_frame, columns=("source", "composer", "detail"),
            show="tree headings", selectmode="extended", height=15)
        album_tree.heading("#0", text="Name")
        album_tree.heading("source", text="Source")
        album_tree.heading("composer", text="Composer")
        album_tree.heading("detail", text="Tracks/Duration")
        album_tree.column("#0", width=400)
        album_tree.column("source", width=80)
        album_tree.column("composer", width=150)
        album_tree.column("detail", width=80, anchor="center")
        album_tree.pack(side="left", fill="both", expand=True)

        a_scroll = ttk.Scrollbar(tree_frame, orient="vertical",
                                 command=album_tree.yview)
        album_tree.configure(yscrollcommand=a_scroll.set)
        a_scroll.pack(side="right", fill="y")

        # Track map for resolving selections
        popup_track_map = {}  # iid → ("work", work_id) or ("track", track_id)

        works = Work.select().where(Work.album == album).order_by(Work.work_sequence)
        for work in works:
            tracks = list(Track.select().where(Track.work == work)
                          .order_by(Track.disc_number, Track.track_number))
            composer = tracks[0].composer.name if tracks and tracks[0].composer_id else ""
            work_iid = album_tree.insert(
                "", "end", text=work.work_name,
                values=(work.work_source, composer, f"{len(tracks)} tracks"))
            popup_track_map[work_iid] = ("work", work.id)

            for t in tracks:
                dur_s = (t.duration_ms or 0) // 1000
                dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
                t_iid = album_tree.insert(
                    work_iid, "end",
                    text=f"{t.disc_number}-{t.track_number:02d}: {t.title}",
                    values=("", t.composer.name if t.composer_id else "", dur_str))
                popup_track_map[t_iid] = ("track", t.id)

        # Selection info
        sel_label = ctk.CTkLabel(popup, text="No tracks selected",
                                 font=ctk.CTkFont(size=11))
        sel_label.pack(padx=10, pady=(5, 0), anchor="w")

        def _update_selection_label(event=None):
            tracks = _resolve_selected_tracks()
            sel_label.configure(text=f"{len(tracks)} track(s) selected")

        album_tree.bind("<<TreeviewSelect>>", _update_selection_label)

        def _album_popup_context_menu(event):
            iid = album_tree.identify_row(event.y)
            if not iid:
                return
            if iid not in album_tree.selection():
                album_tree.selection_set(iid)
            entry = popup_track_map.get(iid)
            if not entry:
                return
            level, eid = entry
            if level == "track":
                menu = tk.Menu(popup, tearoff=0)
                menu.add_command(label="Play",
                                 command=lambda: self._play_track(eid))
                menu.tk_popup(event.x_root, event.y_root)

        album_tree.bind("<Button-3>", _album_popup_context_menu)

        def _resolve_selected_tracks():
            """Resolve selected treeview items to a list of Track objects."""
            sel = album_tree.selection()
            track_ids = set()
            for iid in sel:
                entry = popup_track_map.get(iid)
                if not entry:
                    continue
                level, eid = entry
                if level == "track":
                    track_ids.add(eid)
                elif level == "work":
                    for t in Track.select(Track.id).where(Track.work == eid):
                        track_ids.add(t.id)
            return list(Track.select().where(Track.id.in_(list(track_ids)))
                        ) if track_ids else []

        # --- Action buttons ---
        action_frame = ctk.CTkFrame(popup)
        action_frame.pack(fill="x", padx=10, pady=5)

        # Group Key
        # Work Name
        row_w = ctk.CTkFrame(action_frame, fg_color="transparent")
        row_w.pack(fill="x", padx=5, pady=3)
        ctk.CTkLabel(row_w, text="Work Name:").pack(side="left", padx=5)
        popup_work_name = ctk.CTkEntry(row_w, width=280)
        popup_work_name.pack(side="left", padx=5)

        def _set_work_name():
            name = popup_work_name.get().strip()
            if not name:
                messagebox.showwarning("Empty", "Enter a work name.",
                                       parent=popup)
                return
            tracks = _resolve_selected_tracks()
            if not tracks:
                messagebox.showwarning("Select", "Select tracks first.",
                                       parent=popup)
                return
            work_ids_updated = set()
            for t in tracks:
                set_override(
                    library=self.active_library, scope="track",
                    field="work_name", value=name,
                    match_relative_path=t.relative_path,
                    match_mb_id=t.musicbrainz_recording_id,
                )
                if t.work_id:
                    work_ids_updated.add(t.work_id)
            for wid in work_ids_updated:
                w = Work.get_by_id(wid)
                w.work_name = name
                w.save()
            messagebox.showinfo(
                "Done",
                f"Set work name to '{name}' for {len(tracks)} track(s).",
                parent=popup)
            self._refresh_overrides_list()
            self._refresh_works_list()
            # Refresh the popup tree
            _refresh_popup_tree()

        ctk.CTkButton(row_w, text="Set for Selected", width=130,
                      command=_set_work_name).pack(side="left", padx=5)

        def _make_standalone():
            tracks = _resolve_selected_tracks()
            if not tracks:
                messagebox.showwarning("Select", "Select tracks first.",
                                       parent=popup)
                return
            for t in tracks:
                set_override(
                    library=self.active_library, scope="track",
                    field="work_name", value="__standalone__",
                    match_relative_path=t.relative_path,
                    match_mb_id=t.musicbrainz_recording_id,
                )
            messagebox.showinfo(
                "Done",
                f"Marked {len(tracks)} track(s) as standalone.\n"
                f"Re-detect Works or Rescan to apply.",
                parent=popup)
            self._refresh_overrides_list()

        ctk.CTkButton(row_w, text="Make Standalone", width=130,
                      command=_make_standalone).pack(side="left", padx=5)

        # Composer
        row_c = ctk.CTkFrame(action_frame, fg_color="transparent")
        row_c.pack(fill="x", padx=5, pady=3)
        ctk.CTkLabel(row_c, text="Composer:").pack(side="left", padx=5)
        popup_composer = ctk.CTkEntry(row_c, width=280)
        popup_composer.pack(side="left", padx=5)

        def _set_composer():
            comp = popup_composer.get().strip()
            if not comp:
                messagebox.showwarning("Empty", "Enter a composer name.",
                                       parent=popup)
                return
            tracks = _resolve_selected_tracks()
            if not tracks:
                messagebox.showwarning("Select", "Select tracks first.",
                                       parent=popup)
                return
            for t in tracks:
                set_override(
                    library=self.active_library, scope="track",
                    field="composer", value=comp,
                    match_relative_path=t.relative_path,
                    match_mb_id=t.musicbrainz_recording_id,
                )
            messagebox.showinfo(
                "Done",
                f"Set composer to '{comp}' for {len(tracks)} track(s).\n"
                f"Rescan or apply overrides to update.",
                parent=popup)
            self._refresh_overrides_list()

        ctk.CTkButton(row_c, text="Set for Selected", width=130,
                      command=_set_composer).pack(side="left", padx=5)

        def _refresh_popup_tree():
            """Reload the popup treeview after changes."""
            album_tree.delete(*album_tree.get_children())
            popup_track_map.clear()
            for work in Work.select().where(Work.album == album).order_by(Work.work_sequence):
                tracks = list(Track.select().where(Track.work == work)
                              .order_by(Track.disc_number, Track.track_number))
                composer = tracks[0].composer.name if tracks and tracks[0].composer_id else ""
                w_iid = album_tree.insert(
                    "", "end", text=work.work_name,
                    values=(work.work_source, composer, f"{len(tracks)} tracks"))
                popup_track_map[w_iid] = ("work", work.id)
                for t in tracks:
                    dur_s = (t.duration_ms or 0) // 1000
                    dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
                    t_iid = album_tree.insert(
                        w_iid, "end",
                        text=f"{t.disc_number}-{t.track_number:02d}: {t.title}",
                        values=("", t.composer.name if t.composer_id else "", dur_str))
                    popup_track_map[t_iid] = ("track", t.id)
            sel_label.configure(text="No tracks selected")

        # Bottom bar
        ctk.CTkButton(popup, text="Close", width=80,
                      command=popup.destroy).pack(pady=(0, 10))

    def _set_work_name_override(self):
        """Set a work_name override for all selected works' tracks."""
        work_ids = self._get_selected_cleanup_works()
        if not work_ids:
            return
        new_name = self.edit_work_name.get().strip()
        if not new_name:
            messagebox.showwarning("Empty", "Enter a work name.")
            return

        from music_manager.core.database import Work, Track
        from music_manager.core.overrides import set_override

        total = 0
        for work_id in work_ids:
            work = Work.get_by_id(work_id)
            tracks = list(Track.select().where(Track.work == work))
            for t in tracks:
                set_override(
                    library=self.active_library, scope="track", field="work_name",
                    value=new_name, match_relative_path=t.relative_path,
                    match_mb_id=t.musicbrainz_recording_id,
                )
            work.work_name = new_name
            work.save()
            total += len(tracks)

        messagebox.showinfo("Done", f"Set work name to '{new_name}' "
                           f"for {total} tracks across {len(work_ids)} work(s).")
        self._refresh_cleanup()
        self._refresh_explorer()

    def _make_work_standalone(self):
        """Set __standalone__ work name for all tracks in all selected works."""
        work_ids = self._get_selected_cleanup_works()
        if not work_ids:
            return

        from music_manager.core.database import Work, Track
        from music_manager.core.overrides import set_override

        total = 0
        for work_id in work_ids:
            work = Work.get_by_id(work_id)
            tracks = list(Track.select().where(Track.work == work))
            for t in tracks:
                set_override(
                    library=self.active_library, scope="track", field="work_name",
                    value="__standalone__", match_relative_path=t.relative_path,
                    match_mb_id=t.musicbrainz_recording_id,
                )
            total += len(tracks)

        messagebox.showinfo("Done", f"Marked {total} tracks across "
                           f"{len(work_ids)} work(s) as standalone. "
                           f"Re-detect or rescan to apply.")
        self._refresh_cleanup()

    def _set_composer_override(self):
        """Set a composer override for all selected works' tracks."""
        work_ids = self._get_selected_cleanup_works()
        if not work_ids:
            return
        composer_name = self.edit_composer.get().strip()
        if not composer_name:
            messagebox.showwarning("Empty", "Enter a composer name.")
            return

        from music_manager.core.database import Work, Track
        from music_manager.core.overrides import set_override

        total = 0
        for work_id in work_ids:
            work = Work.get_by_id(work_id)
            tracks = list(Track.select().where(Track.work == work))
            for t in tracks:
                set_override(
                    library=self.active_library, scope="track", field="composer",
                    value=composer_name, match_relative_path=t.relative_path,
                    match_mb_id=t.musicbrainz_recording_id,
                )
            total += len(tracks)

        messagebox.showinfo("Done", f"Set composer to '{composer_name}' "
                           f"for {total} tracks across {len(work_ids)} work(s). "
                           f"Rescan or apply overrides to update.")
        self._refresh_cleanup()

    def _delete_override(self):
        """Delete the selected override."""
        sel = self.overrides_tree.selection()
        if not sel:
            return
        ov_id = self._override_id_map.get(sel[0])
        if not ov_id:
            return

        from music_manager.core.overrides import delete_override
        if delete_override(ov_id):
            self._refresh_overrides_list()

    def _export_overrides(self):
        """Export overrides to a JSON file."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        initial_dir = self._prefs.get("last_export_dir", "")
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialdir=initial_dir or None,
            title="Export Overrides",
            parent=self.root,
        )
        if not path:
            return
        self._prefs["last_export_dir"] = str(Path(path).parent)
        _save_prefs(self._prefs)

        from music_manager.core.overrides import export_overrides
        count = export_overrides(self.active_library, Path(path))
        messagebox.showinfo("Export", f"Exported {count} overrides to:\n{path}")

    def _import_overrides(self):
        """Import overrides from a JSON file."""
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        initial_dir = self._prefs.get("last_export_dir", "")
        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json")],
            initialdir=initial_dir or None,
            title="Import Overrides",
            parent=self.root,
        )
        if not path:
            return
        self._prefs["last_export_dir"] = str(Path(path).parent)
        _save_prefs(self._prefs)

        from music_manager.core.overrides import import_overrides, apply_overrides
        counts = import_overrides(self.active_library, Path(path))
        apply_overrides(self.active_library)
        messagebox.showinfo("Import",
                           f"Imported: {counts['imported']} new, "
                           f"{counts['updated']} updated, "
                           f"{counts['errors']} errors.\n"
                           f"Overrides applied.")
        self._refresh_cleanup()
        self._refresh_metrics()
