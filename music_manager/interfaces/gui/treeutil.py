"""Treeview mechanics: sorting, filtering, view-state.

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


class TreeUtilMixin:
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
