from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"


def _normalized_requirement_names() -> set[str]:
    names: set[str] = set()
    for raw_line in REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        package = re.split(r"[<>=!~]", line, maxsplit=1)[0].strip().lower()
        if package:
            names.add(package)
    return names


def test_requirements_cover_runtime_startup_dependencies():
    requirement_names = _normalized_requirement_names()

    expected_packages = {
        "numpy",
        "pandas",
        "pytz",
        "tzlocal",
        "pytdx",
        "ta-lib",
    }

    missing = expected_packages - requirement_names
    assert missing == set()
