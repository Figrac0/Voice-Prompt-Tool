from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.config import TextPostprocessConfig


class TextPostprocessError(RuntimeError):
    """Raised when text post-processing fails."""


@dataclass(frozen=True, slots=True)
class AppliedReplacement:
    source: str
    target: str
    count: int


@dataclass(frozen=True, slots=True)
class TextPostprocessResult:
    raw_text: str
    cleaned_text: str
    applied_replacements: tuple[AppliedReplacement, ...]
    changed: bool


class TextPostprocessor:
    _whitespace_pattern = re.compile(r"\s+")
    _space_before_punctuation_pattern = re.compile(r"\s+([,.;:!?])")
    _repeated_terminal_pattern = re.compile(r"[!?]{2,}")
    _repeated_separator_pattern = re.compile(r"([,;:])\1+")
    _repeated_period_pattern = re.compile(r"\.{2,}")
    _space_after_separator_pattern = re.compile(r"([,;:!?])(?=[^\W_])")
    _space_after_opening_bracket_pattern = re.compile(r"([(\[{])\s+")
    _space_before_closing_bracket_pattern = re.compile(r"\s+([)\]}])")
    _sentence_start_pattern = re.compile(r"([.!?]\s+)([^\W\d_])")
    _leading_letter_pattern = re.compile(r"^([^\W\d_])")

    # Whisper sometimes outputs the Cyrillic letter «ю» instead of a period
    # at the very end of an utterance (model confuses the punctuation token).
    # Only strip a trailing standalone «ю» — never touch «ю» inside the text.
    _whisper_yu_end = re.compile(r"\s+ю\s*$")

    # Remove trailing «ю» or «б» that Whisper adds at the end of words
    _whisper_trailing_artifacts = re.compile(r"([а-яёa-z]+)[юб]\b", re.IGNORECASE)

    # Conservative list of Russian filler sounds that Whisper sometimes
    # transcribes literally but that carry no meaning.
    _filler_pattern = re.compile(
        r"\b(эм|э-э|ааа+|аа|ммм+|мм|кхм|нуу+|угу|ага\s+ага)\b[,.]?\s*",
        flags=re.IGNORECASE,
    )

    # Block the hallucinated phrase "Продолжение следует" completely
    _continuation_phrase = re.compile(
        r"\b(продолжение\s+следует|continuation\s+follows)\b[.,]?\s*",
        flags=re.IGNORECASE,
    )
    _question_leads = (
        "как ",
        "что ",
        "кто ",
        "где ",
        "когда ",
        "почему ",
        "зачем ",
        "сколько ",
        "какой ",
        "какая ",
        "какие ",
        "какое ",
        "каков ",
        "можно ",
        "можешь ",
        "можете ",
        "будет ли ",
        "есть ли ",
        "how ",
        "what ",
        "who ",
        "where ",
        "when ",
        "why ",
        "can ",
        "could ",
        "would ",
        "should ",
        "do ",
        "does ",
        "did ",
        "is ",
        "are ",
        "will ",
    )

    def __init__(self, config: TextPostprocessConfig, logger: logging.Logger) -> None:
        self._config = config
        self._logger = logger
        self._last_result: TextPostprocessResult | None = None

    @property
    def last_result(self) -> TextPostprocessResult | None:
        return self._last_result

    def process_text(self, raw_text: str) -> TextPostprocessResult:
        if not isinstance(raw_text, str):
            raise TextPostprocessError("Raw transcription text must be a string.")

        cleaned_text = raw_text.strip()
        cleaned_text = self._normalize_whitespace(cleaned_text)
        cleaned_text = self._remove_continuation_phrase(cleaned_text)
        cleaned_text = self._remove_whisper_artifacts(cleaned_text)
        cleaned_text = self._remove_trailing_artifacts(cleaned_text)
        cleaned_text = self._remove_fillers(cleaned_text)
        cleaned_text = self._normalize_punctuation(cleaned_text)
        cleaned_text, applied_replacements = self._apply_custom_replacements(cleaned_text)
        cleaned_text = self._normalize_terminal_mark(cleaned_text)
        cleaned_text = self._capitalize_sentence_starts(cleaned_text)
        cleaned_text = self._normalize_whitespace(cleaned_text)
        cleaned_text = self._normalize_punctuation(cleaned_text)

        result = TextPostprocessResult(
            raw_text=raw_text,
            cleaned_text=cleaned_text,
            applied_replacements=applied_replacements,
            changed=cleaned_text != raw_text,
        )
        self._last_result = result

        self._logger.info(
            "Text post-processing finished | changed=%s | replacements=%s | cleaned_text=%s",
            result.changed,
            sum(item.count for item in applied_replacements),
            result.cleaned_text,
        )

        return result

    def _normalize_whitespace(self, text: str) -> str:
        return self._whitespace_pattern.sub(" ", text).strip()

    def _remove_whisper_artifacts(self, text: str) -> str:
        """Strip trailing standalone «ю» that Whisper adds instead of a period."""
        return self._whisper_yu_end.sub("", text).strip()

    def _remove_continuation_phrase(self, text: str) -> str:
        """Remove the hallucinated phrase 'Продолжение следует' completely."""
        return self._continuation_phrase.sub("", text).strip()

    def _remove_trailing_artifacts(self, text: str) -> str:
        """Remove trailing «ю» or «б» that Whisper incorrectly adds at the end of words."""
        # Only remove if the word would still be valid without the trailing letter
        def replace_trailing(match):
            word = match.group(1)
            # Keep the trailing letter if the word is too short (likely legitimate)
            if len(word) < 3:
                return match.group(0)
            return word

        return self._whisper_trailing_artifacts.sub(replace_trailing, text).strip()

    def _remove_fillers(self, text: str) -> str:
        """Remove transcribed filler sounds (эм, ааа, ммм, кхм …)."""
        return self._filler_pattern.sub("", text).strip()

    def _normalize_punctuation(self, text: str) -> str:
        if not text:
            return text

        text = self._repeated_terminal_pattern.sub(self._collapse_terminal_punctuation, text)
        text = self._repeated_separator_pattern.sub(r"\1", text)
        text = self._repeated_period_pattern.sub(".", text)
        text = self._space_before_punctuation_pattern.sub(r"\1", text)
        text = self._space_after_separator_pattern.sub(r"\1 ", text)
        text = self._space_after_opening_bracket_pattern.sub(r"\1", text)
        text = self._space_before_closing_bracket_pattern.sub(r"\1", text)
        return text.strip()

    def _apply_custom_replacements(
        self,
        text: str,
    ) -> tuple[str, tuple[AppliedReplacement, ...]]:
        applied: list[AppliedReplacement] = []

        for source, target in self._config.custom_replacements:
            pattern = re.compile(
                rf"(?<!\w){re.escape(source)}(?!\w)",
                flags=re.IGNORECASE,
            )
            text, count = pattern.subn(target, text)

            if count:
                applied.append(AppliedReplacement(source=source, target=target, count=count))

        return text, tuple(applied)

    def _capitalize_sentence_starts(self, text: str) -> str:
        if not text:
            return text

        text = self._leading_letter_pattern.sub(lambda match: match.group(1).upper(), text, count=1)
        text = self._sentence_start_pattern.sub(
            lambda match: f"{match.group(1)}{match.group(2).upper()}",
            text,
        )
        return text

    def _normalize_terminal_mark(self, text: str) -> str:
        if not text:
            return text

        stripped = text.strip()
        lowered = stripped.casefold()

        if stripped.endswith(("?", "?!", "!?")):
            return stripped

        if any(lowered.startswith(prefix) for prefix in self._question_leads):
            return stripped.rstrip(".!") + "?"

        if stripped[-1] in ".!":
            return stripped

        return stripped

    @staticmethod
    def _collapse_terminal_punctuation(match: re.Match[str]) -> str:
        token = match.group(0)

        if "?" in token and "!" in token:
            return "?!"

        return token[0]
