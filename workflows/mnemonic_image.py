import base64
import re
from pathlib import Path

import anthropic
import requests

from .base import EnhancementWorkflow, WorkflowError

_MINIMAX_BASE_URL = "https://api.minimax.io/anthropic"
_MINIMAX_IMAGE_URL = "https://api.minimax.io/v1/image_generation"
_IMAGE_PROMPT_RE = re.compile(
    r"\*\*Image prompt\*\*[:\s]+(.*?)(?:\n\n|\Z)", re.DOTALL | re.IGNORECASE
)


class MnemonicImageWorkflow(EnhancementWorkflow):
    WORKFLOW_NAME = "mnemonic_image"
    INPUT_FIELDS = ["Front", "Back"]
    OUTPUT_FIELDS = ["Mnemonic"]

    def __init__(self, config: dict):
        super().__init__(config)
        self._client = anthropic.Anthropic(
            api_key=config["minimax_api_key"],
            base_url=_MINIMAX_BASE_URL,
        )
        self._api_key = config["minimax_api_key"]
        self._input_fields = config.get("input_fields", self.INPUT_FIELDS)
        self._media_dir = Path(config["media_dir"])

        if not self._media_dir.exists():
            raise RuntimeError(
                f"Anki media directory not found: {self._media_dir}\n"
                "Check that ANKI_PROFILE is set correctly in .env"
            )

        prompt_path = Path(__file__).parent.parent / "prompts" / "prompt-visual-designer.md"
        self._prompt_template = prompt_path.read_text()

    def process_note(self, note_id: str, fields: dict[str, str]) -> dict[str, str]:
        question = fields.get(self._input_fields[0], "").strip()
        answer = fields.get(self._input_fields[1], "").strip() if len(self._input_fields) > 1 else ""

        if not question and not answer:
            raise WorkflowError(f"Both {self._input_fields[0]} and {self._input_fields[1] if len(self._input_fields) > 1 else 'answer'} are empty")

        # 1. Design the mnemonic with MiniMax M2.5
        system = (
            self._prompt_template
            .replace("{{question}}", question)
            .replace("{{answer}}", answer)
        )
        try:
            msg = self._client.messages.create(
                model="MiniMax-M2.5",
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": "Generate the visual mnemonic and image prompt."}],
            )
        except anthropic.AuthenticationError:
            raise WorkflowError("API key is invalid. Check MINIMAX_API_KEY in .env")
        except anthropic.APIConnectionError:
            raise WorkflowError("Connection to MiniMax API failed. Check your internet connection")
        except anthropic.APIStatusError as e:
            raise WorkflowError(f"MiniMax API error: {e.status_code} {e.message}")

        claude_text = next(block.text for block in msg.content if block.type == "text")

        # 2. Extract the image prompt section
        match = _IMAGE_PROMPT_RE.search(claude_text)
        if not match:
            raise WorkflowError(f"Could not parse image prompt from M2.5 response:\n{claude_text[:300]}")
        image_prompt = match.group(1).strip()

        # 3. Generate image with MiniMax image-01
        try:
            response = requests.post(
                _MINIMAX_IMAGE_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                json={
                    "model": "image-01",
                    "prompt": image_prompt,
                    "response_format": "base64",
                    "n": 1,
                },
                timeout=60,
            )
            response.raise_for_status()
        except requests.exceptions.Timeout:
            raise WorkflowError(
                f"Image generation timed out (prompt: {image_prompt[:80]}{'...' if len(image_prompt) > 80 else ''})"
            )
        except requests.exceptions.ConnectionError:
            raise WorkflowError("Connection to MiniMax image API failed. Check your internet connection")
        except requests.exceptions.HTTPError as e:
            raise WorkflowError(f"MiniMax image API HTTP error: {e}")

        result = response.json()

        status = result.get("base_resp", {}).get("status_code", -1)
        if status != 0:
            err_msg = result.get("base_resp", {}).get("status_msg", "unknown error")
            raise WorkflowError(f"MiniMax image-01 error ({status}): {err_msg}")

        images = result.get("data", {}).get("image_base64", [])
        if not images:
            raise WorkflowError("MiniMax image-01 returned no images")

        image_bytes = base64.b64decode(images[0])

        # 4. Save PNG to Anki media folder
        filename = f"mnemonic_{note_id}.png"
        (self._media_dir / filename).write_bytes(image_bytes)

        return {"Mnemonic": f'<img src="{filename}">'}
