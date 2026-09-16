"""Authentication and authorization utilities for Bitmod.

Provides:
- API key generation and validation
- JWT token creation and verification
- FastAPI dependency for auth middleware

AUTH IS ON BY DEFAULT. BITMOD_AUTH_ENABLED defaults to "true", so a deployment
that sets nothing at all still rejects unauthenticated requests with 401. This
paragraph previously read "usage is optional / enable auth by setting
BITMOD_AUTH_ENABLED=1", which said the reverse and was acted on downstream.

    BITMOD_AUTH_ENABLED=0                      turn auth OFF (explicit opt-out)
    BITMOD_JWT_SECRET=<random-256-bit-secret>  required for JWT verification
    BITMOD_API_KEYS=key1,key2,key3             accepted as `Authorization: ApiKey <key>`

The other functions here do handle missing configuration without raising —
that part was true and is why the wrong sentence was plausible. Tolerating an
absent secret is not the same as defaulting to open.

Or generate keys programmatically:

    from bitmod.auth import generate_api_key, create_jwt_token

    key = generate_api_key(prefix="bm")
    token = create_jwt_token(subject="user-123", scopes=["read", "write"])
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from bitmod.metrics import record_security_event
from bitmod.observability import log_security_event

# Import FastAPI types at module level so annotation resolution works
# with ``from __future__ import annotations`` in FastAPI dependencies.
try:
    from fastapi import HTTPException, Request, Security
    from fastapi.security import APIKeyHeader
except ImportError:  # pragma: no cover
    pass

logger = logging.getLogger(__name__)

# Optional audit logger — set via init_audit_logger() when a DB backend is available.
_audit_logger = None

# Optional revocation backend — set via init_revocation_backend() for DB persistence.
_revocation_backend = None


def init_audit_logger(backend) -> None:  # noqa: ANN001
    """Initialise the module-level audit logger with a database backend."""
    global _audit_logger
    from bitmod.audit import AuditLogger

    _audit_logger = AuditLogger(backend)


def init_revocation_backend(backend) -> None:  # noqa: ANN001
    """Initialise the module-level revocation backend for DB-persisted token revocation.

    The backend should implement:
        - store_revoked_token(session, jti, expires_at)
        - is_token_revoked(session, jti) -> bool
        - cleanup_expired_revocations(session)

    If any method is missing, that operation is silently skipped.
    """
    global _revocation_backend
    _revocation_backend = backend


def _audit(event_type: str, **kwargs) -> None:  # noqa: ANN003
    """Fire an audit event if the audit logger is initialised."""
    if _audit_logger is not None:
        _audit_logger.log_event(event_type, **kwargs)


# ---------------------------------------------------------------------------
# Configuration (from environment)
# ---------------------------------------------------------------------------

# Default "true": unset means ENFORCED, not open. Anything other than
# 1/true/yes turns auth off, so opting out has to be deliberate.
_AUTH_ENABLED = os.getenv("BITMOD_AUTH_ENABLED", "true").lower() in ("1", "true", "yes")
_JWT_SECRET = os.getenv("BITMOD_JWT_SECRET", "")
_JWT_ALGORITHM = os.getenv("BITMOD_JWT_ALGORITHM", "HS256").upper()
_JWT_EXPIRY_SECONDS = int(os.getenv("BITMOD_JWT_EXPIRY_SECONDS", "3600"))  # 1 hour default
_API_KEYS_RAW = os.getenv("BITMOD_API_KEYS", "")

# ---------------------------------------------------------------------------
# RS256 asymmetric key support
# ---------------------------------------------------------------------------
_JWT_PRIVATE_KEY: bytes | None = None
_JWT_PUBLIC_KEY: bytes | None = None

if _JWT_ALGORITHM not in ("HS256", "RS256"):
    logger.critical("BITMOD_JWT_ALGORITHM must be HS256 or RS256, got '%s'", _JWT_ALGORITHM)
    raise SystemExit(1)


def _resolve_data_dir() -> Path:
    """Return the bitmod data directory, creating it if needed."""
    data_dir = os.getenv("BITMOD_DATA_DIR", "")
    if data_dir:
        p = Path(data_dir)
    else:
        p = Path.home() / ".bitmod"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_rsa_keys() -> tuple[bytes | None, bytes | None]:
    """Load RSA key pair from PEM files, auto-generating if absent."""
    priv_path = os.getenv("BITMOD_JWT_PRIVATE_KEY_FILE", "")
    pub_path = os.getenv("BITMOD_JWT_PUBLIC_KEY_FILE", "")

    if priv_path and pub_path:
        try:
            private_key = Path(priv_path).read_bytes()
            public_key = Path(pub_path).read_bytes()
            logger.info("Loaded RS256 key pair from configured PEM files")
            return private_key, public_key
        except FileNotFoundError as exc:
            logger.critical("RS256 key file not found: %s", exc)
            raise SystemExit(1) from exc
        except OSError as exc:
            logger.critical("Failed to read RS256 key file: %s", exc)
            raise SystemExit(1) from exc

    # Auto-generate a key pair into the data directory
    data_dir = _resolve_data_dir()
    auto_priv = data_dir / "jwt_rs256_private.pem"
    auto_pub = data_dir / "jwt_rs256_public.pem"

    if auto_priv.exists() and auto_pub.exists():
        logger.info("Loaded auto-generated RS256 key pair from %s", data_dir)
        return auto_priv.read_bytes(), auto_pub.read_bytes()

    # Generate new RSA 4096-bit key pair
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key_obj = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        priv_pem = private_key_obj.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_pem = private_key_obj.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        auto_priv.write_bytes(priv_pem)
        auto_priv.chmod(0o600)
        auto_pub.write_bytes(pub_pem)
        auto_pub.chmod(0o644)
        logger.info("Auto-generated RS256 key pair in %s", data_dir)
        return priv_pem, pub_pem
    except ImportError:
        logger.critical(
            "RS256 requires the 'cryptography' package for auto-generation. "
            "Install with: pip install cryptography  "
            "Or provide pre-generated PEM files via BITMOD_JWT_PRIVATE_KEY_FILE and BITMOD_JWT_PUBLIC_KEY_FILE."
        )
        raise SystemExit(1)


if _JWT_ALGORITHM == "RS256":
    _JWT_PRIVATE_KEY, _JWT_PUBLIC_KEY = _load_rsa_keys()

# ---------------------------------------------------------------------------
# JWT secret strength validation (module load time) — HS256 only
# ---------------------------------------------------------------------------
if _JWT_ALGORITHM == "HS256" and _AUTH_ENABLED and _JWT_SECRET and len(_JWT_SECRET) < 32:
    logger.critical(
        "BITMOD_JWT_SECRET is too short (%d chars). Minimum 32 characters required for HS256. "
        'Generate with: python -c "import secrets; print(secrets.token_hex(32))"',
        len(_JWT_SECRET),
    )
    raise SystemExit(1)

# ---------------------------------------------------------------------------
# JWT Token Revocation (in-memory cache + optional DB persistence)
#
# The in-memory OrderedDict is the fast-path lookup. When a revocation
# backend is initialised via init_revocation_backend(), revocations are
# also persisted to the database so they survive process restarts.
# On cache miss the DB is consulted as a fallback and the result is
# promoted into the in-memory cache.
# ---------------------------------------------------------------------------
_MAX_REVOKED_TOKENS = 10_000
_revoked_tokens: OrderedDict[str, float] = OrderedDict()  # jti -> expiry timestamp
_revoked_lock = threading.Lock()

# Periodic cleanup throttle — avoid O(n) scan on every verify_jwt_token() call
_last_cleanup_time: float = 0.0
_CLEANUP_INTERVAL: float = 60.0  # seconds


def revoke_token(jti: str, expires_at: float | None = None) -> None:
    """Revoke a JWT by its jti (JWT ID).

    Args:
        jti: The JWT ID to revoke.
        expires_at: Unix timestamp when the token expires. If not provided,
            defaults to current time + max JWT lifetime. Revocation entries
            are automatically cleaned up after this time.
    """
    if not jti:
        return
    exp = expires_at if expires_at is not None else time.time() + _JWT_EXPIRY_SECONDS
    with _revoked_lock:
        if jti in _revoked_tokens:
            _revoked_tokens.move_to_end(jti)
            _revoked_tokens[jti] = exp
            return
        while len(_revoked_tokens) >= _MAX_REVOKED_TOKENS:
            _revoked_tokens.popitem(last=False)
        _revoked_tokens[jti] = exp

    # Persist to DB if backend is available.
    if _revocation_backend is not None and hasattr(_revocation_backend, "store_revoked_token"):
        try:
            with _revocation_backend.session() as session:
                _revocation_backend.store_revoked_token(session, jti, exp)
        except Exception:
            # nosemgrep: python-logger-credential-disclosure
            logger.warning("Failed to persist token revocation to DB (jti=%s)", jti[:8])

    _audit("token_revoked", action="revoke_token", outcome="success", resource=jti)


def _is_token_revoked(jti: str) -> bool:
    """Check if a token's jti is in the revocation set.

    Fast path: in-memory cache. Fallback: DB lookup (result promoted to cache).
    """
    if not jti:
        return False
    with _revoked_lock:
        if jti in _revoked_tokens:
            return True

    # Fallback to DB if backend is available.
    if _revocation_backend is not None and hasattr(_revocation_backend, "is_token_revoked"):
        try:
            with _revocation_backend.session() as session:
                if _revocation_backend.is_token_revoked(session, jti):
                    # Promote into in-memory cache so subsequent checks are fast.
                    with _revoked_lock:
                        while len(_revoked_tokens) >= _MAX_REVOKED_TOKENS:
                            _revoked_tokens.popitem(last=False)
                        _revoked_tokens[jti] = time.time() + _JWT_EXPIRY_SECONDS
                    return True
        except Exception:
            # nosemgrep: python-logger-credential-disclosure
            logger.warning("Failed to check token revocation in DB (jti=%s)", jti[:8])

    return False


def _cleanup_expired_revocations() -> None:
    """Remove revocation entries for tokens that have already expired."""
    global _last_cleanup_time
    now = time.time()
    _last_cleanup_time = now
    with _revoked_lock:
        expired = [jti for jti, exp in _revoked_tokens.items() if exp <= now]
        for jti in expired:
            del _revoked_tokens[jti]

    # Also clean DB if backend is available.
    if _revocation_backend is not None and hasattr(_revocation_backend, "cleanup_expired_revocations"):
        try:
            with _revocation_backend.session() as session:
                _revocation_backend.cleanup_expired_revocations(session)
        except Exception:
            logger.warning("Failed to clean expired revocations from DB")


# Store API key hashes with per-key scopes.
# Format: BITMOD_API_KEYS=key1:read,key2:read:write,key3:admin
# Bare keys (no colon-delimited scopes) default to ["read"] (least privilege).
_API_KEY_SCOPE_MAP: dict[str, list[str]] = {}  # hash -> scopes
_API_KEY_HASHES: set[str] = set()  # kept for backwards compat with validate_api_key()
_VALID_SCOPES = {"read", "write", "admin"}

if _API_KEYS_RAW:
    for entry in _API_KEYS_RAW.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        raw_key = parts[0]
        if not raw_key:
            continue
        scopes = [s for s in parts[1:] if s in _VALID_SCOPES]
        if not scopes:
            scopes = ["read"]  # principle of least privilege
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        _API_KEY_HASHES.add(key_hash)
        _API_KEY_SCOPE_MAP[key_hash] = scopes


def _check_jwt_available() -> bool:
    """Check if PyJWT is available."""
    try:
        import jwt  # noqa: F401

        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class AuthUser:
    """Represents an authenticated user/client."""

    subject: str  # User ID, service name, or API key identifier
    scopes: list[str] = field(default_factory=list)
    auth_method: str = ""  # "jwt", "api_key", "none"
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# API Key Management
# ---------------------------------------------------------------------------


def generate_api_key(prefix: str = "bm", length: int = 32) -> str:
    """Generate a cryptographically secure API key.

    Format: {prefix}_{random_hex}
    Example: bm_a1b2c3d4e5f6...

    The caller is responsible for storing the key securely. Only the
    SHA-256 hash should be stored in the database.
    """
    if length < 16:
        raise ValueError("API key length must be at least 16 characters")

    random_part = secrets.token_hex(length)
    prefix = prefix.strip("_")
    return f"{prefix}_{random_part}"


def hash_api_key(key: str) -> str:
    """Hash an API key for secure storage. Use SHA-256."""
    return hashlib.sha256(key.encode()).hexdigest()


def validate_api_key(key: str) -> bool:
    """Validate an API key against the configured key hashes.

    Uses constant-time comparison to prevent timing attacks.
    Always iterates ALL hashes to avoid leaking which key matched via timing.
    """
    if not key or not _API_KEY_HASHES:
        return False

    key_hash = hashlib.sha256(key.encode()).hexdigest()

    # Iterate ALL hashes to prevent timing side-channel that reveals
    # how far into the set the match occurred.
    found = False
    for stored_hash in _API_KEY_HASHES:
        if hmac.compare_digest(key_hash, stored_hash):
            found = True
    return found


def lookup_api_key_scopes(key: str) -> tuple[list[str], str]:
    """Look up the scopes and hash prefix for an env-var API key.

    Returns:
        (scopes, hash_prefix) if found, (["read"], "") if not found.
    """
    if not key or not _API_KEY_SCOPE_MAP:
        return ["read"], ""

    key_hash = hashlib.sha256(key.encode()).hexdigest()

    matched_scopes: list[str] = ["read"]
    matched_prefix = ""
    for stored_hash, scopes in _API_KEY_SCOPE_MAP.items():
        if hmac.compare_digest(key_hash, stored_hash):
            matched_scopes = scopes
            matched_prefix = key_hash[:8]
    return matched_scopes, matched_prefix


def validate_api_key_hash(key: str, stored_hash: str) -> bool:
    """Validate an API key against a specific stored hash.

    For use with database-stored key hashes.
    """
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    return hmac.compare_digest(key_hash, stored_hash)


# ---------------------------------------------------------------------------
# JWT Token Management
# ---------------------------------------------------------------------------


def create_jwt_token(
    subject: str,
    scopes: list[str] | None = None,
    expiry_seconds: int | None = None,
    extra_claims: dict | None = None,
) -> str:
    """Create a signed JWT token.

    Args:
        subject: The token subject (user ID, service name).
        scopes: List of permission scopes (e.g., ["read", "write", "admin"]).
        expiry_seconds: Token lifetime in seconds. Defaults to BITMOD_JWT_EXPIRY_SECONDS.
        extra_claims: Additional claims to include in the token.

    Returns:
        Encoded JWT string.

    Raises:
        RuntimeError: If JWT signing key is not configured.
        ImportError: If PyJWT is not installed.
    """
    try:
        import jwt
    except ImportError:
        raise ImportError("JWT support requires PyJWT. Install: pip install PyJWT")

    if _JWT_ALGORITHM == "RS256":
        if not _JWT_PRIVATE_KEY:
            raise RuntimeError(
                "RS256 private key not configured. Set BITMOD_JWT_PRIVATE_KEY_FILE or allow auto-generation."
            )
        signing_key: str | bytes = _JWT_PRIVATE_KEY
    else:
        if not _JWT_SECRET:
            raise RuntimeError("JWT secret not configured. Set BITMOD_JWT_SECRET environment variable.")
        signing_key = _JWT_SECRET

    now = int(time.time())
    expiry = expiry_seconds if expiry_seconds is not None else _JWT_EXPIRY_SECONDS

    payload: dict = {
        "sub": subject,
        "iat": now,
        "exp": now + expiry,
        "jti": str(uuid.uuid4()),
        "scopes": scopes or [],
    }
    if extra_claims:
        # Prevent overriding core claims
        for reserved in ("sub", "iat", "exp", "jti", "scopes"):
            extra_claims.pop(reserved, None)
        payload.update(extra_claims)

    return jwt.encode(payload, signing_key, algorithm=_JWT_ALGORITHM)  # type: ignore[no-any-return]


def verify_jwt_token(token: str) -> AuthUser | None:
    """Verify and decode a JWT token.

    Returns:
        AuthUser if token is valid, None if invalid, expired, or revoked.
    """
    try:
        import jwt
    except ImportError:
        logger.error("PyJWT not installed -- cannot verify JWT tokens")
        return None

    if _JWT_ALGORITHM == "RS256":
        if not _JWT_PUBLIC_KEY:
            logger.error("RS256 public key not configured")
            return None
        verify_key: str | bytes = _JWT_PUBLIC_KEY
    else:
        if not _JWT_SECRET:
            logger.error("JWT secret not configured")
            return None
        verify_key = _JWT_SECRET

    try:
        payload = jwt.decode(
            token,
            verify_key,
            algorithms=[_JWT_ALGORITHM],
            options={
                "require": ["sub", "exp", "iat"],
                "verify_exp": True,
                "verify_iat": True,
            },
        )

        # Check token revocation
        jti = payload.get("jti", "")
        if jti and _is_token_revoked(jti):
            logger.debug("JWT token revoked (jti=%s)", jti)  # nosemgrep: python-logger-credential-disclosure
            return None

        # Periodic cleanup (every 60s, not per-request)
        if time.time() - _last_cleanup_time > _CLEANUP_INTERVAL:
            _cleanup_expired_revocations()

        return AuthUser(
            subject=payload["sub"],
            scopes=payload.get("scopes", []),
            auth_method="jwt",
            metadata={k: v for k, v in payload.items() if k not in ("sub", "scopes")},
        )
    except jwt.ExpiredSignatureError:
        logger.debug("JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug("Invalid JWT token: %s", type(e).__name__)  # nosemgrep: python-logger-credential-disclosure
        return None


# ---------------------------------------------------------------------------
# FastAPI Auth Dependency
# ---------------------------------------------------------------------------


def require_auth(scopes: list[str] | None = None):
    """FastAPI dependency that requires authentication.

    Usage:
        from bitmod.auth import require_auth

        @app.get("/v1/protected")
        async def protected(user: AuthUser = Depends(require_auth(scopes=["read"]))):
            return {"user": user.subject}

    Checks Authorization header for:
        1. Bearer <jwt_token>
        2. ApiKey <api_key>

    AUTH IS ON WHEN BITMOD_AUTH_ENABLED IS UNSET. The default at the top of
    this module is the string "true", so an unconfigured deployment ENFORCES
    auth and unauthenticated requests get 401. To allow anonymous access the
    variable must be set explicitly to 0, false or no.

    This docstring previously said the opposite — that an unset variable
    allowed all requests — and the claim was believed: the README's "changes
    only its base URL, nothing else" pitch was written against it, and the
    documented API examples are all unauthenticated curl commands that return
    401 against a default deployment.
    """
    api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

    async def _auth_dependency(
        request: Request,
        authorization: str | None = Security(api_key_header),
    ) -> AuthUser:
        source_ip = request.client.host if request.client else "unknown"

        # If auth is disabled, return anonymous user with read-only access
        if not _AUTH_ENABLED:
            return AuthUser(subject="anonymous", scopes=["read"], auth_method="none")

        if not authorization:
            raise HTTPException(
                status_code=401,
                detail="Authentication required.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Try Bearer JWT
        if authorization.startswith("Bearer "):
            token = authorization[7:].strip()
            if not token:
                raise HTTPException(status_code=401, detail="Empty bearer token.")

            user = verify_jwt_token(token)
            if user is None:
                record_security_event("auth_failure")
                log_security_event("auth_failure", method="jwt")
                _audit("auth_failure", action="jwt_verify", outcome="failure", source_ip=source_ip)
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or expired token.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Check scopes
            if scopes:
                missing = set(scopes) - set(user.scopes)
                if missing:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Insufficient permissions. Required scopes: {', '.join(scopes)}",
                    )

            record_security_event("auth_success")
            _audit("auth_success", actor=user.subject, action="jwt_verify", outcome="success", source_ip=source_ip)
            return user

        # Try ApiKey
        if authorization.startswith("ApiKey "):
            key = authorization[7:].strip()
            if not key:
                raise HTTPException(status_code=401, detail="Empty API key.")

            if validate_api_key(key):
                key_scopes, hash_prefix = lookup_api_key_scopes(key)
                subject = f"api_key_{hash_prefix}" if hash_prefix else "api_key_user"
                user = AuthUser(
                    subject=subject,
                    scopes=key_scopes,
                    auth_method="api_key",
                )
                # Check required scopes
                if scopes:
                    missing = set(scopes) - set(user.scopes)
                    if missing:
                        raise HTTPException(
                            status_code=403,
                            detail=f"Insufficient permissions. Required scopes: {', '.join(scopes)}",
                        )
                record_security_event("auth_success")
                _audit("auth_success", actor=subject, action="api_key_verify", outcome="success", source_ip=source_ip)
                return user

            record_security_event("auth_failure")
            log_security_event("auth_failure", method="api_key")
            _audit("auth_failure", action="api_key_verify", outcome="failure", source_ip=source_ip)
            raise HTTPException(status_code=401, detail="Invalid API key.")

        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header. Use 'Bearer <token>' or 'ApiKey <key>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _auth_dependency


def is_auth_enabled() -> bool:
    """Check if authentication is enabled."""
    return _AUTH_ENABLED


# ---------------------------------------------------------------------------
# Database-backed API Key Management
# ---------------------------------------------------------------------------


@dataclass
class APIKeyRecord:
    """A database-stored API key."""

    id: str = ""
    key_hash: str = ""
    key_preview: str = ""  # e.g., "bm_a1b2...x9z0"
    name: str = ""
    scopes: list[str] = field(default_factory=lambda: ["read", "write"])
    owner: str = ""  # subject that created this key
    is_active: bool = True
    created_at: str = ""
    last_used_at: str | None = None
    expires_at: str | None = None
    tier: str = ""
    email: str | None = None


class APIKeyManager:
    """Database-backed API key CRUD operations.

    Works with any DatabaseBackend that has the api_keys table.
    """

    def __init__(self, backend):
        self._backend = backend

    def create_key(
        self,
        name: str,
        owner: str = "system",
        scopes: list[str] | None = None,
        expires_in_days: int | None = None,
        email: str | None = None,
    ) -> tuple[str, APIKeyRecord]:
        """Create a new API key. Returns (plaintext_key, record).

        The plaintext key is only available at creation time. Store it securely.
        """
        from datetime import datetime, timedelta, timezone

        raw_key = generate_api_key(prefix="bm")
        key_hash = hash_api_key(raw_key)
        key_preview = f"{raw_key[:6]}...{raw_key[-4:]}"
        key_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        expires_at = None
        if expires_in_days is not None:
            expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()

        record = APIKeyRecord(
            id=key_id,
            key_hash=key_hash,
            key_preview=key_preview,
            name=name,
            scopes=scopes or ["read", "write"],
            owner=owner,
            is_active=True,
            created_at=now,
            expires_at=expires_at,
            email=email,
        )

        with self._backend.session() as session:
            self._store_key(session, record)

        _audit("key_created", actor=owner, action="create_api_key", outcome="success", resource=key_id)
        return raw_key, record

    def validate_key(self, raw_key: str) -> APIKeyRecord | None:
        """Validate an API key against the database. Returns record if valid."""
        from datetime import datetime, timezone

        key_hash = hash_api_key(raw_key)
        with self._backend.session() as session:
            record = self._lookup_key_by_hash(session, key_hash)
            if record is None:
                return None
            if not record.is_active:
                return None
            if record.expires_at:
                try:
                    exp = datetime.fromisoformat(record.expires_at.replace("Z", "+00:00"))
                    if exp < datetime.now(timezone.utc):
                        return None
                except (ValueError, TypeError):
                    pass
            # Update last_used_at
            self._touch_key(session, record.id)
            return record

    def list_keys(self, owner: str | None = None) -> list[APIKeyRecord]:
        """List all API keys, optionally filtered by owner."""
        with self._backend.session() as session:
            return self._list_keys(session, owner)

    def revoke_key(self, key_id: str) -> bool:
        """Revoke (deactivate) an API key by ID."""
        with self._backend.session() as session:
            result = self._revoke_key(session, key_id)
        if result:
            _audit("key_revoked", action="revoke_api_key", outcome="success", resource=key_id)
        return result

    def _store_key(self, session, record: APIKeyRecord) -> None:
        import json as _json

        self._backend.store_api_key(
            session,
            {
                "id": record.id,
                "key_hash": record.key_hash,
                "key_preview": record.key_preview,
                "name": record.name,
                "scopes": _json.dumps(record.scopes),
                "owner": record.owner,
                "is_active": record.is_active,
                "created_at": record.created_at,
                "expires_at": record.expires_at,
                "email": record.email,
            },
        )

    def _lookup_key_by_hash(self, session, key_hash: str) -> APIKeyRecord | None:
        import json as _json

        row = self._backend.lookup_api_key(session, key_hash)
        if row is None:
            return None
        scopes = row["scopes"]
        if isinstance(scopes, str):
            scopes = _json.loads(scopes)
        return APIKeyRecord(
            id=row["id"],
            key_hash=row["key_hash"],
            key_preview=row["key_preview"],
            name=row["name"],
            scopes=scopes,
            owner=row["owner"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            last_used_at=row.get("last_used_at"),
            expires_at=row.get("expires_at"),
            email=row.get("email"),
        )

    def _touch_key(self, session, key_id: str) -> None:
        self._backend.touch_api_key(session, key_id)

    def _list_keys(self, session, owner: str | None) -> list[APIKeyRecord]:
        import json as _json

        rows = self._backend.list_api_keys(session, owner)
        result = []
        for r in rows:
            scopes = r["scopes"]
            if isinstance(scopes, str):
                scopes = _json.loads(scopes)
            result.append(
                APIKeyRecord(
                    id=r["id"],
                    key_hash=r["key_hash"],
                    key_preview=r["key_preview"],
                    name=r["name"],
                    scopes=scopes,
                    owner=r["owner"],
                    is_active=bool(r["is_active"]),
                    created_at=r["created_at"],
                    last_used_at=r.get("last_used_at"),
                    expires_at=r.get("expires_at"),
                    email=r.get("email"),
                )
            )
        return result

    def _revoke_key(self, session, key_id: str) -> bool:
        return self._backend.revoke_api_key(session, key_id)  # type: ignore[no-any-return]


def require_auth_db(backend=None, scopes: list[str] | None = None):
    """FastAPI dependency with database-backed API key validation.

    Falls back to env-var validation if no backend provided.
    When auth is disabled, allows all requests as anonymous.
    """
    api_key_header = APIKeyHeader(name="Authorization", auto_error=False)
    x_api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
    key_mgr = APIKeyManager(backend) if backend else None

    async def _auth_dependency(
        request: Request,
        authorization: str | None = Security(api_key_header),
        x_api_key: str | None = Security(x_api_key_header),
    ) -> AuthUser:
        source_ip = request.client.host if request.client else "unknown"

        if not _AUTH_ENABLED:
            return AuthUser(subject="anonymous", scopes=["read"], auth_method="none")

        # Check x-api-key header first (Anthropic-style)
        raw_key = None
        if x_api_key:
            raw_key = x_api_key

        if not raw_key and authorization:
            if authorization.startswith("Bearer "):
                token = authorization[7:].strip()
                if token:
                    user = verify_jwt_token(token)
                    if user is None:
                        record_security_event("auth_failure")
                        log_security_event("auth_failure", method="jwt")
                        _audit("auth_failure", action="jwt_verify", outcome="failure", source_ip=source_ip)
                        raise HTTPException(
                            status_code=401,
                            detail="Invalid or expired token.",
                            headers={"WWW-Authenticate": "Bearer"},
                        )
                    if scopes:
                        missing = set(scopes) - set(user.scopes)
                        if missing:
                            raise HTTPException(
                                status_code=403,
                                detail=f"Insufficient permissions. Required: {', '.join(scopes)}",
                            )
                    record_security_event("auth_success")
                    _audit(
                        "auth_success",
                        actor=user.subject,
                        action="jwt_verify",
                        outcome="success",
                        source_ip=source_ip,
                    )
                    return user

            if authorization.startswith("ApiKey "):
                raw_key = authorization[7:].strip()
            elif not authorization.startswith("Bearer "):
                raw_key = authorization.strip()

        if raw_key:
            # Try database first
            if key_mgr:
                record = key_mgr.validate_key(raw_key)
                if record:
                    if scopes:
                        missing = set(scopes) - set(record.scopes)
                        if missing:
                            raise HTTPException(
                                status_code=403,
                                detail=f"Insufficient permissions. Required: {', '.join(scopes)}",
                            )
                    record_security_event("auth_success")
                    _audit(
                        "auth_success",
                        actor=record.owner,
                        action="api_key_verify",
                        outcome="success",
                        source_ip=source_ip,
                    )
                    return AuthUser(
                        subject=record.owner,
                        scopes=record.scopes,
                        auth_method="api_key",
                        metadata={"key_id": record.id, "key_name": record.name},
                    )
            # Fall back to env-var keys
            if validate_api_key(raw_key):
                key_scopes, hash_prefix = lookup_api_key_scopes(raw_key)
                subject = f"api_key_{hash_prefix}" if hash_prefix else "api_key_user"
                user = AuthUser(
                    subject=subject,
                    scopes=key_scopes,
                    auth_method="api_key",
                )
                if scopes:
                    missing = set(scopes) - set(user.scopes)
                    if missing:
                        raise HTTPException(
                            status_code=403,
                            detail=f"Insufficient permissions. Required: {', '.join(scopes)}",
                        )
                record_security_event("auth_success")
                _audit(
                    "auth_success",
                    actor=subject,
                    action="api_key_verify",
                    outcome="success",
                    source_ip=source_ip,
                )
                return user

            record_security_event("auth_failure")
            log_security_event("auth_failure", method="api_key")
            _audit("auth_failure", action="api_key_verify", outcome="failure", source_ip=source_ip)
            raise HTTPException(status_code=401, detail="Invalid API key.")

        if not authorization and not x_api_key:
            raise HTTPException(
                status_code=401,
                detail="Authentication required. Use 'Authorization: Bearer <token>' or 'Authorization: ApiKey <key>'.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _auth_dependency
