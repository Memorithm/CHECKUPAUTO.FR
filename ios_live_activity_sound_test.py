import wave
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOUND = ROOT / "ios" / "CheckupAutoReminder" / "Resources" / "checkupauto-horn.wav"
PROJECT = ROOT / "ios" / "CheckupAutoReminder" / "project.yml"
COORDINATOR = ROOT / "ios" / "CheckupAutoReminder" / "Sources" / "CheckupControlLiveActivityCoordinator.swift"
ATTRIBUTES = ROOT / "ios" / "CheckupAutoReminder" / "Shared" / "CheckupControlActivityAttributes.swift"


class IOSLiveActivitySoundTest(unittest.TestCase):
    def test_horn_is_short_pcm_wave(self):
        self.assertTrue(SOUND.is_file())
        self.assertLess(SOUND.stat().st_size, 64 * 1024)
        with wave.open(str(SOUND), "rb") as sound:
            self.assertEqual(sound.getnchannels(), 1)
            self.assertEqual(sound.getsampwidth(), 2)
            self.assertEqual(sound.getframerate(), 22050)
            duration = sound.getnframes() / sound.getframerate()
        self.assertGreater(duration, 0.2)
        self.assertLess(duration, 1.0)

    def test_horn_is_bundled_and_referenced_by_activitykit(self):
        project = PROJECT.read_text()
        coordinator = COORDINATOR.read_text()
        attributes = ATTRIBUTES.read_text()
        self.assertIn("path: Resources", project)
        self.assertIn("buildPhase: resources", project)
        self.assertIn('static let hornSoundName = "checkupauto-horn.wav"', attributes)
        self.assertIn("sound: .named(CheckupControlActivityPolicy.hornSoundName)", coordinator)


if __name__ == "__main__":
    unittest.main()
