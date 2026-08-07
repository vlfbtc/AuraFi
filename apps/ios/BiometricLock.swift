import Foundation
import LocalAuthentication

/// Which biometric hardware the current device exposes for the app lock.
enum BiometricKind: Equatable {
    case faceID
    case touchID
    case none

    /// Human-facing label used in buttons and settings copy.
    var label: String {
        switch self {
        case .faceID: return "Face ID"
        case .touchID: return "Touch ID"
        case .none: return "biometria"
        }
    }

    /// SF Symbol that matches the hardware.
    var systemImage: String {
        switch self {
        case .faceID: return "faceid"
        case .touchID: return "touchid"
        case .none: return "lock"
        }
    }
}

enum BiometricError: Error, Equatable {
    case unavailable
    case cancelled
    case failed
}

/// Abstraction over the biometric prompt so the lock flow can be driven by a
/// fake in tests and previews without touching real `LAContext` hardware.
protocol BiometricAuthenticating: Sendable {
    var availableBiometry: BiometricKind { get }
    func authenticate(reason: String) async -> Result<Void, BiometricError>
}

/// Production implementation backed by `LocalAuthentication`.
///
/// Uses `.deviceOwnerAuthentication` (biometrics *with* device-passcode
/// fallback) so a failed or unenrolled biometric never locks the user out of
/// their own account — the passcode always remains a valid escape hatch.
struct SystemBiometricAuthenticator: BiometricAuthenticating {
    var availableBiometry: BiometricKind {
        let context = LAContext()
        var error: NSError?
        // Passcode fallback requires a device passcode; if none is set the lock
        // simply stays dormant instead of trapping the user.
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            return .none
        }
        switch context.biometryType {
        case .faceID: return .faceID
        case .touchID: return .touchID
        default: return .none
        }
    }

    func authenticate(reason: String) async -> Result<Void, BiometricError> {
        let context = LAContext()
        var availabilityError: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &availabilityError) else {
            return .failure(.unavailable)
        }
        return await withCheckedContinuation { continuation in
            context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason) { success, error in
                if success {
                    continuation.resume(returning: .success(()))
                    return
                }
                let laError = error as? LAError
                switch laError?.code {
                case .userCancel, .appCancel, .systemCancel:
                    continuation.resume(returning: .failure(.cancelled))
                case .biometryNotAvailable, .biometryNotEnrolled, .passcodeNotSet:
                    continuation.resume(returning: .failure(.unavailable))
                default:
                    continuation.resume(returning: .failure(.failed))
                }
            }
        }
    }
}

/// Persists the user's opt-out for the biometric lock. Enabled by default so a
/// device that supports biometrics protects the session out of the box, while
/// remaining fully toggleable from Settings.
struct BiometricPreferenceStore {
    private let key = "aurafi.biometric-lock.enabled.v1"
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func isEnabled() -> Bool {
        guard defaults.object(forKey: key) != nil else { return true }
        return defaults.bool(forKey: key)
    }

    func setEnabled(_ enabled: Bool) {
        defaults.set(enabled, forKey: key)
    }
}
