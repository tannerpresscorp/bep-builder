#!/usr/bin/env python3
"""APS Model Properties API helpers.

Implements the same core flows documented in
https://github.com/autodesk-platform-services/aps-model-properties.powershell:
- get folder contents (for model URNs)
- create/poll model-properties indexes
- create/poll index queries
- download resource URLs returned by APS
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://developer.api.autodesk.com"


class APSAPIError(RuntimeError):
    """Raised when APS returns an HTTP error or invalid payload."""


def _request_json(method, url, token, body=None):
    headers = {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Authorization": f"Bearer {token}",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        raise APSAPIError(f"APS {method} {url} failed: HTTP {e.code}: {text}") from e
    except json.JSONDecodeError as e:
        raise APSAPIError(f"APS {method} {url} returned invalid JSON") from e


def _request_bytes(method, url, token):
    headers = {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        raise APSAPIError(f"APS {method} {url} failed: HTTP {e.code}: {text}") from e


def _is_processing(state):
    return str(state or "").upper() in {"PROCESSING", "INPROGRESS", "PENDING", "RUNNING"}


def _is_finished(state):
    return str(state or "").upper() in {"FINISHED", "COMPLETE", "COMPLETED", "SUCCEEDED", "SUCCESS"}


def _is_failed(state):
    return str(state or "").upper() in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}


def get_folder_contents(project_id, folder_urn, token):
    url = f"{BASE}/data/v1/projects/{project_id}/folders/{folder_urn}/contents"
    return _request_json("GET", url, token)


def create_index(project_id, specification, token):
    url = f"{BASE}/construction/index/v2/projects/{project_id}/indexes:batch-status"
    return _request_json("POST", url, token, specification)


def get_index(project_id, index_id, token):
    url = f"{BASE}/construction/index/v2/projects/{project_id}/indexes/{index_id}"
    return _request_json("GET", url, token)


def create_query(project_id, index_id, query, token):
    url = f"{BASE}/construction/index/v2/projects/{project_id}/indexes/{index_id}/queries"
    return _request_json("POST", url, token, query)


def get_query(project_id, index_id, query_id, token):
    url = f"{BASE}/construction/index/v2/projects/{project_id}/indexes/{index_id}/queries/{query_id}"
    return _request_json("GET", url, token)


def poll_indexes(project_id, indexes, token, poll_seconds=5, max_polls=180):
    """Poll each index until not PROCESSING."""
    out = [dict(x) for x in indexes]
    polls = 0
    while True:
        polls += 1
        if polls > max_polls:
            raise APSAPIError(f"Timed out after {max_polls} polls while waiting for index completion")
        polling = 0
        for i, idx in enumerate(out):
            state = str(idx.get("state", "")).upper()
            if _is_processing(state):
                index_id = idx.get("indexId")
                if not index_id:
                    raise APSAPIError("Index response is missing 'indexId'")
                out[i] = get_index(project_id, index_id, token)
                polling += 1
        if polling == 0:
            return out
        time.sleep(max(1, int(poll_seconds)))


def poll_query(project_id, index_id, query_status, token, poll_seconds=5, max_polls=180):
    """Poll one query until not PROCESSING."""
    out = dict(query_status)
    polls = 0
    while _is_processing(out.get("state")):
        polls += 1
        if polls > max_polls:
            raise APSAPIError(f"Timed out after {max_polls} polls while waiting for query completion")
        query_id = out.get("queryId")
        if not query_id:
            raise APSAPIError("Query response is missing 'queryId'")
        time.sleep(max(1, int(poll_seconds)))
        out = get_query(project_id, index_id, query_id, token)
    return out


def extract_model_urns(folder_contents):
    """Return unique model version URNs from a folder-contents response."""
    urns = []
    seen = set()
    for item in folder_contents.get("data", []) if isinstance(folder_contents, dict) else []:
        relationships = item.get("relationships", {}) if isinstance(item, dict) else {}
        target = relationships.get("tip", {}).get("data", {})
        urn = target.get("id")
        if urn and isinstance(urn, str) and urn.startswith("urn:adsk.wipprod:fs.file:vf.") and urn not in seen:
            seen.add(urn)
            urns.append(urn)
    return urns


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def download_resource(url, token, out_path):
    content = _request_bytes("GET", url, token)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(content)


def ensure_json_from_arg(json_text, json_file, label):
    if bool(json_text) == bool(json_file):
        raise APSAPIError(f"Provide exactly one of --{label}-json or --{label}-file")
    if json_file:
        with open(json_file, encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(json_text)


def basename_from_url(url, fallback):
    path = urllib.parse.urlparse(url).path
    name = path.rsplit("/", 1)[-1] if path else ""
    return name or fallback


def is_finished(state):
    return _is_finished(state)


def is_failed(state):
    return _is_failed(state)
