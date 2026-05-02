from .format_fields import FormatFieldsWorkflow
from .highlight import HighlightWorkflow
from .key_terms import KeyTermsWorkflow
from .leech_review import LeechReviewWorkflow
from .mnemonic_image import MnemonicImageWorkflow

WORKFLOWS = {
    "format_fields": FormatFieldsWorkflow,
    "highlight": HighlightWorkflow,
    "key_terms": KeyTermsWorkflow,
    "leech_review": LeechReviewWorkflow,
    "mnemonic_image": MnemonicImageWorkflow,
}
