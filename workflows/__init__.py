from .format_fields import FormatFieldsWorkflow, FormatQuestionAnswerWorkflow
from .highlight import HighlightWorkflow
from .leech_review import LeechReviewWorkflow
from .mnemonic_image import MnemonicImageWorkflow

WORKFLOWS = {
    "format_fields": FormatFieldsWorkflow,
    "format_qa_fields": FormatQuestionAnswerWorkflow,
    "highlight": HighlightWorkflow,
    "leech_review": LeechReviewWorkflow,
    "mnemonic_image": MnemonicImageWorkflow,
}
