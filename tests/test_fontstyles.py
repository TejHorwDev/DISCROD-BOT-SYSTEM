import unittest
import unicodedata

import fontstyles


class FontStyleTests(unittest.TestCase):
    def test_circled_digits_keep_their_values(self):
        self.assertEqual(fontstyles.apply_style("0123456789", "circled"), "⓪①②③④⑤⑥⑦⑧⑨")

    def test_script_lowercase_uses_assigned_unicode_characters(self):
        self.assertEqual(fontstyles.apply_style("ego", "script"), "ℯℊℴ")

    def test_all_alphabets_use_assigned_characters(self):
        for style in fontstyles.STYLE_ORDER:
            with self.subTest(style=style):
                styled = fontstyles.apply_style("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", style)
                self.assertEqual(len(styled), 62)
                self.assertTrue(all(unicodedata.category(c) != "Cn" for c in styled))

    def test_unknown_style_and_non_ascii_text_are_preserved(self):
        self.assertEqual(fontstyles.apply_style("Hello 🌟", "unknown"), "Hello 🌟")
        self.assertEqual(fontstyles.apply_style("é 🌟", "sans_bold"), "é 🌟")


if __name__ == "__main__":
    unittest.main()
