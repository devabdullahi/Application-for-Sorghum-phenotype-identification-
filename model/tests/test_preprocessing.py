import numpy as np
from PIL import Image

from sorghum_model.preprocessing import load_model_input, square_and_resize


def test_crops_centre_square_before_resizing():
    # 6x2 image: red, green (centre 2x2), blue columns pairs.
    pixels = np.zeros((2, 6, 3), dtype=np.uint8)
    pixels[:, 0:2] = (255, 0, 0)
    pixels[:, 2:4] = (0, 255, 0)
    pixels[:, 4:6] = (0, 0, 255)
    result = square_and_resize(Image.fromarray(pixels), 2)
    assert result.shape == (2, 2, 3)
    assert (result == (0, 255, 0)).all()


def test_applies_exif_orientation(tmp_path):
    # Stored 4 wide x 2 tall, tagged "rotate 90" (orientation 6): upright it is 2 wide x 4 tall.
    pixels = np.zeros((2, 4, 3), dtype=np.uint8)
    pixels[:, :2] = 255  # left half white when stored
    image = Image.fromarray(pixels)
    exif = image.getexif()
    exif[0x0112] = 6
    path = tmp_path / "rotated.jpg"
    image.save(path, exif=exif, quality=100)
    upright = load_model_input(path, 2)
    # After rotating 90 degrees clockwise the white half is on top.
    assert upright[0].mean() > 200 and upright[1].mean() < 50
