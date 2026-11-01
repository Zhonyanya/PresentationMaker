"""Conservative fast refusal for explicit slide-structure commands.

This is not a general natural-language classifier. Other commands still go to
the model; all returned documents must pass the full revision invariants.
"""

import re

_QUOTED = re.compile(r'«[^»]*»|“[^”]*”|"[^"\n]*"')
_RU_POSITION = (
    r'(?:\d+(?:-?[йяе])?|первый|второй|третий|четв[её]ртый|пятый|шестой|'
    r'седьмой|восьмой|девятый|десятый|последний|предпоследний|новый|новые|'
    r'дополнительный|все|эти|этот)'
)
_EN_POSITION = (
    r'(?:\d+(?:st|nd|rd|th)?|a|an|the|new|another|first|second|third|fourth|'
    r'fifth|sixth|seventh|eighth|ninth|tenth|last|all|these|this)'
)
_STRUCTURAL = re.compile(
    r'\b(?:'
    r'(?:удали(?:те)?|добавь(?:те)?|вставь(?:те)?|переставь(?:те)?|перемести(?:те)?)'
    rf'\s+(?:{_RU_POSITION}\s+){{0,2}}слайд(?:ы|а|ов)?'
    r'|(?:поменяй(?:те)?|поменяйте)\s+местами\s+слайды'
    r'|(?:delete|remove|add|insert|move|reorder|swap)'
    rf'\s+(?:{_EN_POSITION}\s+){{0,3}}slides?'
    r'(?!\s+(?:title|body|heading|text|content|notes?|number|caption|subtitle)\b)'
    r')\b',
    re.IGNORECASE,
)


def reject_explicit_structure_change(instruction: str) -> None:
    # Quoted commands are content, e.g. "put «удали слайд» in the title".
    command = _QUOTED.sub(lambda match: ' ' * len(match[0]), instruction)
    for match in _STRUCTURAL.finditer(command):
        prefix = command[:match.start()].rstrip().casefold()
        if re.search(r"(?:\bне|\bnot|\bdon['’]t)\s*$", prefix):
            continue
        raise NotImplementedError('Slide structure changes are not supported')
