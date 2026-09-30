import wave
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOUND_ROOT = ROOT / "ios" / "CheckupAutoReminder" / "Resources"
SOUND_NAMES = ("checkupauto-horn.wav", "checkupauto-horn-double.wav", "checkupauto-horn-low.wav")
PROJECT = ROOT / "ios" / "CheckupAutoReminder" / "project.yml"
COORDINATOR = ROOT / "ios" / "CheckupAutoReminder" / "Sources" / "CheckupControlLiveActivityCoordinator.swift"
ATTRIBUTES = ROOT / "ios" / "CheckupAutoReminder" / "Shared" / "CheckupControlActivityAttributes.swift"


class IOSLiveActivitySoundTest(unittest.TestCase):
    def test_horn_is_short_pcm_wave(self):
        for name in SOUND_NAMES:
            with self.subTest(sound=name):
                path = SOUND_ROOT / name
                self.assertTrue(path.is_file())
                self.assertLess(path.stat().st_size, 64 * 1024)
                with wave.open(str(path), "rb") as sound:
                    self.assertEqual(sound.getnchannels(), 1)
                    self.assertEqual(sound.getsampwidth(), 2)
                    self.assertEqual(sound.getframerate(), 22050)
                    duration = sound.getnframes() / sound.getframerate()
                self.assertGreater(duration, 0.2)
                self.assertLess(duration, 1.0)

    def test_each_horn_uses_full_pcm_level_without_clipped_samples(self):
        for name in SOUND_NAMES:
            with self.subTest(sound=name):
                with wave.open(str(SOUND_ROOT / name), "rb") as sound:
                    data = sound.readframes(sound.getnframes())
                samples = [value[0] for value in struct.iter_unpack("<h", data)]
                self.assertGreaterEqual(max(map(abs, samples)), 32700)
                self.assertLess(max(samples), 32767)
                self.assertGreater(min(samples), -32768)

    def test_horn_is_bundled_and_referenced_by_activitykit(self):
        project = PROJECT.read_text()
        coordinator = COORDINATOR.read_text()
        attributes = ATTRIBUTES.read_text()
        self.assertIn("path: Resources", project)
        self.assertIn("buildPhase: resources", project)
        self.assertIn("CheckupControlHornChoice.current.soundName", attributes)
        self.assertIn("sound: .named(CheckupControlActivityPolicy.hornSoundName)", coordinator)


if __name__ == "__main__":
    unittest.main()
