from __future__ import annotations

from personal_world.model.contracts import DataAccessProfile, PersonalRecord, RecordKind, SensitivityClass


class AccessDeniedError(PermissionError):
    pass


class AccessController:
    def require_purpose(self, profile: DataAccessProfile | None, purpose: str) -> DataAccessProfile:
        if profile is None:
            raise AccessDeniedError("unknown service identity")
        if not profile.allows_purpose(purpose):
            raise AccessDeniedError(f"purpose {purpose!r} is not allowed for {profile.service_identity!r}")
        return profile

    def permits_record(self, profile: DataAccessProfile, record: PersonalRecord) -> bool:
        return (
            record.kind in profile.allowed_kinds
            and int(record.sensitivity) <= int(profile.max_sensitivity)
            and record.deleted_at is None
        )

    @staticmethod
    def development_profile(service_identity: str = "development") -> DataAccessProfile:
        return DataAccessProfile(
            service_identity=service_identity,
            allowed_purposes=("development",),
            allowed_kinds=(RecordKind.RESOURCE_LINK, RecordKind.PREFERENCE),
            max_sensitivity=SensitivityClass.PERSONAL,
        )
