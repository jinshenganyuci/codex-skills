#!/usr/bin/env python3
"""List and anonymously download files from a public Quark share."""

import argparse
import collections
import hashlib
import http.cookiejar
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath


API_ROOT = "https://drive-pc.quark.cn/1/clouddrive"
PAGE_SIZE = 100
MAX_DIRECTORIES = 10_000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class QuarkError(RuntimeError):
    pass


class HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            raise urllib.error.HTTPError(newurl, 403, "拒绝非 HTTPS 重定向", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def parse_share_id(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ("pan.quark.cn", "www.pan.quark.cn"):
        raise QuarkError("只接受 https://pan.quark.cn/s/... 公开分享链接")
    match = re.search(r"(?:^|/)s/([0-9a-zA-Z]+)(?:/|$)", parsed.path)
    if not match:
        raise QuarkError("无法从分享链接中取得分享 ID")
    return match.group(1)


def timestamp_ms(item):
    for key in ("updated_at", "last_update_at", "operated_at", "created_at", "l_updated_at"):
        try:
            value = float(item.get(key))
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        if value < 100_000_000_000:
            value *= 1000
        elif value > 100_000_000_000_000:
            value /= 1000
        return int(value)
    return 0


def timestamp_text(item):
    value = timestamp_ms(item)
    if not value:
        return "未知"
    return datetime.fromtimestamp(
        value / 1000, timezone(timedelta(hours=8))
    ).strftime("%Y-%m-%d %H:%M:%S")


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class QuarkPublicShare:
    def __init__(self, share_url, passcode=""):
        self.share_id = parse_share_id(share_url)
        self.passcode = passcode
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            HttpsOnlyRedirectHandler(),
        )
        self.stoken = None

    def api(self, path, method="GET", params=None, body=None):
        query = urllib.parse.urlencode(params or {})
        url = API_ROOT + path + ("?" + query if query else "")
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "https://pan.quark.cn",
            "Referer": "https://pan.quark.cn/",
        }
        request_data = None
        if body is not None:
            request_data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"

        last_error = None
        for attempt in range(3):
            request = urllib.request.Request(url, data=request_data, headers=headers, method=method)
            try:
                with self.opener.open(request, timeout=60) as response:
                    raw = response.read(10 * 1024 * 1024 + 1)
                if len(raw) > 10 * 1024 * 1024:
                    raise QuarkError("夸克接口响应异常过大")
                result = json.loads(raw)
                break
            except urllib.error.HTTPError as exc:
                last_error = QuarkError(f"夸克接口返回 HTTP {exc.code}")
                exc.close()
                if exc.code not in (408, 425, 429, 500, 502, 503, 504) or attempt == 2:
                    raise last_error
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                last_error = QuarkError("夸克接口网络请求失败或返回异常")
                if attempt == 2:
                    raise last_error from exc
            time.sleep(attempt + 1)
        else:
            raise last_error or QuarkError("夸克接口请求失败")

        if not isinstance(result, dict):
            raise QuarkError("夸克接口返回格式异常")
        if str(result.get("code")) != "0":
            message = str(result.get("message") or result.get("msg") or "未知错误")
            raise QuarkError(f"夸克接口拒绝请求：{message[:200]}（code={result.get('code')}）")
        return result

    def open(self):
        response = self.api(
            "/share/sharepage/token",
            "POST",
            {"pr": "ucpro", "fr": "pc"},
            {"pwd_id": self.share_id, "passcode": self.passcode},
        )
        data = response.get("data")
        token = data.get("stoken") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise QuarkError("未取得匿名分享令牌；该分享可能要求密码或登录")
        self.stoken = token

    def files(self):
        if not self.stoken:
            self.open()
        queue = collections.deque([("0", "")])
        visited = set()
        result = []
        while queue:
            pdir_fid, parent_path = queue.popleft()
            if pdir_fid in visited:
                continue
            visited.add(pdir_fid)
            if len(visited) > MAX_DIRECTORIES:
                raise QuarkError("分享目录数量异常，已停止遍历")
            for page in range(1, MAX_DIRECTORIES + 1):
                response = self.api(
                    "/share/sharepage/detail",
                    params={
                        "pr": "ucpro", "fr": "pc", "pwd_id": self.share_id,
                        "stoken": self.stoken, "pdir_fid": pdir_fid,
                        "_page": page, "_size": PAGE_SIZE,
                    },
                )
                data = response.get("data")
                items = data.get("list") if isinstance(data, dict) else None
                if not isinstance(items, list):
                    raise QuarkError("分享文件列表格式异常")
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    name, fid = item.get("file_name"), item.get("fid")
                    if not isinstance(name, str) or not isinstance(fid, str) or not fid:
                        continue
                    remote_path = f"{parent_path}/{name}" if parent_path else name
                    if item.get("dir"):
                        queue.append((fid, remote_path))
                    elif item.get("file"):
                        result.append((item, remote_path))
                if len(items) < PAGE_SIZE:
                    break
        return result

    def fresh_download_url(self, item):
        fid, token = item.get("fid"), item.get("share_fid_token")
        if not isinstance(fid, str) or not isinstance(token, str) or not token:
            raise QuarkError("目标文件缺少匿名下载令牌")
        response = self.api(
            "/file/share/download",
            "POST",
            {"pr": "ucpro", "fr": "pc"},
            {"fids": [fid], "pwd_id": self.share_id, "stoken": self.stoken, "fids_token": [token]},
        )
        data = response.get("data")
        selected = next((x for x in data if isinstance(x, dict) and x.get("fid") == fid), None) if isinstance(data, list) else None
        url = selected.get("download_url") if selected else None
        parsed = urllib.parse.urlsplit(url or "")
        hostname = (parsed.hostname or "").lower()
        if not isinstance(url, str) or parsed.scheme != "https" or not (hostname == "quark.cn" or hostname.endswith(".quark.cn")):
            raise QuarkError("夸克没有返回可信的匿名下载直链")
        return url

    def download(self, item, destination):
        size = int(item.get("size", -1))
        if size < 0:
            raise QuarkError("目标文件大小字段异常")
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            raise QuarkError(f"拒绝覆盖非普通文件：{destination}")
        if destination.is_file():
            if destination.stat().st_size == size:
                return False, sha256_file(destination)
            raise QuarkError(f"同名文件大小不符，不覆盖：{destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        part = None
        try:
            descriptor, part_name = tempfile.mkstemp(prefix="." + destination.name + ".", suffix=".part", dir=destination.parent)
            os.close(descriptor)
            part = Path(part_name)
            offset, direct_url = 0, self.fresh_download_url(item)
            while offset < size:
                last_error = None
                for attempt in range(3):
                    chunk = part.with_name(part.name + ".chunk")
                    chunk.unlink(missing_ok=True)
                    headers = {
                        "User-Agent": USER_AGENT, "Accept": "*/*",
                        "Accept-Encoding": "identity", "Referer": "https://pan.quark.cn/",
                        "Range": f"bytes={offset}-{size - 1}",
                    }
                    try:
                        with self.opener.open(urllib.request.Request(direct_url, headers=headers), timeout=180) as response, chunk.open("wb") as output:
                            status, content_range, copied = response.getcode(), response.headers.get("Content-Range"), 0
                            while True:
                                block = response.read(1024 * 1024)
                                if not block:
                                    break
                                output.write(block)
                                copied += len(block)
                            output.flush()
                            os.fsync(output.fileno())
                        if status == 200:
                            if offset != 0 or copied != size:
                                raise QuarkError("服务器忽略 Range 且未返回完整文件")
                            os.replace(chunk, part)
                            offset = size
                            break
                        match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", (content_range or "").strip(), flags=re.I)
                        if status != 206 or not match:
                            raise QuarkError(f"下载分段响应异常：HTTP {status}")
                        begin, end, total = int(match.group(1)), int(match.group(2)), match.group(3)
                        if begin != offset or end < begin or (total != "*" and int(total) != size) or copied != end - begin + 1:
                            raise QuarkError("下载分段校验失败")
                        with part.open("ab") as output, chunk.open("rb") as source:
                            shutil.copyfileobj(source, output, length=1024 * 1024)
                            output.flush()
                            os.fsync(output.fileno())
                        chunk.unlink()
                        offset = end + 1
                        break
                    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, QuarkError) as exc:
                        last_error = exc
                        chunk.unlink(missing_ok=True)
                        if attempt < 2:
                            time.sleep(attempt + 1)
                            direct_url = self.fresh_download_url(item)
                else:
                    raise QuarkError(f"下载失败：{last_error}")
            if part.stat().st_size != size:
                raise QuarkError("最终文件大小校验失败")
            digest = sha256_file(part)
            os.chmod(part, 0o644)
            os.replace(part, destination)
            part = None
            return True, digest
        finally:
            if part is not None and part.exists():
                part.unlink()


def safe_destination(output_dir, remote_path, item, incremental):
    relative = PurePosixPath(remote_path)
    if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
        raise QuarkError(f"不安全的远端路径：{remote_path!r}")
    filename = relative.name
    if incremental:
        stamp = timestamp_ms(item)
        if not stamp:
            raise QuarkError("远端没有 updated_at，不能创建增量文件名")
        date_tag = datetime.fromtimestamp(stamp / 1000, timezone(timedelta(hours=8))).strftime("%Y-%m-%d_%H-%M-%S")
        name_path = Path(filename)
        filename = f"{name_path.stem}_{date_tag}{name_path.suffix}"
    return output_dir.joinpath(*relative.parts[:-1], filename)


def print_files(files, as_json):
    if as_json:
        data = [{"path": path, "size": int(item.get("size", 0)), "updated_at": timestamp_text(item)} for item, path in files]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    for item, path in files:
        print(f"{path}\t{int(item.get('size', 0))}\t{timestamp_text(item)}")
    print(f"共 {len(files)} 个文件")


def select_files(files, args):
    if args.all:
        return files
    if args.name:
        matches = [(item, path) for item, path in files if item.get("file_name") == args.name or path == args.name]
    else:
        matches = [(item, path) for item, path in files if args.contains in item.get("file_name", "") or args.contains in path]
    if not matches:
        raise QuarkError("没有匹配的文件")
    if len(matches) == 1:
        return matches
    if args.latest:
        return [max(matches, key=lambda pair: timestamp_ms(pair[0]))]
    print_files(matches, False)
    raise QuarkError("匹配多个文件；改用 --name 精确选择，或明确使用 --latest / --all")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command in ("list", "download"):
        child = subcommands.add_parser(command)
        child.add_argument("share_url")
        child.add_argument("--passcode", default="", help="公开分享提取码；不是账号密码")
    list_parser = subcommands.choices["list"]
    list_parser.add_argument("--json", action="store_true")
    download_parser = subcommands.choices["download"]
    selection = download_parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--name", help="精确文件名或完整远端相对路径")
    selection.add_argument("--contains", help="文件名或路径包含的文本")
    selection.add_argument("--all", action="store_true", help="下载全部匿名可下载文件")
    download_parser.add_argument("--latest", action="store_true", help="多个匹配时仅选 updated_at 最新者")
    download_parser.add_argument("--incremental", action="store_true", help="在文件名追加网盘 updated_at 日期时间")
    download_parser.add_argument("--output-dir", default=".", help="输出目录，默认当前目录")
    args = parser.parse_args()

    try:
        share = QuarkPublicShare(args.share_url, args.passcode)
        files = share.files()
        if args.command == "list":
            print_files(files, args.json)
            return
        selected = select_files(files, args)
        output_dir = Path(args.output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        failures = []
        for item, remote_path in selected:
            try:
                destination = safe_destination(output_dir, remote_path, item, args.incremental)
                downloaded, digest = share.download(item, destination)
                status = "已下载" if downloaded else "已存在，跳过"
                print(f"{status}：{destination}\n  网盘路径：{remote_path}\n  大小：{item.get('size')}\n  SHA-256：{digest}")
            except QuarkError as exc:
                failures.append(f"{remote_path}: {exc}")
                print(f"失败：{remote_path}：{exc}", file=sys.stderr)
        if failures:
            raise QuarkError(f"{len(failures)} 个文件未能匿名下载")
    except QuarkError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
