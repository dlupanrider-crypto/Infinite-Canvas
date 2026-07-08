#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Infinite-Canvas 最小回归检查脚本
用法：
    python scripts/regression_check.py              # 运行全部检查（不含集成提示）
    python scripts/regression_check.py --startup    # 仅启动检查
    python scripts/regression_check.py --api        # 仅 API 健康检查
    python scripts/regression_check.py --data       # 仅数据完整性检查
    python scripts/regression_check.py --frontend   # 仅前端检查
    python scripts/regression_check.py --all        # 运行全部检查（含集成提示）
"""

import sys
import os
import argparse
import json
import re
import py_compile
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Tuple

# Windows 控制台强制 UTF-8 输出（避免 GBK 编码 Unicode 符号失败）
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# 全局配置
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
_config = {
    "api_base_url": "http://127.0.0.1:3000",
    "api_timeout": 5,  # 秒
}

# 结果统计
_stats = {"pass": 0, "fail": 0, "skip": 0}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _pass(label: str, detail: str = ""):
    _stats["pass"] += 1
    suffix = f": {detail}" if detail else ""
    print(f"  \u2713 {label}{suffix}")


def _fail(label: str, detail: str = ""):
    _stats["fail"] += 1
    suffix = f" ({detail})" if detail else ""
    print(f"  \u2717 {label}{suffix}")


def _skip(label: str, detail: str = ""):
    _stats["skip"] += 1
    suffix = f" ({detail})" if detail else ""
    print(f"  \u2298 {label}{suffix}")


def _print_summary():
    total = _stats["pass"] + _stats["fail"] + _stats["skip"]
    print(f"\n[汇总] 通过: {_stats['pass']} | 失败: {_stats['fail']} | 跳过: {_stats['skip']} | 总计: {total}")
    if _stats["fail"] > 0:
        print("\n⚠ 存在失败项，请检查后重试。")


# ---------------------------------------------------------------------------
# 1. 启动检查
# ---------------------------------------------------------------------------

def check_startup():
    print("\n[启动检查]")

    # Python 版本
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        _pass("Python 版本", ver)
    else:
        _fail("Python 版本", f"需要 >= 3.10，当前 {ver}")

    # 依赖导入
    deps = [
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("pydantic", "pydantic"),
        ("httpx", "httpx"),
        ("PIL", "pillow"),
        ("requests", "requests"),
        ("multipart", "python-multipart"),
    ]
    for mod, pkg in deps:
        try:
            __import__(mod)
            _pass("依赖导入", pkg)
        except Exception as e:
            _fail("依赖导入", f"{pkg}: {type(e).__name__}")

    # 语法检查 main.py
    main_py = PROJECT_ROOT / "main.py"
    if not main_py.exists():
        _fail("main.py 语法检查", "文件不存在")
    else:
        try:
            py_compile.compile(str(main_py), doraise=True)
            _pass("main.py 语法检查")
        except py_compile.PyCompileError as e:
            _fail("main.py 语法检查", str(e).splitlines()[0])

    # 数据目录
    for sub in ["data/canvases", "data/conversations"]:
        p = PROJECT_ROOT / sub
        if p.is_dir():
            _pass("数据目录", f"{sub}/")
        else:
            _fail("数据目录", f"{sub}/ 不存在")

    # 配置文件 API/.env
    env_file = PROJECT_ROOT / "API" / ".env"
    if env_file.exists():
        try:
            env_file.read_text(encoding="utf-8")
            _pass("配置文件", "API/.env 可读")
        except Exception as e:
            _fail("配置文件", f"API/.env 不可读: {e}")
    else:
        _skip("配置文件", "API/.env 不存在，跳过")

    # 版本号
    version_file = PROJECT_ROOT / "VERSION"
    if version_file.exists():
        content = version_file.read_text(encoding="utf-8").strip()
        if content:
            _pass("版本号", content)
        else:
            _fail("版本号", "VERSION 文件为空")
    else:
        _fail("版本号", "VERSION 文件不存在")


# ---------------------------------------------------------------------------
# 2. API 健康检查
# ---------------------------------------------------------------------------

_API_ENDPOINTS = [
    "/api/app-info",
    "/api/config",
    "/api/providers",
    "/api/canvases",
    "/api/projects",
    "/api/asset-library",
    "/api/prompt-libraries",
    "/api/shared-folders",
    "/api/conversations",
    "/api/history",
    "/api/comfyui/instances",
    "/api/workflows",
    "/api/queue_status",
]


def check_api():
    print("\n[API 健康检查]")
    base_url = _config["api_base_url"]
    print(f"  目标服务: {base_url}")

    for endpoint in _API_ENDPOINTS:
        url = f"{base_url}{endpoint}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=_config["api_timeout"]) as resp:
                if resp.status == 200:
                    _pass(f"GET {endpoint}")
                else:
                    _fail(f"GET {endpoint}", f"HTTP {resp.status}")
        except urllib.error.URLError as e:
            # 连接失败 → SKIP（服务未启动）
            _skip(f"GET {endpoint}", f"连接失败: {e.reason}")
        except Exception as e:
            _fail(f"GET {endpoint}", f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 3. 数据完整性检查
# ---------------------------------------------------------------------------

def check_data():
    print("\n[数据完整性检查]")

    data_dir = PROJECT_ROOT / "data"
    if not data_dir.is_dir():
        _fail("data/ 目录", "不存在")
        return

    # 遍历所有 .json 文件
    json_files = list(data_dir.rglob("*.json"))
    if not json_files:
        _skip("JSON 文件", "data/ 下无 JSON 文件")
    else:
        for jf in json_files:
            rel = jf.relative_to(PROJECT_ROOT)
            try:
                with open(jf, "r", encoding="utf-8") as f:
                    json.load(f)
                _pass("JSON 格式", str(rel))
            except json.JSONDecodeError as e:
                _fail("JSON 格式", f"{rel}: {e}")
            except Exception as e:
                _fail("JSON 格式", f"{rel}: {type(e).__name__}: {e}")

    # history.json 条数检查
    history_file = data_dir / "history.json"
    if history_file.exists():
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            count = len(data) if isinstance(data, list) else 1
            if count <= 5000:
                _pass("history.json 条数", f"{count} 条 (≤ 5000)")
            else:
                _fail("history.json 条数", f"{count} 条 (> 5000)")
        except Exception:
            pass  # JSON 格式错误已在上面报告
    else:
        _skip("history.json 条数", "文件不存在")

    # api_providers.json 格式检查
    providers_file = PROJECT_ROOT / "static" / "runninghub" / "api_providers.json"
    if providers_file.exists():
        try:
            with open(providers_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, (list, dict)):
                _pass("api_providers.json 格式", f"类型={type(data).__name__}")
            else:
                _fail("api_providers.json 格式", f"期望 list/dict，实际 {type(data).__name__}")
        except json.JSONDecodeError as e:
            _fail("api_providers.json 格式", str(e))
    else:
        _skip("api_providers.json 格式", "文件不存在")

    # VERSION vs APP_VERSION 一致性
    version_file = PROJECT_ROOT / "VERSION"
    main_py = PROJECT_ROOT / "main.py"
    if version_file.exists() and main_py.exists():
        file_ver = version_file.read_text(encoding="utf-8").strip()
        # 从 main.py 提取 APP_VERSION
        app_ver = None
        try:
            content = main_py.read_text(encoding="utf-8")
            m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
            if m:
                app_ver = m.group(1)
        except Exception:
            pass

        if app_ver is None:
            _skip("版本号一致性", "main.py 中未找到 APP_VERSION")
        elif file_ver == app_ver:
            _pass("版本号一致性", f"VERSION={file_ver} == APP_VERSION={app_ver}")
        else:
            _fail("版本号一致性", f"VERSION={file_ver} != APP_VERSION={app_ver}")
    else:
        _skip("版本号一致性", "VERSION 或 main.py 不存在")


# ---------------------------------------------------------------------------
# 4. 前端检查
# ---------------------------------------------------------------------------

_CORE_PAGES = [
    "index.html",
    "canvas.html",
    "smart-canvas.html",
    "canvas-list.html",
    "api-settings.html",
    "asset-manager.html",
    "comfyui-settings.html",
    "gpt-chat.html",
    "online.html",
]

_I18N_FILES = [
    "api-settings.js",
    "canvas.js",
    "comfyui-settings.js",
    "common.js",
    "smart-canvas.js",
    "studio.js",
]


class _StaticAssetParser(HTMLParser):
    """解析 HTML 中引用的 JS/CSS 静态资源路径"""

    def __init__(self):
        super().__init__()
        self.assets: List[str] = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if tag == "script" and "src" in attr_dict:
            self.assets.append(attr_dict["src"])
        elif tag == "link" and attr_dict.get("rel") == "stylesheet" and "href" in attr_dict:
            self.assets.append(attr_dict["href"])


def _extract_static_paths(html_file: Path) -> List[str]:
    """从 HTML 文件中提取 JS/CSS 静态资源路径（去掉查询参数）"""
    parser = _StaticAssetParser()
    try:
        content = html_file.read_text(encoding="utf-8")
        parser.feed(content)
    except Exception:
        return []

    paths = []
    for raw in parser.assets:
        # 去掉查询参数 ?v=...
        clean = raw.split("?")[0]
        # 只处理绝对路径（以 / 开头）
        if clean.startswith("/"):
            paths.append(clean.lstrip("/"))
    return paths


def check_frontend():
    print("\n[前端检查]")
    static_dir = PROJECT_ROOT / "static"

    # 核心 HTML 页面存在性
    for page in _CORE_PAGES:
        p = static_dir / page
        if p.exists():
            _pass("HTML 页面", page)
        else:
            _fail("HTML 页面", f"{page} 不存在")

    # 静态资源引用完整性
    missing_assets = []
    checked_assets = set()
    for page in _CORE_PAGES:
        html_file = static_dir / page
        if not html_file.exists():
            continue
        for asset_path in _extract_static_paths(html_file):
            if asset_path in checked_assets:
                continue
            checked_assets.add(asset_path)
            full = PROJECT_ROOT / asset_path
            if not full.exists():
                missing_assets.append((page, asset_path))

    if not missing_assets:
        _pass("静态资源引用", f"共检查 {len(checked_assets)} 个引用，全部存在")
    else:
        for page, asset in missing_assets:
            _fail("静态资源引用", f"{page} 引用 {asset} 但文件不存在")

    # i18n 翻译文件完整性
    i18n_dir = static_dir / "js" / "i18n"
    for i18n_file in _I18N_FILES:
        p = i18n_dir / i18n_file
        if p.exists():
            _pass("i18n 翻译文件", i18n_file)
        else:
            _fail("i18n 翻译文件", f"{i18n_file} 不存在")


# ---------------------------------------------------------------------------
# 5. 集成检查（仅提示）
# ---------------------------------------------------------------------------

def check_integration():
    print("\n[集成检查 - 需手动验证]")
    items = [
        "外部 API 调用（需要有效 API Key）",
        "WebSocket 连接（需要客户端建立连接）",
        "ComfyUI 集成（需要 ComfyUI 服务运行）",
        "AI 生图功能（需要配置模型和 API）",
        "Photoshop 插件连接（需要 PS 运行）",
    ]
    for item in items:
        print(f"  ⊘ {item}")
    print("  以上项目需要手动验证，不自动执行。")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Infinite-Canvas 最小回归检查脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--startup", action="store_true", help="运行启动检查")
    parser.add_argument("--api", action="store_true", help="运行 API 健康检查")
    parser.add_argument("--data", action="store_true", help="运行数据完整性检查")
    parser.add_argument("--frontend", action="store_true", help="运行前端检查")
    parser.add_argument("--integration", action="store_true", help="显示集成检查提示")
    parser.add_argument("--all", action="store_true", help="运行全部检查（含集成提示）")
    parser.add_argument(
        "--api-url",
        default=_config["api_base_url"],
        help=f"API 服务地址 (默认: {_config['api_base_url']})",
    )
    args = parser.parse_args()

    # 修改 API 地址
    _config["api_base_url"] = args.api_url

    # 如果没有指定任何类别，默认运行全部（不含集成提示）
    run_all = args.all
    specified = any([args.startup, args.api, args.data, args.frontend, args.integration])
    if not specified and not run_all:
        run_all = True

    print("=== Infinite-Canvas 回归检查 ===")
    print(f"项目根目录: {PROJECT_ROOT}")

    if args.startup or run_all:
        check_startup()
    if args.api or run_all:
        check_api()
    if args.data or run_all:
        check_data()
    if args.frontend or run_all:
        check_frontend()
    if args.integration or args.all:
        check_integration()

    _print_summary()

    # 有失败项时返回非零退出码
    sys.exit(1 if _stats["fail"] > 0 else 0)


if __name__ == "__main__":
    main()
