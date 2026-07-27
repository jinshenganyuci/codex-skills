#!/usr/bin/env python3
"""Fetch a JSON control document and list URL-bearing fields without downloading payloads."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlsplit, urlunsplit


URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
DOTTED_VERSION_RE = re.compile(
    r'(^\s*"[^"\r\n]+"\s*:\s*)(-?\d+(?:\.\d+){2,})(\s*[,}])',
    re.MULTILINE,
)


def encode_url(url: str) -> str:
    """Return an ASCII URL suitable for urllib while preserving URL semantics."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"unsupported or malformed URL: {url}")
    try:
        hostname = (parsed.hostname or "").encode("idna").decode("ascii")
        port = parsed.port
    except (UnicodeError, ValueError) as exc:
        raise ValueError(f"invalid URL authority: {url}") from exc
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    userinfo = ""
    if parsed.username is not None:
        userinfo = quote(parsed.username, safe="")
        if parsed.password is not None:
            userinfo += ":" + quote(parsed.password, safe="")
        userinfo += "@"
    netloc = userinfo + hostname + (f":{port}" if port is not None else "")
    path = quote(parsed.path, safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="=&?/%:@!$'()*+,;~-._")
    fragment = quote(parsed.fragment, safe="=&?/%:@!$'()*+,;~-._")
    return urlunsplit((parsed.scheme, netloc, path, query, fragment))


def request(
    url: str, method: str, timeout: float, max_bytes: int
) -> tuple[bytes, dict[str, str], str, int | None]:
    encoded_url = encode_url(url)
    req = urllib.request.Request(
        encoded_url,
        method=method,
        headers={"User-Agent": "Codex-Xiongda-Static-Analyzer/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        headers = {key.lower(): value for key, value in response.headers.items()}
        final_url = response.geturl()
        status = getattr(response, "status", None)
        if method == "HEAD":
            return b"", headers, final_url, status
        length = response.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            raise ValueError(f"response Content-Length exceeds {max_bytes} bytes")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(f"response exceeds {max_bytes} bytes")
        return data, headers, final_url, status


def walk(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")
    else:
        yield path, value


def extract_urls(document: Any) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for path, value in walk(document):
        if not isinstance(value, str):
            continue
        for match in URL_RE.finditer(value):
            records.append({"json_path": path, "url": match.group().rstrip(".,;:!?)")})
    return records


def parse_document(data: bytes) -> tuple[Any, str, list[dict[str, str]]]:
    text = data.decode("utf-8-sig")
    try:
        return json.loads(text), "strict_json", []
    except json.JSONDecodeError as original_error:
        repairs: list[dict[str, str]] = []

        def quote_version(match: re.Match[str]) -> str:
            value = match.group(2)
            repairs.append({
                "kind": "quote_invalid_dotted_numeric_version",
                "value": value,
            })
            return f'{match.group(1)}"{value}"{match.group(3)}'

        repaired = DOTTED_VERSION_RE.sub(quote_version, text)
        if not repairs:
            raise original_error
        try:
            return json.loads(repaired), "repaired_json", repairs
        except json.JSONDecodeError:
            raise original_error


def safe_headers(headers: dict[str, str]) -> dict[str, str]:
    allowed = {
        "content-type", "content-length", "content-disposition", "last-modified",
        "etag", "location", "server", "cache-control",
    }

    def normalize(value: str) -> str:
        try:
            return value.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return value

    return {key: normalize(value) for key, value in headers.items() if key in allowed}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect a remote JSON control document and its URL fields."
    )
    parser.add_argument("url")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-bytes", type=int, default=4 * 1024 * 1024)
    parser.add_argument(
        "--probe-links",
        action="store_true",
        help="Send HEAD requests to discovered URLs; do not download their bodies.",
    )
    parser.add_argument("--output", type=Path, help="Write JSON report.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        data, headers, final_url, status = request(
            args.url, "GET", args.timeout, args.max_bytes
        )
        document, parse_mode, repairs = parse_document(data)
        urls = extract_urls(document)
        report: dict[str, Any] = {
            "requested_url": args.url,
            "requested_url_encoded": encode_url(args.url),
            "final_url": final_url,
            "status": status,
            "retrieved_at": datetime.now().astimezone().isoformat(),
            "json_parse_mode": parse_mode,
            "json_repairs": repairs,
            "response_headers": safe_headers(headers),
            "document": document,
            "url_fields": urls,
            "link_probes": [],
        }
        if args.probe_links:
            for record in urls:
                try:
                    _, link_headers, link_final, link_status = request(
                        record["url"], "HEAD", args.timeout, args.max_bytes
                    )
                    report["link_probes"].append({
                        **record, "ok": True, "final_url": link_final,
                        "status": link_status,
                        "headers": safe_headers(link_headers),
                    })
                except (OSError, ValueError, urllib.error.URLError) as exc:
                    report["link_probes"].append({
                        **record, "ok": False, "error": str(exc),
                    })
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError, urllib.error.URLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
