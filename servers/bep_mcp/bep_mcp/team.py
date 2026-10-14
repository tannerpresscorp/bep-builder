"""Team mode for bep_mcp: who may use the server (per-user bearer tokens) and which plans each
user may see or change (grants). Design: docs/design/mcp-server.md, "Team server".

The config is a JSON file kept OUTSIDE the plans folder and the repository. It stores only
sha256 hashes of tokens, never the tokens. Make a token and its hash with `bep_mcp --new-token`.

    {"public_url": "https://bep.example.com",
     "allowed_hosts": ["bep.example.com"],
     "allowed_origins": ["https://bep.example.com", "https://claude.ai"],
     "users": {"alice": {"token_sha256": "<64 hex>", "grants": {"*": "editor"}},
               "bob":   {"token_sha256": "<64 hex>",
                         "grants": {"clinic*.json": "viewer", "barracks.json": "editor"}}}}
"""
import fnmatch
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from mcp.server.auth.provider import AccessToken

ROLES = ("viewer", "editor")
_RANK = {None: 0, "viewer": 1, "editor": 2}
_HASH = re.compile(r"[0-9a-fA-F]{64}")


@dataclass(frozen=True)
class User:
    name: str
    token_sha256: str
    grants: dict = field(default_factory=dict)   # file-name pattern -> "viewer" | "editor"


@dataclass(frozen=True)
class TeamConfig:
    public_url: str
    users: dict                                  # user name -> User
    allowed_hosts: tuple = ()
    allowed_origins: tuple = ()


def hash_token(token):
    """The sha256 hex digest a config stores for a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_config(path):
    """Read and check a team config file. Raises ValueError with a message for people."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"team config {path} doesn't exist") from None
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"can't read team config {path}: {e.__class__.__name__}") from None
    except json.JSONDecodeError as e:
        raise ValueError(f"team config {path} isn't valid JSON (line {e.lineno}, column {e.colno}: {e.msg})") from None
    if not isinstance(data, dict):
        raise ValueError("team config must be a JSON object")
    url = data.get("public_url")
    if not isinstance(url, str) or not re.fullmatch(r"https?://[^/\s]+(/\S*)?", url):
        raise ValueError("team config needs 'public_url', e.g. \"https://bep.example.com\"")
    if url.rstrip("/").endswith("/mcp"):
        raise ValueError("team config 'public_url' is the site address without /mcp, "
                         "e.g. \"https://bep.example.com\"; the server adds /mcp")
    lists = {}
    for key in ("allowed_hosts", "allowed_origins"):
        v = data.get(key, [])
        if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
            raise ValueError(f"team config '{key}' must be a list of strings")
        lists[key] = tuple(v)
    raw_users = data.get("users")
    if not isinstance(raw_users, dict) or not raw_users:
        raise ValueError("team config needs at least one entry under 'users'")
    users = {}
    for name, u in raw_users.items():
        if not isinstance(u, dict):
            raise ValueError(f"user '{name}' must be an object with token_sha256 and grants")
        if "token" in u:
            raise ValueError(f"user '{name}' has a plain 'token'; store only 'token_sha256' "
                             "(bep_mcp --new-token prints both)")
        digest = u.get("token_sha256")
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            raise ValueError(f"user '{name}' needs 'token_sha256': 64 hex characters")
        grants = u.get("grants")
        if not isinstance(grants, dict) or not grants:
            raise ValueError(f"user '{name}' needs 'grants', e.g. {{\"*\": \"viewer\"}}")
        for pattern, role in grants.items():
            if role not in ROLES:
                raise ValueError(f"user '{name}': grant '{pattern}' must be \"viewer\" or \"editor\"")
        users[name] = User(name, digest.lower(), {p.lower(): r for p, r in grants.items()})
    hashes = [u.token_sha256 for u in users.values()]
    if len(set(hashes)) != len(hashes):
        raise ValueError("two users share the same token_sha256; give each user their own token")
    return TeamConfig(url.rstrip("/"), users, lists["allowed_hosts"], lists["allowed_origins"])


def role_for(config, user, plan):
    """None, "viewer" or "editor": the highest grant of `user` that matches the file name
    `plan` (case-insensitive fnmatch). Depends only on the name and the grants, never on
    whether the file exists."""
    u = config.users.get(user)
    if u is None:
        return None
    name = plan.lower()
    best = None
    for pattern, role in u.grants.items():
        if fnmatch.fnmatchcase(name, pattern) and _RANK[role] > _RANK[best]:
            best = role
    return best


def effective_role(config, user, plans_dir, plan):
    """role_for(plan), lowered to role_for(the file's real name) when `plan` is a link to
    another file in the folder, so a link can't reach a plan its owner has no grant on. A link
    that leaves the plans folder gets no role."""
    role = role_for(config, user, plan)
    if role is None:
        return None
    root = Path(os.path.realpath(plans_dir))
    real = Path(os.path.realpath(root / plan))
    if real.parent != root:
        return None
    other = role_for(config, user, real.name)
    return role if _RANK[role] <= _RANK[other] else other


def config_inside(config_path, plans_dir):
    """True when the config file is in the plans folder (or below it), where the tools could
    read and change it."""
    cfg, root = os.path.realpath(config_path), os.path.realpath(plans_dir)
    try:
        return os.path.commonpath([cfg, root]) == root
    except ValueError:      # different drives on Windows
        return False


class TeamTokenVerifier:
    """Maps a bearer token to its user. Compares the token's hash with every user's hash
    (no early exit) using hmac.compare_digest. Never raises and never logs a token."""

    def __init__(self, config):
        self._users = [(u.name, u.token_sha256) for u in config.users.values()]

    async def verify_token(self, token):
        try:
            digest = hash_token(token)
            found = None
            for name, stored in self._users:
                if hmac.compare_digest(digest, stored):
                    found = name
            if found is None:
                return None
            return AccessToken(token=token, client_id=found, scopes=["bep"], expires_at=None,
                               subject=found)
        except Exception:
            return None
