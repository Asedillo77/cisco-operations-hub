from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .commands import load_commands
from .logging_utils import configure_logging
from .service import run_job

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_DIR = PACKAGE_TEMPLATE_DIR if PACKAGE_TEMPLATE_DIR.is_dir() else PROJECT_ROOT / "templates"


class QueueHandler(logging.Handler):
    def __init__(self, messages: queue.Queue) -> None:
        super().__init__()
        self.messages = messages

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.put(("log", self.format(record)))


class CommandRunnerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.messages: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.last_output: Path | None = None

        root.title("Cisco Command Runner")
        root.geometry("1080x820")
        root.minsize(900, 700)

        self.inventory = tk.StringVar(value=str(PROJECT_ROOT / "samples" / "inventory.csv"))
        self.command_file = tk.StringVar()
        self.credential_mode = tk.StringVar(value="file")
        self.credentials_file = tk.StringVar(
            value=str(PROJECT_ROOT / "credentials" / "credentials.txt")
        )
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.secret = tk.StringVar()
        self.port = tk.StringVar(value="22")
        self.timeout = tk.StringVar(value="30")
        self.output_root = tk.StringVar(value=str(PROJECT_ROOT / "outputs"))
        self.max_devices = tk.StringVar(value="50")
        self.max_workers = tk.StringVar(value="3")
        self.result_handling = tk.StringVar(value="Complete output")
        self.apply = tk.BooleanVar(value=False)
        self.debug = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Ready — dry-run is selected")
        self._build()
        self._refresh_credentials()
        root.after(100, self._poll)

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)
        ttk.Label(outer, text="Cisco Command Runner", font=("Segoe UI", 19, "bold")).grid(
            row=0, column=0, sticky=tk.W, pady=(0, 10)
        )

        inputs = ttk.LabelFrame(outer, text="Devices and outputs", padding=10)
        inputs.grid(row=1, column=0, sticky=tk.EW)
        inputs.columnconfigure(1, weight=1)
        self._path_row(inputs, 0, "Inventory CSV/XLSX", self.inventory, self._browse_inventory)
        self._path_row(inputs, 1, "Output folder", self.output_root, self._browse_output)

        middle = ttk.Frame(outer)
        middle.grid(row=2, column=0, sticky=tk.NSEW, pady=(8, 0))
        middle.columnconfigure(0, weight=3)
        middle.columnconfigure(1, weight=2)
        self._build_commands(middle)
        self._build_credentials(middle)

        options = ttk.LabelFrame(outer, text="Execution", padding=10)
        options.grid(row=3, column=0, sticky=tk.EW, pady=(8, 0))
        ttk.Label(options, text="Maximum devices").grid(row=0, column=0)
        ttk.Entry(options, textvariable=self.max_devices, width=7).grid(
            row=0, column=1, padx=(5, 18)
        )
        ttk.Label(options, text="Parallel devices").grid(row=0, column=2)
        ttk.Entry(options, textvariable=self.max_workers, width=7).grid(
            row=0, column=3, padx=(5, 18)
        )
        ttk.Label(options, text="Result handling").grid(row=0, column=4)
        ttk.Combobox(
            options,
            textvariable=self.result_handling,
            values=("Complete output", "Common summary (where available)"),
            state="readonly",
            width=31,
        ).grid(row=0, column=5, padx=(5, 18))
        ttk.Checkbutton(options, text="Debug logging", variable=self.debug).grid(row=0, column=6)
        ttk.Checkbutton(
            options,
            text="Apply — connect to devices and run commands",
            variable=self.apply,
            command=self._apply_changed,
        ).grid(row=0, column=7, padx=(22, 0))

        progress_frame = ttk.LabelFrame(outer, text="Progress", padding=8)
        progress_frame.grid(row=4, column=0, sticky=tk.NSEW, pady=(8, 0))
        progress_frame.rowconfigure(0, weight=1)
        progress_frame.columnconfigure(0, weight=1)
        self.log = ScrolledText(
            progress_frame, state=tk.DISABLED, wrap=tk.WORD, font=("Consolas", 9)
        )
        self.log.grid(row=0, column=0, sticky=tk.NSEW)

        actions = ttk.Frame(outer)
        actions.grid(row=5, column=0, sticky=tk.EW, pady=(10, 0))
        actions.columnconfigure(1, weight=1)
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=0)
        ttk.Label(actions, textvariable=self.status).grid(row=0, column=1, sticky=tk.W, padx=10)
        self.open_button = ttk.Button(
            actions, text="Open reports", command=self._open_reports, state=tk.DISABLED
        )
        self.open_button.grid(row=0, column=2, padx=5)
        self.run_button = ttk.Button(actions, text="Validate dry-run", command=self._start)
        self.run_button.grid(row=0, column=3, padx=(5, 0))

    def _build_commands(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Commands (one per line)", padding=10)
        frame.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 4))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        bar = ttk.Frame(frame)
        bar.grid(row=0, column=0, sticky=tk.EW, pady=(0, 6))
        bar.columnconfigure(0, weight=1)
        ttk.Entry(bar, textvariable=self.command_file).grid(row=0, column=0, sticky=tk.EW)
        ttk.Button(bar, text="Load", command=self._load_command_file).grid(
            row=0, column=1, padx=(6, 0)
        )
        ttk.Button(bar, text="Save", command=self._save_commands).grid(row=0, column=2, padx=(6, 0))
        self.commands = ScrolledText(frame, height=12, wrap=tk.NONE, font=("Consolas", 10))
        self.commands.grid(row=1, column=0, sticky=tk.NSEW)
        self.commands.insert("1.0", "show version\nshow ip interface brief\n")

    def _build_credentials(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Credentials", padding=10)
        frame.grid(row=0, column=1, sticky=tk.NSEW, padx=(4, 0))
        frame.columnconfigure(1, weight=1)
        ttk.Radiobutton(
            frame,
            text="Credential file",
            variable=self.credential_mode,
            value="file",
            command=self._refresh_credentials,
        ).grid(row=0, column=0)
        ttk.Radiobutton(
            frame,
            text="Enter manually",
            variable=self.credential_mode,
            value="manual",
            command=self._refresh_credentials,
        ).grid(row=0, column=1)
        ttk.Label(frame, text="File").grid(row=1, column=0, sticky=tk.W, pady=(10, 3))
        self.credential_entry = ttk.Entry(frame, textvariable=self.credentials_file)
        self.credential_entry.grid(row=1, column=1, sticky=tk.EW, pady=(10, 3))
        self.credential_button = ttk.Button(frame, text="Browse", command=self._browse_credentials)
        self.credential_button.grid(row=1, column=2, padx=(5, 0), pady=(10, 3))
        labels = (
            ("Username", self.username, ""),
            ("Password", self.password, "*"),
            ("Enable secret", self.secret, "*"),
            ("Port", self.port, ""),
            ("Timeout", self.timeout, ""),
        )
        self.manual_entries = []
        for row, (label, variable, show) in enumerate(labels, start=2):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=3)
            entry = ttk.Entry(frame, textvariable=variable, show=show)
            entry.grid(row=row, column=1, columnspan=2, sticky=tk.EW, pady=3)
            self.manual_entries.append(entry)

    def _path_row(
        self, frame: ttk.Frame, row: int, label: str, variable: tk.StringVar, command: object
    ) -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=3)
        ttk.Entry(frame, textvariable=variable).grid(
            row=row, column=1, sticky=tk.EW, padx=7, pady=3
        )
        ttk.Button(frame, text="Browse", command=command).grid(row=row, column=2, pady=3)

    def _browse_inventory(self) -> None:
        value = filedialog.askopenfilename(
            filetypes=(("Inventory", "*.csv *.xlsx"), ("All files", "*.*"))
        )
        if value:
            self.inventory.set(value)

    def _browse_output(self) -> None:
        value = filedialog.askdirectory()
        if value:
            self.output_root.set(value)

    def _browse_credentials(self) -> None:
        value = filedialog.askopenfilename(filetypes=(("Text", "*.txt"), ("All files", "*.*")))
        if value:
            self.credentials_file.set(value)

    def _load_command_file(self) -> None:
        value = filedialog.askopenfilename(
            filetypes=(("Command files", "*.txt *.csv *.json"), ("All files", "*.*"))
        )
        if not value:
            return
        try:
            commands = load_commands(Path(value))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Commands", str(exc))
            return
        self.command_file.set(value)
        self.commands.delete("1.0", tk.END)
        self.commands.insert("1.0", "\n".join(commands) + "\n")

    def _save_commands(self) -> None:
        value = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=(("Text", "*.txt"),)
        )
        if value:
            Path(value).write_text(
                self.commands.get("1.0", tk.END).strip() + "\n", encoding="utf-8"
            )

    def _refresh_credentials(self) -> None:
        file_state = tk.NORMAL if self.credential_mode.get() == "file" else tk.DISABLED
        manual_state = tk.NORMAL if self.credential_mode.get() == "manual" else tk.DISABLED
        self.credential_entry.configure(state=file_state)
        self.credential_button.configure(state=file_state)
        for entry in self.manual_entries:
            entry.configure(state=manual_state)

    def _apply_changed(self) -> None:
        confirmation = (
            "Apply mode will connect to every enabled device and run the validated "
            "commands. Continue?"
        )
        if self.apply.get() and not messagebox.askyesno("Confirm apply mode", confirmation):
            self.apply.set(False)
        self.run_button.configure(text="Run on devices" if self.apply.get() else "Validate dry-run")
        self.status.set(
            "Ready — apply mode selected" if self.apply.get() else "Ready — dry-run is selected"
        )

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.run_button.configure(state=tk.DISABLED)
        self.open_button.configure(state=tk.DISABLED)
        self.progress.start(12)
        self.status.set("Working…")
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()

    def _work(self) -> None:
        logger = configure_logging(self.debug.get())
        handler = QueueHandler(self.messages)
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(handler)
        try:
            manual = None
            credentials_file = None
            if self.credential_mode.get() == "file":
                credentials_file = Path(self.credentials_file.get())
            else:
                manual = {
                    "username": self.username.get(),
                    "password": self.password.get(),
                    "secret": self.secret.get(),
                    "port": self.port.get(),
                    "timeout": self.timeout.get(),
                }
            output = run_job(
                inventory_file=Path(self.inventory.get()),
                commands_text=self.commands.get("1.0", tk.END),
                credentials_file=credentials_file,
                credentials=manual,
                output_root=Path(self.output_root.get()),
                template_dir=TEMPLATE_DIR,
                apply=self.apply.get(),
                max_devices=int(self.max_devices.get()),
                max_workers=int(self.max_workers.get()),
                result_handling=(
                    "common_summary"
                    if self.result_handling.get().startswith("Common summary")
                    else "complete"
                ),
                logger=logger,
            )
            self.messages.put(("done", output))
        except Exception as exc:  # GUI boundary keeps errors visible to the operator
            logger.exception("Run stopped")
            self.messages.put(("error", str(exc)))

    def _poll(self) -> None:
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == "log":
                    self.log.configure(state=tk.NORMAL)
                    self.log.insert(tk.END, value + "\n")
                    self.log.see(tk.END)
                    self.log.configure(state=tk.DISABLED)
                elif kind == "done":
                    self.last_output = Path(value)
                    self._finish("Completed")
                    self.open_button.configure(state=tk.NORMAL)
                    messagebox.showinfo("Completed", f"Reports created:\n{value}")
                elif kind == "error":
                    self._finish("Stopped — review the error")
                    messagebox.showerror("Run stopped", value)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _finish(self, status: str) -> None:
        self.progress.stop()
        self.run_button.configure(state=tk.NORMAL)
        self.status.set(status)

    def _open_reports(self) -> None:
        if not self.last_output:
            return
        if os.name == "nt":
            os.startfile(self.last_output)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(self.last_output)])


def main() -> None:
    root = tk.Tk()
    CommandRunnerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
