"""Low-resolution warning: a card that is small in the photo gives an uncertain scale.

Report-only: this module only reads a mask and formats a message; it never changes a
measurement. Live runs show the warning on the measurements screen (replay.analysis reads
it from the run's own card mask); run_real_photos.py prints it to the console.
"""
from measure import card_scale  # reused, not changed

MIN_CARD_PX = 600  # below this, small holes and edges lose precision (why 600: see CLAUDE.md)


def card_long_edge_px(card_mask):
    """Long edge of the card in pixels, from its mask."""
    return max(card_scale(card_mask).rect[1])


def resolution_warning(card_long_px):
    """Warning text for the measurements screen when the card is small; else None."""
    if card_long_px >= MIN_CARD_PX:
        return None
    return (f"The card is only {card_long_px:.0f} px long, so small holes and edges lose precision. "
            "Send the photo at original quality (messenger apps shrink photos).")
