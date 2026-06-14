from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from startup_preflight import build_startup_checks, format_startup_report


def test_build_startup_checks_reports_missing_files_and_modules(tmp_path):
    def fake_find_spec(module_name: str):
        if module_name in {"flask", "tornado"}:
            return object()
        return None

    report = build_startup_checks(tmp_path, find_spec=fake_find_spec)

    assert report["ok"] is False
    assert "src/chanlun/config.py" in report["config"]["message"]
    assert "src/pyarmor_runtime_005445/pyarmor.rkey" in report["license"]["message"]
    missing_modules = set(report["dependencies"]["missing_modules"])
    assert "flask_login" in missing_modules
    assert "pinyin" in missing_modules


def test_build_startup_checks_passes_when_files_and_modules_exist(tmp_path):
    (tmp_path / "src" / "chanlun").mkdir(parents=True)
    (tmp_path / "src" / "pyarmor_runtime_005445").mkdir(parents=True)
    (tmp_path / "src" / "chanlun" / "config.py").write_text(
        "WEB_HOST='0.0.0.0'\nDATA_PATH='runtime_data'\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "pyarmor_runtime_005445" / "pyarmor.rkey").write_text("demo", encoding="utf-8")

    report = build_startup_checks(
        tmp_path,
        find_spec=lambda _module_name: object(),
        write_probe=lambda _path: (True, "ok"),
    )

    assert report["ok"] is True
    assert report["dependencies"]["missing_modules"] == []
    assert report["config"]["ok"] is True
    assert report["license"]["ok"] is True
    assert report["data_path"]["ok"] is True


def test_format_startup_report_includes_install_and_config_tips(tmp_path):
    report = build_startup_checks(tmp_path, find_spec=lambda _module_name: None)

    output = format_startup_report(report)

    assert "启动前检查未通过" in output
    assert "pip install -r requirements.txt" in output
    assert "cp src/chanlun/config.py.demo src/chanlun/config.py" in output
    assert "python app.py nobrowser" in output


def test_build_startup_checks_reports_unwritable_log_directory(tmp_path):
    (tmp_path / "src" / "chanlun").mkdir(parents=True)
    (tmp_path / "src" / "pyarmor_runtime_005445").mkdir(parents=True)
    (tmp_path / "src" / "chanlun" / "config.py").write_text(
        "WEB_HOST='0.0.0.0'\nDATA_PATH='runtime_data'\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "pyarmor_runtime_005445" / "pyarmor.rkey").write_text("demo", encoding="utf-8")

    report = build_startup_checks(
        tmp_path,
        find_spec=lambda _module_name: object(),
        write_probe=lambda _path: (False, "Permission denied"),
    )

    assert report["ok"] is False
    assert report["data_path"]["ok"] is False
    assert "Permission denied" in report["data_path"]["message"]
