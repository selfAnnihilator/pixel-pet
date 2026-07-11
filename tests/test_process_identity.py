import subprocess
import sys
import unittest


class ProcessIdentityTests(unittest.TestCase):
    def test_linux_process_name_is_pixel_pet(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from process_identity import set_process_name; "
                    "set_process_name('pixel-pet'); "
                    "print(open('/proc/self/comm', encoding='utf-8').read().strip())"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), "pixel-pet")


if __name__ == "__main__":
    unittest.main()
