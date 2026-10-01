"""Pure validation tests; do not launch a game or send desktop input."""
import unittest
from agent import coordinate, key_code, literal_text, integer


class ValidationTests(unittest.TestCase):
    def test_coordinates_use_actual_rounded_image_height(self):
        self.assertEqual(coordinate(213, 114, (2560, 1369, 426, 228), (2560, 1369)), (1280, 684))

    def test_coordinates_expire_after_resize(self):
        with self.assertRaisesRegex(ValueError, "resized"):
            coordinate(10, 10, (854, 480, 426, 239), (900, 480))

    def test_uncaptured_coordinates_fail(self):
        with self.assertRaisesRegex(ValueError, "screenshot"):
            coordinate(1, 1, None, (854, 480))

    def test_outside_and_non_finite_coordinates_fail(self):
        for x, y in [(-1, 0), (426, 0), (0, 240), (float("nan"), 0), (float("inf"), 0), (True, 1)]:
            with self.subTest(x=x, y=y), self.assertRaises(ValueError):
                coordinate(x, y, (854, 480, 426, 240), (854, 480))

    def test_unicode_is_preserved(self):
        value = "Minecraft 한글 Ω 😀"
        self.assertEqual(literal_text(value), value)

    def test_control_text_is_rejected_before_input(self):
        for value in ["a\nb", "\t", "a\x00b", "\x7f", "a" * 4097, None, "\ud800"]:
            with self.subTest(value=repr(value)[:30]), self.assertRaises((ValueError, UnicodeError)):
                literal_text(value)

    def test_key_aliases(self):
        self.assertEqual(key_code("W"), 87)
        self.assertEqual(key_code("enter"), key_code("return"))
        self.assertEqual(key_code("f12"), 123)

    def test_unknown_keys_do_not_fall_back_to_other_keys(self):
        for value in ["super", "win", "f13", "typo", None]:
            with self.assertRaises(ValueError):
                key_code(value)

    def test_bounded_delays_reject_invalid_numbers(self):
        for value in [False, -1, 0, 60001, 1.5, float("inf"), "60"]:
            with self.assertRaises(ValueError):
                integer(value, "hold_ms", 1, 60000)


if __name__ == "__main__":
    unittest.main()
