from pathlib import Path
from tempfile import TemporaryDirectory

from daily_network_health_monitor.cli import _mock_report

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    destination = PROJECT_ROOT / "sample_reports"
    destination.mkdir(exist_ok=True)
    with TemporaryDirectory() as temporary_directory:
        generated = _mock_report(Path(temporary_directory))
        for source in generated.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(generated)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    print(f"Sample reports created: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
