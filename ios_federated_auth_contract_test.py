from pathlib import Path

ROOT=Path(__file__).resolve().parent
IOS=ROOT/"ios"/"CheckupAutoReminder"

def test_ios_federated_auth_contract():
    ent=(IOS/"CheckupAutoReminder.entitlements").read_text()
    project=(IOS/"project.yml").read_text()
    apple=(IOS/"Sources"/"AppleSignIn.swift").read_text()
    google=(IOS/"Sources"/"GoogleCustomerSignIn.swift").read_text()
    # The entry page and account card now share one authentication component.
    view=(IOS/"Sources"/"CustomerAuthenticationOptions.swift").read_text()
    welcome=(IOS/"Sources"/"PremiumWelcomeView.swift").read_text()
    model=(IOS/"Sources"/"AppModel.swift").read_text()

    assert "com.apple.developer.applesignin" in ent
    assert "<string>Default</string>" in ent
    assert "checkupauto" in project and "CFBundleURLSchemes" in project
    assert "AppleSignInNonce.sha256" in model
    assert 'MobileAPI.endpoint("/api/mobile/auth/apple")' in apple
    assert 'MobileAPI.endpoint("/api/mobile/auth/exchange")' in google
    assert 'callbackURLScheme: "checkupauto"' in google
    assert "SignInWithAppleButton" in view
    assert "Continuer avec Google" in view
    assert "CustomerAuthenticationOptions()" in welcome
    assert "Se connecter par e-mail" in view
    assert "CustomerSessionKeychain" in apple
    assert "CustomerSessionKeychain" in google
