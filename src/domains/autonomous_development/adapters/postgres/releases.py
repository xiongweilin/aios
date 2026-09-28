from __future__ import annotations

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.exc import IntegrityError

from autonomous_development.domain.models import ReleasedVersion
from autonomous_development.ports.persistence import (
    OperationConflictError,
    ReleasedVersionRepository,
    ServingReleaseReceipt,
)

from .records import insert_once, load_one, record_from_row, record_values
from .schema import (
    released_versions,
    serving_release_operations,
    serving_releases,
)


class SqlReleasedVersionRepository(ReleasedVersionRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, release: ReleasedVersion) -> ReleasedVersion:
        return insert_once(
            self._engine,
            insert(released_versions).values(**record_values(released_versions, release)),
            load=lambda: self.get(release.id),
            expected=release,
            conflict=lambda: ValueError(
                f"release id already exists with different identity: {release.id}"
            ),
        )

    def get(self, release_id: str) -> ReleasedVersion | None:
        return load_one(
            self._engine,
            select(released_versions).where(released_versions.c.id == release_id),
            ReleasedVersion,
        )

    def get_serving(self, target_id: str) -> ReleasedVersion | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(released_versions)
                    .join(
                        serving_releases,
                        serving_releases.c.release_id == released_versions.c.id,
                    )
                    .where(serving_releases.c.target_id == target_id)
                )
                .mappings()
                .first()
            )
        return record_from_row(ReleasedVersion, row) if row is not None else None

    def set_serving(
        self,
        target_id: str,
        release_id: str,
        *,
        operation_id: str,
    ) -> ServingReleaseReceipt:
        if not operation_id.strip():
            raise ValueError("operation_id must be non-empty")

        existing = self._get_operation(operation_id)
        if existing is not None:
            return _validate_receipt(existing, target_id, release_id)

        try:
            with self._engine.begin() as connection:
                release_row = (
                    connection.execute(
                        select(released_versions).where(released_versions.c.id == release_id)
                    )
                    .mappings()
                    .first()
                )
                if release_row is None:
                    raise ValueError(f"unknown release: {release_id}")
                if str(release_row["target_id"]) != target_id:
                    raise ValueError("release does not belong to target")

                current = (
                    connection.execute(
                        select(serving_releases.c.release_id).where(
                            serving_releases.c.target_id == target_id
                        )
                    )
                    .scalar_one_or_none()
                )
                receipt = ServingReleaseReceipt(
                    operation_id=operation_id,
                    target_id=target_id,
                    release_id=release_id,
                    previous_release_id=str(current) if current is not None else None,
                )
                connection.execute(
                    insert(serving_release_operations).values(
                        operation_id=receipt.operation_id,
                        target_id=receipt.target_id,
                        release_id=receipt.release_id,
                        previous_release_id=receipt.previous_release_id,
                    )
                )

                if current is None:
                    connection.execute(
                        insert(serving_releases).values(
                            target_id=target_id,
                            release_id=release_id,
                        )
                    )
                elif str(current) != release_id:
                    result = connection.execute(
                        update(serving_releases)
                        .where(
                            serving_releases.c.target_id == target_id,
                            serving_releases.c.release_id == str(current),
                        )
                        .values(release_id=release_id)
                    )
                    if result.rowcount != 1:
                        raise RuntimeError(
                            "serving release changed concurrently before pointer update"
                        )
        except IntegrityError as exc:
            persisted = self._get_operation(operation_id)
            if persisted is None:
                raise
            try:
                return _validate_receipt(persisted, target_id, release_id)
            except OperationConflictError as conflict:
                raise conflict from exc

        persisted = self._get_operation(operation_id)
        if persisted is None:
            raise RuntimeError("serving release operation receipt was not persisted")
        return _validate_receipt(persisted, target_id, release_id)

    def _get_operation(self, operation_id: str) -> ServingReleaseReceipt | None:
        return load_one(
            self._engine,
            select(serving_release_operations).where(
                serving_release_operations.c.operation_id == operation_id
            ),
            ServingReleaseReceipt,
        )


def _validate_receipt(
    receipt: ServingReleaseReceipt,
    target_id: str,
    release_id: str,
) -> ServingReleaseReceipt:
    if receipt.target_id != target_id or receipt.release_id != release_id:
        raise OperationConflictError(
            f"operation id {receipt.operation_id} is already bound to another serving release"
        )
    return receipt


