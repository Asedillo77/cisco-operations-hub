from __future__ import annotations

from tkinter import Tk, filedialog

from .contracts import ToolField


def select_path(field: ToolField) -> str:
    """Open a native Windows picker and return the selected local path."""
    if field.picker not in {"file", "folder"}:
        raise ValueError("This field does not support path selection.")
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if field.picker == "folder":
            return str(filedialog.askdirectory(parent=root, mustexist=True) or "")
        filetypes = list(field.extensions) or [("All files", "*.*")]
        return str(filedialog.askopenfilename(parent=root, filetypes=filetypes) or "")
    finally:
        root.destroy()
