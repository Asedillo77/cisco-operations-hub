"""Tkinter interface for the standalone connectivity evidence tool."""

from __future__ import annotations

import logging
import os
import queue
import threading
import tkinter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import BooleanVar, IntVar, StringVar, Tk, filedialog, messagebox, ttk

from .credentials import load_credentials, load_solarwinds_credentials
from .engine import investigate_device
from .inventory import devices_for_site, load_inventory, sites_from_inventory
from .reporting import build_report, write_reports
from .solarwinds import SolarWindsAlertClient, SolarWindsError, UnavailableSolarWindsCollector


@dataclass(slots=True)
class GuiRequest:
    """Validated GUI inputs passed to the background worker."""

    inventory: Path
    credentials: Path | None
    report_dir: Path
    site: str
    apply: bool
    debug: bool
    ping_count: int
    ping_timeout: int
    solarwinds_alerts: bool
    solarwinds_credentials: Path | None


class QueueHandler(logging.Handler):
    """Send log messages from the worker thread to Tkinter."""

    def __init__(self, events: queue.Queue[tuple[str, object]]) -> None:
        """Initialise the handler with the GUI event queue."""
        super().__init__()
        self.events = events

    def emit(self, record: logging.LogRecord) -> None:
        """Queue one formatted log record."""
        self.events.put(("log", self.format(record)))


class ConnectivityGui:
    """Responsive desktop interface with safe dry-run defaults."""

    def __init__(self, root: Tk) -> None:
        """Initialise state, widgets, and event polling."""
        self.root = root
        self.root.title("Network Connectivity Evidence Explorer")
        self.root.minsize(820, 620)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.inventory_path = StringVar()
        self.credentials_path = StringVar()
        self.solarwinds_credentials_path = StringVar()
        self.output_path = StringVar(value=str(Path.cwd() / "reports"))
        self.site = StringVar()
        self.apply = BooleanVar(value=False)
        self.debug = BooleanVar(value=False)
        self.solarwinds_alerts = BooleanVar(value=False)
        self.ping_count = IntVar(value=15)
        self.ping_timeout = IntVar(value=2)
        self.status = StringVar(value="Ready — dry-run mode")
        self.last_html: Path | None = None
        self.last_json: Path | None = None
        self._build()
        self.root.after(100, self._poll_events)

    def _build(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Header.TLabel", background="#0F766E", foreground="#FFFFFF", font=("Aptos", 20, "bold"))
        style.configure("Run.TButton", font=("Aptos", 10, "bold"))
        container = ttk.Frame(self.root, padding=16)
        container.grid(sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        ttk.Label(
            container,
            text="Network Connectivity Evidence Explorer",
            style="Header.TLabel",
            padding=14,
        ).grid(row=0, column=0, sticky="ew")

        inputs = ttk.LabelFrame(container, text="Investigation Input", padding=12)
        inputs.grid(row=1, column=0, sticky="ew", pady=12)
        inputs.columnconfigure(1, weight=1)
        self._path_row(inputs, 0, "Inventory JSON", self.inventory_path, self._choose_inventory)
        self._path_row(inputs, 1, "Credentials file", self.credentials_path, self._choose_credentials)
        self._path_row(
            inputs,
            2,
            "SolarWinds credentials",
            self.solarwinds_credentials_path,
            self._choose_solarwinds_credentials,
        )
        self._path_row(inputs, 3, "Report folder", self.output_path, self._choose_output)
        ttk.Label(inputs, text="Site").grid(row=4, column=0, sticky="w", pady=6)
        self.site_box = ttk.Combobox(inputs, textvariable=self.site, state="readonly")
        self.site_box.grid(row=4, column=1, sticky="ew", padx=8, pady=6)

        options = ttk.LabelFrame(container, text="Safe Execution", padding=12)
        options.grid(row=2, column=0, sticky="ew")
        ttk.Checkbutton(
            options,
            text="Run live read-only collection",
            variable=self.apply,
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(options, text="Debug logging", variable=self.debug).grid(row=0, column=1, sticky="w", padx=20)
        ttk.Checkbutton(
            options,
            text="Check SolarWinds active alerts",
            variable=self.solarwinds_alerts,
        ).grid(row=0, column=2, sticky="w", padx=20)
        ttk.Label(options, text="Ping count").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Spinbox(options, from_=1, to=20, textvariable=self.ping_count, width=6).grid(
            row=1, column=0, padx=(85, 0), sticky="w"
        )
        ttk.Label(options, text="Timeout (s)").grid(row=1, column=1, sticky="w", padx=(20, 0))
        ttk.Spinbox(options, from_=1, to=10, textvariable=self.ping_timeout, width=6).grid(
            row=1, column=1, padx=(105, 0), sticky="w"
        )

        actions = ttk.Frame(container)
        actions.grid(row=3, column=0, sticky="ew", pady=12)
        self.run_button = ttk.Button(actions, text="Generate Report", style="Run.TButton", command=self._start)
        self.run_button.grid(row=0, column=0)
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.cancel_event.set, state="disabled")
        self.cancel_button.grid(row=0, column=1, padx=8)
        self.html_button = ttk.Button(actions, text="Open HTML", command=self._open_html, state="disabled")
        self.html_button.grid(row=0, column=2)
        ttk.Label(actions, textvariable=self.status).grid(row=0, column=3, sticky="w", padx=16)

        log_frame = ttk.LabelFrame(container, text="Execution Log", padding=8)
        log_frame.grid(row=4, column=0, sticky="nsew")
        container.rowconfigure(4, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log = tkinter.Text(log_frame, height=14, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")

    def _path_row(
        self,
        frame: ttk.LabelFrame,
        row: int,
        label: str,
        variable: StringVar,
        command: Callable[[], None],
    ) -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8, pady=6)
        ttk.Button(frame, text="Browse", command=command).grid(row=row, column=2)

    def _choose_inventory(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON inventory", "*.json")])
        if path:
            self.inventory_path.set(path)
            try:
                sites = sites_from_inventory(load_inventory(Path(path)))
                self.site_box.configure(values=sites)
                if sites:
                    self.site.set(sites[0])
            except (OSError, ValueError) as exc:
                messagebox.showerror("Inventory error", str(exc))

    def _choose_credentials(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            self.credentials_path.set(path)

    def _choose_solarwinds_credentials(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            self.solarwinds_credentials_path.set(path)

    def _choose_output(self) -> None:
        if path := filedialog.askdirectory():
            self.output_path.set(path)

    def _request(self) -> GuiRequest:
        if not self.inventory_path.get() or not self.site.get():
            raise ValueError("Select an inventory file and site.")
        if self.apply.get() and not self.credentials_path.get():
            raise ValueError("Select a local credentials file for live collection.")
        if self.apply.get() and self.solarwinds_alerts.get() and not self.solarwinds_credentials_path.get():
            raise ValueError("Select a SolarWinds credentials file for the optional live alert check.")
        return GuiRequest(
            Path(self.inventory_path.get()),
            Path(self.credentials_path.get()) if self.credentials_path.get() else None,
            Path(self.output_path.get()),
            self.site.get(),
            self.apply.get(),
            self.debug.get(),
            self.ping_count.get(),
            self.ping_timeout.get(),
            self.solarwinds_alerts.get(),
            Path(self.solarwinds_credentials_path.get()) if self.solarwinds_credentials_path.get() else None,
        )

    def _start(self) -> None:
        try:
            request = self._request()
        except ValueError as exc:
            messagebox.showerror("Cannot start", str(exc))
            return
        if request.apply and not messagebox.askyesno(
            "Confirm live collection", "Run ping and read-only SSH commands now?"
        ):
            return
        self.cancel_event.clear()
        self.run_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.status.set("Running…")
        threading.Thread(target=self._execute, args=(request,), daemon=True).start()

    def _execute(self, request: GuiRequest) -> None:
        logger = logging.getLogger("site_connectivity.gui")
        logger.handlers.clear()
        handler = QueueHandler(self.events)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG if request.debug else logging.INFO)
        try:
            targets = devices_for_site(load_inventory(request.inventory), request.site)
            credentials = load_credentials(request.credentials) if request.credentials else None
            solarwinds_collector = None
            if request.solarwinds_alerts and request.apply:
                try:
                    if request.solarwinds_credentials is None:
                        raise ValueError("SolarWinds credentials file was not selected.")
                    sw_credentials = load_solarwinds_credentials(request.solarwinds_credentials)
                    solarwinds_collector = SolarWindsAlertClient(sw_credentials, logger)
                except (OSError, ValueError, SolarWindsError) as exc:
                    logger.error("Optional SolarWinds setup failed: %s", exc)
                    solarwinds_collector = UnavailableSolarWindsCollector(str(exc))
            results = [
                investigate_device(
                    target,
                    credentials,
                    apply=request.apply,
                    ping_count=request.ping_count,
                    ping_timeout=request.ping_timeout,
                    logger=logger,
                    cancelled=self.cancel_event.is_set,
                    solarwinds_collector=solarwinds_collector,
                    solarwinds_requested=request.solarwinds_alerts,
                )
                for target in targets
                if not self.cancel_event.is_set()
            ]
            paths = write_reports(build_report(request.site, results, dry_run=not request.apply), request.report_dir)
            self.events.put(("complete", paths))
        except Exception as exc:  # Worker failures are returned to the GUI.
            logger.exception("Investigation failed")
            self.events.put(("error", str(exc)))

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "log":
                    self.log.configure(state="normal")
                    self.log.insert("end", f"{payload}\n")
                    self.log.see("end")
                    self.log.configure(state="disabled")
                elif event == "complete":
                    self.last_html, self.last_json = payload  # type: ignore[misc]
                    self.status.set("Report complete")
                    self.run_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    self.html_button.configure(state="normal")
                elif event == "error":
                    self.status.set("Failed")
                    self.run_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    messagebox.showerror("Investigation failed", str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _open_html(self) -> None:
        if self.last_html:
            os.startfile(self.last_html)  # type: ignore[attr-defined]  # noqa: S606


def main() -> int:
    """Launch the desktop interface."""
    root = Tk()
    ConnectivityGui(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
