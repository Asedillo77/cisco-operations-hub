from cisco_command_runner.result_summaries import summarize_result

EDGE_SHOW_VERSION = """Cisco IOS XE Software, Version 17.12.07b
ROM: 17.6(8.1r)

LAB-RTR-01 uptime is 11 weeks, 4 days, 19 hours, 31 minutes
System image file is "bootflash:packages.conf"
Last reload reason: Reload Command
cisco C8200-1N-4T (1RU) processor with 7782293K/6147K bytes of memory.
Processor board ID FGL2719LGCH
"""


def test_show_version_common_summary_extracts_available_fields() -> None:
    summary, fields = summarize_result("show version", EDGE_SHOW_VERSION)
    assert fields == {
        "IOS Version": "17.12.07b",
        "ROM Version": "17.6(8.1r)",
        "Uptime": "11 weeks, 4 days, 19 hours, 31 minutes",
        "Reload Reason": "Reload Command",
        "Model": "C8200-1N-4T",
        "Serial Number": "FGL2719LGCH",
        "System Image": "bootflash:packages.conf",
    }
    assert "IOS Version: 17.12.07b" in summary
    assert "ROM Version: 17.6(8.1r)" in summary


def test_filtered_show_version_and_text_rommon_are_supported() -> None:
    output = "Cisco IOS XE Software, Version 17.15.03\nROM: IOS-XE ROMMON"
    _, fields = summarize_result(
        "show version | include ^Cisco IOS XE Software, Version|^ROM:", output
    )
    assert fields["IOS Version"] == "17.15.03"
    assert fields["ROM Version"] == "IOS-XE ROMMON"


def test_unrelated_command_is_not_interpreted() -> None:
    assert summarize_result("show inventory", EDGE_SHOW_VERSION) == ("", {})
