import SwiftUI
import Charts

struct TokenDashboardView: View {
    @ObservedObject var logService: ClaudeLogService

    var body: some View {
        if logService.isLoading && logService.stats == nil {
            loadingView
        } else if let stats = logService.stats {
            statsContent(stats)
        } else {
            emptyView
        }
    }

    // MARK: - Loading Skeleton

    @ViewBuilder
    private var loadingView: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 0) {
                ForEach(0..<4, id: \.self) { _ in
                    VStack(spacing: 4) {
                        skeletonRect(width: 50, height: 16)
                        skeletonRect(width: 36, height: 8)
                    }
                    .frame(maxWidth: .infinity)
                }
            }
            skeletonRect(width: .infinity, height: 6)
            skeletonRect(width: .infinity, height: 60)
            skeletonRect(width: .infinity, height: 60)
        }
        .frame(maxWidth: .infinity, minHeight: 180)
        .redacted(reason: .placeholder)
    }

    @ViewBuilder
    private func skeletonRect(width: CGFloat, height: CGFloat) -> some View {
        RoundedRectangle(cornerRadius: 3)
            .fill(.quaternary)
            .frame(maxWidth: width == .infinity ? .infinity : width, minHeight: height, maxHeight: height)
    }

    // MARK: - Empty State

    @ViewBuilder
    private var emptyView: some View {
        VStack(spacing: 10) {
            Image(systemName: "chart.bar.xaxis")
                .font(.system(size: 28))
                .foregroundStyle(.tertiary)
            Text("No Claude Code logs found.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Button {
                logService.refresh()
            } label: {
                Label("Scan Logs", systemImage: "magnifyingglass")
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
        }
        .frame(maxWidth: .infinity, minHeight: 100, alignment: .center)
    }

    // MARK: - Stats Content

    @ViewBuilder
    private func statsContent(_ stats: AggregatedStats) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            headerGrid(stats)
            tokenBreakdownBar(stats.totalUsage)

            thinSeparator
            todaySection(stats)

            if !stats.lastHourMinutes.isEmpty {
                thinSeparator
                lastHourChart(stats.lastHourMinutes)
            }

            if !stats.dailyBreakdown.isEmpty {
                thinSeparator
                trendChart(stats.dailyBreakdown)
            }

            if !stats.modelBreakdown.isEmpty {
                thinSeparator
                modelsSection(stats)
            }

            footer
        }
    }

    private var thinSeparator: some View {
        Rectangle()
            .fill(.quaternary)
            .frame(height: 0.5)
    }

    // MARK: - Header

    @ViewBuilder
    private func headerGrid(_ stats: AggregatedStats) -> some View {
        HStack(spacing: 0) {
            statCell(value: TokenFormatter.format(stats.totalUsage.total), label: "tokens", color: .primary)
            statCell(value: "\(stats.sessionCount)", label: "sessions", color: .blue)
            statCell(value: "\(stats.totalMessages)", label: "messages", color: .orange)
            statCell(value: TokenFormatter.formatCost(stats.estimatedCost), label: "API est.", color: .green)
        }
    }

    @ViewBuilder
    private func statCell(value: String, label: String, color: Color) -> some View {
        VStack(spacing: 2) {
            Text(value)
                .font(.system(.title3, design: .rounded).monospacedDigit().bold())
                .foregroundStyle(color)
                .contentTransition(.numericText())
            Text(label)
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Token Breakdown Bar

    @ViewBuilder
    private func tokenBreakdownBar(_ usage: TokenUsage) -> some View {
        let total = max(usage.total, 1)
        GeometryReader { geo in
            HStack(spacing: 1) {
                breakdownSegment(width: segmentWidth(usage.cacheRead, total: total, in: geo), color: .blue.opacity(0.7))
                breakdownSegment(width: segmentWidth(usage.cacheWrite, total: total, in: geo), color: .purple.opacity(0.7))
                breakdownSegment(width: segmentWidth(usage.input, total: total, in: geo), color: .green)
                breakdownSegment(width: segmentWidth(usage.output, total: total, in: geo), color: .orange)
            }
            .clipShape(RoundedRectangle(cornerRadius: 3))
        }
        .frame(height: 6)

        HStack(spacing: 8) {
            legendDot(color: .blue.opacity(0.7), text: "\(TokenFormatter.format(usage.cacheRead)) cache read")
            legendDot(color: .purple.opacity(0.7), text: "\(TokenFormatter.format(usage.cacheWrite)) cache write")
            legendDot(color: .green, text: "\(TokenFormatter.format(usage.input)) input")
            legendDot(color: .orange, text: "\(TokenFormatter.format(usage.output)) output")
        }
        .font(.system(size: 8))
        .foregroundStyle(.secondary)
    }

    private func segmentWidth(_ count: Int, total: Int, in geo: GeometryProxy) -> CGFloat {
        max(CGFloat(count) / CGFloat(total) * geo.size.width, count > 0 ? 2 : 0)
    }

    @ViewBuilder
    private func breakdownSegment(width: CGFloat, color: Color) -> some View {
        Rectangle()
            .fill(color.gradient)
            .frame(width: width)
    }

    @ViewBuilder
    private func legendDot(color: Color, text: String) -> some View {
        HStack(spacing: 2) {
            Circle().fill(color).frame(width: 5, height: 5)
            Text(text)
        }
    }

    // MARK: - Today

    @ViewBuilder
    private func todaySection(_ stats: AggregatedStats) -> some View {
        HStack {
            Text("Today")
                .font(.subheadline.bold())
            Spacer()
            Text("~\(TokenFormatter.formatCost(todayCost(stats))) est.")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }

        HStack(alignment: .firstTextBaseline, spacing: 4) {
            Text(TokenFormatter.format(stats.todayUsage.total))
                .font(.system(.title2, design: .rounded).monospacedDigit().bold())
                .foregroundStyle(.blue)
                .contentTransition(.numericText())
            Text("tokens")
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            Text("\(stats.todayMessages) msgs")
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
        }

        tokenBreakdownBar(stats.todayUsage)
    }

    private func todayCost(_ stats: AggregatedStats) -> Double {
        guard stats.totalUsage.total > 0 else { return 0 }
        return stats.estimatedCost * Double(stats.todayUsage.total) / Double(stats.totalUsage.total)
    }

    // MARK: - Last Hour Chart

    @ViewBuilder
    private func lastHourChart(_ minutes: [MinuteStats]) -> some View {
        HStack {
            Text("Last Hour")
                .font(.subheadline.bold())
            Spacer()
            let totalLastHour = minutes.reduce(0) { $0 + $1.tokens }
            let avgPerMin = minutes.isEmpty ? 0 : totalLastHour / minutes.count
            HStack(spacing: 2) {
                Circle().fill(.orange).frame(width: 5, height: 5)
                Text("\(TokenFormatter.format(avgPerMin))/m")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.orange)
            }
        }

        Chart(minutes) { minute in
            BarMark(
                x: .value("Time", minute.id),
                y: .value("Tokens", minute.tokens)
            )
            .foregroundStyle(.orange.gradient)
            .cornerRadius(1)
        }
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: 3)) { _ in
                AxisValueLabel(format: .dateTime.hour().minute())
                    .font(.caption2)
            }
        }
        .chartYAxis {
            AxisMarks(values: .automatic(desiredCount: 3)) { value in
                AxisValueLabel {
                    if let v = value.as(Int.self) {
                        Text(TokenFormatter.format(v)).font(.caption2)
                    }
                }
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.3))
            }
        }
        .frame(height: 80)
    }

    // MARK: - 14-Day Trend

    @ViewBuilder
    private func trendChart(_ daily: [DailyStats]) -> some View {
        HStack {
            Text("14-Day Trend")
                .font(.subheadline.bold())
            Spacer()
        }

        Chart(daily) { day in
            BarMark(
                x: .value("Date", day.displayDate, unit: .day),
                y: .value("Messages", day.messageCount)
            )
            .foregroundStyle(.orange.opacity(0.6).gradient)
            .cornerRadius(2)
        }
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: 5)) { _ in
                AxisValueLabel(format: .dateTime.weekday(.abbreviated))
                    .font(.caption2)
            }
        }
        .chartYAxis {
            AxisMarks(values: .automatic(desiredCount: 3)) { value in
                AxisValueLabel {
                    if let v = value.as(Int.self) {
                        Text("\(v)").font(.caption2)
                    }
                }
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.3))
            }
        }
        .frame(height: 80)

        HStack(spacing: 8) {
            let totalMsgs = daily.reduce(0) { $0 + $1.messageCount }
            let totalTokens = daily.reduce(0) { $0 + $1.usage.total }
            let activeDays = daily.filter { $0.messageCount > 0 }.count
            let avgMsgs = activeDays > 0 ? totalMsgs / activeDays : 0
            summaryPill(icon: "circle", text: "\(avgMsgs) msgs/day")
            summaryPill(icon: "sum", text: "\(TokenFormatter.format(totalMsgs)) total msgs")
            summaryPill(icon: "number", text: "\(TokenFormatter.format(totalTokens)) tokens")
        }
        .font(.system(size: 9))
        .foregroundStyle(.secondary)
    }

    @ViewBuilder
    private func summaryPill(icon: String, text: String) -> some View {
        HStack(spacing: 2) {
            Image(systemName: icon)
                .font(.system(size: 7))
            Text(text)
        }
        .padding(.horizontal, 6)
        .padding(.vertical, 3)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 4))
    }

    // MARK: - Models

    @ViewBuilder
    private func modelsSection(_ stats: AggregatedStats) -> some View {
        HStack {
            Text("Models")
                .font(.subheadline.bold())
            Spacer()
            Text(TokenFormatter.format(stats.totalUsage.total))
                .font(.caption.monospacedDigit())
                .foregroundStyle(.tertiary)
        }

        // Stacked model bar
        let maxTokens = max(stats.totalUsage.total, 1)
        GeometryReader { geo in
            HStack(spacing: 1) {
                ForEach(stats.modelBreakdown) { model in
                    Rectangle()
                        .fill(modelColor(for: model.model).gradient)
                        .frame(width: max(CGFloat(model.usage.total) / CGFloat(maxTokens) * geo.size.width, 2))
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 3))
        }
        .frame(height: 6)

        ForEach(stats.modelBreakdown) { model in
            HStack(spacing: 6) {
                Circle()
                    .fill(modelColor(for: model.model))
                    .frame(width: 6, height: 6)
                Text(model.model)
                    .font(.caption)
                Spacer()
                Text("\(TokenFormatter.format(model.usage.input)) in")
                    .font(.system(size: 9).monospacedDigit())
                    .foregroundStyle(.secondary)
                Text("\(TokenFormatter.format(model.usage.output)) out")
                    .font(.system(size: 9).monospacedDigit().bold())
            }
        }
    }

    private func modelColor(for model: String) -> Color {
        let lowered = model.lowercased()
        if lowered.contains("opus") {
            return .orange
        } else if lowered.contains("haiku") {
            return .green
        } else {
            return .blue
        }
    }

    // MARK: - Footer

    @ViewBuilder
    private var footer: some View {
        thinSeparator
        HStack {
            if let scanned = logService.lastScanned {
                Text("Scanned \(scanned, style: .relative) ago")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Spacer()
            Button {
                logService.refresh()
            } label: {
                if logService.isLoading {
                    ProgressView()
                        .controlSize(.mini)
                } else {
                    Label("Refresh", systemImage: "arrow.clockwise")
                        .font(.caption)
                }
            }
            .buttonStyle(.borderless)
            .disabled(logService.isLoading)
        }
    }
}
