import Foundation

@main
struct MobileBootstrapSmoke {
    static func main() throws {
        let json = """
        {"schemaVersion":1,"reminders":{"leadDays":[60,30,15,7,1],"hour":9,"timezone":"Europe/Paris"},"booking":{"url":"https://rdv.checkupauto.fr/"},"notifications":{"remotePushActive":false,"localFallback":true},"referral":{"rewardCents":500,"currency":"EUR"},"app":{"landingUrl":"https://www.checkupauto.fr/app","available":false,"downloadPath":"/go/app"}}
        """.data(using: .utf8)!
        let config = try JSONDecoder().decode(MobileBootstrap.self, from: json).validated()
        precondition(config.reminders.leadDays == [60, 30, 15, 7, 1])
        precondition(config.booking.url == "https://rdv.checkupauto.fr/")
        precondition(config.referral.rewardCents == 500)
        print("MOBILE_BOOTSTRAP_SMOKE_OK")
    }
}
