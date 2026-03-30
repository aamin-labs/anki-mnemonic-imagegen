import re
from pathlib import Path

import anthropic
from google import genai
from google.genai import types
from google.genai import errors as genai_errors

from .base import EnhancementWorkflow, WorkflowError

_IMAGE_PROMPT_RE = re.compile(
    r"\*\*Image prompt:?\*\*[:\s]+(.*?)(?:\n\n|\Z)", re.DOTALL | re.IGNORECASE
)
_ENCODING_RE = re.compile(
    r"\*\*Encoding:?\*\*[:\s]+(.*?)(?=\n\n|\*\*Image prompt|\Z)", re.DOTALL | re.IGNORECASE
)

_TEXT_MODEL = "claude-sonnet-4-6"
_IMAGE_MODEL = "imagen-4.0-generate-001"
_DEFAULT_PROMPT_FILE = "prompt-visual-designer.md"


class MnemonicImageWorkflow(EnhancementWorkflow):
    WORKFLOW_NAME = "mnemonic_image"
    INPUT_FIELDS = ["Front", "Back"]
    OUTPUT_FIELDS = ["Mnemonic", "Encoding"]
    REQUIRED_ENV_KEYS = ["ANTHROPIC_API_KEY", "GEMINI_API_KEY"]
    DEFAULT_ADD_TAG = "image-updated"
    DEFAULT_REMOVE_TAG = "need-image"

    def __init__(self, config: dict):
        super().__init__(config)
        self._anthropic = anthropic.Anthropic(api_key=config["anthropic_api_key"])
        self._genai = genai.Client(api_key=config["gemini_api_key"])
        self._media_dir = Path(config["media_dir"])

        if not self._media_dir.exists():
            raise RuntimeError(
                f"Anki media directory not found: {self._media_dir}\n"
                "Check that ANKI_PROFILE is set correctly in .env"
            )

        prompt_file = config.get("prompt_file") or _DEFAULT_PROMPT_FILE
        prompt_path = Path(__file__).parent.parent / "prompts" / prompt_file
        self._prompt_template = prompt_path.read_text()

    def process_note(self, note_id: str, fields: dict[str, str]) -> dict[str, str]:
        if not any(fields.get(f, "").strip() for f in self._input_fields):
            raise WorkflowError(f"All input fields are empty: {self._input_fields}")

        # Map positionally: input_fields[0] → {{question}}, input_fields[1] → {{answer}}
        question = fields.get(self._input_fields[0], "").strip()
        answer = fields.get(self._input_fields[1], "").strip() if len(self._input_fields) > 1 else ""
        system = (
            self._prompt_template
            .replace("{{question}}", question)
            .replace("{{answer}}", answer)
        )

        # 1. Design the mnemonic with Claude
        try:
            msg = self._anthropic.messages.create(
                model=_TEXT_MODEL,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": "Generate the visual mnemonic and image prompt."}],
            )
        except anthropic.APIError as e:
            raise WorkflowError(f"Claude API error: {e}")

        claude_text = msg.content[0].text

        # 2. Extract the image prompt
        match = _IMAGE_PROMPT_RE.search(claude_text)
        if not match:
            raise WorkflowError(f"Could not parse image prompt from Claude response:\n{claude_text[:300]}")
        image_prompt = match.group(1).strip()

        # 3. Generate image with Imagen
        try:
            img_response = self._genai.models.generate_images(
                model=_IMAGE_MODEL,
                prompt=image_prompt,
                config=types.GenerateImagesConfig(number_of_images=1),
            )
        except genai_errors.ClientError as e:
            raise WorkflowError(f"Imagen API client error: {e}")
        except genai_errors.ServerError as e:
            raise WorkflowError(f"Imagen API server error: {e}")
        except genai_errors.APIError as e:
            raise WorkflowError(f"Imagen API error: {e}")

        if not img_response.generated_images:
            raise WorkflowError("Imagen returned no images")

        image_bytes = img_response.generated_images[0].image.image_bytes

        # 4. Save PNG to Anki media folder
        filename = f"mnemonic_{note_id}.png"
        (self._media_dir / filename).write_bytes(image_bytes)

        encoding_match = _ENCODING_RE.search(claude_text)
        encoding_text = encoding_match.group(1).strip() if encoding_match else ""

        image_field = self._output_fields[0] if self._output_fields else "Mnemonic"
        encoding_field = self._output_fields[1] if len(self._output_fields) > 1 else "Encoding"

        return {
            image_field: f'<img src="{filename}">',
            encoding_field: encoding_text,
            "__image_prompt__": image_prompt,
        }
