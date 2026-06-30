"""Whitelists used by the SDV save parser.

Vendored from SDV-Summary's `sdv/validate.py`.
"""

MARRIAGE_CANDIDATES = [
    "Alex", "Elliott", "Harvey", "Sam", "Sebastian",
    "Abigail", "Haley", "Leah", "Maru", "Penny", "Shane", "Emily",
]

NON_MARRIAGE_CANDIDATES = [
    "Caroline", "Clint", "Demetrius", "Dwarf", "Evelyn", "George",
    "Gus", "Jas", "Jodi", "Kent", "Krobus", "Lewis", "Linus", "Marnie",
    "Pam", "Pierre", "Robin", "Sandy", "Vincent", "Willy", "Wizard",
    "Henchman",
]

NON_GIFTABLE_NPCS = [
    "Bouncer", "Gil", "Governor", "Grandpa", "Gunther", "Marlon",
    "Morris", "Mr. Qi", "Alex's Mom",
]

GIFTABLE_NPCS = MARRIAGE_CANDIDATES + NON_MARRIAGE_CANDIDATES
NPCS = GIFTABLE_NPCS + NON_GIFTABLE_NPCS

SEASONS = ["spring", "summer", "fall", "winter"]
