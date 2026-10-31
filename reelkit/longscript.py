"""Long-form project script format.

    # Video title                      (optional, first line)
    ## Chapter title
    > broll: shower water | cold lake swimmer | thermometer close up     (footage search pool for the chapter)
    > images: Wim Hof | cryotherapy chamber                              (still images from Wikimedia Commons)
    > source: https://example.org/study                                  (where this chapter's facts come from)
    > card: off                                                          (no chapter title card)

    > shot: heart rate monitor close up                                  (footage for the shot that starts at the next paragraph)
    > fact: 11 minutes a week                                            (big text card over the start of the next paragraph)
    Paragraph of narration. Blank line = new paragraph.

Chapter-level directives may appear anywhere in the chapter; `shot` and `fact` apply to the paragraph that follows.
*Asterisks* are accepted and removed (they only matter for short reels)."""
import re
from dataclasses import dataclass, field

from .common import Scene
from .script import strip_emphasis

CHAPTER_DIRECTIVES = {"broll", "images", "source", "sources", "card"}
PARA_DIRECTIVES = {"shot", "fact"}


@dataclass
class Chapter:
    title: str
    broll: list = field(default_factory=list)
    images: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    card: bool = True
    blocks: list = field(default_factory=list)
    start: float = 0.0
    end: float = 0.0

    @property
    def words(self): return sum(len(b.words) for b in self.blocks)


@dataclass
class Project:
    title: str = ""
    chapters: list = field(default_factory=list)

    @property
    def blocks(self): return [b for c in self.chapters for b in c.blocks]

    @property
    def words(self): return sum(c.words for c in self.chapters)


def split_blocks(paragraph: str, max_words: int):
    """Split a paragraph into narration blocks at sentence ends, each at most ~max_words words."""
    sents = [s for s in re.split(r"(?<=[.!?…])\s+", paragraph.strip()) if s]
    blocks, cur = [], []
    for s in sents:
        n = len(s.split())
        if cur and sum(len(x.split()) for x in cur) + n > max_words:
            blocks.append(" ".join(cur)); cur = []
        cur.append(s)
        if n > max_words * 1.6:                      # one very long sentence: break at a comma near the middle
            blocks.append(" ".join(cur)); cur = []
    if cur:
        blocks.append(" ".join(cur))
    return blocks


def parse(text: str, max_words: int = 42) -> Project:
    proj, ch, para, pending = Project(), None, [], {}

    def flush():
        nonlocal para, pending
        if para and ch is not None:
            raw = " ".join(para)
            parts = split_blocks(raw, max_words)
            for i, part in enumerate(parts):
                words, _ = strip_emphasis(part.split())
                b = Scene(text=" ".join(words), words=words, kind="card", chapter=len(proj.chapters) - 1)
                b.para_end = i == len(parts) - 1
                if i == 0:
                    b.shot, b.fact = pending.get("shot"), pending.get("fact")
                ch.blocks.append(b)
            pending = {}
        para = []

    for line in text.splitlines():
        s = line.strip()
        if not s:
            flush(); continue
        if s.startswith("## "):
            flush()
            ch = Chapter(title=s[3:].strip())
            proj.chapters.append(ch)
        elif s.startswith("# ") and not proj.chapters and not proj.title:
            proj.title = s[2:].strip()
        elif s.startswith(">"):
            m = re.match(r">\s*([a-zA-Z]+)\s*:\s*(.*)$", s)
            if not m:
                continue
            key, val = m.group(1).lower(), m.group(2).strip()
            if key in PARA_DIRECTIVES:
                flush(); pending[key] = val
            elif key in CHAPTER_DIRECTIVES and ch is not None:
                if key == "broll": ch.broll += [q.strip() for q in val.split("|") if q.strip()]
                elif key == "images": ch.images += [q.strip() for q in val.split("|") if q.strip()]
                elif key in ("source", "sources"): ch.sources += [u.strip() for u in re.split(r"[|\s]+", val) if u.strip()]
                elif key == "card": ch.card = val.lower() not in ("off", "no", "false", "0")
        elif s.startswith("#"):
            continue
        else:
            if ch is None:                           # text before the first chapter belongs to an implicit intro
                ch = Chapter(title="Intro", card=False)
                proj.chapters.append(ch)
            para.append(s)
    flush()
    proj.chapters = [c for c in proj.chapters if c.blocks]
    for i, c in enumerate(proj.chapters):
        for b in c.blocks:
            b.chapter = i
    return proj
