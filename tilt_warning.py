"""Camera-tilt warning: a card that photographs as a trapezoid was shot at an angle.

Report-only: this module only reads a mask and formats a message; it never changes a
measurement. Live runs show the warning on the measurements screen (replay.analysis reads
it from the run's own card mask); run_real_photos.py prints it to the console.
"""
from homography import card_corners, edge_differences, largest_contour  # reused, not changed

TILT_WARNING_THRESHOLD = 0.02  # warn above this (why 0.02: measured values in CLAUDE.md)


def card_tilt(card_mask):
    """How far the card is from a rectangle in the photo: the largest relative length
    difference between opposite edges (left vs right, top vs bottom)."""
    return max(abs(d) for d in edge_differences(card_corners(largest_contour(card_mask))))


def tilt_warning(tilt):
    """Warning text for the measurements screen when the phone looks tilted; else None."""
    if tilt <= TILT_WARNING_THRESHOLD:
        return None
    return "Phone looks tilted \u2014 hold it parallel to the table and retake."
