"""M2 opt-in surface processing. These operations never invent missing anatomy."""

from __future__ import annotations

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter


def sculpt_depth(h: np.ndarray, amount: float, mask: np.ndarray | None = None) -> np.ndarray:
    if amount <= 0:
        return h
    weight = np.ones_like(h) if mask is None else np.clip(mask, 0, 1)

    def normalized_blur(sigma):
        divisor = gaussian_filter(weight, sigma)
        return gaussian_filter(h * weight, sigma) / np.maximum(divisor, 1e-6)

    small = normalized_blur(1.0)
    broad = normalized_blur(5.0)
    # Limit narrow high-amplitude residuals, rather than sharpening photo shadows.
    residual = small - broad
    target = broad + 0.045 * np.tanh(residual / 0.045)
    return np.clip(h * (1 - amount) + target * amount, 0, 1).astype(np.float32)


def guarded_detail(h: np.ndarray, luma: np.ndarray, amount: float, guard: float) -> np.ndarray:
    if amount <= 0:
        return h
    ordinary = luma - gaussian_filter(luma, 8.0)
    if guard <= 0:
        return (h + amount * 0.15 * ordinary).astype(np.float32)
    fine = gaussian_filter(luma, 0.8) - gaussian_filter(luma, 8.0)
    bounded = 0.08 * np.tanh(fine / 0.08)
    detail = (1 - guard) * ordinary + guard * bounded
    return (h + amount * 0.15 * detail).astype(np.float32)


def refine_cnc_surface(
    h: np.ndarray, width_mm: float, relief_mm: float, mask: np.ndarray | None = None
) -> np.ndarray:
    """Reduce narrow peaks and grooves, with a 0.18 mm maximum height change."""
    feature_mm = 1.2
    sigma = max(0.35, feature_mm * (h.shape[1] - 1) / width_mm * 0.35)
    if mask is None:
        average = gaussian_filter(h, sigma)
    else:
        weight = np.clip(mask, 0, 1)
        average = gaussian_filter(h * weight, sigma) / np.maximum(
            gaussian_filter(weight, sigma), 1e-6
        )
    allowance = 0.12 * feature_mm / relief_mm
    residual = h - average
    delta = allowance * np.tanh(residual / allowance) - residual
    limit = 0.25 * feature_mm / relief_mm
    return np.clip(h + 0.6 * np.clip(delta, -limit, limit), 0, 1).astype(np.float32)


def mask_alpha(
    mask: np.ndarray, width_mm: float, feather_mm: float, transition_mm: float
) -> np.ndarray:
    mask = np.clip(mask, 0, 1).astype(np.float32)
    if mask.min() >= 0.999:
        return np.ones_like(mask)
    if mask.max() < 0.001:
        return np.zeros_like(mask)
    pixels_per_mm = max(1, mask.shape[1] - 1) / width_mm
    soft = gaussian_filter(mask, max(0, feather_mm * pixels_per_mm * 0.5))
    distance = cv2.distanceTransform(
        (soft >= 0.5).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE
    )
    # Smooth the sampled distance gradient to avoid striped diagonal bevels.
    distance = gaussian_filter(distance, 0.8)
    t = np.clip(distance / max(1.5, transition_mm * pixels_per_mm), 0, 1)
    return np.clip(soft * t * t * (3 - 2 * t), 0, 1).astype(np.float32)
