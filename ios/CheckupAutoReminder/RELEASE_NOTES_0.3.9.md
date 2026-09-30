# Checkup Auto 0.3.9 (12)

- Expanded Dynamic Island: one amber line, “Pensez à votre contrôle technique”, beside the silver car. A 22-point bold condensed font scales only when the available width requires it.
- Expanded reminder content requests 116 points in height. iOS controls the final capsule size; the compact island remains system-sized and shows the car with a larger, single-line “CT” label.
- All three horn files are amplified by 2.39 dB to a peak of 32760/32767, without clipping PCM samples. This applies to both previews and scheduled notifications.
- iPhone alert volume and silent mode still control notification playback. This release does not change device volume.

Validation: PCM level/format/duration checks, existing Swift and simulator tests, and native visual review. Actual system island layout and perceived loudness require confirmation on an iPhone.
