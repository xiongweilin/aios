from dataclasses import dataclass

from semantic_language import Revision, SemanticRef, semantic_digest

from .ledger import SemanticLedger
from .lineage import RevisionLineageService


@dataclass(frozen=True, slots=True)
class SemanticTypeDefinition:
    name: str
    owner: str
    version: str
    description: str = ""


class OntologyRegistry:
    """Type ownership/version registry, not a universal domain ontology."""

    NAMESPACE = "world-runtime.ontology"
    KIND = "semantic-type-definition"

    def __init__(
        self,
        ledger: SemanticLedger,
        lineage: RevisionLineageService | None = None,
    ) -> None:
        self.ledger = ledger
        self.lineage = lineage or RevisionLineageService(ledger)

    @classmethod
    def definition_ref(cls, definition: SemanticTypeDefinition) -> SemanticRef:
        return SemanticRef(
            kind=cls.KIND,
            id=f"{definition.name}@{definition.version}",
            namespace=cls.NAMESPACE,
        )

    @staticmethod
    def _version_key(name: str, version: str) -> str:
        return semantic_digest({"name": name, "version": version})

    @staticmethod
    def _value(definition: SemanticTypeDefinition) -> dict[str, str]:
        return {
            "name": definition.name,
            "owner": definition.owner,
            "version": definition.version,
            "description": definition.description,
        }

    def register(self, definition: SemanticTypeDefinition) -> None:
        existing_row = self.ledger.project_get("ontology.type", definition.name)
        value = self._value(definition)
        if existing_row is not None:
            existing = SemanticTypeDefinition(**existing_row[0])
            if existing.owner != definition.owner:
                raise ValueError(
                    f"type {definition.name!r} is already owned by {existing.owner!r}"
                )
            if existing.version != definition.version:
                raise ValueError(
                    "new ontology version requires explicit Revision supersession"
                )
            if existing != definition:
                raise ValueError("ontology type version identity rebound")
            return

        with self.ledger.transaction():
            self.ledger.project_put(
                "ontology.type-version",
                self._version_key(definition.name, definition.version),
                value,
                expected_version=0,
            )
            self.ledger.project_put(
                "ontology.type",
                definition.name,
                value,
                expected_version=0,
            )
            self.ledger.append(
                stream=f"ontology:{definition.name}",
                kind="ontology.type.registered",
                payload=value,
            )

    def supersede(
        self,
        definition: SemanticTypeDefinition,
        revision: Revision,
    ) -> None:
        current_row = self.ledger.project_get("ontology.type", definition.name)
        if current_row is None:
            raise KeyError(definition.name)
        current_value, current_version = current_row
        current = SemanticTypeDefinition(**current_value)
        if current.owner != definition.owner:
            raise ValueError("ontology type ownership cannot change by version supersession")
        if current.version == definition.version:
            raise ValueError("ontology successor must use a new version")

        previous_ref = self.definition_ref(current)
        target_ref = self.definition_ref(definition)
        if revision.supersedes_ref != previous_ref:
            raise ValueError("ontology Revision must supersede the current definition")
        if revision.target_ref != target_ref:
            raise ValueError("ontology Revision target must be the new definition")

        value = self._value(definition)
        with self.ledger.transaction():
            self.ledger.project_put(
                "ontology.type-version",
                self._version_key(definition.name, definition.version),
                value,
                expected_version=0,
            )
            self.lineage.record(revision)
            self.ledger.project_put(
                "ontology.type",
                definition.name,
                value,
                expected_version=current_version,
            )
            self.ledger.append(
                stream=f"ontology:{definition.name}",
                kind="ontology.type.superseded",
                payload={
                    **value,
                    "revision_id": revision.id,
                    "supersedes_version": current.version,
                },
            )

    def resolve(self, name: str) -> SemanticTypeDefinition | None:
        row = self.ledger.project_get("ontology.type", name)
        return None if row is None else SemanticTypeDefinition(**row[0])

    def resolve_version(
        self,
        name: str,
        version: str,
    ) -> SemanticTypeDefinition | None:
        row = self.ledger.project_get(
            "ontology.type-version",
            self._version_key(name, version),
        )
        return None if row is None else SemanticTypeDefinition(**row[0])

    def history(self, name: str) -> tuple[SemanticTypeDefinition, ...]:
        values: list[SemanticTypeDefinition] = []
        for event in self.ledger.events(stream=f"ontology:{name}"):
            if event.kind not in {
                "ontology.type.registered",
                "ontology.type.superseded",
            }:
                continue
            payload = event.payload
            values.append(
                SemanticTypeDefinition(
                    name=str(payload["name"]),
                    owner=str(payload["owner"]),
                    version=str(payload["version"]),
                    description=str(payload.get("description", "")),
                )
            )
        return tuple(values)
