from pathlib import Path

from site_connectivity.credentials import load_solarwinds_credentials


def test_solarwinds_web_url_is_reduced_to_hostname(tmp_path: Path) -> None:
    path = tmp_path / "solarwinds.txt"
    path.write_text(
        "solarwinds_hostname=https://orion.example.org/Orion/SummaryView.aspx\n"
        "solarwinds_username=test-user\n"
        "solarwinds_password=test-password\n",
        encoding="utf-8",
    )
    credentials = load_solarwinds_credentials(path)
    assert credentials.hostname == "orion.example.org"
    assert credentials.port == 17774
