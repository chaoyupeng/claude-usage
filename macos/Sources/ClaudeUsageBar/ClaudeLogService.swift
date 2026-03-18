import Foundation
import Combine

@MainActor
class ClaudeLogService: ObservableObject {
    @Published var stats: AggregatedStats?
    @Published var isLoading = false
    @Published var lastScanned: Date?
    @Published var lastError: String?

    func refresh() {
        guard !isLoading else { return }
        isLoading = true
        lastError = nil

        Task.detached {
            let result = ClaudeLogParser.scanAndAggregate()
            await MainActor.run { [weak self] in
                guard let self else { return }
                switch result {
                case .success(let stats):
                    self.stats = stats
                    self.lastError = nil
                case .failure(let error):
                    self.lastError = error.localizedDescription
                }
                self.lastScanned = Date()
                self.isLoading = false
            }
        }
    }
}

// MARK: - Parser (nonisolated, testable)

enum ClaudeLogParser {
    static let projectsDirectory: URL = {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".claude/projects", isDirectory: true)
    }()

    // Cached date formatters — created once, reused across all parsing
    private static let primaryDateFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    private static let fallbackDateFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    // File cache: skip re-parsing unchanged files
    private static var fileCache: [String: CachedFile] = [:]
    private static let cacheLock = NSLock()

    private struct CachedFile {
        let modDate: Date
        let fileSize: Int
        let records: [MessageRecord]
    }

    // MARK: - Public API

    static func scanAndAggregate() -> Result<AggregatedStats, Error> {
        let fm = FileManager.default
        guard fm.fileExists(atPath: projectsDirectory.path) else {
            return .success(AggregatedStats())
        }

        guard let enumerator = fm.enumerator(
            at: projectsDirectory,
            includingPropertiesForKeys: [.isRegularFileKey, .contentModificationDateKey, .fileSizeKey],
            options: [.skipsHiddenFiles]
        ) else {
            return .success(AggregatedStats())
        }

        var allRecords: [MessageRecord] = []
        var seenPaths = Set<String>()

        for case let fileURL as URL in enumerator {
            guard fileURL.pathExtension == "jsonl" else { continue }
            let path = fileURL.path
            seenPaths.insert(path)

            let resourceValues = try? fileURL.resourceValues(forKeys: [.contentModificationDateKey, .fileSizeKey])
            let modDate = resourceValues?.contentModificationDate
            let fileSize = resourceValues?.fileSize ?? 0

            // Check cache
            cacheLock.lock()
            let cached = fileCache[path]
            cacheLock.unlock()

            if let cached, let modDate,
               cached.modDate == modDate && cached.fileSize == fileSize {
                allRecords.append(contentsOf: cached.records)
                continue
            }

            // Parse and cache
            let records = parseJSONLFile(fileURL)
            if let modDate {
                cacheLock.lock()
                fileCache[path] = CachedFile(modDate: modDate, fileSize: fileSize, records: records)
                cacheLock.unlock()
            }
            allRecords.append(contentsOf: records)
        }

        // Evict deleted files from cache
        cacheLock.lock()
        fileCache = fileCache.filter { seenPaths.contains($0.key) }
        cacheLock.unlock()

        let stats = aggregate(allRecords)
        return .success(stats)
    }

    // MARK: - Date Parsing

    static func parseDate(_ string: String) -> Date? {
        primaryDateFormatter.date(from: string) ?? fallbackDateFormatter.date(from: string)
    }

    // MARK: - JSONL Parsing (Data-level, no String round-trip)

    static func parseJSONLFile(_ url: URL) -> [MessageRecord] {
        guard let data = try? Data(contentsOf: url) else { return [] }
        return parseJSONLData(data)
    }

    static func parseJSONLData(_ data: Data) -> [MessageRecord] {
        guard !data.isEmpty else { return [] }

        var records: [MessageRecord] = []
        let newline = UInt8(ascii: "\n")
        var start = data.startIndex

        while start < data.endIndex {
            let end = data[start...].firstIndex(of: newline) ?? data.endIndex
            let lineSlice = data[start..<end]
            start = min(end + 1, data.endIndex)

            guard !lineSlice.isEmpty else { continue }

            guard let json = try? JSONSerialization.jsonObject(with: lineSlice) as? [String: Any],
                  json["type"] as? String == "assistant" else {
                continue
            }

            guard let message = json["message"] as? [String: Any],
                  let model = message["model"] as? String,
                  let usageDict = message["usage"] as? [String: Any] else {
                continue
            }

            let sessionId = json["sessionId"] as? String ?? ""
            let timestampStr = json["timestamp"] as? String ?? ""
            guard let timestamp = parseDate(timestampStr) else { continue }

            let input = usageDict["input_tokens"] as? Int ?? 0
            let output = usageDict["output_tokens"] as? Int ?? 0
            let cacheRead = usageDict["cache_read_input_tokens"] as? Int ?? 0
            let cacheWrite = usageDict["cache_creation_input_tokens"] as? Int ?? 0

            let usage = TokenUsage(
                input: input, output: output,
                cacheRead: cacheRead, cacheWrite: cacheWrite
            )

            guard usage.total > 0 else { continue }

            records.append(MessageRecord(
                timestamp: timestamp,
                model: model,
                sessionId: sessionId,
                usage: usage
            ))
        }

        return records
    }

    // MARK: - Aggregation

    static func aggregate(_ records: [MessageRecord], now: Date = Date()) -> AggregatedStats {
        var stats = AggregatedStats()

        let calendar = Calendar.current
        let todayStart = calendar.startOfDay(for: now)
        let oneHourAgo = now.addingTimeInterval(-3600)

        var modelMap: [String: (count: Int, usage: TokenUsage)] = [:]
        var dayMap: [String: (count: Int, usage: TokenUsage)] = [:]
        var minuteMap: [Date: Int] = [:]

        for record in records {
            stats.totalUsage += record.usage
            stats.totalMessages += 1
            stats.sessionIds.insert(record.sessionId)
            stats.estimatedCost += CostEstimator.estimateCost(
                model: record.model, usage: record.usage
            )

            // Per-model
            var entry = modelMap[record.model] ?? (count: 0, usage: TokenUsage())
            entry.count += 1
            entry.usage += record.usage
            modelMap[record.model] = entry

            // Per-day — use dateComponents instead of DateFormatter (3.5)
            let comps = calendar.dateComponents([.year, .month, .day], from: record.timestamp)
            let dayKey = "\(comps.year!)-\(String(format: "%02d", comps.month!))-\(String(format: "%02d", comps.day!))"
            var dayEntry = dayMap[dayKey] ?? (count: 0, usage: TokenUsage())
            dayEntry.count += 1
            dayEntry.usage += record.usage
            dayMap[dayKey] = dayEntry

            // Today
            if record.timestamp >= todayStart {
                stats.todayUsage += record.usage
                stats.todayMessages += 1
            }

            // Last hour (per-minute buckets)
            if record.timestamp >= oneHourAgo {
                let minuteComps = calendar.dateComponents([.year, .month, .day, .hour, .minute], from: record.timestamp)
                if let minuteDate = calendar.date(from: minuteComps) {
                    minuteMap[minuteDate, default: 0] += record.usage.total
                }
            }
        }

        stats.modelBreakdown = modelMap.map { key, value in
            ModelStats(model: key, messageCount: value.count, usage: value.usage)
        }.sorted { $0.usage.total > $1.usage.total }

        stats.dailyBreakdown = buildDailyBreakdown(
            dayMap: dayMap, days: 14, calendar: calendar, today: todayStart
        )

        stats.lastHourMinutes = buildMinuteBreakdown(
            minuteMap: minuteMap, calendar: calendar, now: now
        )

        return stats
    }

    private static func buildDailyBreakdown(
        dayMap: [String: (count: Int, usage: TokenUsage)],
        days: Int,
        calendar: Calendar,
        today: Date
    ) -> [DailyStats] {
        (0..<days).reversed().map { offset in
            let date = calendar.date(byAdding: .day, value: -offset, to: today)!
            let comps = calendar.dateComponents([.year, .month, .day], from: date)
            let key = "\(comps.year!)-\(String(format: "%02d", comps.month!))-\(String(format: "%02d", comps.day!))"
            let entry = dayMap[key]
            return DailyStats(
                date: key,
                displayDate: date,
                messageCount: entry?.count ?? 0,
                usage: entry?.usage ?? TokenUsage()
            )
        }
    }

    private static func buildMinuteBreakdown(
        minuteMap: [Date: Int],
        calendar: Calendar,
        now: Date
    ) -> [MinuteStats] {
        let comps = calendar.dateComponents([.year, .month, .day, .hour, .minute], from: now)
        guard let currentMinute = calendar.date(from: comps) else { return [] }

        return (0..<60).reversed().map { offset in
            let minute = currentMinute.addingTimeInterval(Double(-offset) * 60)
            return MinuteStats(id: minute, tokens: minuteMap[minute] ?? 0)
        }
    }
}
