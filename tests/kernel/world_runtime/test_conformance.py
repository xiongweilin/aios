from world_runtime.contracts import PUBLIC_CONFORMANCE_SUITE_VERSION, conformance_vectors


def test_public_conformance_vectors_are_versioned_and_complete() -> None:
    suite = conformance_vectors()
    ids = {item["id"] for item in suite["vectors"]}

    assert suite["suite_version"] == PUBLIC_CONFORMANCE_SUITE_VERSION
    assert len(suite["vectors"]) == len(ids) == 65
    assert {
        "ambiguous-effect-never-blind-redispatches",
        "runtime-state-survives-restart",
        "provider-result-read-is-principal-actor-bound",
    } <= ids
