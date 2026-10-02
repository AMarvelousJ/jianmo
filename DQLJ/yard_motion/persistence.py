"""Checksummed, atomic material snapshots with one previous valid generation."""
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


FORMAT = "dqlj-material-snapshot-v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


class SnapshotStore:
    def __init__(self, path, configuration):
        self.path = Path(path)
        self.backup = self.path.with_name(self.path.name + ".bak")
        self.configuration = configuration
        self.last_valid_bytes = None
        self.status = dict(enabled=True, interval_s=1.0, last_saved_at_utc=None,
                           last_saved_snapshot_seq=None, last_saved_material_version=None,
                           error=None, recovery_required=False, loaded_from=None, recovery_warning=None)

    def load(self, validate):
        failures = []
        for source in (self.path, self.backup):
            if not source.exists():
                continue
            try:
                raw = source.read_bytes()
                envelope = json.loads(raw)
                if not isinstance(envelope, dict) or set(envelope) != {"format", "saved_at_utc", "payload", "sha256"}:
                    raise ValueError("SNAPSHOT_STRUCTURE")
                body = {key: envelope[key] for key in ("format", "saved_at_utc", "payload")}
                if envelope["format"] != FORMAT:
                    raise ValueError("SNAPSHOT_FORMAT")
                if hashlib.sha256(canonical(body)).hexdigest() != envelope["sha256"]:
                    raise ValueError("SNAPSHOT_CHECKSUM")
                if envelope["payload"]["configuration"] != self.configuration:
                    raise ValueError("SNAPSHOT_CONFIGURATION")
                datetime.fromisoformat(envelope["saved_at_utc"])
                validate(envelope["payload"])
                self.last_valid_bytes = raw
                self.status.update(last_saved_at_utc=envelope["saved_at_utc"],
                                   last_saved_snapshot_seq=envelope["payload"]["snapshot_seq"],
                                   last_saved_material_version=envelope["payload"]["material"]["version"],
                                   loaded_from="primary" if source == self.path else "backup",
                                   recovery_warning="; ".join(failures) or ("PRIMARY_MISSING" if source == self.backup else None))
                return envelope["payload"]
            except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
                failures.append(f"{source.name}: {type(error).__name__}: {error}")
                # Keep the source intact and preserve a second copy before any
                # subsequent successful recovery is allowed to replace it.
                try:
                    evidence = source.with_name(source.name + ".rejected-" + uuid.uuid4().hex)
                    evidence.write_bytes(source.read_bytes())
                except OSError as evidence_error:
                    self.status.update(error="; ".join(failures) +
                                       f"; EVIDENCE_PRESERVATION_FAILED: {type(evidence_error).__name__}",
                                       recovery_required=True)
                    return None  # keep the source intact, block replacement
        if failures:
            self.status.update(error="; ".join(failures), recovery_required=True)
        return None

    @staticmethod
    def _atomic_write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def save(self, payload):
        if self.status["recovery_required"]:
            return False  # never overwrite unresolved corrupt/incompatible files
        try:
            body = dict(format=FORMAT, saved_at_utc=datetime.now(timezone.utc).isoformat(), payload=payload)
            data = canonical(dict(body, sha256=hashlib.sha256(canonical(body)).hexdigest()))
            if self.last_valid_bytes is not None:
                self._atomic_write(self.backup, self.last_valid_bytes)
            self._atomic_write(self.path, data)
            self.last_valid_bytes = data
            self.status.update(last_saved_at_utc=body["saved_at_utc"],
                               last_saved_snapshot_seq=payload["snapshot_seq"],
                               last_saved_material_version=payload["material"]["version"], error=None)
            return True
        except (OSError, ValueError, TypeError) as error:
            self.status["error"] = f"SNAPSHOT_SAVE_FAILED: {type(error).__name__}: {error}"
            return False
