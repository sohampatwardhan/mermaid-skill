"""Text corpus substituted into every free-text field of every kept builder.

Every kept builder must accept each PLAIN string in every text field (Requirement 4.8).
Each HOSTILE string must either render cleanly through the pinned check or be rejected
with an IRError at the substituted JSON path (Requirements 4.1, 4.3, 4.4).
"""

PLAIN = (
    "Alpha",
    "Two words",
    "release 2 build 7",
    "Ünïcode 日本",
)

HOSTILE = (
    "Order (paid)",
    "a: b",
    'say "hi"',
    "it's",
    "a;b",
    "#tag",
    "[x]",
    "{y}",
    "<b>bold</b>",
    "end",
    "a|b",
    "back\\slash",
    "%%note",
    "`tick`",
    "---",
    "a, b",
    "-->",
)
