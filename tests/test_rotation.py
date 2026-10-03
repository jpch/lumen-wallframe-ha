# -*- coding: utf-8 -*-
"""Tests for rotation.py. Shared by the Pi app and the Home Assistant integration."""
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for _dir in (HERE, os.path.join(HERE, "..", "custom_components", "lume")):
    if os.path.isfile(os.path.join(_dir, "rotation.py")) and _dir not in sys.path:
        sys.path.insert(0, _dir)

from rotation import Rotation  # noqa: E402


def landscapes(n):
    return ["L%d" % i for i in range(n)]


def take(rotation, n):
    return [rotation.next() for _ in range(n)]


class RotationTests(unittest.TestCase):
    def test_empty_album(self):
        rotation = Rotation(random.Random(1))
        self.assertIsNone(rotation.next())
        self.assertEqual([], rotation.peek(2))

    def test_each_photo_once_per_cycle(self):
        ids = landscapes(12)
        for seed in range(50):
            rotation = Rotation(random.Random(seed))
            rotation.update(ids, set())
            for _cycle in range(5):
                shown = [slide[0] for slide in take(rotation, len(ids))]
                self.assertEqual(sorted(ids), sorted(shown))

    def test_order_is_shuffled(self):
        ids = landscapes(12)
        orders = set()
        for seed in range(10):
            rotation = Rotation(random.Random(seed))
            rotation.update(ids, set())
            orders.add(tuple(slide[0] for slide in take(rotation, len(ids))))
        self.assertGreater(len(orders), 5)
        self.assertNotIn(tuple(ids), orders)

    def test_no_repeat_across_cycles(self):
        for n in (2, 3, 5, 8):
            ids = landscapes(n)
            for seed in range(200):
                rotation = Rotation(random.Random(seed))
                rotation.update(ids, set())
                slides = take(rotation, n * 6)
                for before, after in zip(slides, slides[1:]):
                    self.assertNotEqual(before, after)
                if n >= 3:
                    # The last photo of a cycle is not in the first two of the next one.
                    for cycle in range(5):
                        last = slides[cycle * n + n - 1][0]
                        head = [s[0] for s in slides[(cycle + 1) * n:(cycle + 1) * n + 2]]
                        self.assertNotIn(last, head)

    def test_single_photo_repeats(self):
        rotation = Rotation(random.Random(3))
        rotation.update(["only"], set())
        self.assertEqual([["only"]] * 4, take(rotation, 4))

    def test_portraits_are_paired(self):
        ids = ["P%d" % i for i in range(6)] + landscapes(3)
        portraits = set(i for i in ids if i.startswith("P"))
        for seed in range(100):
            rotation = Rotation(random.Random(seed))
            rotation.update(ids, portraits)
            for _cycle in range(3):
                slides = take(rotation, 6)  # 3 pairs + 3 landscapes per cycle
                shown = [uid for slide in slides for uid in slide]
                self.assertEqual(sorted(ids), sorted(shown))
                for slide in slides:
                    if slide[0] in portraits:
                        self.assertEqual(2, len(slide))
                        self.assertTrue(all(uid in portraits for uid in slide))
                    else:
                        self.assertEqual(1, len(slide))

    def test_odd_portrait_shows_alone(self):
        ids = ["P0", "P1", "P2", "L0"]
        rotation = Rotation(random.Random(5))
        rotation.update(ids, {"P0", "P1", "P2"})
        slides = take(rotation, 3)
        self.assertEqual(sorted(ids), sorted(uid for slide in slides for uid in slide))
        self.assertEqual([1, 1, 2], sorted(len(slide) for slide in slides))

    def test_peek_does_not_consume(self):
        rotation = Rotation(random.Random(7))
        rotation.update(landscapes(6), set())
        ahead = rotation.peek(2)
        self.assertEqual(ahead, rotation.peek(2))
        self.assertEqual(ahead[0], rotation.next())
        self.assertEqual(ahead[1], rotation.next())

    def test_removed_photos_leave_plan_and_cycle(self):
        ids = landscapes(8)
        rotation = Rotation(random.Random(11))
        rotation.update(ids, set())
        ahead = rotation.peek(2)
        gone = ahead[0][0]
        rotation.update([i for i in ids if i != gone], set())
        rest = [slide[0] for slide in take(rotation, 7)]
        self.assertNotIn(gone, rest)
        self.assertEqual(sorted(i for i in ids if i != gone), sorted(rest))
        # The rest of the plan is kept in order.
        self.assertEqual(ahead[1][0], rest[0])

    def test_new_photos_join_current_cycle(self):
        ids = landscapes(6)
        rotation = Rotation(random.Random(13))
        rotation.update(ids, set())
        first = [slide[0] for slide in take(rotation, 2)]
        rotation.update(ids + ["NEW"], set())
        rest = [slide[0] for slide in take(rotation, 5)]
        self.assertIn("NEW", rest)
        self.assertEqual(sorted(ids + ["NEW"]), sorted(first + rest))

    def test_duplicates_are_ignored(self):
        rotation = Rotation(random.Random(2))
        rotation.update(["a", "b", "a"], set())
        self.assertEqual(2, rotation.size)


if __name__ == "__main__":
    unittest.main()
