"""Shared utility helpers used by multiple PetWindow mixins."""

# Sentinel prefix used by _say() to skip appearance-easter-egg text effects
# when _revert_appearance() speaks a revert line.
REVERT_TAG = "\x00REVERT\x00"


def match_words(q_lower: str, word_set: set) -> bool:
    """Return True if *q_lower* matches any word/phrase in *word_set*.

    Single-word entries are matched against individual tokens; multi-word
    phrases are matched as substrings of the cleaned input.
    """
    tokens = [tk.strip(".,;:!?¿¡\"'()") for tk in q_lower.split()]
    q_clean = " ".join(tokens)
    for w in word_set:
        if " " in w:
            if w in q_clean:
                return True
        else:
            if w in tokens:
                return True
    return False
