"""Theme preferences without loading the graphics stack during Bluetooth boot."""
import re

PALETTE = {'Blue':'#2214aa','Red':'#700c1d','Green':'#0a693b',
           'Amber':'#945109','Purple':'#62199a','Graphite':'#485568'}


def normalize_color(value):
    if not isinstance(value,str):raise ValueError('Enter a six-digit hex color')
    value=value.strip()
    if value.startswith('#'):value=value[1:]
    if not re.fullmatch('[0-9a-fA-F]{6}',value):raise ValueError('Enter a six-digit hex color')
    return '#'+value.upper()
