"""Utilities for image encoding, Gemini response parsing, block name resolution,
and 2D-to-3D projection."""
import numpy as np
import json
import re


def encode_image_to_bytes(cv_image, fmt='png'):
    """Encode an OpenCV BGR image to PNG or JPEG bytes.

    Args:
        cv_image: OpenCV BGR image (numpy array).
        fmt: Output format, 'png' or 'jpeg'.

    Returns:
        bytes: Encoded image bytes.
    """
    import cv2
    if fmt == 'jpeg':
        _, buf = cv2.imencode('.jpg', cv_image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    else:
        _, buf = cv2.imencode('.png', cv_image)
    return buf.tobytes()


def parse_gemini_response(response_text):
    """Parse Gemini's JSON response, stripping code fences if present.

    Args:
        response_text: Raw text from Gemini API response.

    Returns:
        Parsed JSON (list or dict).

    Raises:
        json.JSONDecodeError: If the response is not valid JSON.
    """
    text = response_text.strip()
    # Strip markdown code fences
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return json.loads(text)


# Blocks are published to TF as 'Block1'..'Block9', but Gemini usually refers to
# them by the spawn color defined in isaacsim_scripts/three_robot_tower.py.
NUM_BLOCKS = 9

_BLOCK_COLORS = {
    'red': 1,
    'green': 2,
    'blue': 3,
    'yellow': 4,
    'magenta': 5,
    'cyan': 6,
    'orange': 7,
    'purple': 8,
    'lime': 9,
}


def resolve_block_key(label):
    """Resolve a free-form block reference to its canonical TF frame name.

    Gemini may name a block by index ('Block1', 'block_1', 'Block 1', '1') or by
    its color ('Red Cube', 'the purple cylinder'). Both are mapped to the
    'BlockN' frame published by the simulation.

    Args:
        label: Free-form block reference produced by Gemini.

    Returns:
        str: Canonical block key, e.g. 'Block1', or None if unresolvable.
    """
    if not isinstance(label, str):
        return None
    text = label.strip().lower()
    if not text:
        return None

    # Explicit index: 'Block1', 'block_1', 'block 1', 'block-1'
    match = re.search(r'block[\s_\-#]*(\d+)', text)
    if match is None:
        # Bare index: '1', '#3'
        match = re.fullmatch(r'#?\s*(\d+)', text)
    if match is not None:
        index = int(match.group(1))
        return f'Block{index}' if 1 <= index <= NUM_BLOCKS else None

    # Fall back to the block color (e.g. 'Red Cube' -> 'Block1')
    for color, index in _BLOCK_COLORS.items():
        if re.search(r'\b' + color + r'\b', text):
            return f'Block{index}'
    return None


def normalized_2d_to_pixel(y_norm, x_norm, img_height, img_width):
    """Convert Gemini's normalized [y, x] (0-1000) to pixel coordinates.

    Args:
        y_norm: Normalized y coordinate (0-1000).
        x_norm: Normalized x coordinate (0-1000).
        img_height: Image height in pixels.
        img_width: Image width in pixels.

    Returns:
        tuple: (py, px) pixel coordinates, clipped to image bounds.
    """
    px = int(x_norm / 1000.0 * img_width)
    py = int(y_norm / 1000.0 * img_height)
    px = np.clip(px, 0, img_width - 1)
    py = np.clip(py, 0, img_height - 1)
    return int(py), int(px)


def pixel_to_3d_world(px, py, depth_image, camera_intrinsics, camera_extrinsics):
    """Back-project a pixel coordinate to 3D world coordinates using depth.

    Args:
        px: Pixel x coordinate.
        py: Pixel y coordinate.
        depth_image: HxW depth image in meters.
        camera_intrinsics: 3x3 camera intrinsic matrix.
        camera_extrinsics: 4x4 camera-to-world transform.

    Returns:
        numpy.ndarray: [x, y, z] world coordinates, or None if depth is invalid.
    """
    z = depth_image[py, px]
    if z <= 0 or z > 10.0:
        return None

    fx, fy = camera_intrinsics[0, 0], camera_intrinsics[1, 1]
    cx, cy = camera_intrinsics[0, 2], camera_intrinsics[1, 2]

    x_cam = (px - cx) * z / fx
    y_cam = (py - cy) * z / fy
    z_cam = z

    p_cam = np.array([x_cam, y_cam, z_cam, 1.0])
    p_world = camera_extrinsics @ p_cam
    return p_world[:3]


def gemini_points_to_3d(detections, depth_image, camera_intrinsics, camera_extrinsics):
    """Convert a list of Gemini detection dicts to 3D world coordinates.

    Args:
        detections: List of {"point": [y, x], "label": str} dicts.
        depth_image: HxW depth image in meters.
        camera_intrinsics: 3x3 camera intrinsic matrix.
        camera_extrinsics: 4x4 camera-to-world transform.

    Returns:
        List of {"label": str, "world_pos": [x, y, z]} dicts.
    """
    h, w = depth_image.shape[:2]
    results = []
    for det in detections:
        y_norm, x_norm = det['point']
        py, px = normalized_2d_to_pixel(y_norm, x_norm, h, w)
        world_pos = pixel_to_3d_world(px, py, depth_image, camera_intrinsics, camera_extrinsics)
        if world_pos is not None:
            results.append({
                'label': det['label'],
                'world_pos': world_pos.tolist(),
                'pixel': [py, px],
                'normalized': [y_norm, x_norm]
            })
    return results
