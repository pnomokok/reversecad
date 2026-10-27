"""Deterministic measurements from masks: card scale and part length in millimeters.

Simple scale without perspective correction: the card's minimum-area
rectangle gives one mm/px ratio from its long edge (85.60 mm) and one from its
short edge (53.98 mm), and their mean is used. This assumes a straight-down
shot; homography.py corrects tilted shots and checks for tilt.
"""
from dataclasses import dataclass

import cv2
import numpy as np

CARD_LONG_MM = 85.60
CARD_SHORT_MM = 53.98


@dataclass
class CardScale:
    mm_per_pixel_long: float
    mm_per_pixel_short: float
    rect: tuple  # cv2.minAreaRect result: ((cx, cy), (w, h), angle)

    @property
    def mm_per_pixel(self):
        return (self.mm_per_pixel_long + self.mm_per_pixel_short) / 2


def min_area_rect(mask):
    """Minimum-area rotated rectangle around the largest blob in the mask."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError("mask is empty")
    return cv2.minAreaRect(max(contours, key=cv2.contourArea))


def side_lengths_px(rect):
    """(long, short) side lengths of a minAreaRect in pixels."""
    width, height = rect[1]
    return max(width, height), min(width, height)


def card_scale(card_mask):
    rect = min_area_rect(card_mask)
    long_px, short_px = side_lengths_px(rect)
    return CardScale(CARD_LONG_MM / long_px, CARD_SHORT_MM / short_px, rect)


def long_side_mm(part_mask, mm_per_pixel):
    """Length of the part's minAreaRect long side, in millimeters."""
    rect = min_area_rect(part_mask)
    return side_lengths_px(rect)[0] * mm_per_pixel, rect
