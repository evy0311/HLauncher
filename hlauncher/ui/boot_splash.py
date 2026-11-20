"""Keep HDMI active and black until the paired launcher's first full UI frame."""
from PIL import Image


def render(size=(720,480)):
    return Image.new('RGB',size,'black')
