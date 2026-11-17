import unittest

import renderer


class MessageBuilderTests(unittest.TestCase):
    def product(self, **kwargs):
        return {"name": "Example", "plans": [{"label": "Standard", "price": "10"}],
                "ticketLineMode": "show", **kwargs}

    def fields(self, result):
        return [field for message in result["messages"] for embed in message["embeds"]
                for field in embed.get("fields", [])]

    def test_custom_fields_are_in_payload_before_ticket_for_each_layout(self):
        for preset in ("modern", "minimal", "banner", "flash"):
            with self.subTest(preset=preset):
                result = renderer.render_content(self.product(preset=preset, customFields=[
                    {"name": "Compatibility", "value": "Windows 11", "inline": True},
                    {"name": "Support", "value": "Open a ticket", "inline": False},
                ]))
                self.assertTrue(result["ok"], result["errors"])
                fields = self.fields(result)
                custom = next(i for i, field in enumerate(fields) if field["name"] == "Compatibility")
                self.assertEqual(fields[custom]["value"], "Windows 11")
                self.assertTrue(fields[custom]["inline"])
                self.assertEqual(fields[custom + 1]["name"], "Support")
                self.assertEqual(fields[-1]["name"], renderer.DIVIDER)

    def test_incomplete_custom_field_blocks_send(self):
        result = renderer.render_content(self.product(customFields=[{"name": "Support", "value": ""}]))
        self.assertFalse(result["ok"])
        self.assertTrue(any("both a heading and a value" in error for error in result["errors"]))

    def test_empty_price_warns_instead_of_silently_showing_free(self):
        result = renderer.render_content(self.product(plans=[{"label": "Standard", "price": ""}]))
        self.assertTrue(any("Free" in warning for warning in result["warnings"]))
        paid = renderer.render_content(self.product())
        self.assertFalse(any("blank price" in warning for warning in paid["warnings"]))

    def test_oversized_field_returns_error_without_hanging(self):
        result = renderer.render_content(self.product(included="x" * 7000))
        self.assertFalse(result["ok"])
        self.assertTrue(any("1024" in error for error in result["errors"]))

    def test_existing_product_without_custom_fields(self):
        result = renderer.render_content(self.product(ticketLineMode="hide"))
        self.assertTrue(result["ok"], result["errors"])


class PricingRegressionTests(unittest.TestCase):
    def test_unnamed_priced_plan_is_not_dropped(self):
        content = {"name": "Example", "plans": [{"label": "", "price": "9.99"}], "ticketLineMode": "hide"}
        normalized = renderer.normalize_content(content)
        self.assertEqual(normalized["plans"][0]["label"], "Plan 1")
        self.assertEqual(normalized["plans"][0]["price"], "9.99")
        result = renderer.render_content(content)
        self.assertTrue(result["ok"], result["errors"])
        self.assertTrue(any("9.99" in field["value"] for message in result["messages"]
                            for embed in message["embeds"] for field in embed.get("fields", [])))


if __name__ == "__main__":
    unittest.main()
