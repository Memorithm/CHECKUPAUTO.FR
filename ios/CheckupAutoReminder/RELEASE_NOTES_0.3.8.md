# CheckupAuto 0.3.8 (11)

- In the compact Dynamic Island, the selected silver car and the two-line “Pensez au CT” label share the leading region, so the reminder begins immediately beside the car.
- A small amber bell occupies the trailing region; the full sentence remains beside the car in the expanded island and lock-screen presentation.
- The reminder uses bright amber on black and dark amber on the light lock-screen card.
- Continuous blinking is not implemented: ActivityKit controls Live Activity animation timing. The reminder remains readable and the car stays fixed.
- Native CI captures the in-app compact/expanded review and a background system screenshot. The simulator’s background screenshot does not prove physical Dynamic Island rendering; iPhone rendering remains subject to confirmation.

- The Dynamic Island demo also schedules a separate one-shot custom horn notification after five seconds, when notification sounds are enabled. Stopping or restarting the demo cancels its pending horn notification. A user-initiated “Écouter le klaxon” button previews the bundled sound; the system’s silent-mode and volume settings remain unchanged.
- Three selectable sounds are stored on the device: Court (original), Double (two original honks separated by 160 ms), and Grave (original played at 74% of its pitch/speed). The chosen sound applies to subsequent tests and newly scheduled ActivityKit alerts. Existing scheduled alerts keep the sound chosen when they were created.
