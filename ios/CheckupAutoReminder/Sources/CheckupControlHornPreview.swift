import AudioToolbox
import Foundation

/// A user-initiated sound preview; this never changes silent-mode or volume settings.
@MainActor
final class CheckupControlHornPreview {
    private var soundIDs: [CheckupControlHornChoice: SystemSoundID] = [:]

    func play(choice: CheckupControlHornChoice) throws {
        let soundID: SystemSoundID
        if let existing = soundIDs[choice] {
            soundID = existing
        } else {
            guard let url = Bundle.main.url(forResource: choice.soundName, withExtension: nil) else {
                throw IslandHornTestError.soundMissing
            }
            var created: SystemSoundID = 0
            let status = AudioServicesCreateSystemSoundID(url as CFURL, &created)
            guard status == kAudioServicesNoError, created != 0 else {
                throw CocoaError(.fileReadCorruptFile)
            }
            soundIDs[choice] = created
            soundID = created
        }
        AudioServicesPlaySystemSound(soundID)
    }

    deinit {
        for soundID in soundIDs.values { AudioServicesDisposeSystemSoundID(soundID) }
    }
}
