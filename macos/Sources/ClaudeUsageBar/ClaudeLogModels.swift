import Foundation

/// Token counts for a single message or aggregation.
struct TokenUsage {
    var input: Int = 0
    var output: Int = 0
    var cacheRead: Int = 0
    var cacheWrite: Int = 0
    /// Portion of `cacheWrite` written with a 1-hour TTL, which bills at 2x the
    /// input rate instead of 1.25x. This is a *subset* of `cacheWrite`, so it is
    /// never added into `total` — it only splits the write for pricing.
    var cacheWrite1h: Int = 0

    var total: Int { input + output + cacheRead + cacheWrite }

    /// Cache writes billed at the 5-minute rate (everything that isn't 1-hour).
    var cacheWrite5m: Int { max(cacheWrite - cacheWrite1h, 0) }

    static func + (lhs: TokenUsage, rhs: TokenUsage) -> TokenUsage {
        TokenUsage(
            input: lhs.input + rhs.input,
            output: lhs.output + rhs.output,
            cacheRead: lhs.cacheRead + rhs.cacheRead,
            cacheWrite: lhs.cacheWrite + rhs.cacheWrite,
            cacheWrite1h: lhs.cacheWrite1h + rhs.cacheWrite1h
        )
    }

    static func += (lhs: inout TokenUsage, rhs: TokenUsage) {
        lhs = lhs + rhs
    }
}

/// A single parsed assistant message from JSONL logs.
struct MessageRecord {
    let timestamp: Date
    let model: String
    let sessionId: String
    let usage: TokenUsage
    /// Claude Code writes one JSONL line per content block of a single API
    /// response, each repeating that response's `usage`. These two fields
    /// identify the response so the repeats can be collapsed.
    var messageId: String = ""
    var requestId: String = ""
    /// `usage.speed` — "fast" bills at the fast-mode premium.
    var speed: String? = nil
    /// `usage.inference_geo` — "us" adds a data-residency multiplier.
    var inferenceGeo: String? = nil
    /// `usage.server_tool_use.web_search_requests` — billed per search.
    var webSearchRequests: Int = 0

    /// Non-token inputs to this response's price.
    var billing: BillingContext {
        BillingContext(
            timestamp: timestamp,
            speed: speed,
            inferenceGeo: inferenceGeo,
            webSearchRequests: webSearchRequests
        )
    }
}

/// Everything other than token counts that affects what a response cost.
struct BillingContext {
    /// When the request was made. Promotional rates are date-gated, so cost has
    /// to be evaluated against the message's own timestamp, not "now".
    let timestamp: Date
    /// `usage.speed`; "fast" bills Opus 5 / Opus 4.8 at the premium tier.
    var speed: String? = nil
    /// `usage.inference_geo`; "us" applies a 1.1x multiplier to every token
    /// category. "global", "not_available" and nil are standard-priced.
    var inferenceGeo: String? = nil
    /// `usage.server_tool_use.web_search_requests`; charged per search on top
    /// of tokens.
    var webSearchRequests: Int = 0
}

/// Aggregated stats for a specific model (dynamic — never hardcoded).
struct ModelStats: Identifiable {
    var id: String { model }
    let model: String
    var messageCount: Int
    var usage: TokenUsage
}

/// Aggregated stats for a single calendar day.
struct DailyStats: Identifiable {
    var id: String { date }
    let date: String       // "yyyy-MM-dd"
    let displayDate: Date  // for chart X axis
    var messageCount: Int
    var usage: TokenUsage
}

/// Per-minute bucket for the "last hour" chart.
struct MinuteStats: Identifiable {
    let id: Date
    var tokens: Int
}

/// Top-level aggregated stats.
struct AggregatedStats {
    var totalUsage: TokenUsage = TokenUsage()
    var totalMessages: Int = 0
    var sessionIds: Set<String> = []
    var modelBreakdown: [ModelStats] = []
    var dailyBreakdown: [DailyStats] = []
    var todayUsage: TokenUsage = TokenUsage()
    var todayMessages: Int = 0
    var lastHourMinutes: [MinuteStats] = []
    var estimatedCost: Double = 0.0
    /// Today's cost, summed per message at that message's own model rate.
    /// Prorating `estimatedCost` by token share instead would assume every
    /// token cost the same, which is wrong whenever models are mixed.
    var todayCost: Double = 0.0
    /// Models priced by a family guess rather than a published rate. Non-empty
    /// means `estimatedCost` includes at least one guessed figure, which the UI
    /// marks rather than presenting as fact.
    var modelsWithoutPublishedRate: Set<String> = []

    var sessionCount: Int { sessionIds.count }

    /// Whether any part of the cost estimate came from a guessed rate.
    var costIncludesGuessedRate: Bool { !modelsWithoutPublishedRate.isEmpty }
}

// MARK: - Cost Estimation

enum CostEstimator {
    typealias Rate = (input: Double, output: Double)

    /// Published input/output price in USD per million tokens, per model.
    ///
    /// Keys are matched exact-first then longest-prefix, so `claude-opus-4`
    /// covers dated IDs like `claude-opus-4-20250514` without shadowing the
    /// longer `claude-opus-4-8`.
    ///
    /// IDs are normalised first (see `normalizedModelID`), which strips provider
    /// prefixes and the `[1m]` long-context suffix.
    ///
    /// Long-context requests are standard-priced on Claude 4.6 and later, so
    /// dropping `[1m]` is exact for those. On the older Sonnet 4 / 4.5 1M beta a
    /// long-context premium applied above 200K input tokens; that premium is not
    /// modelled here, so those sessions are under-estimated. Deliberately not
    /// guessed at — the rate is no longer published.
    private static let baseRates: [String: Rate] = [
        "claude-fable-5": (10.0, 50.0),
        "claude-mythos-5": (10.0, 50.0),
        "claude-opus-5": (5.0, 25.0),
        "claude-opus-4-8": (5.0, 25.0),
        "claude-opus-4-7": (5.0, 25.0),
        "claude-opus-4-6": (5.0, 25.0),
        "claude-opus-4-5": (5.0, 25.0),
        "claude-opus-4-1": (15.0, 75.0),
        "claude-opus-4": (15.0, 75.0),
        "claude-sonnet-5": (3.0, 15.0),  // promotional rate applied below
        "claude-sonnet-4-6": (3.0, 15.0),
        "claude-sonnet-4-5": (3.0, 15.0),
        "claude-sonnet-4": (3.0, 15.0),
        "claude-haiku-4-5": (1.0, 5.0),
        // Pre-Claude-4 IDs put the generation before the family
        // ("claude-3-5-haiku-20241022"), so they need their own keys — the
        // family-first spelling above never matches them.
        "claude-3-5-haiku": (0.80, 4.0),
    ]

    // Cache rates are fixed multiples of the model's input rate rather than
    // separate per-model constants: reads are 0.1x, 5-minute writes 1.25x,
    // and 1-hour writes 2x. Verified against every row of the published table.
    private static let cacheReadMultiplier = 0.10
    private static let cacheWrite5mMultiplier = 1.25
    private static let cacheWrite1hMultiplier = 2.0

    /// Sonnet 5 introductory pricing ($2/$10) runs through 2026-08-31; standard
    /// pricing ($3/$15) starts 2026-09-01. Boundary taken as UTC midnight — the
    /// published date carries no zone, so a few hours either side is possible.
    private static let sonnet5PromoRate: Rate = (2.0, 10.0)
    private static let sonnet5PromoEnd: Date = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar.date(from: DateComponents(year: 2026, month: 9, day: 1))!
    }()

    /// Fast mode bills Opus 5 / Opus 4.8 at a flat premium across the whole
    /// context window. It is unavailable on other models.
    private static let fastModeRate: Rate = (10.0, 50.0)
    private static let fastModeModels: Set<String> = ["claude-opus-5", "claude-opus-4-8"]

    /// `inference_geo: "us"` multiplies every token category by 1.1.
    private static let usDataResidencyMultiplier = 1.10

    /// Web search is billed at $10 per 1,000 searches.
    private static let costPerWebSearch = 0.01

    /// Estimated API cost for one response, in USD.
    static func estimateCost(model: String, usage: TokenUsage, billing: BillingContext) -> Double {
        guard let rate = rate(for: model, billing: billing) else { return 0.0 }

        let perMillion = { (tokens: Int, price: Double) in
            Double(tokens) / 1_000_000.0 * price
        }
        let tokenCost = perMillion(usage.input, rate.input)
            + perMillion(usage.output, rate.output)
            + perMillion(usage.cacheRead, rate.input * cacheReadMultiplier)
            + perMillion(usage.cacheWrite5m, rate.input * cacheWrite5mMultiplier)
            + perMillion(usage.cacheWrite1h, rate.input * cacheWrite1hMultiplier)

        // Data residency scales token pricing only, not per-search charges.
        let residency = billing.inferenceGeo?.lowercased() == "us" ? usDataResidencyMultiplier : 1.0
        let searchCost = Double(billing.webSearchRequests) * costPerWebSearch

        return tokenCost * residency + searchCost
    }

    /// Normalises a logged model ID for rate lookup.
    ///
    /// Bedrock and Vertex prefix the provider onto the ID
    /// (`anthropic.claude-opus-4-1-20250805`, `us.anthropic.claude-...`), and
    /// long-context variants suffix it (`claude-opus-5[1m]`). Prefix matching is
    /// anchored, so without stripping both, a prefixed ID matches nothing and
    /// silently falls through to a family guess.
    static func normalizedModelID(_ model: String) -> String {
        var id = model.lowercased()
        if let claudeStart = id.range(of: "claude")?.lowerBound {
            id = String(id[claudeStart...])
        }
        if let suffixStart = id.firstIndex(of: "[") {
            id = String(id[..<suffixStart])
        }
        return id.trimmingCharacters(in: CharacterSet(charactersIn: "-_. "))
    }

    /// Whether this model's cost is based on a published rate rather than a
    /// family guess. Callers surface the difference rather than presenting a
    /// guess as fact.
    static func hasPublishedRate(for model: String) -> Bool {
        let id = normalizedModelID(model)
        guard id != "<synthetic>" else { return true }
        return baseEntry(for: id) != nil
    }

    /// Resolves the rate in effect for this model at this point in time, or nil
    /// for entries that were never billed as API calls.
    private static func rate(for model: String, billing: BillingContext) -> Rate? {
        // Claude Code logs `<synthetic>` for messages it generated locally.
        // Checked before normalising, which would strip the angle brackets.
        guard model.lowercased() != "<synthetic>" else { return nil }

        let id = normalizedModelID(model)

        guard let (matchedKey, baseRate) = baseEntry(for: id) else {
            return fallbackRate(for: id)
        }

        // Fast mode replaces the base rate outright where it is supported.
        if billing.speed?.lowercased() == "fast", fastModeModels.contains(matchedKey) {
            return fastModeRate
        }

        if matchedKey == "claude-sonnet-5", billing.timestamp < sonnet5PromoEnd {
            return sonnet5PromoRate
        }

        return baseRate
    }

    /// Longest-prefix lookup, returning the matched key so callers can apply
    /// model-specific rules without re-deriving which model matched.
    private static func baseEntry(for normalizedID: String) -> (key: String, rate: Rate)? {
        if let exact = baseRates[normalizedID] { return (normalizedID, exact) }
        guard let match = baseRates
            .filter({ normalizedID.hasPrefix($0.key) })
            .max(by: { $0.key.count < $1.key.count })
        else { return nil }
        return (match.key, match.value)
    }

    /// Last-resort tier guess for an ID with no published rate — a model newer
    /// than this table, or one retired long enough to have been dropped from the
    /// pricing page (Opus 3, Sonnet 3.x, Haiku 3).
    ///
    /// This is a guess, and for retired models it is known to be wrong: Opus 3
    /// billed at $15/$75, not the $5/$25 the current Opus tier returns. Rather
    /// than bake in rates that are no longer published, `hasPublishedRate`
    /// reports when a guess was used so the UI can mark the total approximate.
    private static func fallbackRate(for normalizedID: String) -> Rate {
        if normalizedID.contains("fable") || normalizedID.contains("mythos") {
            return (10.0, 50.0)
        } else if normalizedID.contains("opus") {
            return (5.0, 25.0)
        } else if normalizedID.contains("haiku") {
            return (1.0, 5.0)
        } else {
            return (3.0, 15.0)  // Sonnet tier
        }
    }
}

// MARK: - Formatting Helpers

enum TokenFormatter {
    static func format(_ count: Int) -> String {
        if count >= 1_000_000_000 {
            return String(format: "%.1fB", Double(count) / 1_000_000_000.0)
        } else if count >= 1_000_000 {
            return String(format: "%.1fM", Double(count) / 1_000_000.0)
        } else if count >= 1_000 {
            return String(format: "%.1fK", Double(count) / 1_000.0)
        }
        return "\(count)"
    }

    static func formatCost(_ amount: Double) -> String {
        // printf rounds halves to even, so "$%.0f" renders 2100.5 as "$2100".
        // Money conventionally rounds halves up, so round to the displayed
        // precision first and hand printf an already-rounded value.
        if amount >= 1000 {
            return String(format: "$%.0f", roundedHalfUp(amount, places: 0))
        } else if amount >= 100 {
            return String(format: "$%.1f", roundedHalfUp(amount, places: 1))
        }
        return String(format: "$%.2f", roundedHalfUp(amount, places: 2))
    }

    /// Rounds to `places` decimals, breaking ties away from zero.
    private static func roundedHalfUp(_ value: Double, places: Int) -> Double {
        let factor = pow(10.0, Double(places))
        return (value * factor).rounded() / factor
    }
}
