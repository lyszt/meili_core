"""
CC-CEDICT backed Chinese dictionary: lookup, word segmentation, pinyin.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pypinyin import lazy_pinyin, Style

from ..utils import Logger

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CEDICT = ROOT / "data" / "cedict" / "cedict_ts.u8"

_LINE = re.compile(r"^(\S+) (\S+) \[([^\]]+)\] /(.+)/$")

# Keep the by-word dictionary strips short
MAX_WORDS_SHOWN = 5


def char_pinyin(text: str) -> str:
    """Per-character pinyin with tone marks for a hanzi string."""
    if not text:
        return ""
    try:
        parts = lazy_pinyin(text, style=Style.TONE)
        return " ".join(parts)
    except Exception:
        return ""


class CEDict:
    """
    In-memory simplified-Chinese dictionary.

    Loads CC-CEDICT once (a couple of seconds) and provides:
      * lookup(word) -> pinyin + English
      * segment(text) -> longest-match word breakdown
      * breakdown(text) -> compact study lines for the HUD
    """

    def __init__(self, path: Path = DEFAULT_CEDICT):
        self.path = Path(path)
        # simplified -> (traditional, pinyin, [meanings])
        self._entries: Dict[str, Tuple[str, str, List[str]]] = {}
        self._max_word_length = 0
        self.loaded = False

    def load(self) -> bool:
        if self.loaded:
            return True
        if not self.path.exists():
            Logger.warning(f"CEDict: no dictionary file at {self.path}")
            return False
        try:
            with open(self.path, "r", encoding="utf8", errors="replace") as f:
                for line in f:
                    if line.startswith("#"):
                        continue
                    match = _LINE.match(line.strip())
                    if not match:
                        continue
                    traditional, simplified, pinyin, meanings = match.groups()
                    glosses = [m.strip() for m in meanings.split("/") if m.strip()]
                    self._entries[simplified] = (traditional, pinyin, glosses)
                    self._max_word_length = max(self._max_word_length,
                                                len(simplified))
            self.loaded = True
            Logger.info(f"CEDict: loaded {len(self._entries)} entries")
            return True
        except Exception as e:
            Logger.error(f"CEDict: failed to load: {e}")
            return False

    def lookup(self, word: str) -> Optional[Tuple[str, str, List[str]]]:
        return self._entries.get(word)

    def segment(self, text: str) -> List[str]:
        """Longest-match segmentation of a hanzi string into dictionary words.

        Characters not found in the dictionary are passed through as
        single-character tokens so nothing is silently dropped.
        """
        # Strip non-CJK noise (digits, punctuation, spaces)
        cleaned = re.sub(r"[^\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+", "", text)
        words: List[str] = []
        index = 0
        while index < len(cleaned):
            matched = None
            for length in range(min(self._max_word_length, len(cleaned) - index),
                                0, -1):
                candidate = cleaned[index:index + length]
                if candidate in self._entries:
                    matched = candidate
                    break
            if matched:
                words.append(matched)
                index += len(matched)
            else:
                words.append(cleaned[index])
                index += 1
        return words

    def breakdown(self, text: str) -> List[str]:
        """Compact word-by-word study lines: '字  zì  character' ..."""
        if not self.load():
            return []
        cleaned = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
        results: List[str] = []
        for chunk in cleaned.split():
            for word in self.segment(chunk):
                if len(results) >= MAX_WORDS_SHOWN:
                    return results
                entry = self._entries.get(word)
                if entry:
                    _traditional, _pinyin, glosses = entry
                    gloss = glosses[0] if glosses else ""
                    # Keep the gloss short: first clause only
                    gloss = gloss.split(";")[0].strip()
                    results.append(f"{word}  {char_pinyin(word)}  {gloss}")
                else:
                    results.append(f"{word}  {char_pinyin(word)}")
        return results
