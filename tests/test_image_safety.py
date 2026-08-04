import io
import unittest

from PIL import Image

from wy_media.image_safety import ImageLimits, decode_image


def png_bytes(size: tuple[int, int] = (2, 2)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, (80, 120, 160)).save(output, format="PNG")
    return output.getvalue()


class ImageSafetyTest(unittest.TestCase):
    def test_decode_returns_rgb_for_allowed_static_image(self) -> None:
        image = decode_image(png_bytes())
        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.size, (2, 2))

    def test_pixel_limit_is_checked_before_decode(self) -> None:
        with self.assertRaisesRegex(ValueError, "pixel count"):
            decode_image(png_bytes((10, 10)), ImageLimits(max_pixels=10))

    def test_animated_image_is_held_by_decoder_boundary(self) -> None:
        output = io.BytesIO()
        first = Image.new("RGB", (2, 2), (0, 0, 0))
        second = Image.new("RGB", (2, 2), (255, 255, 255))
        first.save(output, format="GIF", save_all=True, append_images=[second], duration=100, loop=0)
        with self.assertRaisesRegex(ValueError, "animated"):
            decode_image(output.getvalue())


if __name__ == "__main__":
    unittest.main()
