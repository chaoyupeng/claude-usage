import Foundation

func isDiscouragedPollingOption(_ minutes: Int) -> Bool {
    minutes == 5 || minutes == 15
}

func pollingOptionLabel(
    for minutes: Int,
    locale: Locale = .autoupdatingCurrent,
    resourceBundle: Bundle? = claudeUsageBarResourceBundle()
) -> String {
    let interval = localizedPollingInterval(for: minutes, locale: locale)
    guard isDiscouragedPollingOption(minutes) else {
        return interval
    }

    let fallbackFormat = "%@ (not recommended)"
    let format = resourceBundle.map {
        NSLocalizedString(
            "polling.option.not_recommended",
            bundle: $0,
            value: fallbackFormat,
            comment: "Polling interval option label for refresh intervals that are discouraged"
        )
    } ?? fallbackFormat
    return String(format: format, locale: locale, interval)
}

func localizedPollingInterval(for minutes: Int, locale: Locale) -> String {
    let measurement: Measurement<UnitDuration>
    if minutes < 60 {
        measurement = Measurement(value: Double(minutes), unit: .minutes)
    } else {
        measurement = Measurement(value: Double(minutes) / 60.0, unit: .hours)
    }

    return measurement.formatted(
        .measurement(
            width: .narrow,
            usage: .asProvided,
            numberFormatStyle: .number.precision(.fractionLength(0)).locale(locale)
        )
    )
}
