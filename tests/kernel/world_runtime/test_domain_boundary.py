from world_runtime import OntologyRegistry, SQLiteLedger
from world_runtime.ontology import SemanticTypeDefinition


def test_runtime_cannot_take_domain_type_ownership():
    ontology = OntologyRegistry(SQLiteLedger())
    ontology.register(SemanticTypeDefinition("development.ReleaseCandidate", "autonomous-development", "1"))
    try:
        ontology.register(SemanticTypeDefinition("development.ReleaseCandidate", "world-runtime", "2"))
    except ValueError:
        pass
    else:
        raise AssertionError("runtime stole a domain-owned semantic type")
