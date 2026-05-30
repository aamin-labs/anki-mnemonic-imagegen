from workflows.import_refactor import (
    _finalize_reverse_answer,
    _reverse_answer_target_from_question,
)


def test_reverse_answer_target_for_definition_question():
    assert _reverse_answer_target_from_question("What is index-free adjacency?") == "index-free adjacency"


def test_reverse_answer_target_drops_article_for_answer_form():
    assert _reverse_answer_target_from_question("What is the capital of France?") == "Capital of France"
    assert _reverse_answer_target_from_question("What is an API gateway?") == "API gateway"


def test_finalize_reverse_answer_replaces_copied_definition_with_question_target():
    question = "What is index-free adjacency?"
    answer = (
        "Each node stores its relationships directly; traversal follows pointers with cost "
        "proportional to neighbourhood size, not total DB size."
    )
    copied_reverse = (
        "A graph-database property where traversal cost depends on neighbourhood size rather "
        "than total DB size, achieved by storing relationships directly on nodes."
    )

    assert (
        _finalize_reverse_answer(
            question=question,
            answer=answer,
            existing_reverse=copied_reverse,
            proposed_reverse=copied_reverse,
        )
        == "index-free adjacency"
    )


def test_finalize_reverse_answer_replaces_long_definition_even_when_not_exact_copy():
    assert (
        _finalize_reverse_answer(
            question="What is index-free adjacency?",
            answer="Long definition.",
            existing_reverse="",
            proposed_reverse="A graph DB traversal feature that makes pointer hops scale with local neighborhood size.",
        )
        == "index-free adjacency"
    )


def test_finalize_reverse_answer_keeps_good_model_output():
    assert (
        _finalize_reverse_answer(
            question="What is index-free adjacency?",
            answer="Long definition.",
            existing_reverse="",
            proposed_reverse="index-free adjacency",
        )
        == "index-free adjacency"
    )
