import re

# Tooltip icons, footnote markers, and other noise characters
_NOISE_PATTERN = re.compile(r"[ⓘ①②③④⑤⑥⑦⑧⑨⑩*†‡§¶#]")


def clean_text(text: str) -> str:
    """Remove tooltip icons, footnote markers, and normalize whitespace."""
    text = _NOISE_PATTERN.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def convert_symbol(value: str, symbol_map: dict) -> str:
    """Convert symbol characters to normalized text using the symbol_map.
    Non-symbol text values are preserved as-is after stripping.
    """
    stripped = value.strip()
    if stripped in symbol_map:
        return symbol_map[stripped]
    return stripped
