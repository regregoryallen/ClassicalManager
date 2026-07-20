"""Application shell: window, sidebar, scanning, autosave, prefs.

V3 Phase 3: mechanically split from gui.py. The App class keeps
its full V2 surface; tab/dialog/tree methods live in mixins.
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

from music_manager.interfaces.gui.dialogs import DialogsMixin
from music_manager.interfaces.gui.rules_window import RulesWindowMixin
from music_manager.interfaces.gui.builder_tab import BuilderTabMixin
from music_manager.interfaces.gui.treeutil import TreeUtilMixin
from music_manager.interfaces.gui.similarity_ui import SimilarityUIMixin
from music_manager.interfaces.gui.cleanup_tab import CleanupTabMixin


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


class App(DialogsMixin, RulesWindowMixin, BuilderTabMixin, TreeUtilMixin, SimilarityUIMixin, CleanupTabMixin):
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
        self._lib_index = None  # cached LibraryIndex (V3 Phase 4)
        self._current_selections = []  # in-memory selections: [{level, key, excluded, pin_position, track_paths, display}]
        self._profile_picker_open = False
        self._rules_window = None      # singleton Rules window (Phase 5)
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
        icon_path = PROJECT_ROOT / "app_icon.png"
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
        main_py = PROJECT_ROOT / "main.py"
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

        # Capture current UI state
        length_val = self.length_value.get().strip()
        seed_val = self.seed_entry.get().strip()
        profile_name = self.profile_name_entry.get().strip()

        # Atomic delete+recreate: a kill mid-autosave must not lose the
        # previous autosave (V3 Phase 6).
        from music_manager.core.database import database
        with database.atomic():
            for existing in PlaylistProfile.select().where(
                (PlaylistProfile.library == self.active_library) &
                (PlaylistProfile.name == "__autosave__")
            ):
                existing.delete_instance()  # CASCADE deletes selections

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
        self.tab_cleanup = self.tabview.add("Cleanup / Overlay")

        self._build_builder_tab()
        self._build_cleanup_tab()

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
            if stats.analyses_preserved:
                msg += f", {stats.analyses_preserved} analyses kept"
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
        messagebox.showinfo(
            "Re-detect Complete",
            f"Albums processed: {result['albums_processed']}\n"
            f"Override: {result['override']}  |  "
            f"MB Work ID: {result['mb_workid']}  |  "
            f"Work Tag: {result['work_tag']}\n"
            f"Heuristic: {result['heuristic']}  |  "
            f"Standalone: {result['standalone']}")

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
