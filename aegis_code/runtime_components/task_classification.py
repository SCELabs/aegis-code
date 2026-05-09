from __future__ import annotations


def is_constructive_task(task: str) -> bool:
    lowered = str(task or "").lower()
    if is_test_generation_task(lowered):
        return True

    positive = (
        "add",
        "create",
        "implement",
        "build",
        "write",
        "generate",
        "refactor",
        "update",
        "extend",
    )
    negative = ("run tests", "execute tests", "check tests", "analyze", "summarize", "explain")
    if any(token in lowered for token in negative):
        return False
    return any(token in lowered for token in positive)


def _has_implementation_intent(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    impl_phrases = (
        "fix",
        "update",
        "change",
        "modify",
        "add a module",
        "create a module",
        "add a helpers module",
        "add helpers module",
        "add helper",
        "create helper",
        "add function",
        "create function",
        "implement",
        "helpers module",
        "add endpoint",
        "add route",
        "api route",
        "add handler",
        "request body validation",
        "schema",
        "validation",
    )
    return any(phrase in lowered for phrase in impl_phrases)


def _has_test_intent(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    test_phrases = ("test", "tests", "coverage")
    return any(phrase in lowered for phrase in test_phrases)


def _is_explicit_tests_only_task(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    tests_only_phrases = (
        "tests only",
        "test only",
        "write tests only",
        "do not modify source files",
        "do not modify source",
    )
    return any(phrase in lowered for phrase in tests_only_phrases)


def _is_docs_task(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    docs_phrases = (
        "readme",
        "docs",
        "documentation",
        "usage examples",
        "setup instructions",
    )
    return any(phrase in lowered for phrase in docs_phrases)


def _has_feature_implementation_intent(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    feature_phrases = (
        "add endpoint",
        "add api route",
        "api route",
        "add route",
        "post /",
        "get /",
        "put /",
        "delete /",
        "add feature",
        "add handler",
        "implement handler",
        "add schema",
        "implement schema",
        "request body validation",
        "body validation",
        "payload validation",
    )
    if any(phrase in lowered for phrase in feature_phrases):
        return True
    if "implement" in lowered and any(token in lowered for token in ("endpoint", "route", "handler", "schema", "validation", "api")):
        return True
    return False


def _is_vague_feature_task(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    vague_phrases = (
        "add a new feature",
        "add feature",
        "new feature with tests",
    )
    if any(phrase in lowered for phrase in vague_phrases):
        has_specific_anchor = any(
            token in lowered
            for token in (" in ", " file", " module", " function", "class ", " endpoint", " api ", " cli ")
        )
        return not has_specific_anchor
    return False


def _is_tagging_support_task(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    return "tag" in lowered and "todo" in lowered and ("filter" in lowered or "filtering" in lowered) and "test" in lowered


def classify_task_type(task: str) -> str:
    lowered = str(task or "").lower().strip()
    if not lowered:
        return "general"
    if _is_vague_feature_task(lowered):
        return "vague_task"
    if _is_explicit_tests_only_task(lowered):
        return "test_generation"
    if _has_feature_implementation_intent(lowered):
        return "feature_implementation"
    if _is_docs_task(lowered):
        return "docs_task"
    if _has_implementation_intent(lowered) and _has_test_intent(lowered):
        return "implementation_with_tests"
    if is_test_generation_task(lowered):
        return "test_generation"
    return "general"


def is_test_generation_task(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    if not lowered:
        return False
    if _has_implementation_intent(lowered) and _has_test_intent(lowered) and not _is_explicit_tests_only_task(lowered):
        return False
    verification_only = ("run tests", "execute tests", "check tests")
    if any(phrase in lowered for phrase in verification_only):
        return False

    if _is_explicit_tests_only_task(lowered):
        return True
    generation_phrases = (
        "add test",
        "add tests",
        "write test",
        "write tests",
        "generate test",
        "generate tests",
        "test for",
        "tests for",
        "coverage",
        "verify behavior",
        "assert",
    )
    return any(phrase in lowered for phrase in generation_phrases)

