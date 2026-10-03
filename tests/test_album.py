# -*- coding: utf-8 -*-
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for _dir in (HERE, os.path.join(HERE, "..", "custom_components", "lume")):
    if os.path.isfile(os.path.join(_dir, "album.py")) and _dir not in sys.path:
        sys.path.insert(0, _dir)

import album  # noqa: E402

PAGE = """
AF_initDataCallback({key: 'ds:1', hash: '2', data:[null,[
["AF1QipAAA",["https://lh3.googleusercontent.com/pw/abc",100,200],1],
["AF1QipBBB",["https://lh3.googleusercontent.com/pw/def",400,300],1],
["AF1QipAAA",["https://lh3.googleusercontent.com/pw/abc",100,200],1]
]]});</script>
"""

VIDEO_PAGE = r"""
AF_initDataCallback({key: 'ds:1', hash: '2', data:[null,[
["AF1QipPHOTO1",["https://lh3.googleusercontent.com/pw/p1",2048,1536,null,[null,null,1],[8614239]],1,"3VKB",0,1,["AF1QipOWNER"],[[2],[8]],2,{"15":321209,"101428965":[0,"vdhi7fmu"]}],
["AF1QipVIDEO1",["https://lh3.googleusercontent.com/pw/v1",1080,1920,null,[null,null,1],[7764346]],1,"WxhT",0,1,["AF1QipOWNER"],[[2],[8]],2,{"15":321209,"76647426":[9527,null,1080,1920,null,4,134,null,[[1,null,1080,1920]],0,null,null,null,["https://lh3.googleusercontent.com/pw/v1"]]}],
["AF1QipPHOTO2",["https://lh3.googleusercontent.com/pw/p2",1152,2048],1,"a ] tricky [ \" caption",0,{"15":1}],
["AF1QipVIDEO2",["https://lh3.googleusercontent.com/pw/v2",1920,1080],1,["https://video-downloads.googleusercontent.com/abc=dv"]],
["AF1QipVIDEO3",["https://lh3.googleusercontent.com/pw/v3",1920,1080],1,[{"mimeType":"video/mp4"}]],
["AF1QipVIDEO1",["https://lh3.googleusercontent.com/pw/v1",1080,1920],1]
]]});</script>
"""


class AlbumTests(unittest.TestCase):
    def test_parse_and_dedupe(self):
        found = []
        seen = set()
        for uid, remote, width, height in album.PHOTO_RE.findall(PAGE):
            if uid in seen:
                continue
            seen.add(uid)
            found.append((uid, int(width), int(height), remote))
        self.assertEqual(
            [
                ("AF1QipAAA", 100, 200, "https://lh3.googleusercontent.com/pw/abc"),
                ("AF1QipBBB", 400, 300, "https://lh3.googleusercontent.com/pw/def"),
            ],
            found,
        )
        self.assertTrue(found[0][1] < found[0][2])
        self.assertFalse(found[1][1] < found[1][2])

    def test_videos_are_dropped(self):
        found = album.parse_album_page(VIDEO_PAGE)
        self.assertEqual(["AF1QipPHOTO1", "AF1QipPHOTO2"], [item["id"] for item in found])
        self.assertEqual({"id": "AF1QipPHOTO2", "remote": "https://lh3.googleusercontent.com/pw/p2", "w": 1152, "h": 2048}, found[1])
        self.assertFalse(album.is_video('["AF1QipX",["https://lh3.googleusercontent.com/pw/x=w200-h200",1,1],"dvd"]'))

    def test_picker_videos(self):
        import google_photos

        self.assertTrue(google_photos.is_video({"type": "VIDEO", "mediaFile": {"mimeType": "image/jpeg"}}))
        self.assertTrue(google_photos.is_video({"type": "PHOTO", "mediaFile": {"mimeType": "video/mp4"}}))
        self.assertTrue(google_photos.is_video({"mediaFile": {"mediaFileMetadata": {"videoMetadata": {}}}}))
        self.assertFalse(google_photos.is_video({"type": "PHOTO", "mediaFile": {"mimeType": "image/jpeg"}}))

    def test_share_url(self):
        self.assertTrue(album.validate_share_url("https://photos.app.goo.gl/abc").endswith("abc"))
        self.assertTrue(album.validate_share_url("https://photos.google.com/share/AF1QipX?key=abc"))
        with self.assertRaises(album.AlbumError):
            album.validate_share_url("http://192.168.200.1/foto")
        with self.assertRaises(album.AlbumError):
            album.validate_share_url("https://photos.google.com/u/0/photos")

    def test_size_suffix(self):
        self.assertEqual(
            "https://lh3.googleusercontent.com/pw/abc=w1280-h1280",
            album.sized_url("https://lh3.googleusercontent.com/pw/abc=w200-h200"),
        )


if __name__ == "__main__":
    unittest.main()
