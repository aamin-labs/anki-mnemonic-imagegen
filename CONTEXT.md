# Anki Enrichment

This context covers local tools that enrich Abu's Anki cards with formatting, images, and review metadata before syncing back to AnkiWeb.

## Language

**Flagged Image Queue**:
Cards marked with Anki purple flag (`flag:6`) for automatic enrichment with an existing contextual image.
_Avoid_: tag:6, needs-wiki-image tag

**Existing Context Image**:
A small-to-medium image found from Wikipedia/Wikimedia and written to the card's `Image` field to give factual context for a card topic.
_Avoid_: AI-generated mnemonic image, generated image

**Image Lookup Title**:
The field value used as the Wikipedia search/title candidate; defaults to the card's `Answer` field.
_Avoid_: prompt, image prompt

**Image Source**:
The Wikipedia page URL recorded in the card's existing `Source` field when available.
_Avoid_: caption, citation block

## Relationships

- A **Flagged Image Queue** card can receive one **Existing Context Image**.
- A successfully enriched **Flagged Image Queue** card leaves the queue by clearing `flag:6` and gains the `wiki-image-added` tag for audit.
- An **Existing Context Image** is only added when the target image field is empty, unless overwrite is explicitly requested.
- An **Existing Context Image** is distinct from an AI-generated mnemonic image: it illustrates context rather than encoding recall.

## Example dialogue

> **Dev:** "Should the image workflow process notes tagged `tag:6`?"
> **Domain expert:** "No — use Anki's purple card flag, `flag:6`, as the queue."

## Flagged ambiguities

- "tag (flag:6)" was used to mean an Anki tag — resolved: this feature uses the purple Anki card flag (`flag:6`), not a note tag.
