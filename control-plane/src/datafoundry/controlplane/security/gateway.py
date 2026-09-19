"""Security gateway abstraction (feature 005, T003).

The security engine never talks to a cloud SDK directly — it goes through a
gateway. :class:`SimulatedSecurityGateway` provides in-memory fake KMS, token
vault, protection engine, and source-encryption fixtures with fault-injection
hooks so every classification/protection/tokenisation/key/access/audit path is
exercisable offline (no docker/terraform/database). Live adapters (AWS KMS /
GCP Cloud KMS) are added later.
"""

from __future__ import annotations

import abc
import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet


@dataclass
class KeyMaterial:
    """One key version's material (in-memory only; never persisted)."""

    key_ref_id: str
    version: int
    lifecycle_state: str  # active | revoked
    fernet: Fernet


class SecurityGateway(abc.ABC):
    """Operations the security engine needs to protect/decrypt/tokenise."""

    @abc.abstractmethod
    def encrypt(self, *, key_ref_id: str, version: int, value: str) -> str:
        """Encrypt a value with a key version (FR-008)."""

    @abc.abstractmethod
    def decrypt(self, *, key_ref_id: str, version: int, ciphertext: str) -> str:
        """Decrypt a value; raises on revoked key (FR-008)."""

    @abc.abstractmethod
    def tokenise(self, *, value: str, deterministic: bool) -> str:
        """Tokenise a value (deterministic or random, FR-011)."""

    @abc.abstractmethod
    def detokenise(self, *, token: str) -> str:
        """Detokenise a token back to its original value (FR-012)."""


class SimulatedSecurityGateway(SecurityGateway):
    """In-memory security inventory (dev mode / tests)."""

    def __init__(self) -> None:
        self._keys: dict[str, dict[int, KeyMaterial]] = {}
        self._token_vault: dict[str, str] = {}  # token -> original
        self._faults: set[str] = set()  # test hooks

    # -- test hooks ---------------------------------------------------------

    def force_kms_unavailable(self) -> None:
        """Make KMS operations raise (fail-closed, FR-019)."""
        self._faults.add("kms_unavailable")

    def force_token_vault_unavailable(self) -> None:
        """Make token vault operations raise (fail-closed, FR-019)."""
        self._faults.add("token_vault_unavailable")

    def force_verification_failure(self) -> None:
        """Make source-encryption verification fail (FR-006)."""
        self._faults.add("verification_failure")

    def clear_faults(self) -> None:
        self._faults.clear()

    # -- key management -----------------------------------------------------

    def create_key(self, key_ref_id: str, version: int = 1) -> None:
        """Create a key reference with material (in-memory)."""
        self._keys.setdefault(key_ref_id, {})[version] = KeyMaterial(
            key_ref_id=key_ref_id,
            version=version,
            lifecycle_state="active",
            fernet=Fernet(Fernet.generate_key()),
        )

    def rotate_key(self, key_ref_id: str) -> int:
        """Rotate to a new version; prior versions stay readable (FR-009)."""
        versions = self._keys.get(key_ref_id, {})
        if not versions:
            raise KeyError(f"no key {key_ref_id}")
        new_version = max(versions) + 1
        versions[new_version] = KeyMaterial(
            key_ref_id=key_ref_id,
            version=new_version,
            lifecycle_state="active",
            fernet=Fernet(Fernet.generate_key()),
        )
        return new_version

    def revoke_key(self, key_ref_id: str) -> None:
        """Revoke the current version; blocks further decryption (FR-008)."""
        versions = self._keys.get(key_ref_id, {})
        if not versions:
            raise KeyError(f"no key {key_ref_id}")
        current = max(versions)
        versions[current].lifecycle_state = "revoked"

    def key_version(self, key_ref_id: str) -> int:
        versions = self._keys.get(key_ref_id, {})
        if not versions:
            raise KeyError(f"no key {key_ref_id}")
        return max(versions)

    # -- SecurityGateway ------------------------------------------------------

    def encrypt(self, *, key_ref_id: str, version: int, value: str) -> str:
        if "kms_unavailable" in self._faults:
            raise RuntimeError("simulated KMS unavailable (FR-019)")
        material = self._keys.get(key_ref_id, {}).get(version)
        if material is None:
            raise KeyError(f"no key version {key_ref_id}:{version}")
        return material.fernet.encrypt(value.encode()).decode()

    def decrypt(self, *, key_ref_id: str, version: int, ciphertext: str) -> str:
        if "kms_unavailable" in self._faults:
            raise RuntimeError("simulated KMS unavailable (FR-019)")
        material = self._keys.get(key_ref_id, {}).get(version)
        if material is None:
            raise KeyError(f"no key version {key_ref_id}:{version}")
        if material.lifecycle_state == "revoked":
            raise RuntimeError(f"key {key_ref_id}:{version} revoked (FR-008)")
        return material.fernet.decrypt(ciphertext.encode()).decode()

    def tokenise(self, *, value: str, deterministic: bool) -> str:
        if "token_vault_unavailable" in self._faults:
            raise RuntimeError("simulated token vault unavailable (FR-019)")
        if deterministic:
            digest = hashlib.sha256(value.encode()).hexdigest()[:12]
            token = f"tok_{digest}"
            self._token_vault[token] = value
            return token
        token = f"tok_{uuid.uuid4().hex[:12]}"
        self._token_vault[token] = value
        return token

    def detokenise(self, *, token: str) -> str:
        if "token_vault_unavailable" in self._faults:
            raise RuntimeError("simulated token vault unavailable (FR-019)")
        if token not in self._token_vault:
            raise KeyError(f"no token {token}")
        return self._token_vault[token]


def build_security_gateway(settings: Any) -> SecurityGateway:
    """Build the security gateway for the app (simulated in dev/tests).

    MVP uses the in-memory :class:`SimulatedSecurityGateway` so every
    classification/protection/tokenisation/key/access/audit path is
    exercisable offline. Live KMS adapters are added later.
    """
    return SimulatedSecurityGateway()
