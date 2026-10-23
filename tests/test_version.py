"""VERSION.txt is the one place the version is written; everything else
reads it, and CHANGELOG.md's newest release must agree with it."""
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import scribe_lang

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
RELEASE = re.compile(r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})$", re.MULTILINE)


def version_file() -> str:
    return (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()


def test_version_file_holds_one_semantic_version():
    assert SEMVER.match(version_file())


def test_the_newest_release_in_the_changelog_is_the_current_version():
    releases = RELEASE.findall((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    assert releases[0][0] == version_file()


def test_changelog_releases_go_down_in_version_and_date():
    releases = RELEASE.findall((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    versions = [tuple(int(part) for part in v.split(".")) for v, _ in releases]
    dates = [d for _, d in releases]
    assert versions == sorted(versions, reverse=True) and len(set(versions)) == len(versions)
    assert dates == sorted(dates, reverse=True)


def test_pyproject_reads_the_version_file():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in project["project"]
    assert "version" in project["project"]["dynamic"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {"file": "VERSION.txt"}


def test_the_package_reports_the_version():
    assert scribe_lang.__version__ == version_file()


def test_the_command_prints_the_version():
    run = subprocess.run([sys.executable, "-m", "scribe_lang.cli", "--version"], capture_output=True, text=True)
    assert (run.returncode, run.stdout) == (0, f"scribe {version_file()}\n")
