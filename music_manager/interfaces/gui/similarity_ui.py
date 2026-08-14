"""Find Similar UI: analysis progress and results popup.

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
    UIThrottle,
)

logger = logging.getLogger(__name__)


def pw_fn_avg():
    """AVG(duration_ms), for converting a duration cap into a track count."""
    import peewee as pw

    from music_manager.core.database import Track
    return pw.fn.AVG(Track.duration_ms)

# Above this many unanalyzed tracks, Find Similar warns loudly rather
# than quietly launching hours of librosa work.
_LARGE_ANALYSIS_GAP = 100


class SimilarityUIMixin:
    def _analysis_gap(self):
        """(unanalyzed_count, total_tracks) for the active library."""
        from music_manager.core.similarity import TrackAnalysis, FEATURE_VERSION
        from music_manager.core.database import Track
        current = TrackAnalysis.select().join(Track).where(
            (Track.library == self.active_library) &
            (TrackAnalysis.feature_version == FEATURE_VERSION)).count()
        total = Track.select().where(
            Track.library == self.active_library).count()
        return max(0, total - current), total

    def _analyze_audio(self):
        """Deliberate batch audio analysis (v3.1).

        Replaces the old Track Similarity popup, whose seed/browse UI was
        superseded by the Builder's Find Similar. What remains valuable
        is starting the long librosa pass on purpose, with progress and
        cancel — the same shape as the scan button.
        """
        if not self.active_library:
            messagebox.showwarning("No Library", "Select a library first.")
            return

        missing, total = self._analysis_gap()
        if not total:
            messagebox.showinfo("Analyze Audio",
                                "This library has no tracks to analyze.")
            return
        if not missing:
            messagebox.showinfo(
                "Analyze Audio",
                f"All {total} tracks are already analyzed.\n\n"
                f"Use Find Similar in the Playlist Builder to search by "
                f"audio similarity.")
            return

        workers = self._ask_analysis_workers(missing)
        if workers is None:
            return

        self._run_sim_analysis(None, workers=workers)

    def _ask_analysis_workers(self, missing):
        """Confirm the batch and choose how many cores to give it.

        Analysis is CPU-bound, so the worker count is the one setting that
        changes how long this takes — twenty hours against under three. It
        belongs next to the decision to start, not only in the CLI.

        grab_set() MUST come after wait_visibility(). Grabbing a window that
        is not yet mapped raises TclError, which aborted this method before
        it created a single widget or applied its geometry — the symptom was
        a small empty window, not an error dialog. Every other Toplevel here
        follows the same order.

        Plain tk widgets on a "#2b2b2b" Toplevel to match _ask_scan_mode.
        (CTk widgets do work in a plain Toplevel — _run_sim_analysis uses
        them — but the surrounding dialogs are tk, so this stays consistent.)

        Returns the chosen worker count, or None if cancelled.
        """
        import os as _os
        from music_manager.core.similarity import default_worker_count

        cores = _os.cpu_count() or 2
        default = default_worker_count()
        choices = sorted({n for n in (1, 2, 4, 8, 12, 16, 24, 32)
                          if n <= cores} | {cores, default})

        dialog = tk.Toplevel(self.root)
        dialog.title("Analyze Audio")
        dialog.transient(self.root)
        dialog.configure(bg="#2b2b2b")
        self._center_on_main(dialog, 560, 330)
        dialog.wait_visibility()
        dialog.grab_set()

        tk.Label(dialog, text="Analyze Audio", bg="#2b2b2b", fg="white",
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=16,
                                                     pady=(14, 6))
        total = self._analysis_gap()[1]
        tk.Label(dialog,
                 text=(f"{missing} of {total} tracks need audio analysis.\n"
                       f"Progress is saved as it goes — you can cancel and "
                       f"resume later."),
                 bg="#2b2b2b", fg="gray80", justify="left",
                 font=("Segoe UI", 11)).pack(anchor="w", padx=16)

        row = tk.Frame(dialog, bg="#2b2b2b")
        row.pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(row, text="Worker processes:", bg="#2b2b2b", fg="white",
                 font=("Segoe UI", 11)).pack(side="left")
        worker_var = tk.StringVar(value=str(default))
        option = tk.OptionMenu(row, worker_var, *[str(n) for n in choices])
        option.configure(bg="#3b3b3b", fg="white", activebackground="#4b4b4b",
                         activeforeground="white", highlightthickness=0,
                         font=("Segoe UI", 11), width=4)
        option["menu"].configure(bg="#3b3b3b", fg="white")
        option.pack(side="left", padx=8)
        tk.Label(row, text=f"of {cores} cores", bg="#2b2b2b", fg="gray70",
                 font=("Segoe UI", 10)).pack(side="left")

        estimate = tk.Label(dialog, bg="#2b2b2b", fg="#e0b050",
                            justify="left", font=("Segoe UI", 11))
        estimate.pack(anchor="w", padx=16, pady=(6, 0))
        tk.Label(dialog,
                 text=("More workers finish sooner but leave less machine for\n"
                       "everything else. Measured scaling flattens past about\n"
                       "12 — the workers start competing for memory bandwidth."),
                 bg="#2b2b2b", fg="gray70", justify="left",
                 font=("Segoe UI", 10)).pack(anchor="w", padx=16, pady=(8, 0))

        def refresh(*_args):
            estimate.configure(
                text=self._analysis_estimate(missing, workers=int(worker_var.get())))

        worker_var.trace_add("write", refresh)
        refresh()

        result = {"workers": None}

        def start():
            result["workers"] = int(worker_var.get())
            dialog.destroy()

        btns = tk.Frame(dialog, bg="#2b2b2b")
        btns.pack(fill="x", padx=16, pady=14, side="bottom")
        tk.Button(btns, text="Start", bg="#2d7d46", fg="white",
                  font=("Segoe UI", 11), command=start).pack(side="left")
        tk.Button(btns, text="Cancel", bg="#3b3b3b", fg="white",
                  font=("Segoe UI", 11),
                  command=dialog.destroy).pack(side="right")

        dialog.wait_window()
        return result["workers"]

    @staticmethod
    def _analysis_estimate(count, workers=1):
        """Human-scale expectation for a librosa batch.

        Based on measurement rather than hope: ~10.5s per track on one core
        at a typical classical track length, divided by the speedup actually
        observed for that worker count — which is well short of linear.
        """
        from music_manager.core.similarity import (
            SECONDS_PER_TRACK, expected_speedup)
        seconds = count * SECONDS_PER_TRACK / expected_speedup(workers)
        if seconds < 120:
            return "Estimated time: under a minute."
        if seconds < 5400:
            return (f"Estimated time: roughly "
                    f"{max(1, round(seconds / 60))} minutes.")
        return f"Estimated time: roughly {seconds / 3600:.1f} hours."

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

        # Top up any missing analyses first. Small gaps just run; a large
        # gap gets an explicit warning with a time estimate, so clicking
        # a search button never silently starts a multi-hour job.
        unanalyzed, total_tracks = self._analysis_gap()

        if unanalyzed > 0:
            if unanalyzed >= _LARGE_ANALYSIS_GAP:
                proceed = messagebox.askyesno(
                    "Analysis Required",
                    f"{unanalyzed} of {total_tracks} tracks still need audio "
                    f"analysis.\n\n{self._analysis_estimate(unanalyzed)}\n"
                    f"You can cancel partway and resume later, or run "
                    f"Analyze Audio from the sidebar when convenient.\n\n"
                    f"Start the analysis now?")
            else:
                proceed = messagebox.askyesno(
                    "Analysis Required",
                    f"{unanalyzed} track(s) need analysis first. "
                    f"{self._analysis_estimate(unanalyzed)}\n\nProceed?")
            if not proceed:
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
            track_ids = resolve_selections(profile).track_ids
        finally:
            profile.delete_instance(recursive=True)
        return track_ids

    def _run_sim_analysis(self, seed_ids, workers=None):
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
                # Rate limited for the same reason as the scan: one
                # after() per track across thousands of tracks floods the
                # event loop and interrupts CustomTkinter's canvas redraw,
                # which is what tore the sidebar buttons.
                throttle = UIThrottle()

                def prog(current, total, msg):
                    if self._sim_cancel_flag:
                        raise AnalysisCancelled()
                    if not throttle.ready(force=(current >= total)):
                        return
                    title = (msg[:35] + "...") if len(msg) > 35 else msg
                    self.root.after(0, lambda c=current, t=total, m=title:
                                   _update(c, t, m))

                stats = analyze_library(self.active_library,
                                        progress_callback=prog,
                                        workers=workers)
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
            self._restore_grab(owner)
            if seed_ids is None:
                messagebox.showinfo(
                    "Analyze Audio",
                    f"Analyzed {stats['analyzed']} track(s); "
                    f"{stats['skipped']} already current"
                    + (f"; {stats['failed']} failed"
                       if stats["failed"] else "") + ".")
            else:
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

        # Bound after sim_state exists; the slider is built before it.
        vol_change_hook = {"fn": lambda: None}

        def _on_vol_change():
            vol_change_hook["fn"]()

        from music_manager.core.similarity import MAX_DYNAMIC_RANGE_DB

        # Dynamic range is now measured in dB (95th minus 10th percentile of
        # frame loudness), not the old unitless ratio. A 0-1 slider would
        # have excluded every track, since even very even music spans more
        # than 1 dB. Typical values: under 10 dB even, over 25 dB very wide.
        ctk.CTkLabel(param_frame, text="Max dyn range:").pack(
            side="left", padx=(0, 4))
        vol_var = tk.DoubleVar(value=MAX_DYNAMIC_RANGE_DB)
        vol_slider = ctk.CTkSlider(
            param_frame, from_=0.0, to=MAX_DYNAMIC_RANGE_DB, variable=vol_var,
            width=110,
            command=lambda v: (
                vol_label.configure(
                    text=f"{float(v):.0f} dB" if vol_enabled.get() else "Off"),
                _on_vol_change()))
        vol_slider.pack(side="left", padx=(0, 2))
        vol_label = ctk.CTkLabel(param_frame, text="Off", width=44)
        vol_label.pack(side="left", padx=(0, 2))
        vol_enabled = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            param_frame, text="", variable=vol_enabled, width=20,
            command=lambda: vol_label.configure(
                text=f"{vol_var.get():.0f} dB" if vol_enabled.get() else "Off")
        ).pack(side="left", padx=(0, 12))

        # -- v3.8 quietness filters -----------------------------------------
        # Two controls, not five. A3 measured the alternatives over the
        # library: startle_delta inverts on sustained loud passages,
        # rise_rate reports how deep the trough was ten seconds ago rather
        # than how loud the music is, and lra correlates at 0.78 with the
        # dyn-range slider three widgets to the left. See
        # no_git/CM-quietness-A4-report.md §6.
        #
        # Unlike the dyn-range slider, these filter in the tree rather
        # than in the query, so a drag is instant. _apply_quietness_filter
        # is bound to the slider command, not to Search.
        from music_manager.core.quietness import (
            MAX_LEVEL_OFFSET_DB, MAX_STARTLE_LU, MIN_LEVEL_OFFSET_DB,
        )

        ctk.CTkLabel(param_frame, text="Max startle:").pack(
            side="left", padx=(0, 4))
        startle_var = tk.DoubleVar(value=MAX_STARTLE_LU)
        startle_enabled = tk.BooleanVar(value=False)
        startle_label = ctk.CTkLabel(param_frame, text="Off", width=48)

        def _startle_text():
            return (f"{startle_var.get():.0f} LU" if startle_enabled.get()
                    else "Off")

        startle_slider = ctk.CTkSlider(
            param_frame, from_=0.0, to=MAX_STARTLE_LU, variable=startle_var,
            width=110)
        startle_slider.pack(side="left", padx=(0, 2))
        startle_label.pack(side="left", padx=(0, 2))
        ctk.CTkCheckBox(param_frame, text="", variable=startle_enabled,
                        width=20).pack(side="left", padx=(0, 12))

        ctk.CTkLabel(param_frame, text="Max level vs work:").pack(
            side="left", padx=(0, 4))
        level_var = tk.DoubleVar(value=MAX_LEVEL_OFFSET_DB)
        level_enabled = tk.BooleanVar(value=False)
        level_label = ctk.CTkLabel(param_frame, text="Off", width=48)

        def _level_text():
            return (f"{level_var.get():+.1f} dB" if level_enabled.get()
                    else "Off")

        level_slider = ctk.CTkSlider(
            param_frame, from_=MIN_LEVEL_OFFSET_DB, to=MAX_LEVEL_OFFSET_DB,
            variable=level_var, width=110)
        level_slider.pack(side="left", padx=(0, 2))
        level_label.pack(side="left", padx=(0, 2))
        ctk.CTkCheckBox(param_frame, text="", variable=level_enabled,
                        width=20).pack(side="left", padx=(0, 2))
        # Next to the controls whose names prompt the question. There is
        # a second one on the pool panel: this window is 900x560, so its
        # top and bottom are far enough apart that one button would be
        # off-screen from wherever the reader happens to be looking.
        ctk.CTkButton(
            param_frame, text="?", width=26, height=24,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._show_help("quietness")).pack(
            side="left", padx=(0, 12))

        ctk.CTkLabel(param_frame, text="Blend:").pack(
            side="left", padx=(0, 4))
        blend_var = tk.DoubleVar(value=0.5)
        ctk.CTkSlider(param_frame, from_=0.0, to=1.0,
                      variable=blend_var, width=110).pack(
            side="left", padx=(0, 4))
        ctk.CTkLabel(param_frame, text="nearest seed ↔ all seeds",
                     font=ctk.CTkFont(size=10)).pack(side="left", padx=(0, 12))

        search_btn = ctk.CTkButton(param_frame, text="Search", width=70)
        search_btn.pack(side="left")

        # -- Feature weights ------------------------------------------------
        # Groups are normalised by size before these apply, so a weight is a
        # real decision rather than a side effect of how many columns a
        # group happens to have. Timbre used to take 42% of every comparison
        # purely for having 13 of 31 columns.
        from music_manager.core.similarity import (
            DEFAULT_GROUP_WEIGHTS, GROUP_DESCRIPTIONS, resolve_group_weights)

        weight_vars = {}
        weights_frame = ctk.CTkFrame(popup)
        weights_shown = tk.BooleanVar(value=False)

        def toggle_weights():
            if weights_shown.get():
                weights_frame.pack_forget(); weights_shown.set(False)
                weights_btn.configure(text="Feature weights \u25be")
            else:
                weights_frame.pack(fill="x", padx=12, pady=(0, 4),
                                   before=tree_frame)
                weights_shown.set(True)
                weights_btn.configure(text="Feature weights \u25b4")

        weights_btn = ctk.CTkButton(
            param_frame, text="Feature weights \u25be", width=140,
            fg_color="gray30", hover_color="gray40", command=toggle_weights)
        weights_btn.pack(side="left", padx=(8, 0))

        start_weights = resolve_group_weights(None)
        grid = ctk.CTkFrame(weights_frame, fg_color="transparent")
        grid.pack(fill="x", padx=8, pady=6)
        for row, group in enumerate(DEFAULT_GROUP_WEIGHTS):
            ctk.CTkLabel(grid, text=group.capitalize(), width=80,
                         anchor="w").grid(row=row, column=0, sticky="w", pady=1)
            var = tk.DoubleVar(value=start_weights.get(group, 1.0))
            weight_vars[group] = var
            value_label = ctk.CTkLabel(grid, text=f"{var.get():.1f}", width=32)
            ctk.CTkSlider(
                grid, from_=0.0, to=2.0, number_of_steps=20, variable=var,
                width=150,
                command=lambda v, lbl=value_label: lbl.configure(
                    text=f"{float(v):.1f}")).grid(row=row, column=1, padx=6)
            value_label.grid(row=row, column=2)
            ctk.CTkLabel(grid, text=GROUP_DESCRIPTIONS.get(group, ""),
                         text_color=("gray25", "gray70"), anchor="w").grid(
                row=row, column=3, sticky="w", padx=(8, 0))

        def reset_weights():
            for group, var in weight_vars.items():
                var.set(DEFAULT_GROUP_WEIGHTS[group])

        btn_row = ctk.CTkFrame(weights_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=(0, 6))
        ctk.CTkButton(btn_row, text="Reset to defaults", width=140,
                      fg_color="gray30", hover_color="gray40",
                      command=reset_weights).pack(side="left")
        ctk.CTkLabel(btn_row,
                     text="0 removes a group entirely; 2 doubles its say.",
                     text_color=("gray25", "gray70")).pack(side="left", padx=10)

        # -- Results Treeview --
        tree_frame = ctk.CTkFrame(popup, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=12, pady=4)

        result_tree = ttk.Treeview(
            tree_frame,
            columns=("composer", "album", "match", "rank", "volatility",
                     "startle", "level"),
            show="tree headings", selectmode="extended")
        result_tree.heading("#0", text="Title")
        result_tree.heading("composer", text="Composer")
        result_tree.heading("album", text="Album")
        result_tree.heading("match", text="Match")
        result_tree.heading("rank", text="Rank")
        result_tree.heading("volatility", text="Dyn Range")
        # Shown, not just filtered on (C3). With 50-100 rows on screen the
        # numbers should be visible and orderable — it is also how the
        # metrics get sanity-checked against the music in practice.
        result_tree.heading("startle", text="Startle")
        result_tree.heading("level", text="vs Work")
        result_tree.column("#0", width=200)
        result_tree.column("composer", width=130)
        result_tree.column("album", width=150)
        result_tree.column("match", width=60)
        result_tree.column("rank", width=90, anchor="e")
        result_tree.column("volatility", width=80, anchor="e")
        result_tree.column("startle", width=78, anchor="e")
        result_tree.column("level", width=88, anchor="e")
        result_tree.pack(fill="both", expand=True)
        result_tree.tag_configure("match_close", foreground="#2d7d46")
        result_tree.tag_configure("match_loose", foreground="#c98a1f")
        result_tree.tag_configure("match_weak", foreground="#a03a3a")

        scroll = ttk.Scrollbar(tree_frame, orient="vertical",
                               command=result_tree.yview)
        result_tree.configure(yscrollcommand=scroll.set)
        scroll.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne",
                     in_=result_tree)

        # Sortable headers (double-click) — e.g. rank by Match or
        # Volatility. Numeric-aware for %, ratios, and floats.
        self._setup_tree_sort(result_tree)

        result_tree.bind("<Button-3>", lambda e: self._sim_result_context_menu(
            e, result_tree, sim_state))

        # -- Pool report (C6) ------------------------------------------------
        # Describes the profile's accepted tracks, not the search results.
        # Every profile shuffles, so there is no sequence to describe —
        # but the pool's properties hold for every ordering the shuffle
        # can reach, which makes them exact rather than indicative.
        pool_frame = ctk.CTkFrame(popup)
        pool_frame.pack(fill="x", padx=12, pady=(4, 0))
        pool_header = ctk.CTkFrame(pool_frame, fg_color="transparent")
        pool_header.pack(fill="x", padx=8, pady=(6, 0))
        ctk.CTkLabel(pool_header, text="This profile's pool",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left")
        # Links straight to the glossary, not to the chapter containing
        # it: the terms are the thing being asked about.
        ctk.CTkButton(
            pool_header, text="?", width=26, height=24,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._show_help("quietness")).pack(
            side="left", padx=(8, 0))

        # Full size and default colour, not a 10pt grey caption. These
        # are the numbers the panel exists to report, and the first
        # version rendered them almost unreadable.
        pool_label = ctk.CTkLabel(
            pool_frame, text="", justify="left", anchor="w",
            font=ctk.CTkFont(size=12))
        pool_label.pack(anchor="w", padx=8, pady=(2, 8), fill="x")

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
                vol_enabled, blend_var, weight_vars)
        ).pack(side="left", padx=(0, 4))
        measure_btn = ctk.CTkButton(
            bot_frame, text="Measure quietness", width=150,
            command=lambda: self._measure_visible_quietness(
                result_tree, sim_state, limit_var))
        measure_btn.pack(side="left", padx=(0, 4))
        # A2.1: ffmpeg is not on a default Windows PATH, and the
        # tag-derived Level column works without it. Disable with a
        # reason rather than letting the button raise.
        self._disable_without_ffmpeg(measure_btn)

        ctk.CTkButton(
            bot_frame, text="Close", width=70,
            command=popup.destroy).pack(side="left", padx=(0, 4))

        status_label = ctk.CTkLabel(bot_frame, text="", text_color="gray")
        status_label.pack(side="right", padx=10)

        # Shared state dict for the results window
        sim_state = {
            "seed_ids": seed_ids,
            "result_map": {},       # iid → result dict, visible rows only
            "all_results": [],      # every scored candidate (v3.8)
            "status_label": status_label,
            "popup": popup,
            "startle_var": startle_var,
            "startle_enabled": startle_enabled,
            "level_var": level_var,
            "level_enabled": level_enabled,
            "pool_label": pool_label,
            "vol_var": vol_var,
            "vol_enabled": vol_enabled,
        }
        self._refresh_pool_report(sim_state)

        # The quietness sliders re-render from the cached scores; they do
        # not re-run the search. Wired after sim_state exists because the
        # callbacks close over it.
        def _on_quietness_change(*_args):
            startle_label.configure(text=_startle_text())
            level_label.configure(text=_level_text())
            if sim_state["all_results"]:
                self._apply_quietness_filter(result_tree, sim_state, limit_var)

        startle_slider.configure(command=lambda _v: _on_quietness_change())
        level_slider.configure(command=lambda _v: _on_quietness_change())
        startle_enabled.trace_add("write", _on_quietness_change)
        level_enabled.trace_add("write", _on_quietness_change)
        # Dyn range behaves like its neighbours now.
        vol_enabled.trace_add("write", _on_quietness_change)
        vol_change_hook["fn"] = _on_quietness_change

        # Wire up search button
        search_btn.configure(command=lambda: self._do_sim_search(
            result_tree, sim_state, limit_var, vol_var,
            vol_enabled, blend_var, weight_vars))

        # Run initial search
        self._do_sim_search(result_tree, sim_state, limit_var, vol_var,
                            vol_enabled, blend_var, weight_vars)

    def _do_sim_search(self, result_tree, sim_state, limit_var, vol_var,
                       vol_enabled, blend_var, weight_vars=None):
        """Score the library against the seeds, then render (v3.8).

        Split in two. This half is the expensive part — the query, the
        z-scoring, the distance matrix — and runs only on Search. The
        quietness sliders re-render from `all_results` without touching
        the database, which is what makes dragging one feel like a
        filter rather than a search.

        `limit=None` deliberately: every scored candidate is kept, so
        `_apply_quietness_filter` can restate Match % over a complete
        candidate set. The loop in `find_similar` builds those dicts
        regardless, so asking for all of them costs nothing.
        """
        from music_manager.core.similarity import find_similar

        blend = blend_var.get()
        seed_ids = sim_state["seed_ids"]

        results = find_similar(
            list(seed_ids), limit=None,
            # Not volatility_max: that filtered in the query, so the
            # slider only bit on Search while its two neighbours redrew
            # as they moved. It is applied in the tree now, with them.
            blend=blend,
            weights={g: v.get() for g, v in (weight_vars or {}).items()})

        # Filter out tracks already in the profile
        selected_track_ids = self._resolve_current_to_track_ids()
        sim_state["all_results"] = [
            r for r in results if r["track_id"] not in selected_track_ids]

        self._apply_quietness_filter(result_tree, sim_state, limit_var)

    def _apply_quietness_filter(self, result_tree, sim_state, limit_var):
        """Re-render from the cached scores. No query, no re-scoring.

        Bound to the sliders, so it runs on every drag.
        """
        from music_manager.core.similarity import (
            filter_by_quietness, recompute_match_percentiles,
        )
        from music_manager.interfaces.gui.treeutil import UNMEASURED

        try:
            limit = int(limit_var.get())
        except ValueError:
            limit = 50

        results = sim_state.get("all_results") or []
        startle_max = (sim_state["startle_var"].get()
                       if sim_state["startle_enabled"].get() else None)
        level_max = (sim_state["level_var"].get()
                     if sim_state["level_enabled"].get() else None)
        volatility_max = (sim_state["vol_var"].get()
                          if sim_state["vol_enabled"].get() else None)

        survivors, dropped = filter_by_quietness(
            results, startle_max=startle_max, level_max=level_max,
            volatility_max=volatility_max)

        # Restated over the survivors, so "closer than 92% of candidates"
        # keeps referring to the candidates that got through the filter —
        # which is how volatility_max has always behaved, it just does its
        # filtering before scoring rather than after.
        survivors = recompute_match_percentiles(survivors)
        visible = survivors[:limit]

        result_tree.delete(*result_tree.get_children())
        sim_state["result_map"].clear()
        for r in visible:
            match_pct = r.get("match_pct")
            if match_pct is None:
                tag = "match_loose"
            elif match_pct >= 70:
                tag = "match_close"
            elif match_pct >= 40:
                tag = "match_loose"
            else:
                tag = "match_weak"
            startle = r.get("startle_local")
            offset = r.get("playback_offset")
            iid = result_tree.insert(
                "", "end", text=r["title"],
                tags=(tag,),
                values=(
                    r["composer"],
                    r["album"],
                    f"{match_pct:.0f}%" if match_pct is not None else "",
                    f"{r['rank']} of {r['candidate_count']}",
                    f"{r['volatility']:.1f} dB" if r["volatility"] is not None else "",
                    # An em dash, not a blank and not a zero: unmeasured
                    # has to be visibly different from "measured, and it
                    # is fine".
                    f"{startle:.1f}" if startle is not None else UNMEASURED,
                    f"{offset:+.1f}" if offset is not None else UNMEASURED,
                ))
            sim_state["result_map"][iid] = r

        unmeasured_visible = sum(
            1 for r in visible if r.get("startle_local") is None)
        sim_state["status_label"].configure(
            text=self._quietness_status(len(visible), len(survivors),
                                        len(results), dropped,
                                        unmeasured_visible))

    @staticmethod
    def _quietness_status(visible, surviving, total, dropped,
                          unmeasured_visible=0):
        """The surviving-candidate count, and what the filters removed.

        Not decoration. The level slider has a cliff at zero — 68.8% of
        the library is a standalone work and scores exactly 0.0 — so
        nudging it below zero drops two thirds of the candidates in one
        step. Without a live count that reads as a broken control rather
        than as the filter doing exactly what was asked.

        Unmeasured tracks are counted apart from tracks that genuinely
        failed, because the two ask for different things: one is "run
        Measure", the other is "this track is loud".

        `unmeasured_visible` covers the case with no filter on at all.
        Nothing measures quietness until asked, so a first search shows a
        column of dashes — and reporting only "50 of 7241 shown" left
        nothing to connect those dashes to the button that fills them in.
        """
        if surviving == total:
            shown = f"{visible} of {total} shown"
            if unmeasured_visible:
                shown += (f" — {unmeasured_visible} not yet measured for "
                          f"startle (use Measure quietness)")
            return shown

        parts = [f"{visible} shown, {surviving} of {total} pass"]
        failed = dropped["startle"] + dropped["level"]
        if failed:
            parts.append(f"{failed} too loud")
        unmeasured = dropped["startle_unmeasured"] + dropped["level_unmeasured"]
        if unmeasured:
            parts.append(f"{unmeasured} unmeasured")
        if unmeasured_visible:
            parts.append(f"{unmeasured_visible} shown unmeasured")
        return " — ".join(parts)

    @staticmethod
    def _restore_grab(window):
        """Hand the input grab back to `window`.

        Destroying a window that holds a grab does not return the grab to
        whoever had it before — it leaves no grab at all. The Find Similar
        popup grabs when it opens, so every transient dialog raised over
        it has to give the grab back on the way out, or the next modal
        dialog is the only thing that can take input.

        `winfo_viewable()` rather than `wait_visibility()`, and the
        distinction is the point: grab_set() raises TclError on a window
        that is not mapped, and the usual way to guarantee that is to
        wait. Here there is nothing to wait *for* — the owner was mapped
        and grabbed before the dialog over it ever existed. If it is
        somehow not viewable now, the window is going away and there is
        no grab worth restoring, so testing is right where waiting would
        hang.
        """
        try:
            if (window is not None and window.winfo_exists()
                    and window.winfo_viewable()):
                window.grab_set()
        except tk.TclError:                         # pragma: no cover
            pass

    @staticmethod
    def _disable_without_ffmpeg(button):
        """Grey a control out when ffmpeg is missing, and say why (A2.1).

        The quietness metrics need an external binary; the tag-derived
        playback level does not. ffmpeg is absent from a default Windows
        PATH, and nothing about a Find Similar button warns a user that a
        system binary is involved — so the control has to explain itself
        rather than raise from a thread.
        """
        from music_manager.core.quietness import MeasurementError, find_ffmpeg
        try:
            find_ffmpeg()
        except MeasurementError:
            button.configure(state="disabled")
            try:
                # CTk has no tooltip; the label carries the reason.
                button.configure(text="Measure (needs ffmpeg)")
            except Exception:       # pragma: no cover - cosmetic only
                pass
            return False
        return True

    def _measure_visible_quietness(self, result_tree, sim_state, limit_var):
        """Measure the top candidates that have no quietness data yet (C4).

        Scoped to the candidates the user is actually looking at, in score
        order, ignoring the quietness sliders. Ignoring them is the point:
        with a filter on, unmeasured tracks are excluded from the view, so
        measuring only what is displayed could never measure anything.

        There is no library-wide pass in this design. The library fills in
        as curation proceeds.
        """
        import threading

        from music_manager.core.quietness import MeasurementError
        from music_manager.core.similarity import (
            AnalysisCancelled, measure_quietness, tracks_needing_quietness,
        )

        try:
            limit = int(limit_var.get())
        except ValueError:
            limit = 50

        # parent= on every one of these. The Find Similar popup holds a
        # grab, so a dialog parented to root instead appears behind it,
        # takes the input grab, and cannot be seen or reached: the app
        # simply freezes. _accept_sim_tracks already knew this.
        owner = sim_state.get("popup")

        candidates = (sim_state.get("all_results") or [])[:limit]
        candidate_ids = [r["track_id"] for r in candidates]

        # The profile's own tracks as well, not only the candidates.
        # _do_sim_search deliberately excludes anything already accepted
        # from the results, so a pool track that was never measured could
        # not be reached from this window at all: the pool report said
        # "1 not measured" and Measure replied that everything on screen
        # was done. Both were true, and between them there was no way to
        # fix it.
        pool_ids = [t for t in self._resolve_current_to_track_ids()
                    if t not in set(candidate_ids)]

        if not candidate_ids and not pool_ids:
            messagebox.showinfo("Measure", "Run a search first.", parent=owner)
            return

        try:
            todo = tracks_needing_quietness(candidate_ids + pool_ids)
        except Exception as exc:                    # noqa: BLE001 - reported
            messagebox.showerror("Measure", str(exc), parent=owner)
            return
        if not todo:
            messagebox.showinfo(
                "Measure",
                f"All {len(candidates)} candidates on screen and "
                f"{len(pool_ids)} pool track(s) are already measured.",
                parent=owner)
            return

        from_pool = sum(1 for t in todo if t in set(pool_ids))
        from_candidates = len(todo) - from_pool
        what = []
        if from_candidates:
            what.append(f"{from_candidates} of the top {len(candidates)} "
                        f"candidates")
        if from_pool:
            what.append(f"{from_pool} track(s) already in the profile")

        # ~24 tracks a minute measured over the library share (A3).
        minutes = max(1, round(len(todo) / 24))
        if not messagebox.askyesno(
                "Measure quietness",
                f"Measure {' and '.join(what)}?\n\nRoughly {minutes} "
                f"minute(s). Results are saved as they finish, so this can "
                f"be run again to continue.", parent=owner):
            return

        self._sim_cancel_flag = False
        ctk = self.ctk
        popup = tk.Toplevel(self.root)
        popup.title("Measuring quietness")
        popup.transient(self.root)
        popup.resizable(False, False)
        self._center_on_main(popup, 400, 120)
        popup.wait_visibility()
        popup.grab_set()

        status = ctk.CTkLabel(popup, text="Measuring...")
        status.pack(padx=20, pady=(15, 5))
        progress = ctk.CTkProgressBar(popup, width=300)
        progress.pack(padx=20, pady=5)
        progress.set(0)
        ctk.CTkButton(
            popup, text="Cancel", width=80,
            command=lambda: setattr(self, "_sim_cancel_flag", True)
        ).pack(pady=(5, 10))

        def _update(current, total):
            if total:
                progress.set(current / total)
            status.configure(text=f"Measuring {current}/{total}")

        def _done(stats):
            popup.destroy()
            self._restore_grab(owner)
            # Re-render so the new numbers appear in the columns without
            # re-running the search — but the cached results predate the
            # measurement, so they have to be refreshed from the database.
            self._refresh_cached_quietness(sim_state)
            self._apply_quietness_filter(result_tree, sim_state, limit_var)
            self._refresh_pool_report(sim_state)
            parts = [f"Measured {stats['measured']}"]
            if stats["silent"]:
                parts.append(f"{stats['silent']} silent or too short")
            if stats["failed"]:
                parts.append(f"{stats['failed']} failed")
            if stats["missing"]:
                parts.append(f"{stats['missing']} file missing")
            messagebox.showinfo("Measure", "; ".join(parts) + ".",
                                parent=owner)

        def worker():
            try:
                throttle = UIThrottle()

                def prog(current, total, _msg):
                    if not throttle.ready(force=(current >= total)):
                        return
                    self.root.after(0, lambda c=current, t=total:
                                    _update(c, t))

                stats = measure_quietness(
                    todo, progress_callback=prog,
                    cancel_check=lambda: self._sim_cancel_flag)
                self.root.after(0, lambda: _done(stats))
            except AnalysisCancelled:
                # Whatever finished before the cancel is already written.
                self.root.after(0, lambda: (popup.destroy(),
                                            self._restore_grab(owner)))
            except MeasurementError as exc:
                self.root.after(0, lambda e=exc: (
                    popup.destroy(), self._restore_grab(owner),
                    messagebox.showerror("Measure", str(e), parent=owner)))
            except Exception as exc:                # noqa: BLE001 - reported
                self.root.after(0, lambda e=exc: (
                    popup.destroy(), self._restore_grab(owner),
                    messagebox.showerror("Measure", str(e), parent=owner)))

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _refresh_cached_quietness(sim_state):
        """Re-read the metrics for the cached results after measuring.

        `all_results` is a snapshot taken at search time, so it still
        holds the nulls the measurement has just replaced. Only the
        quietness columns are re-read — the scores and rankings are
        unaffected by measurement and re-running the search would be a
        needless several seconds.
        """
        from music_manager.core.similarity import LOUDNESS_FIELDS, TrackAnalysis

        results = sim_state.get("all_results") or []
        if not results:
            return
        by_id = {r["track_id"]: r for r in results}
        rows = (TrackAnalysis
                .select(TrackAnalysis.track, *[
                    getattr(TrackAnalysis, n) for n in LOUDNESS_FIELDS])
                .where(TrackAnalysis.track.in_(list(by_id))))
        for row in rows:
            result = by_id.get(row.track_id)
            if result is None:
                continue
            for name in LOUDNESS_FIELDS:
                result[name] = getattr(row, name)

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

        # C6: the pool report describes the profile's selections, so it
        # moves every time something is accepted.
        self._refresh_pool_report(sim_state)

    def _refresh_pool_report(self, sim_state):
        """Recompute the pool panel from the profile's current selections.

        Describes what the *profile* will produce, not what the search
        returned — under shuffle the search order means nothing and the
        pool is the only thing with stable properties.
        """
        panel = sim_state.get("pool_label")
        if panel is None:
            return
        try:
            report = self._build_pool_report()
        except Exception as exc:                    # noqa: BLE001 - shown
            logger.debug("Pool report failed: %s", exc)
            panel.configure(text="Pool report unavailable.")
            return
        from music_manager.core.pool_report import describe
        panel.configure(text="\n".join(describe(report)))

    def _build_pool_report(self):
        """Gather the profile's accepted tracks and reduce them to a report."""
        from music_manager.core.database import Track
        from music_manager.core.pool_report import PoolTrack, build_report
        from music_manager.core.quietness import playback_offset
        from music_manager.core.similarity import TrackAnalysis

        track_ids = self._resolve_current_to_track_ids()
        if not track_ids:
            return build_report([], playlist_length=0)

        rows = (TrackAnalysis
                .select(TrackAnalysis, Track)
                .join(Track)
                .where(TrackAnalysis.track.in_(list(track_ids))))
        by_id = {r.track_id: r for r in rows}

        pool = []
        for track in Track.select().where(Track.id.in_(list(track_ids))):
            analysis = by_id.get(track.id)
            pool.append(PoolTrack(
                track_id=track.id,
                title=track.title,
                startle_local=getattr(analysis, "startle_local", None),
                head_level=getattr(analysis, "head_level", None),
                tail_level=getattr(analysis, "tail_level", None),
                playback_offset=playback_offset(track.rg_track_gain,
                                                track.rg_album_gain),
            ))
        return build_report(pool,
                            playlist_length=self._profile_playlist_length(
                                len(pool)))

    def _profile_playlist_length(self, pool_size):
        """How many tracks a night actually draws from the pool.

        The cap is what makes the ceiling probabilistic rather than
        certain, so getting it roughly right matters more than getting it
        exactly right. A duration cap is converted at the library's mean
        track length; anything else means the whole pool plays.
        """
        profile = getattr(self, "current_profile", None)
        mode = getattr(profile, "length_mode", None)
        value = getattr(profile, "length_value", None)
        if mode == "count" and value:
            return min(int(value), pool_size)
        if mode == "duration" and value:
            from music_manager.core.database import Track
            average = (Track
                       .select(pw_fn_avg())
                       .where(Track.library == self.active_library)
                       .scalar())
            if average:
                return max(1, min(pool_size,
                                  int(round(value * 1000 / average))))
        return pool_size

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
        # C5. Only offered when there is a moment to jump to — a track
        # that has not been measured, or measured as silent, has none.
        if r.get("loud_at_ms") is not None:
            at_s = r["loud_at_ms"] / 1000.0
            menu.add_command(
                label=f"Audition loudest moment ({int(at_s // 60)}:"
                      f"{int(at_s % 60):02d})",
                command=lambda: self._audition_loud_moment(
                    track.id, r, owner=sim_state.get("popup")))
        if track.work_id:
            menu.add_command(label="Details...",
                             command=lambda: self._show_work_details(track.work_id))
        if track.album_id:
            menu.add_command(label="Show Album",
                             command=lambda: self._show_album_popup(track.album_id))
        menu.add_command(label="Show in Folder",
                         command=lambda: self._show_track_in_folder(track.id))
        menu.tk_popup(event.x_root, event.y_root)

    def _audition_loud_moment(self, track_id, result, owner=None):
        """Play the passage the startle score came from (C5).

        Eight seconds of listening in place of trusting a number. The
        extraction is quick but not instant over the share, so it runs
        off the UI thread; the player is then handed the excerpt on the
        UI thread like any other file.
        """
        import threading

        from music_manager.core.database import Track
        from music_manager.core.quietness import (
            MeasurementError, extract_excerpt, prune_auditions,
        )

        track = Track.get_by_id(track_id)
        source = Path(track.folder.root_path) / track.relative_path
        if not source.exists():
            messagebox.showerror("File Not Found",
                                 f"File not found:\n{source}", parent=owner)
            return

        at_ms = result.get("loud_at_ms")
        if at_ms is None:
            messagebox.showinfo(
                "Audition",
                "This track has no measured loud moment. Run Measure "
                "quietness first.", parent=owner)
            return

        def worker():
            try:
                prune_auditions()
                # The work gain, so the excerpt plays at the level MA
                # would play it. Without this the audition answers a
                # question nobody asked: how loud the file is, rather
                # than how loud it will be in the playlist.
                excerpt = extract_excerpt(source, at_ms,
                                          gain_db=track.rg_album_gain)
                self.root.after(0, lambda: self._open_in_player(excerpt))
            except MeasurementError as exc:
                self.root.after(0, lambda e=exc: messagebox.showerror(
                    "Audition", str(e), parent=owner))
            except Exception as exc:                # noqa: BLE001 - reported
                self.root.after(0, lambda e=exc: messagebox.showerror(
                    "Audition", str(e), parent=owner))

        threading.Thread(target=worker, daemon=True).start()

    def _sim_re_search(self, result_tree, sim_state, limit_var, vol_var,
                       vol_enabled, blend_var, weight_vars=None):
        """Re-resolve selections (including accepted tracks) and re-search."""
        new_seed_ids = self._resolve_current_to_track_ids()
        if not new_seed_ids:
            messagebox.showinfo(
                "No Seeds", "No tracks to use as seeds.",
                parent=sim_state["popup"])
            return
        sim_state["seed_ids"] = new_seed_ids
        self._do_sim_search(result_tree, sim_state, limit_var, vol_var,
                            vol_enabled, blend_var, weight_vars)
