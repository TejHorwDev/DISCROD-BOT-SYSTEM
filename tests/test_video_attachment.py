import io
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import app as application
import renderer


class VideoRendererTests(unittest.TestCase):
    def test_video_attached_to_last_message_and_invalid_path_rejected(self):
        content = {"name": "Product", "videoAttachment": "clip_123.mp4", "ticketLineMode": "hide"}
        result = renderer.render_content(content)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["messages"][-1]["video"], "clip_123.mp4")
        self.assertIn("clip_123.mp4", result["messages"][-1]["files"])
        content["videoAttachment"] = "../clip.mp4"
        self.assertFalse(renderer.render_content(content)["ok"])

    def test_video_on_split_message(self):
        content = {"name": "Product", "videoAttachment": "clip.webm", "preset": "minimal",
                   "features": "a " * 4000, "ticketLineMode": "hide"}
        result = renderer.render_content(content)
        self.assertTrue(result["ok"], result["errors"])
        self.assertGreater(len(result["messages"]), 1)
        self.assertEqual(result["messages"][-1]["video"], "clip.webm")
        self.assertTrue(all("video" not in msg for msg in result["messages"][:-1]))


class VideoUploadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patch = patch.object(application, "UPLOAD_DIR", self.directory.name)
        self.patch.start()
        self.client = application.app.test_client()
        with self.client.session_transaction() as session:
            session["authenticated"] = True
            session["user_id"] = "admin"

    def tearDown(self):
        self.patch.stop()
        self.directory.cleanup()

    def upload(self, data, name):
        return self.client.post("/api/upload-video", data={"file": (io.BytesIO(data), name)})

    def test_video_upload_and_resolve(self):
        response = self.upload(b"\x00\x00\x00\x18ftypisom" + b"data", "clip.mp4")
        self.assertEqual(response.status_code, 200)
        name = response.json["filename"]
        files, missing = application.resolve_upload_files([name])
        self.assertEqual(missing, [])
        self.assertEqual(files[0][2], "video/mp4")
        self.assertTrue(os.path.isfile(os.path.join(self.directory.name, name)))

    def test_invalid_and_oversized_files_are_rejected(self):
        self.assertEqual(self.upload(b"not video", "clip.mp4").status_code, 400)
        self.assertEqual(self.upload(b"x", "clip.exe").status_code, 400)
        self.assertEqual(self.upload(b"x" * (8 * 1024 * 1024 + 1), "clip.webm").status_code, 400)
        self.assertEqual(os.listdir(self.directory.name), [])

    def test_unauthenticated_upload_is_rejected(self):
        client = application.app.test_client()
        self.assertEqual(client.post("/api/upload-video").status_code, 401)

    def test_edit_keeps_existing_video_without_reupload_and_keeps_buttons(self):
        video = "clip_123.mp4"
        content = {"name": "Product", "videoAttachment": video, "ticketLineMode": "hide",
                   "buttons": [{"label": "Support", "url": "https://example.com"}]}
        entry = {"id": "hist", "message_ids": ["123"], "attachments": [
            {"id": "456", "filename": video, "message_index": 0}], "content": content}
        client = MagicMock()
        client.edit_message.return_value = {"id": "123", "attachments": entry["attachments"]}
        record = {"id": "bot", "display_name": "Bot"}
        result = renderer.render_content(content)
        with patch.object(application, "_find_history_entry", return_value=entry), \
                patch.object(application, "_bot_for_message_action", return_value=(record, client, None)), \
                patch.object(application, "render_for_bot", return_value=result), \
                patch.object(application, "_update_history_entry", return_value=entry):
            response = self.client.post("/api/messages/update", json={"channel_id": "999", "history_id": "hist", "content": content})
        self.assertEqual(response.status_code, 200, response.json)
        args, kwargs = client.edit_message.call_args
        self.assertEqual(args[2]["attachments"], [{"id": "456"}])
        self.assertEqual(args[2]["components"][0]["components"][0]["label"], "Support")
        self.assertIsNone(kwargs["files"])


if __name__ == "__main__":
    unittest.main()
