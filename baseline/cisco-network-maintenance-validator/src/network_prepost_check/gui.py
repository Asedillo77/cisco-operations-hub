from __future__ import annotations

import argparse
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .cli import run_postcheck, run_precheck
from .credentials import validate_credentials
from .paths import PROJECT_ROOT


class QueueLogHandler(logging.Handler):
    def __init__(self, message_queue: queue.Queue) -> None:
        super().__init__()
        self.message_queue = message_queue

    def emit(self, record: logging.LogRecord) -> None:
        self.message_queue.put(("log", self.format(record)))


class NetworkPrePostApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.message_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None

        self.root.title("Network Precheck / Postcheck")
        self.root.geometry("980x780")
        self.root.minsize(840, 680)

        self.check_type = tk.StringVar(value="precheck")
        self.target_mode = tk.StringVar(value="inventory")
        self.hostname = tk.StringVar()
        self.inventory_file = tk.StringVar(value=str(PROJECT_ROOT / "samples" / "inventory.csv"))
        self.device_type = tk.StringVar(value="switch")
        self.credentials_mode = tk.StringVar(value="file")
        self.credentials_file = tk.StringVar(
            value=str(PROJECT_ROOT / "credentials" / "credentials.txt")
        )
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.secret = tk.StringVar()
        self.port = tk.StringVar(value="22")
        self.timeout = tk.StringVar(value="30")
        self.output_root = tk.StringVar(value=str(PROJECT_ROOT / "outputs"))
        self.commands_file = tk.StringVar()
        self.template_file = tk.StringVar(
            value=str(PROJECT_ROOT / "reports" / "prepost_report.html.j2")
        )
        self.baseline_file = tk.StringVar()
        self.max_workers = tk.StringVar(value="3")
        self.max_devices = tk.StringVar(value="50")
        self.delay_minutes = tk.StringVar(value="50")
        self.wait_before_postcheck = tk.BooleanVar(value=False)
        self.apply_run = tk.BooleanVar(value=False)
        self.debug = tk.BooleanVar(value=False)
        self.status_text = tk.StringVar(value="Ready")

        self._build_window()
        self._refresh_controls()
        self.root.after(100, self._process_messages)

    def _build_window(self) -> None:
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(4, weight=1)

        title = ttk.Label(main, text="Network Precheck / Postcheck", font=("Segoe UI", 18, "bold"))
        title.grid(row=0, column=0, sticky=tk.W, pady=(0, 10))

        run_frame = ttk.LabelFrame(main, text="Run", padding=10)
        run_frame.grid(row=1, column=0, sticky=tk.EW, pady=(0, 8))
        ttk.Radiobutton(
            run_frame,
            text="Precheck",
            variable=self.check_type,
            value="precheck",
            command=self._refresh_controls,
        ).grid(row=0, column=0, sticky=tk.W, padx=(0, 18))
        ttk.Radiobutton(
            run_frame,
            text="Postcheck",
            variable=self.check_type,
            value="postcheck",
            command=self._refresh_controls,
        ).grid(row=0, column=1, sticky=tk.W)
        ttk.Checkbutton(run_frame, text="Debug logging", variable=self.debug).grid(
            row=0, column=2, sticky=tk.W, padx=(28, 0)
        )

        content = ttk.Frame(main)
        content.grid(row=2, column=0, sticky=tk.EW)
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)

        self._build_target_frame(content)
        self._build_credentials_frame(content)
        self._build_options_frame(main)

        log_frame = ttk.LabelFrame(main, text="Progress", padding=8)
        log_frame.grid(row=4, column=0, sticky=tk.NSEW, pady=(8, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_output = ScrolledText(
            log_frame,
            height=12,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Consolas", 9),
        )
        self.log_output.grid(row=0, column=0, sticky=tk.NSEW)

        action_frame = ttk.Frame(main)
        action_frame.grid(row=5, column=0, sticky=tk.EW, pady=(10, 0))
        action_frame.columnconfigure(1, weight=1)
        self.progress = ttk.Progressbar(action_frame, mode="indeterminate", length=170)
        self.progress.grid(row=0, column=0, sticky=tk.W)
        ttk.Label(action_frame, textvariable=self.status_text).grid(
            row=0, column=1, sticky=tk.W, padx=10
        )
        self.open_button = ttk.Button(
            action_frame,
            text="Open Outputs",
            command=self._open_outputs,
        )
        self.open_button.grid(row=0, column=2, padx=(8, 0))
        self.run_button = ttk.Button(action_frame, text="Run", command=self._start_run)
        self.run_button.grid(row=0, column=3, padx=(8, 0))

    def _build_target_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Devices", padding=10)
        frame.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 4))
        frame.columnconfigure(1, weight=1)

        ttk.Radiobutton(
            frame,
            text="Single device",
            variable=self.target_mode,
            value="single",
            command=self._refresh_controls,
        ).grid(row=0, column=0, sticky=tk.W)
        ttk.Radiobutton(
            frame,
            text="Inventory",
            variable=self.target_mode,
            value="inventory",
            command=self._refresh_controls,
        ).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(frame, text="Hostname or IP").grid(row=1, column=0, sticky=tk.W, pady=(10, 4))
        self.hostname_entry = ttk.Entry(frame, textvariable=self.hostname)
        self.hostname_entry.grid(row=1, column=1, sticky=tk.EW, pady=(10, 4))

        ttk.Label(frame, text="Inventory file").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.inventory_entry = ttk.Entry(frame, textvariable=self.inventory_file)
        self.inventory_entry.grid(row=2, column=1, sticky=tk.EW, pady=4)
        self.inventory_button = ttk.Button(
            frame,
            text="Browse",
            command=lambda: self._browse_file(
                self.inventory_file,
                (("Inventory", "*.csv *.json"), ("All files", "*.*")),
            ),
        )
        self.inventory_button.grid(row=2, column=2, padx=(6, 0), pady=4)

        ttk.Label(frame, text="Device type").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.device_type_combo = ttk.Combobox(
            frame,
            textvariable=self.device_type,
            values=("switch", "edge_router", "auto"),
            state="readonly",
        )
        self.device_type_combo.grid(row=3, column=1, sticky=tk.EW, pady=4)

    def _build_credentials_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Credentials", padding=10)
        frame.grid(row=0, column=1, sticky=tk.NSEW, padx=(4, 0))
        frame.columnconfigure(1, weight=1)

        ttk.Radiobutton(
            frame,
            text="Credential file",
            variable=self.credentials_mode,
            value="file",
            command=self._refresh_controls,
        ).grid(row=0, column=0, sticky=tk.W)
        ttk.Radiobutton(
            frame,
            text="Enter manually",
            variable=self.credentials_mode,
            value="manual",
            command=self._refresh_controls,
        ).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(frame, text="Credential file").grid(row=1, column=0, sticky=tk.W, pady=(10, 4))
        self.credentials_entry = ttk.Entry(frame, textvariable=self.credentials_file)
        self.credentials_entry.grid(row=1, column=1, sticky=tk.EW, pady=(10, 4))
        self.credentials_button = ttk.Button(
            frame,
            text="Browse",
            command=lambda: self._browse_file(
                self.credentials_file,
                (("Text files", "*.txt"), ("All files", "*.*")),
            ),
        )
        self.credentials_button.grid(row=1, column=2, padx=(6, 0), pady=(10, 4))

        ttk.Label(frame, text="Username").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.username_entry = ttk.Entry(frame, textvariable=self.username)
        self.username_entry.grid(row=2, column=1, columnspan=2, sticky=tk.EW, pady=4)

        ttk.Label(frame, text="Password").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.password_entry = ttk.Entry(frame, textvariable=self.password, show="*")
        self.password_entry.grid(row=3, column=1, columnspan=2, sticky=tk.EW, pady=4)

        ttk.Label(frame, text="Enable secret").grid(row=4, column=0, sticky=tk.W, pady=4)
        self.secret_entry = ttk.Entry(frame, textvariable=self.secret, show="*")
        self.secret_entry.grid(row=4, column=1, columnspan=2, sticky=tk.EW, pady=4)

        ttk.Label(frame, text="Port").grid(row=5, column=0, sticky=tk.W, pady=4)
        self.port_entry = ttk.Entry(frame, textvariable=self.port, width=8)
        self.port_entry.grid(row=5, column=1, sticky=tk.W, pady=4)
        ttk.Label(frame, text="Timeout").grid(row=5, column=1, sticky=tk.E, pady=4)
        self.timeout_entry = ttk.Entry(frame, textvariable=self.timeout, width=8)
        self.timeout_entry.grid(row=5, column=2, sticky=tk.E, pady=4)

    def _build_options_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Options", padding=10)
        frame.grid(row=3, column=0, sticky=tk.EW, pady=(8, 0))
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(4, weight=1)

        ttk.Label(frame, text="Output folder").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=self.output_root).grid(
            row=0, column=1, columnspan=3, sticky=tk.EW, pady=4
        )
        ttk.Button(
            frame,
            text="Browse",
            command=lambda: self._browse_directory(self.output_root),
        ).grid(row=0, column=4, sticky=tk.E, padx=(6, 0), pady=4)

        ttk.Label(frame, text="Commands JSON").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=self.commands_file).grid(
            row=1, column=1, columnspan=3, sticky=tk.EW, pady=4
        )
        ttk.Button(
            frame,
            text="Browse",
            command=lambda: self._browse_file(
                self.commands_file,
                (("JSON files", "*.json"), ("All files", "*.*")),
            ),
        ).grid(row=1, column=4, sticky=tk.E, padx=(6, 0), pady=4)

        ttk.Label(frame, text="Workers").grid(row=2, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(frame, from_=1, to=50, textvariable=self.max_workers, width=7).grid(
            row=2, column=1, sticky=tk.W, pady=4
        )
        ttk.Label(frame, text="Device limit").grid(row=2, column=2, sticky=tk.E, pady=4)
        ttk.Spinbox(frame, from_=1, to=1000, textvariable=self.max_devices, width=7).grid(
            row=2, column=3, sticky=tk.W, padx=(6, 0), pady=4
        )

        ttk.Label(frame, text="Baseline JSON").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.baseline_entry = ttk.Entry(frame, textvariable=self.baseline_file)
        self.baseline_entry.grid(row=3, column=1, columnspan=3, sticky=tk.EW, pady=4)
        self.baseline_button = ttk.Button(
            frame,
            text="Browse",
            command=lambda: self._browse_file(
                self.baseline_file,
                (("JSON files", "*.json"), ("All files", "*.*")),
            ),
        )
        self.baseline_button.grid(row=3, column=4, sticky=tk.E, padx=(6, 0), pady=4)

        ttk.Label(frame, text="Postcheck delay").grid(row=4, column=0, sticky=tk.W, pady=4)
        self.delay_entry = ttk.Spinbox(
            frame,
            from_=0,
            to=1440,
            textvariable=self.delay_minutes,
            width=7,
        )
        self.delay_entry.grid(row=4, column=1, sticky=tk.W, pady=4)
        self.wait_check = ttk.Checkbutton(
            frame,
            text="Wait before postcheck",
            variable=self.wait_before_postcheck,
        )
        self.wait_check.grid(row=4, column=2, columnspan=2, sticky=tk.W, pady=4)
        ttk.Checkbutton(frame, text="Connect and collect", variable=self.apply_run).grid(
            row=4, column=4, sticky=tk.E, pady=4
        )

    def _refresh_controls(self) -> None:
        single = self.target_mode.get() == "single"
        self._set_state(self.hostname_entry, single)
        self._set_state(self.inventory_entry, not single)
        self._set_state(self.inventory_button, not single)
        self._set_state(self.device_type_combo, single, readonly=True)

        file_credentials = self.credentials_mode.get() == "file"
        self._set_state(self.credentials_entry, file_credentials)
        self._set_state(self.credentials_button, file_credentials)
        for widget in (
            self.username_entry,
            self.password_entry,
            self.secret_entry,
            self.port_entry,
            self.timeout_entry,
        ):
            self._set_state(widget, not file_credentials)

        postcheck = self.check_type.get() == "postcheck"
        baseline_allowed = postcheck and single
        self._set_state(self.baseline_entry, baseline_allowed)
        self._set_state(self.baseline_button, baseline_allowed)
        self._set_state(self.delay_entry, postcheck)
        self._set_state(self.wait_check, postcheck)

    @staticmethod
    def _set_state(widget: tk.Widget, enabled: bool, readonly: bool = False) -> None:
        if enabled and readonly:
            widget.configure(state="readonly")
        else:
            widget.configure(state=tk.NORMAL if enabled else tk.DISABLED)

    def _browse_file(self, variable: tk.StringVar, filetypes: tuple) -> None:
        selected = filedialog.askopenfilename(filetypes=filetypes)
        if selected:
            variable.set(selected)

    def _browse_directory(self, variable: tk.StringVar) -> None:
        selected = filedialog.askdirectory()
        if selected:
            variable.set(selected)

    def _start_run(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            args, credentials = self._build_run_inputs()
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        if args.apply and not messagebox.askyesno(
            "Confirm device collection",
            f"Connect to the selected device(s) and run the {args.command} commands?",
        ):
            return

        self._clear_log()
        self.status_text.set("Running")
        self.run_button.configure(state=tk.DISABLED)
        self.progress.start(12)
        self.worker = threading.Thread(
            target=self._run_worker,
            args=(args, credentials, self.debug.get()),
            daemon=True,
        )
        self.worker.start()

    def _build_run_inputs(
        self,
    ) -> tuple[argparse.Namespace, dict[str, str | int] | None]:
        single_target = self.target_mode.get() == "single"
        hostname = self.hostname.get().strip() if single_target else None
        inventory_text = self.inventory_file.get().strip() if not single_target else ""
        if not hostname and not inventory_text:
            raise ValueError("Provide a hostname/IP address or select an inventory file.")

        credentials = None
        credentials_file = None
        if self.credentials_mode.get() == "manual":
            credentials = validate_credentials(
                {
                    "username": self.username.get(),
                    "password": self.password.get(),
                    "secret": self.secret.get(),
                    "port": self.port.get(),
                    "timeout": self.timeout.get(),
                }
            )
        else:
            credentials_text = self.credentials_file.get().strip()
            if not credentials_text:
                raise ValueError("Select a credential file.")
            credentials_file = Path(credentials_text)

        output_text = self.output_root.get().strip()
        template_text = self.template_file.get().strip()
        if not output_text:
            raise ValueError("Select an output folder.")
        if not template_text:
            raise ValueError("Select an HTML report template.")

        command = self.check_type.get()
        args = argparse.Namespace(
            command=command,
            hostname=hostname,
            inventory_file=Path(inventory_text) if inventory_text else None,
            device_type=self.device_type.get(),
            credentials_file=credentials_file,
            commands_file=self._optional_path(self.commands_file.get()),
            output_root=Path(output_text),
            template_file=Path(template_text),
            apply=self.apply_run.get(),
            max_workers=self._positive_integer(self.max_workers.get(), "Workers"),
            max_devices=self._positive_integer(self.max_devices.get(), "Device limit"),
            baseline_file=self._optional_path(self.baseline_file.get())
            if command == "postcheck" and single_target
            else None,
            delay_minutes=self._nonnegative_integer(self.delay_minutes.get(), "Postcheck delay")
            if command == "postcheck"
            else 0,
            wait=self.wait_before_postcheck.get() if command == "postcheck" else False,
        )
        return args, credentials

    def _run_worker(
        self,
        args: argparse.Namespace,
        credentials: dict[str, str | int] | None,
        debug: bool,
    ) -> None:
        logger = self._build_gui_logger(debug)
        try:
            runner = run_precheck if args.command == "precheck" else run_postcheck
            exit_code = runner(args, logger, credentials)
            self.message_queue.put(("done", exit_code))
        except Exception:
            logger.exception("Run failed")
            self.message_queue.put(("done", 1))

    def _build_gui_logger(self, debug: bool) -> logging.Logger:
        logger = logging.getLogger("network_prepost_check.gui")
        logger.handlers.clear()
        logger.setLevel(logging.DEBUG if debug else logging.INFO)
        handler = QueueLogHandler(self.message_queue)
        handler.setLevel(logging.DEBUG if debug else logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
        return logger

    def _process_messages(self) -> None:
        try:
            while True:
                event, value = self.message_queue.get_nowait()
                if event == "log":
                    self._append_log(value)
                elif event == "done":
                    self._finish_run(int(value))
        except queue.Empty:
            pass
        self.root.after(100, self._process_messages)

    def _finish_run(self, exit_code: int) -> None:
        self.progress.stop()
        self.run_button.configure(state=tk.NORMAL)
        if exit_code == 0:
            self.status_text.set("Completed")
            messagebox.showinfo("Run complete", "The run completed successfully.")
        else:
            self.status_text.set("Completed with errors")
            messagebox.showerror("Run failed", "The run completed with errors. Review the log.")

    def _append_log(self, message: str) -> None:
        self.log_output.configure(state=tk.NORMAL)
        self.log_output.insert(tk.END, message + "\n")
        self.log_output.see(tk.END)
        self.log_output.configure(state=tk.DISABLED)

    def _clear_log(self) -> None:
        self.log_output.configure(state=tk.NORMAL)
        self.log_output.delete("1.0", tk.END)
        self.log_output.configure(state=tk.DISABLED)

    def _open_outputs(self) -> None:
        output_path = Path(self.output_root.get().strip())
        output_path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(output_path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(output_path)])

    @staticmethod
    def _optional_path(value: str) -> Path | None:
        cleaned = value.strip()
        return Path(cleaned) if cleaned else None

    @staticmethod
    def _positive_integer(value: str, label: str) -> int:
        parsed = int(value)
        if parsed < 1:
            raise ValueError(f"{label} must be 1 or higher.")
        return parsed

    @staticmethod
    def _nonnegative_integer(value: str, label: str) -> int:
        parsed = int(value)
        if parsed < 0:
            raise ValueError(f"{label} cannot be negative.")
        return parsed


def main() -> None:
    root = tk.Tk()
    NetworkPrePostApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
