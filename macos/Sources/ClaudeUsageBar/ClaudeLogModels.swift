import Foundation

/// Token counts for a single message or aggregation.
struct TokenUsage {
    var input: Int = 0
    var output: Int = 0
    var cacheRead: Int = 0
    var cacheWrite: Int = 0

    var total: Int { input + output + cacheRead + cacheWrite }

    static func + (lhs: TokenUsage, rhs: TokenUsage) -> TokenUsage {
        TokenUsage(
            input: lhs.input + rhs.input,
            output: lhs.output + rhs.output,
            cacheRead: lhs.cacheRead + rhs.cacheRead,
            cacheWrite: lhs.cacheWrite + rhs.cacheWrite
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

    var sessionCount: Int { sessionIds.count }
}

// MARK: - Cost Estimation

enum CostEstimator {
    /// Approximate cost using pattern-matched model pricing.
    /// Model names are never hardcoded — pricing is determined by pattern matching.
    static func estimateCost(model: String, usage: TokenUsage) -> Double {
        let pricing = pricingForModel(model)
        let inputCost = Double(usage.input) / 1_000_000.0 * pricing.inputPerMillion
        let outputCost = Double(usage.output) / 1_000_000.0 * pricing.outputPerMillion
        let cacheReadCost = Double(usage.cacheRead) / 1_000_000.0 * pricing.cacheReadPerMillion
        let cacheWriteCost = Double(usage.cacheWrite) / 1_000_000.0 * pricing.cacheWritePerMillion
        return inputCost + outputCost + cacheReadCost + cacheWriteCost
    }

    private struct ModelPricing {
        let inputPerMillion: Double
        let outputPerMillion: Double
        let cacheReadPerMillion: Double
        let cacheWritePerMillion: Double
    }

    private static func pricingForModel(_ model: String) -> ModelPricing {
        let lowered = model.lowercased()
        if lowered.contains("opus") {
            return ModelPricing(
                inputPerMillion: 15.0, outputPerMillion: 75.0,
                cacheReadPerMillion: 1.50, cacheWritePerMillion: 18.75
            )
        } else if lowered.contains("haiku") {
            return ModelPricing(
                inputPerMillion: 0.25, outputPerMillion: 1.25,
                cacheReadPerMillion: 0.025, cacheWritePerMillion: 0.30
            )
        } else {
            // Default to Sonnet pricing
            return ModelPricing(
                inputPerMillion: 3.0, outputPerMillion: 15.0,
                cacheReadPerMillion: 0.30, cacheWritePerMillion: 3.75
            )
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
        if amount >= 1000 {
            return String(format: "$%.0f", amount)
        } else if amount >= 100 {
            return String(format: "$%.1f", amount)
        }
        return String(format: "$%.2f", amount)
    }
}
