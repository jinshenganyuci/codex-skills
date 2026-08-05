---
name: quark-anonymous-download
description: List and download files from public pan.quark.cn share links without logging in or using account cookies. Use when a user provides a Quark share URL and asks to inspect its files, anonymously download a named file, download eligible files, retry a temporary direct link, or keep date-stamped incremental versions. Do not use to bypass files that Quark requires a login or transfer to download.
---

# Quark Anonymous Download

Use `scripts/quark_anonymous_download.py`. It uses only Python 3 standard
library modules, an in-memory anonymous cookie jar, and Quark's public-share
endpoints. Never add account cookies, browser profiles, saved credentials, or
login steps.

## Workflow

1. List before downloading unless the requested file name is exact and
   unambiguous:

   ```bash
   python3 scripts/quark_anonymous_download.py list 'https://pan.quark.cn/s/SHARE_ID'
   ```

2. Download one exact file, a uniquely matching name fragment, or all files:

   ```bash
   python3 scripts/quark_anonymous_download.py download URL --name 'exact-file.zip' --output-dir OUTPUT
   python3 scripts/quark_anonymous_download.py download URL --contains '关键词' --output-dir OUTPUT
   python3 scripts/quark_anonymous_download.py download URL --all --output-dir OUTPUT
   ```

   If `--contains` matches several files, stop and use the listed path with
   `--name`, or pass `--latest` only when the user explicitly wants the newest
   `updated_at` version.

3. Add `--incremental` when the user wants version history. It appends the
   remote `updated_at` timestamp in Beijing time, preserves older files, and
   skips an existing matching dated file.

4. Report each completed file with its remote path, byte size, and SHA-256.
   Do not extract, execute, install, or inspect executable payloads unless the
   user separately asks.

## Limits and failures

- Reissue a fresh temporary direct URL when a request fails with HTTP 412,
  then use a `Range` request with `Referer: https://pan.quark.cn/`.
- Treat API errors such as `download file size limit`, `require login`, or a
  missing direct URL as a server-side anonymous-download restriction. Report
  the affected files; do not claim success and do not attempt a login bypass.
- The script validates response ranges, final byte size, SHA-256, and writes
  with a temporary file followed by atomic replacement.
- Share IDs, file IDs, tokens, direct URLs, timestamps, availability, and
  hashes are remote and time-specific. Obtain them anew for every share.
