"""下载 scrcpy-server.jar（scrcpy 源要用它）。

    python -m imeg.tools.fetch_scrcpy_server                 # 默认 3.3.1
    python -m imeg.tools.fetch_scrcpy_server --version v4.1
    python -m imeg.tools.fetch_scrcpy_server --list          # 列出可用版本
    python -m imeg.tools.fetch_scrcpy_server --dest ./vendor

下载到 ``~/.imeg/scrcpy-server.jar``，并在旁边写 ``scrcpy-server.json`` 记录版本号
（启动服务端时必须传一模一样的版本号，否则服务端拒绝运行）。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

__all__ = ["DEFAULT_VERSION", "download", "list_versions", "asset_url"]

DEFAULT_VERSION = "3.3.1"
RELEASES_API = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"
ALL_RELEASES_API = "https://api.github.com/repos/Genymobile/scrcpy/releases?per_page=20"


def asset_url(version: str) -> str:
    tag = version if str(version).startswith("v") else f"v{version}"
    return f"https://github.com/Genymobile/scrcpy/releases/download/{tag}/scrcpy-server-{tag}"


def list_versions(limit: int = 12) -> list[str]:
    req = urllib.request.Request(ALL_RELEASES_API, headers={"User-Agent": "IMEG"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    return [r["tag_name"] for r in data][:limit]


def download(version: str = DEFAULT_VERSION, dest: str | None = None) -> str:
    dest_path = Path(dest) if dest else Path.home() / ".imeg" / "scrcpy-server.jar"
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    url = asset_url(version)
    print(f"下载 {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "IMEG"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"下载失败（{exc.code}）：{url}\n可用版本用 --list 查看") from exc
    if len(data) < 100_000 or data[:2] != b"PK":
        raise SystemExit(f"下载内容不像 jar（{len(data)} 字节），请检查版本号")
    dest_path.write_bytes(data)
    sidecar = dest_path.with_suffix(".json")
    sidecar.write_text(json.dumps({"version": str(version).lstrip("v"), "url": url},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已保存 {dest_path}  ({len(data) / 1024:.0f} KB)")
    print(f"版本记录在 {sidecar}")
    return str(dest_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="下载 scrcpy-server.jar")
    parser.add_argument("--version", default=DEFAULT_VERSION, help=f"版本，默认 {DEFAULT_VERSION}")
    parser.add_argument("--dest", default=None, help="保存路径，默认 ~/.imeg/scrcpy-server.jar")
    parser.add_argument("--list", action="store_true", help="列出最近的版本")
    args = parser.parse_args(argv)
    if args.list:
        try:
            for tag in list_versions():
                print(" ", tag)
        except Exception as exc:
            print(f"获取版本列表失败: {exc}", file=sys.stderr)
            return 1
        return 0
    try:
        download(args.version, args.dest)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
