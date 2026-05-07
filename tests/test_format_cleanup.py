from workflows.format_fields import _validate_format_cleanup_output


def test_format_cleanup_accepts_short_precision_underlines():
    output = {
        "Answer": "<ul><li><b>Learning rate</b> = step <u>size</u>.</li><li><b>Batch size</b> = step <u>frequency</u>.</li></ul>",
        "Explanation": "Learning rate controls how much weights change per update.",
    }

    assert _validate_format_cleanup_output(output) == []


def test_format_cleanup_rejects_underlined_phrases():
    output = {
        "Answer": "Learning rate = <u>step size</u>.",
        "Explanation": "",
    }

    assert "underline only individual words" in " ".join(_validate_format_cleanup_output(output))


def test_format_cleanup_rejects_inline_numbered_items():
    output = {
        "Answer": "Two failures: (1) <b>token waste</b>; (2) <b>information loss</b>.",
        "Explanation": "",
    }

    assert "convert them to an HTML list" in " ".join(_validate_format_cleanup_output(output))


def test_format_cleanup_rejects_long_parenthetical_in_answer():
    output = {
        "Answer": "Learning rate = step size (how much weights change per update).",
        "Explanation": "",
    }

    assert "move extra context to Explanation" in " ".join(
        _validate_format_cleanup_output(output)
    )


def test_format_cleanup_rejects_square_bracket_details_in_answer():
    output = {
        "Answer": "Learning rate = step size [how much weights change per update].",
        "Explanation": "",
    }

    assert "move extra context to Explanation" in " ".join(
        _validate_format_cleanup_output(output)
    )


def test_format_cleanup_rejects_inline_period_numbered_items():
    output = {
        "Answer": "Two failures: 1. <b>token waste</b>; 2. <b>information loss</b>.",
        "Explanation": "",
    }

    assert "convert them to an HTML list" in " ".join(_validate_format_cleanup_output(output))


def test_format_cleanup_rejects_underlines_in_bare_equivalent_item_list():
    output = {
        "Answer": "<u>RadixAttention</u>, prefix caching, and continuous batching",
        "Explanation": "",
    }

    assert "do not underline any one item" in " ".join(_validate_format_cleanup_output(output))
