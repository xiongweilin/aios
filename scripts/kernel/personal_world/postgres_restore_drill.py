from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import UUID, uuid4

from personal_world.model.contracts import (
    DataAccessProfile,
    ErasureRequest,
    PersonalFactCreate,
    RecordKind,
    RevisionRequest,
    SemanticRef,
    SensitivityClass,
    SourceClass,
    SourceDescriptorCreate,
)
from personal_world.persistence import SqlAlchemyPersonalWorldStore, create_database_engine
from personal_world.service import PersonalWorldService


def service_for(url: str) -> PersonalWorldService:
    return PersonalWorldService(SqlAlchemyPersonalWorldStore(create_database_engine(url)))


def seed(url: str, manifest_path: Path) -> None:
    service = service_for(url)
    service.put_access_profile(
        DataAccessProfile(
            service_identity="administrative-orchestrator",
            allowed_purposes=("*",),
            allowed_kinds=tuple(RecordKind),
            max_sensitivity=SensitivityClass.HIGHLY_SENSITIVE,
        )
    )
    source = service.create_source(
        SourceDescriptorCreate(
            source_class=SourceClass.HUMAN_EXPLICIT,
            actor_ref="human:self",
            description="physical restore drill",
        )
    )
    subject = uuid4()
    first = service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="restore-drill-city", namespace="personal"),
            value="Tokyo",
            source_refs=(source.id,),
        )
    )
    second = service.revise(
        first.id,
        RevisionRequest(
            expected_revision=1,
            value="Osaka",
            source_refs=(source.id,),
            qualification_reason="restore-drill-correction",
        ),
    )
    service.current_for_subject(
        subject,
        service_identity="administrative-orchestrator",
        purpose="backup-drill",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "subject_id": str(subject),
                "lineage_id": str(first.lineage_id),
                "current_id": str(second.id),
                "history_values": ["Tokyo", "Osaka"],
                "service_identity": "administrative-orchestrator",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def verify(url: str, manifest_path: Path) -> None:
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    service = service_for(url)
    subject = UUID(expected["subject_id"])
    lineage = UUID(expected["lineage_id"])

    current = service.store.current_record(lineage)
    history = service.store.history(subject)
    profile = service.store.get_access_profile(expected["service_identity"])
    disclosures = service.list_disclosures(subject)

    if str(current.id) != expected["current_id"]:
        raise SystemExit("restored current record id does not match backup")
    if [record.value for record in history] != expected["history_values"]:
        raise SystemExit("restored lineage history does not match backup")
    if profile is None or "*" not in profile.allowed_purposes:
        raise SystemExit("restored access profile is missing")
    if not disclosures or disclosures[-1].action != "current":
        raise SystemExit("restored disclosure audit is missing")


def erase(url: str, manifest_path: Path, erasure_path: Path) -> None:
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    subject = UUID(expected["subject_id"])
    service = service_for(url)
    result = service.erase(
        ErasureRequest(
            subject_id=subject,
            reason="restore-drill-post-backup-erasure",
        )
    )
    erasure_path.write_text(
        json.dumps(
            {
                "subject_id": str(subject),
                "reason": "restore-drill-post-backup-erasure",
                "completed_at": result.completed_at.isoformat(),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def replay_erasure(url: str, erasure_path: Path) -> None:
    obligation = json.loads(erasure_path.read_text(encoding="utf-8"))
    service = service_for(url)
    service.erase(
        ErasureRequest(
            subject_id=UUID(obligation["subject_id"]),
            reason=f"replay:{obligation['reason']}",
        )
    )


def verify_erased(url: str, manifest_path: Path) -> None:
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    service = service_for(url)
    subject = UUID(expected["subject_id"])
    if service.store.list_records(subject):
        raise SystemExit("post-restore erasure replay left current records")
    if service.store.history(subject):
        raise SystemExit("post-restore erasure replay left history")
    serialized = service.export_bundle().model_dump_json()
    for value in expected["history_values"]:
        if value in serialized:
            raise SystemExit("post-restore erasure replay leaked erased content")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=("seed", "verify", "erase", "replay-erasure", "verify-erased"),
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--erasure", type=Path)
    args = parser.parse_args()

    if args.mode in {"seed", "verify", "erase", "verify-erased"} and args.manifest is None:
        parser.error("--manifest is required for this mode")
    if args.mode in {"erase", "replay-erasure"} and args.erasure is None:
        parser.error("--erasure is required for this mode")

    if args.mode == "seed":
        seed(args.url, args.manifest)
    elif args.mode == "verify":
        verify(args.url, args.manifest)
    elif args.mode == "erase":
        erase(args.url, args.manifest, args.erasure)
    elif args.mode == "replay-erasure":
        replay_erasure(args.url, args.erasure)
    else:
        verify_erased(args.url, args.manifest)


if __name__ == "__main__":
    main()
