"""
Text filters for OCR output: keep only Chinese content.
"""

import re

# Han + CJK punctuation + fullwidth forms; digits and spaces are kept
# when embedded between CJK characters (e.g. "第 01 集")
_CJK_RUN = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\u3000-\u303f\uff00-\uffef0-9\s]+"
)
_HAS_HANZI = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_KEEP = re.compile(
    r"[^\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\u3000-\u303f\uff00-\uffef0-9 ]"
)


def cjk_only(text: str) -> str:
    """
    Filter captured text down to Chinese content only.

    Drops browser chrome, Latin app names, URLs and other UI noise while
    keeping hanzi, CJK punctuation, and digits embedded between hanzi
    (episode numbers like 第 01 集).
    """
    result_lines = []
    for line in text.splitlines():
        picks = []
        for run in _CJK_RUN.findall(line):
            if not _HAS_HANZI.search(run):
                continue
            cleaned = _KEEP.sub("", run)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if cleaned:
                picks.append(cleaned)
        if picks:
            result_lines.append("  ".join(picks))
    return "\n".join(result_lines)
