import unittest

from PIL import Image, ImageChops


class CatboneAssetTests(unittest.TestCase):
    def test_hunt_iris_moves_between_gaze_frames(self):
        sheet = Image.open("assets/catbone/hunt.png").convert("RGBA")
        forward = sheet.crop((0, 0, 64, 64))
        for gaze in (1, 3, 5, 7):
            with self.subTest(gaze=gaze):
                frame = sheet.crop((gaze * 64, 0, gaze * 64 + 64, 64))
                difference = ImageChops.difference(
                    forward.convert("RGB"), frame.convert("RGB")
                )
                self.assertIsNotNone(difference.getbbox())
                changed = sum(
                    pixel != (0, 0, 0) for pixel in difference.get_flattened_data()
                )
                self.assertGreaterEqual(changed, 20)

    def test_mouse_hunt_crouches_have_opaque_black_body_fill(self):
        sheet = Image.open("assets/catbone/hunt.png").convert("RGBA")

        frames = [(0, column) for column in range(9)]
        frames.extend((1, column) for column in range(5))
        for row, column in frames:
            with self.subTest(row=row, column=column):
                frame = sheet.crop(
                    (column * 64, row * 64, column * 64 + 64, row * 64 + 64)
                )
                black = white = transparent = 0
                pixels = frame.get_flattened_data()
                for red, _green, _blue, alpha in pixels:
                    if alpha == 0:
                        transparent += 1
                        continue
                    if red < 128:
                        black += 1
                    else:
                        white += 1
                self.assertGreaterEqual(
                    black,
                    150,
                    f"hunt frame row={row} column={column} is hollow",
                )
                self.assertGreater(black * 3, white)
                self.assertGreater(transparent, 2500)
                self.assertTrue(all(alpha in (0, 255) for *_rgb, alpha in pixels))


if __name__ == "__main__":
    unittest.main()
