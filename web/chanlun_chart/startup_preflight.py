from __future__ import annotations

import importlib.util
import pathlib
import runpy
import sys
from typing import Callable, Iterable


_SUPPORTED_PYTHON = ((3, 8), (3, 11))
_CORE_MODULES = (
    ("flask", "flask"),
    ("flask_login", "flask-login"),
    ("tornado", "tornado"),
    ("sqlalchemy", "sqlalchemy"),
    ("apscheduler", "apscheduler"),
    ("pytz", "pytz"),
    ("tzlocal", "tzlocal"),
    ("pinyin", "pinyin"),
    ("numpy", "numpy"),
    ("pandas", "pandas"),
)
_OPTIONAL_MODULES = (
    ("redis", "redis"),
    ("pymysql", "pymysql"),
    ("chromadb", "chromadb"),
    ("sentence_transformers", "sentence-transformers"),
    ("jieba", "jieba"),
    ("langchain", "langchain"),
)


def _check_python_version(version_info: tuple[int, int, int] | None = None) -> dict[str, object]:
    version_info = version_info or sys.version_info
    current = (version_info[0], version_info[1])
    min_supported, max_supported = _SUPPORTED_PYTHON
    ok = min_supported <= current <= max_supported
    return {
        "ok": ok,
        "current": f"{version_info[0]}.{version_info[1]}.{version_info[2]}",
        "message": (
            f"当前 Python 版本为 {version_info[0]}.{version_info[1]}.{version_info[2]}，"
            f"支持范围 {min_supported[0]}.{min_supported[1]} - {max_supported[0]}.{max_supported[1]}"
        ),
    }


def _check_path_exists(path: pathlib.Path, create_tip: str) -> dict[str, object]:
    ok = path.exists()
    return {
        "ok": ok,
        "path": str(path),
        "message": f"{path} {'已存在' if ok else '不存在'}。{create_tip if not ok else ''}".strip(),
    }


def _collect_missing_modules(
    modules: Iterable[tuple[str, str]],
    find_spec: Callable[[str], object | None],
) -> list[dict[str, str]]:
    missing = []
    for module_name, install_name in modules:
        if find_spec(module_name) is None:
            missing.append({"module": module_name, "install_name": install_name})
    return missing


def _resolve_data_path(project_root: pathlib.Path, config_path: pathlib.Path) -> pathlib.Path | None:
    if not config_path.exists():
        return None
    config_values = runpy.run_path(str(config_path))
    raw_data_path = str(config_values.get("DATA_PATH") or ".chanlun_pro")
    data_path = pathlib.Path(raw_data_path)
    if raw_data_path.startswith("."):
        data_path = pathlib.Path.home() / raw_data_path
    elif data_path.is_absolute() is False:
        data_path = project_root / data_path
    return data_path


def _default_write_probe(path: pathlib.Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe_file = path / ".startup_probe"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink()
        return True, "可写"
    except Exception as exc:
        return False, str(exc)


def build_startup_checks(
    project_root: pathlib.Path,
    find_spec: Callable[[str], object | None] | None = None,
    write_probe: Callable[[pathlib.Path], tuple[bool, str]] | None = None,
) -> dict[str, object]:
    root = pathlib.Path(project_root)
    find_spec = find_spec or importlib.util.find_spec
    write_probe = write_probe or _default_write_probe
    config_path = root / "src" / "chanlun" / "config.py"
    license_path = root / "src" / "pyarmor_runtime_005445" / "pyarmor.rkey"

    python_check = _check_python_version()
    config_check = _check_path_exists(
        config_path,
        "可先执行: cp src/chanlun/config.py.demo src/chanlun/config.py",
    )
    license_check = _check_path_exists(
        license_path,
        "请将授权文件放到该路径后再启动。",
    )

    missing_core = _collect_missing_modules(_CORE_MODULES, find_spec)
    missing_optional = _collect_missing_modules(_OPTIONAL_MODULES, find_spec)
    data_path = _resolve_data_path(root, config_path)
    if data_path is None:
        data_path_check = {
            "ok": False,
            "path": "",
            "message": "未找到 config.py，暂时无法判断 DATA_PATH 与 logs 目录权限。",
        }
    else:
        logs_path = data_path / "logs"
        writable, reason = write_probe(logs_path)
        data_path_check = {
            "ok": writable,
            "path": str(logs_path),
            "message": f"{logs_path} {'可写' if writable else '不可写'}。{reason}",
        }
    ok = (
        python_check["ok"]
        and config_check["ok"]
        and license_check["ok"]
        and not missing_core
        and data_path_check["ok"]
    )

    return {
        "ok": bool(ok),
        "project_root": str(root),
        "python": python_check,
        "config": config_check,
        "license": license_check,
        "data_path": data_path_check,
        "dependencies": {
            "ok": not missing_core,
            "missing_modules": [item["module"] for item in missing_core],
            "missing_core": missing_core,
            "missing_optional": missing_optional,
        },
    }


def format_startup_report(report: dict[str, object]) -> str:
    python_check = report["python"]
    config_check = report["config"]
    license_check = report["license"]
    data_path_check = report["data_path"]
    dependencies = report["dependencies"]
    missing_core = dependencies["missing_core"]
    missing_optional = dependencies["missing_optional"]

    lines = ["=" * 72]
    if report["ok"]:
        lines.append("启动前检查通过")
    else:
        lines.append("启动前检查未通过")
    lines.append(f"项目根目录: {report['project_root']}")
    lines.append("-" * 72)
    lines.append(f"Python: {python_check['message']}")
    lines.append(f"配置文件: {config_check['message']}")
    lines.append(f"授权文件: {license_check['message']}")
    lines.append(f"数据目录: {data_path_check['message']}")

    if missing_core:
        core_modules = ", ".join(item["module"] for item in missing_core)
        lines.append(f"核心依赖缺失: {core_modules}")
        lines.append("安装命令: pip install -r requirements.txt")
    else:
        lines.append("核心依赖: 已安装")

    if missing_optional:
        optional_modules = ", ".join(item["module"] for item in missing_optional)
        lines.append(f"可选依赖缺失: {optional_modules}")
        lines.append("这些依赖主要影响 Redis / 向量检索 / 扩展分析能力，未必阻止 Web 首页启动。")

    if not config_check["ok"]:
        lines.append("配置文件示例命令: cp src/chanlun/config.py.demo src/chanlun/config.py")
    if not data_path_check["ok"]:
        lines.append("请确认 DATA_PATH 对当前运行用户可写，尤其是 logs 子目录。")

    lines.append("建议启动命令: python app.py nobrowser")
    lines.append("=" * 72)
    return "\n".join(lines)
