import { useEffect, useMemo, useState } from "react";

const currency = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
});

const fallbackCategories = [
  "Food",
  "Transport",
  "Shopping",
  "Bills",
  "Entertainment",
  "Health",
  "Education",
  "Other",
  "Income",
];

const themes = [
  {
    id: "mint",
    name: "Clean Mint",
  },
  {
    id: "midnight",
    name: "Midnight Pro",
  },
];
const themeStorageKey = "expense-tracker-theme";

const navItems = [
  { id: "dashboard", label: "Dashboard", path: "/" },
  { id: "add", label: "Add", path: "/add" },
  { id: "transactions", label: "Transactions", path: "/transactions" },
  { id: "reports", label: "Reports", path: "/reports" },
  { id: "imports", label: "Imports", path: "/imports" },
  { id: "budgets", label: "Budgets", path: "/budgets" },
  { id: "cleanup", label: "Cleanup", path: "/cleanup" },
  { id: "settings", label: "Settings", path: "/settings" },
];

const monthBasedRoutes = new Set(["dashboard", "transactions", "reports", "budgets"]);

function padDatePart(value) {
  return String(value).padStart(2, "0");
}

function getLocalDateParts(date = new Date()) {
  return {
    year: date.getFullYear(),
    month: padDatePart(date.getMonth() + 1),
    day: padDatePart(date.getDate()),
  };
}

function getCurrentMonth() {
  const dateParts = getLocalDateParts();
  return `${dateParts.year}-${dateParts.month}`;
}

function getToday() {
  const dateParts = getLocalDateParts();
  return `${dateParts.year}-${dateParts.month}-${dateParts.day}`;
}

function getPreferredTheme() {
  const savedTheme = window.localStorage?.getItem(themeStorageKey);

  if (themes.some((theme) => theme.id === savedTheme)) {
    return savedTheme;
  }

  if (window.matchMedia?.("(prefers-color-scheme: dark)").matches) {
    return "midnight";
  }

  return "mint";
}

function formatAmount(value) {
  return currency.format(Number(value || 0));
}

function isPaymentRailMerchant(merchant) {
  const normalized = String(merchant || "").trim().toUpperCase();

  return ["BENEFITPAY", "BENEFIT PAY", "FAWRI", "FAWRI+", "BENEFITPAY / FAWRI+"].includes(
    normalized
  );
}

function filterRecurringMerchants(merchants = []) {
  return merchants.filter((merchant) => !isPaymentRailMerchant(merchant.merchant));
}

function getRouteFromPath(pathname) {
  if (pathname === "/login") {
    return "login";
  }

  if (/^\/invite\/[^/]+$/.test(pathname)) {
    return "invite";
  }

  if (/^\/day\/\d{4}-\d{2}-\d{2}$/.test(pathname)) {
    return "day";
  }

  if (pathname === "/add") {
    return "add";
  }

  if (pathname === "/transactions") {
    return "transactions";
  }

  if (pathname === "/reports") {
    return "reports";
  }

  if (pathname === "/imports") {
    return "imports";
  }

  if (pathname === "/budgets") {
    return "budgets";
  }

  if (pathname === "/cleanup") {
    return "cleanup";
  }

  if (pathname === "/settings" || pathname === "/app-settings") {
    return "settings";
  }

  return "dashboard";
}

function getDayFromPath(pathname) {
  const match = pathname.match(/^\/day\/(\d{4}-\d{2}-\d{2})$/);
  return match ? match[1] : "";
}

function getInviteTokenFromPath(pathname) {
  const match = pathname.match(/^\/invite\/([^/]+)$/);
  return match ? decodeURIComponent(match[1]) : "";
}

function getAssistantMessage(dashboard) {
  if (!dashboard) {
    return "Waiting for your spending picture to come into focus.";
  }

  if (dashboard.budget_warning) {
    return dashboard.budget_warning;
  }

  if (dashboard.unusual_alerts.length) {
    return "I found a few transactions worth reviewing this month.";
  }

  if (filterRecurringMerchants(dashboard.recurring_merchants).length) {
    return "Recurring merchants are visible. This is a good month to review subscriptions.";
  }

  return "Everything looks calm for the selected month.";
}

function buildQuery(params) {
  const query = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined && value !== false) {
      query.set(key, value);
    }
  });

  return query.toString();
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.error || `Request failed with ${response.status}`);
  }

  return data;
}

function SummaryCard({ label, value, detail, tone, readout }) {
  return (
    <article className={`metric-card ${tone || ""}`}>
      <span>{label}</span>
      <strong>{formatAmount(value)}</strong>
      <small>{detail}</small>
      {readout && <p className="metric-readout">{readout}</p>}
    </article>
  );
}

function EmptyState({ title, detail }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}

function LoadingDashboard() {
  return (
    <div className="loading-grid" aria-label="Loading dashboard">
      <div className="loading-card" />
      <div className="loading-card" />
      <div className="loading-card wide" />
    </div>
  );
}

function DashboardView({
  dashboard,
  loading,
  chartType,
  monthTransactions = [],
  onChartTypeChange,
  onDaySelect,
  onNavigate,
}) {
  const totalExpenses = Number(dashboard?.total_expenses || 0);
  const totalIncome = Number(dashboard?.total_income || 0);
  const fallbackNetSpent = totalExpenses - totalIncome;
  const rawNetSpent = Number(dashboard?.net_spent);
  const netSpent =
    Number.isFinite(rawNetSpent) && (rawNetSpent !== 0 || fallbackNetSpent === 0)
      ? rawNetSpent
      : fallbackNetSpent;
  const categoryRows = useMemo(() => {
    const rows = dashboard?.category_chart_rows || [];
    const categoryTotal = rows.reduce((sum, row) => sum + Number(row.total || 0), 0);

    if (!rows.length || categoryTotal <= 0 || Math.abs(categoryTotal - netSpent) <= 0.01) {
      return rows;
    }

    const netRatio = Math.max(netSpent, 0) / categoryTotal;
    return rows
      .map((row) => ({
        ...row,
        gross_total: row.gross_total ?? row.total,
        total: Number(row.total || 0) * netRatio,
      }))
      .filter((row) => Number(row.total || 0) > 0);
  }, [dashboard?.category_chart_rows, netSpent]);
  const maxCategoryTotal = useMemo(() => {
    if (!categoryRows.length) {
      return 0;
    }

    return Math.max(...categoryRows.map((row) => row.total));
  }, [categoryRows]);

  const pieSegments = useMemo(() => {
    if (!categoryRows.length) {
      return [];
    }

    const total = categoryRows.reduce(
      (sum, row) => sum + Number(row.total || 0),
      0
    );
    let cursor = 0;

    return categoryRows.map((row) => {
      const percent = total ? (Number(row.total || 0) / total) * 100 : 0;
      const segment = {
        ...row,
        percent,
        start: cursor,
        end: cursor + percent,
      };
      cursor += percent;
      return segment;
    });
  }, [dashboard]);

  const pieBackground = useMemo(() => {
    if (!pieSegments.length) {
      return "var(--surface-muted)";
    }

    return `conic-gradient(${pieSegments
      .map((segment) => `${segment.color} ${segment.start}% ${segment.end}%`)
      .join(", ")})`;
  }, [pieSegments]);

  if (loading) {
    return <LoadingDashboard />;
  }

  if (!dashboard) {
    return null;
  }

  const monthlyBudgetLimit = Number(dashboard.monthly_budget_limit || 0);
  const monthlyBudgetPercentRaw = monthlyBudgetLimit
    ? (netSpent / monthlyBudgetLimit) * 100
    : 0;
  const monthlyBudgetPercentDisplay = Math.max(monthlyBudgetPercentRaw, 0);
  const monthlyBudgetPercent = Math.min(Math.max(monthlyBudgetPercentRaw, 0), 100);
  const monthlyBudgetTone =
    monthlyBudgetPercentRaw >= 100
      ? "over"
      : monthlyBudgetPercentRaw >= 80
        ? "warning"
        : "good";
  const predictionOverBudget =
    dashboard.selected_month.is_current &&
    monthlyBudgetLimit > 0 &&
    Number(dashboard.monthly_prediction || 0) > monthlyBudgetLimit;
  const fallbackInsights = [];

  if (categoryRows.length) {
    fallbackInsights.push({
      type: "top_category",
      tone: "info",
      text: `You spent most on ${categoryRows[0].category}.`,
    });
  }

  if (monthlyBudgetLimit) {
    const budgetPercent = Math.round(
      ((dashboard.selected_month.is_current
        ? Number(dashboard.monthly_prediction || 0)
        : netSpent) /
        monthlyBudgetLimit) *
        100
    );
    fallbackInsights.push({
      type: "budget_pace",
      tone: budgetPercent >= 90 ? "warning" : "good",
      text: `You are on pace to use ${budgetPercent}% of your budget.`,
    });
  }

  if (dashboard.pending_import_reviews) {
    fallbackInsights.push({
      type: "review_queue",
      tone: "warning",
      text: `${dashboard.pending_import_reviews} import${
        dashboard.pending_import_reviews === 1 ? "" : "s"
      } need review.`,
    });
  }

  const dashboardTransactions = monthTransactions.length
    ? monthTransactions
    : dashboard.recent_transactions || [];
  const recurringMerchants = filterRecurringMerchants(dashboard.recurring_merchants);

  if (dashboardTransactions.length) {
    const biggestRecent = [...dashboardTransactions]
      .filter((transaction) => transaction.category !== "Income")
      .sort((a, b) => Number(b.amount || 0) - Number(a.amount || 0))[0];

    if (biggestRecent) {
      fallbackInsights.push({
        type: "biggest_transaction",
        tone: "info",
        text: `Your biggest recent transaction was ${
          biggestRecent.display_merchant
        }, BHD ${formatAmount(biggestRecent.amount)}.`,
      });
    }
  }

  const monthlyInsights = dashboard.monthly_insights?.length
    ? dashboard.monthly_insights
    : fallbackInsights;
  const fallbackDailyTotals = dashboardTransactions.reduce(
    (totals, transaction) => {
      const amount = Number(transaction.amount || 0);
      totals[transaction.date] =
        (totals[transaction.date] || 0) +
        (transaction.category === "Income" ? -amount : amount);
      return totals;
    },
    {}
  );
  const [selectedYear, selectedMonthNumber] = dashboard.selected_month.value
    .split("-")
    .map(Number);
  const selectedMonthStart = new Date(selectedYear, selectedMonthNumber - 1, 1);
  const fallbackCalendarDays = Array.from(
    { length: dashboard.selected_month.days_in_month || 0 },
    (_, index) => {
      const dayNumber = index + 1;
      const date = `${dashboard.selected_month.value}-${padDatePart(dayNumber)}`;
      const total = fallbackDailyTotals[date] || 0;

      return {
        date,
        day: dayNumber,
        total,
        has_spending: total !== 0,
        is_today: date === getToday(),
      };
    }
  );
  const fallbackMaxDailySpending = Math.max(
    0,
    ...Object.values(fallbackDailyTotals).map((total) => Math.abs(total))
  );
  const calendar = dashboard.calendar_spending?.days?.length
    ? dashboard.calendar_spending
    : {
        leading_blank_days: (selectedMonthStart.getDay() + 6) % 7,
        days: fallbackCalendarDays,
        max_daily_spending: fallbackMaxDailySpending,
      };
  const todayString = getToday();

  return (
    <>
      <section className="metric-grid">
        <SummaryCard
          label="Today"
          value={dashboard.today_spending}
          detail="Recorded today"
        />
        <SummaryCard
          label="Expenses"
          value={dashboard.total_expenses}
          detail={`For ${dashboard.selected_month.label}`}
          tone="expense"
        />
        <SummaryCard
          label="Money in"
          value={dashboard.total_income}
          detail="Money received"
          tone="income"
        />
        <SummaryCard
          label="Net spent"
          value={netSpent}
          detail="Expenses minus money in"
          tone={netSpent >= 0 ? "expense" : "income"}
        />
        <SummaryCard
          label={dashboard.selected_month.is_current ? "Prediction" : "Month total"}
          value={dashboard.monthly_prediction}
          detail={
            dashboard.selected_month.is_current
              ? "Projected net"
              : "Net selected month"
          }
          tone={predictionOverBudget ? "warning" : ""}
          readout={getAssistantMessage(dashboard)}
        />
      </section>

      <section className="dashboard-budget-card">
        <div className="budget-card-readout">
          <strong>{formatAmount(netSpent)}</strong>
          <span>
            {monthlyBudgetLimit
              ? `${Math.round(monthlyBudgetPercentDisplay)}% of ${formatAmount(monthlyBudgetLimit)}`
              : "Monthly budget tracks net spent"}
          </span>
        </div>
        <div className="bar-track dashboard-budget-track">
          <div
            className={`bar-fill budget-total-fill ${monthlyBudgetTone}`}
            style={{ width: `${monthlyBudgetPercent}%` }}
          />
          <span className="bar-percent">
            {monthlyBudgetLimit
              ? `${Math.round(monthlyBudgetPercentDisplay)}% used`
              : "Set a budget"}
          </span>
        </div>
      </section>

      <section className="dashboard-grid monthly-overview-grid">
        <article className="panel monthly-insights-panel">
          <div className="panel-title">
            <div>
              <span>Month at a glance</span>
              <h2>{dashboard.selected_month.label}</h2>
            </div>
          </div>

          {monthlyInsights.length ? (
            <ul className="monthly-insight-list">
              {monthlyInsights.map((insight) => (
                <li className={insight.tone} key={`${insight.type}-${insight.text}`}>
                  <span aria-hidden="true" />
                  <p>{insight.text}</p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No monthly insights yet"
              detail="Add transactions to build a useful monthly readout."
            />
          )}
        </article>

        <article className="panel calendar-panel">
          <div className="panel-title">
            <div>
              <span>Calendar view</span>
              <h2>Daily spending</h2>
            </div>
          </div>

          <div className="calendar-weekdays" aria-hidden="true">
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => (
              <span key={day}>{day}</span>
            ))}
          </div>
          <div className="calendar-grid">
            {Array.from({ length: calendar.leading_blank_days || 0 }).map((_, index) => (
              <span className="calendar-blank" key={`blank-${index}`} />
            ))}
            {calendar.days.map((day) => {
              const dailyPercent = calendar.max_daily_spending
                ? Math.abs(Number(day.total || 0)) / calendar.max_daily_spending
                : 0;
              const isFutureDay = day.date > todayString;
              const isNoSpendDay = !day.has_spending && !isFutureDay;

              return (
                <button
                  className={`calendar-day${day.has_spending ? " has-spending" : ""}${
                    isNoSpendDay ? " no-spend" : ""
                  }${isFutureDay ? " future-day" : ""}${day.is_today ? " today" : ""}`}
                  disabled={isFutureDay}
                  key={day.date}
                  type="button"
                  style={{
                    "--spend-alpha": Math.min(0.3, 0.08 + dailyPercent * 0.26),
                  }}
                  title={
                    isFutureDay
                      ? `${day.date}: future day`
                      : `${day.date}: BHD ${formatAmount(day.total)}`
                  }
                  onClick={() => {
                    if (!isFutureDay) {
                      onDaySelect(day.date);
                    }
                  }}
                >
                  <strong>{day.day}</strong>
                  <span>
                    {day.has_spending ? formatAmount(day.total) : isFutureDay ? "" : "No spend"}
                  </span>
                </button>
              );
            })}
          </div>
        </article>
      </section>

      <section className="dashboard-grid">
        <article className="panel chart-panel">
          <div className="panel-title">
            <div>
              <span>Visual breakdown</span>
              <h2>Category spending</h2>
            </div>
            <div className="chart-toggle" aria-label="Chart type">
              <button
                className={chartType === "pie" ? "active" : ""}
                type="button"
                onClick={() => onChartTypeChange("pie")}
              >
                Pie
              </button>
              <button
                className={chartType === "bar" ? "active" : ""}
                type="button"
                onClick={() => onChartTypeChange("bar")}
              >
                Bar
              </button>
            </div>
          </div>

          {categoryRows.length ? (
            chartType === "pie" ? (
              <div className="pie-layout">
                <div
                  className="pie-chart"
                  style={{ background: pieBackground }}
                  aria-label="Category spending pie chart"
                >
                  <div>
                    <span>Total</span>
                    <strong>{formatAmount(netSpent)}</strong>
                  </div>
                </div>
                <ul className="pie-legend">
                  {pieSegments.map((segment) => (
                    <li key={segment.category}>
                      <span
                        className="category-dot"
                        style={{ background: segment.color }}
                      />
                      <strong>{segment.category}</strong>
                      <em>{Math.round(segment.percent)}%</em>
                      <small>{formatAmount(segment.total)}</small>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="bar-list">
                {categoryRows.map((category) => {
                  const percent = maxCategoryTotal
                    ? (category.total / maxCategoryTotal) * 100
                    : 0;

                  return (
                    <div className="bar-row" key={category.category}>
                      <div className="bar-row-label">
                        <span
                          className="category-dot"
                          style={{ background: category.color }}
                        />
                        <strong>{category.category}</strong>
                        <span>{formatAmount(category.total)}</span>
                      </div>
                      <div className="bar-track">
                        <div
                          className="bar-fill"
                          style={{
                            width: `${percent}%`,
                            background: category.color,
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            )
          ) : (
            <EmptyState
              title="No category spending"
              detail="Add or import transactions to build the chart."
            />
          )}
        </article>

        <article className="panel recent-panel">
          <div className="panel-title">
            <div>
              <span>Latest activity</span>
              <h2>Recent transactions</h2>
            </div>
            <button
              className="text-link"
              type="button"
              onClick={() => onNavigate("transactions")}
            >
              View all
            </button>
          </div>

          {dashboard.recent_transactions.length ? (
            <ul className="transaction-list">
              {dashboard.recent_transactions.map((transaction) => (
                <li
                  className={transaction.category === "Income" ? "income-row" : ""}
                  key={transaction.id}
                >
                  <div>
                    <strong>{transaction.display_merchant}</strong>
                    <span>
                      {transaction.date} - {transaction.category}
                    </span>
                  </div>
                  <em
                    className={transaction.category === "Income" ? "income-text" : ""}
                  >
                    {transaction.category === "Income" ? "+" : ""}
                    {formatAmount(transaction.amount)}
                  </em>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No recent transactions"
              detail="This month is quiet so far."
            />
          )}
        </article>
      </section>

      <section className="insight-grid">
        {dashboard.pending_import_reviews ? (
          <article className="panel review-queue-panel">
            <div className="panel-title">
              <div>
                <span>Import safety</span>
                <h2>Review queue</h2>
              </div>
              <strong>{dashboard.pending_import_reviews}</strong>
            </div>
            <p className="panel-note">
              Some SMS imports were parsed but need confirmation before becoming
              transactions.
            </p>
            <button
              className="primary-button"
              type="button"
              onClick={() => onNavigate("imports")}
            >
              Review imports
            </button>
          </article>
        ) : null}

        <article className="panel">
          <div className="panel-title">
            <div>
              <span>Pattern watch</span>
              <h2>Recurring merchants</h2>
            </div>
          </div>

          {recurringMerchants.length ? (
            <ul className="compact-list">
              {recurringMerchants.map((merchant) => (
                <li key={merchant.merchant}>
                  <div>
                    <strong>{merchant.merchant}</strong>
                    <span>
                      {merchant.transaction_count} times across{" "}
                      {merchant.months_seen} month
                      {merchant.months_seen === 1 ? "" : "s"}
                    </span>
                  </div>
                  <em>{formatAmount(merchant.average_amount)}</em>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No repeated merchants yet"
              detail="Subscriptions and repeated spending will appear here."
            />
          )}
        </article>

        <article className="panel alert-panel">
          <div className="panel-title">
            <div>
              <span>Review queue</span>
              <h2>Unusual alerts</h2>
            </div>
          </div>

          {dashboard.unusual_alerts.length ? (
            <ul className="compact-list alert-list">
              {dashboard.unusual_alerts.map((alert) => (
                <li key={`${alert.transaction.id}-${alert.reason}`}>
                  <div>
                    <strong>{alert.transaction.display_merchant}</strong>
                    <span>{alert.reason}</span>
                  </div>
                  <em>{formatAmount(alert.transaction.amount)}</em>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No alerts"
              detail="Nothing unusual detected for this month."
            />
          )}
        </article>
      </section>
    </>
  );
}

function AddTransactionView({ apiKey, categories, onCreated, onNavigate }) {
  const [form, setForm] = useState({
    date: getToday(),
    amount: "",
    merchant: "",
    category: "Food",
    source: "manual",
  });
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);

  function updateField(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setSaving(true);
    setStatus("");

    try {
      await fetchJson("/api/transactions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
        body: JSON.stringify(form),
      });
      setStatus("Transaction saved.");
      setForm((current) => ({
        ...current,
        amount: "",
        merchant: "",
        source: "manual",
      }));
      onCreated(form.date.slice(0, 7));
      onNavigate("transactions");
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="view-stack reports-view">
      <article className="panel">
        <div className="panel-title">
          <div>
            <span>Manual entry</span>
            <h2>Add transaction</h2>
          </div>
        </div>

        <form className="react-form add-transaction-form" onSubmit={handleSubmit}>
          <label>
            Date
            <input
              required
              type="date"
              value={form.date}
              onChange={(event) => updateField("date", event.target.value)}
            />
          </label>
          <label>
            Amount
            <input
              required
              min="0.001"
              step="0.001"
              type="number"
              value={form.amount}
              onChange={(event) => updateField("amount", event.target.value)}
            />
          </label>
          <label>
            Merchant
            <input
              required
              type="text"
              value={form.merchant}
              placeholder="MCDONALDS, friend paid back, refund..."
              onChange={(event) => updateField("merchant", event.target.value)}
            />
          </label>
          <label>
            Category
            <select
              value={form.category}
              onChange={(event) => updateField("category", event.target.value)}
            >
              {categories.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
          </label>
          <label>
            Source
            <input
              required
              type="text"
              value={form.source}
              onChange={(event) => updateField("source", event.target.value)}
            />
          </label>
          <button className="primary-button" disabled={saving} type="submit">
            {saving ? "Saving..." : "Save transaction"}
          </button>
          {status && <p className="form-status">{status}</p>}
        </form>
      </article>
    </section>
  );
}

function TransactionsView({
  selectedMonth,
  categories,
  apiKey,
  selectedDate = "",
  onBackToDashboard,
}) {
  const [filters, setFilters] = useState({
    merchant: "",
    category: "",
    source: "",
    min_amount: "",
    max_amount: "",
    sort: "newest",
    unusual_only: false,
  });
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [categoryNudge, setCategoryNudge] = useState(null);
  const [editForm, setEditForm] = useState({
    date: "",
    amount: "",
    merchant: "",
    category: "Food",
    source: "",
  });

  useEffect(() => {
    let isCurrentRequest = true;
    const query = buildQuery({
      month: selectedMonth,
      date: selectedDate,
      ...filters,
      unusual_only: filters.unusual_only ? "1" : "",
    });

    async function loadTransactions() {
      setLoading(true);
      setError("");

      try {
        const result = await fetchJson(`/api/transactions?${query}`);

        if (isCurrentRequest) {
          setData(result);
        }
      } catch (requestError) {
        if (isCurrentRequest) {
          setError(requestError.message);
        }
      } finally {
        if (isCurrentRequest) {
          setLoading(false);
        }
      }
    }

    loadTransactions();

    return () => {
      isCurrentRequest = false;
    };
  }, [selectedMonth, selectedDate, filters]);

  function updateFilter(field, value) {
    setFilters((current) => ({ ...current, [field]: value }));
  }

  function startEdit(transaction) {
    setStatus("");
    setError("");
    setCategoryNudge(null);
    setEditingId(transaction.id);
    setEditForm({
      date: transaction.date,
      amount: String(transaction.amount),
      merchant: transaction.merchant,
      category: transaction.category,
      source: transaction.source,
    });
  }

  function updateEditField(field, value) {
    setEditForm((current) => ({ ...current, [field]: value }));
  }

  async function saveEdit(event, transactionId) {
    event.preventDefault();
    setBusyAction(`edit-${transactionId}`);
    setStatus("");
    setError("");
    const originalTransaction = (data?.transactions || []).find(
      (transaction) => transaction.id === transactionId
    );

    try {
      const result = await fetchJson(`/api/transactions/${transactionId}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
        body: JSON.stringify(editForm),
      });
      setData((current) => ({
        ...current,
        transactions: current.transactions.map((transaction) =>
          transaction.id === transactionId ? result.transaction : transaction
        ),
      }));
      setEditingId(null);
      setStatus("Transaction updated.");
      if (
        originalTransaction &&
        originalTransaction.category !== editForm.category &&
        editForm.category !== "Income"
      ) {
        setCategoryNudge({
          merchant: result.transaction.display_merchant || result.transaction.merchant,
          keyword: result.transaction.merchant,
          category: result.transaction.category,
        });
      } else {
        setCategoryNudge(null);
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  async function saveCategoryNudge() {
    if (!categoryNudge) {
      return;
    }

    setBusyAction("category-nudge");
    setError("");

    try {
      const result = await fetchJson("/api/category-rules", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
        body: JSON.stringify({
          keyword: categoryNudge.keyword,
          category: categoryNudge.category,
        }),
      });
      setStatus(
        `Saved rule for ${categoryNudge.merchant}. Updated ${
          result.updated_transactions || 0
        } existing Other transactions.`
      );
      setCategoryNudge(null);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  async function deleteTransaction(transaction) {
    const confirmed = window.confirm(
      `Delete ${transaction.display_merchant} for BHD ${formatAmount(transaction.amount)}?`
    );

    if (!confirmed) {
      return;
    }

    setBusyAction(`delete-${transaction.id}`);
    setStatus("");
    setError("");

    try {
      await fetchJson(`/api/transactions/${transaction.id}`, {
        method: "DELETE",
        headers: { "X-API-Key": apiKey },
      });
      setData((current) => ({
        ...current,
        transactions: current.transactions.filter((item) => item.id !== transaction.id),
        count: Math.max((current.count || 1) - 1, 0),
      }));
      setStatus("Transaction deleted.");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  const visibleTransactions = selectedDate
    ? (data?.transactions || []).filter((transaction) => transaction.date === selectedDate)
    : data?.transactions || [];
  const visibleCount = selectedDate
    ? visibleTransactions.length
    : data?.count || visibleTransactions.length;
  const dayTotal = visibleTransactions
    .filter((transaction) => transaction.category !== "Income")
    .reduce((sum, transaction) => sum + Number(transaction.amount || 0), 0);

  return (
    <section className="view-stack">
      <article className="panel">
        <div className="panel-title">
          <div>
            <span>{selectedDate ? "Daily view" : "Transaction list"}</span>
            <h2>{selectedDate ? `Transactions on ${selectedDate}` : "Transactions"}</h2>
          </div>
          <div className="panel-title-actions">
            {selectedDate ? (
              <button
                className="secondary-button"
                type="button"
                onClick={onBackToDashboard}
              >
                Back to dashboard
              </button>
            ) : null}
            <strong>{visibleCount}</strong>
          </div>
        </div>

        {!selectedDate ? (
          <div className="filter-grid">
          <label>
            Search merchant
            <input
              type="search"
              value={filters.merchant}
              placeholder="OPENAI, MCDONALDS..."
              onChange={(event) => updateFilter("merchant", event.target.value)}
            />
          </label>
          <label>
            Category
            <select
              value={filters.category}
              onChange={(event) => updateFilter("category", event.target.value)}
            >
              <option value="">All categories</option>
              {categories.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
          </label>
          <label>
            Source
            <select
              value={filters.source}
              onChange={(event) => updateFilter("source", event.target.value)}
            >
              <option value="">All sources</option>
              {(data?.sources || []).map((source) => (
                <option key={source} value={source}>
                  {source}
                </option>
              ))}
            </select>
          </label>
          <label>
            Min
            <input
              min="0"
              step="0.001"
              type="number"
              value={filters.min_amount}
              onChange={(event) => updateFilter("min_amount", event.target.value)}
            />
          </label>
          <label>
            Max
            <input
              min="0"
              step="0.001"
              type="number"
              value={filters.max_amount}
              onChange={(event) => updateFilter("max_amount", event.target.value)}
            />
          </label>
          <label>
            Sort
            <select
              value={filters.sort}
              onChange={(event) => updateFilter("sort", event.target.value)}
            >
              <option value="newest">Newest</option>
              <option value="oldest">Oldest</option>
              <option value="highest">Highest amount</option>
              <option value="lowest">Lowest amount</option>
            </select>
          </label>
          <label className="check-control">
            <input
              checked={filters.unusual_only}
              type="checkbox"
              onChange={(event) => updateFilter("unusual_only", event.target.checked)}
            />
            Show only unusual
          </label>
          </div>
        ) : (
          <p className="panel-note">
            Showing every transaction recorded on this day.
          </p>
        )}
      </article>

      <article className="panel">
        {status && <p className="form-status">{status}</p>}
        {error && <p className="form-status error-text">{error}</p>}
        {categoryNudge ? (
          <div className="category-nudge-card">
            <div>
              <strong>Always use {categoryNudge.category}?</strong>
              <span>
                Save this as the default category for {categoryNudge.merchant}.
              </span>
            </div>
            <div className="row-actions">
              <button
                className="primary-button"
                disabled={busyAction === "category-nudge"}
                type="button"
                onClick={saveCategoryNudge}
              >
                Save rule
              </button>
              <button
                className="secondary-button"
                type="button"
                onClick={() => setCategoryNudge(null)}
              >
                Not now
              </button>
            </div>
          </div>
        ) : null}
        {loading && <EmptyState title="Loading transactions" detail="Fetching rows from SQLite." />}
        {!loading && selectedDate && visibleTransactions.length ? (
          <div className="daily-transactions">
            <div className="daily-total-card">
              <span>Total spent</span>
              <strong>BHD {formatAmount(dayTotal)}</strong>
              <small>
                {visibleCount} transaction{visibleCount === 1 ? "" : "s"} on {selectedDate}
              </small>
            </div>

            <ul className="daily-transaction-list">
              {visibleTransactions.map((transaction) => (
                <li
                  className={transaction.category === "Income" ? "income-row" : ""}
                  key={transaction.id}
                >
                  <div>
                    <strong>{transaction.display_merchant}</strong>
                    <span>
                      {transaction.category} - {transaction.source}
                    </span>
                  </div>
                  <em className={transaction.category === "Income" ? "income-text" : ""}>
                    {transaction.category === "Income" ? "+" : ""}
                    {formatAmount(transaction.amount)}
                  </em>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {!loading && !selectedDate && visibleTransactions.length ? (
          <ul className="transaction-list large-list">
            {visibleTransactions.map((transaction) => (
              <li
                className={transaction.category === "Income" ? "income-row" : ""}
                key={transaction.id}
              >
                {editingId === transaction.id ? (
                  <form
                    className="transaction-edit-form"
                    onSubmit={(event) => saveEdit(event, transaction.id)}
                  >
                    <label>
                      Date
                      <input
                        required
                        type="date"
                        value={editForm.date}
                        onChange={(event) => updateEditField("date", event.target.value)}
                      />
                    </label>
                    <label>
                      Amount
                      <input
                        required
                        min="0"
                        step="0.001"
                        type="number"
                        value={editForm.amount}
                        onChange={(event) => updateEditField("amount", event.target.value)}
                      />
                    </label>
                    <label>
                      Merchant
                      <input
                        required
                        type="text"
                        value={editForm.merchant}
                        onChange={(event) => updateEditField("merchant", event.target.value)}
                      />
                    </label>
                    <label>
                      Category
                      <select
                        value={editForm.category}
                        onChange={(event) => updateEditField("category", event.target.value)}
                      >
                        {categories.map((category) => (
                          <option key={category} value={category}>
                            {category}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Source
                      <input
                        required
                        type="text"
                        value={editForm.source}
                        onChange={(event) => updateEditField("source", event.target.value)}
                      />
                    </label>
                    <div className="row-actions">
                      <button
                        className="primary-button"
                        disabled={busyAction === `edit-${transaction.id}`}
                        type="submit"
                      >
                        Save
                      </button>
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => setEditingId(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : (
                  <>
                    <div>
                      <strong>{transaction.display_merchant}</strong>
                      <span>
                        {transaction.date} - {transaction.category} - {transaction.source}
                      </span>
                    </div>
                    <div className="transaction-actions">
                      <em className={transaction.category === "Income" ? "income-text" : ""}>
                        {transaction.category === "Income" ? "+" : ""}
                        {formatAmount(transaction.amount)}
                      </em>
                      <div className="row-actions">
                        <button
                          className="secondary-button"
                          type="button"
                          onClick={() => startEdit(transaction)}
                        >
                          Edit
                        </button>
                        <button
                          className="danger-button"
                          disabled={busyAction === `delete-${transaction.id}`}
                          type="button"
                          onClick={() => deleteTransaction(transaction)}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        ) : null}
        {!loading && !visibleTransactions.length ? (
          <EmptyState
            title="No transactions found"
            detail={
              selectedDate
                ? "No transactions were recorded on this day."
                : "Try a different search, month, category, or amount range."
            }
          />
        ) : null}
      </article>
    </section>
  );
}

function ReportsView({ selectedMonth }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let isCurrentRequest = true;

    async function loadReport() {
      setLoading(true);
      setError("");

      try {
        const result = await fetchJson(`/api/reports?month=${selectedMonth}`);

        if (isCurrentRequest) {
          setReport(result);
        }
      } catch (requestError) {
        if (isCurrentRequest) {
          setError(requestError.message);
        }
      } finally {
        if (isCurrentRequest) {
          setLoading(false);
        }
      }
    }

    loadReport();

    return () => {
      isCurrentRequest = false;
    };
  }, [selectedMonth]);

  const topCategory = report?.category_rows?.[0];
  const exportHref = `/reports/monthly.csv?month=${selectedMonth}`;

  return (
    <section className="view-stack">
      <article className="panel report-hero">
        <div>
          <h2>Monthly report</h2>
          <p>
            {topCategory
              ? `You spent most on ${topCategory.category} this month. Net spent is BHD ${formatAmount(
                  report.net_spent
                )}.`
              : "No spending data is available for this selected month yet."}
          </p>
        </div>
        <a className="primary-button" href={exportHref}>
          Export CSV
        </a>
      </article>

      {error && <section className="notice error">{error}</section>}
      {loading && <LoadingDashboard />}

      {report && !loading && (
        <>
          <section className="metric-grid report-metrics">
            <SummaryCard
              label="Expenses"
              value={report.totals.expenses}
              detail={report.selected_month.label}
              tone="expense"
            />
            <SummaryCard
              label="Money in"
              value={report.totals.income}
              detail="Money received"
              tone="income"
            />
            <SummaryCard
              label="Net spent"
              value={report.net_spent}
              detail="Expenses minus money in"
              tone={Number(report.net_spent || 0) >= 0 ? "expense" : "income"}
            />
            <article className="metric-card">
              <span>Rows</span>
              <strong>{report.transaction_count}</strong>
              <small>Transactions in this month</small>
            </article>
          </section>

          <section className="panel">
            <div className="panel-title">
              <div>
                <span>Trend view</span>
                <h2>Monthly net spending trend</h2>
              </div>
            </div>

            {report.monthly_trends.length ? (
              <div className="trend-chart">
                {report.monthly_trends.map((month) => (
                  <div className="trend-column" key={month.month}>
                    <div className="trend-bar-shell">
                      <span
                        className="trend-bar"
                        style={{ height: `${Math.max(month.percent, 6)}%` }}
                      />
                    </div>
                    <strong>{month.label}</strong>
                    <span>{formatAmount(month.net_spent)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                title="No monthly trend yet"
                detail="Trends appear after transactions exist across months."
              />
            )}
          </section>

          <section className="dashboard-grid">
            <article className="panel">
              <div className="panel-title">
                <div>
                  <span>Breakdown</span>
                  <h2>Categories</h2>
                </div>
              </div>

              {report.category_rows.length ? (
                <ul className="report-list">
                  {report.category_rows.map((row) => (
                    <li key={row.category}>
                      <div>
                        <strong>{row.category}</strong>
                        <span>Monthly net category total</span>
                      </div>
                      <em>{formatAmount(row.total)}</em>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  title="No category totals"
                  detail="Add or import transactions to build this report."
                />
              )}
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <span>Largest merchants</span>
                  <h2>Top merchants</h2>
                </div>
              </div>

              {report.top_merchants.length ? (
                <ul className="report-list">
                  {report.top_merchants.map((merchant) => (
                    <li key={`${merchant.merchant}-${merchant.category}`}>
                      <div>
                        <strong>{merchant.display_merchant}</strong>
                        <span>
                          {merchant.transaction_count} transaction
                          {merchant.transaction_count === 1 ? "" : "s"} -{" "}
                          {merchant.category}
                        </span>
                      </div>
                      <em>{formatAmount(merchant.total)}</em>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  title="No merchant totals"
                  detail="Top merchants will appear once this month has spending."
                />
              )}
            </article>
          </section>

          <section className="dashboard-grid">
            <article className="panel">
              <div className="panel-title">
                <div>
                  <span>Last 6 months</span>
                  <h2>Category trends</h2>
                </div>
              </div>

              {report.category_trends.length ? (
                <div className="bar-list">
                  {report.category_trends.map((category) => (
                    <div className="bar-row" key={category.category}>
                      <div className="bar-row-label">
                        <span
                          className="category-dot"
                          style={{ background: category.color }}
                        />
                        <strong>{category.category}</strong>
                        <span>{formatAmount(category.total)}</span>
                      </div>
                      <div className="bar-track">
                        <div
                          className="bar-fill"
                          style={{
                            width: `${category.percent}%`,
                            background: category.color,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState
                  title="No category trend"
                  detail="Category trends need spending history."
                />
              )}
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <span>Last 6 months</span>
                  <h2>Merchant trends</h2>
                </div>
              </div>

              {report.merchant_trends.length ? (
                <ul className="report-list">
                  {report.merchant_trends.map((merchant) => (
                    <li key={merchant.merchant}>
                      <div>
                        <strong>{merchant.display_merchant}</strong>
                        <span>
                          {merchant.transaction_count} transaction
                          {merchant.transaction_count === 1 ? "" : "s"}
                        </span>
                      </div>
                      <em>{formatAmount(merchant.total)}</em>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  title="No merchant trend"
                  detail="Top merchant trends will appear with more history."
                />
              )}
            </article>
          </section>
        </>
      )}
    </section>
  );
}

function CleanupView({ apiKey, categories, initialKeyword, onInitialKeywordUsed }) {
  const [rules, setRules] = useState([]);
  const [aliases, setAliases] = useState([]);
  const [merchantIntel, setMerchantIntel] = useState(null);
  const [parserRules, setParserRules] = useState([]);
  const [ruleForm, setRuleForm] = useState({
    keyword: initialKeyword || "",
    category: "Food",
  });
  const [aliasForm, setAliasForm] = useState({
    keyword: "",
    display_name: "",
  });
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("");
  const [busyAction, setBusyAction] = useState("");

  async function loadCleanupData() {
    setLoading(true);
    setStatus("");

    try {
      const [ruleData, aliasData, merchantData, parserRuleData] = await Promise.all([
        fetchJson("/api/category-rules"),
        fetchJson("/api/merchant-aliases"),
        fetchJson("/api/merchant-intelligence"),
        fetchJson("/api/sms-parser-rules"),
      ]);
      setRules(ruleData.rules || []);
      setAliases(aliasData.aliases || []);
      setMerchantIntel(merchantData);
      setParserRules(parserRuleData.rules || []);
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadCleanupData();
  }, []);

  useEffect(() => {
    if (initialKeyword) {
      setRuleForm((current) => ({ ...current, keyword: initialKeyword }));
      onInitialKeywordUsed();
    }
  }, [initialKeyword, onInitialKeywordUsed]);

  async function saveRule(event) {
    event.preventDefault();
    setBusyAction("rule");
    setStatus("");

    try {
      const result = await fetchJson("/api/category-rules", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
        body: JSON.stringify(ruleForm),
      });
      setStatus(
        `Category rule saved. Updated ${result.updated_transactions || 0} existing Other transactions.`
      );
      setRuleForm((current) => ({ ...current, keyword: "" }));
      await loadCleanupData();
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  async function saveAlias(event) {
    event.preventDefault();
    setBusyAction("alias");
    setStatus("");

    try {
      await fetchJson("/api/merchant-aliases", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
        body: JSON.stringify(aliasForm),
      });
      setStatus("Merchant display name saved.");
      setAliasForm({ keyword: "", display_name: "" });
      await loadCleanupData();
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  async function saveAliasSuggestion(suggestion) {
    setBusyAction(`suggestion-${suggestion.keyword}`);
    setStatus("");

    try {
      await fetchJson("/api/merchant-aliases", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
        body: JSON.stringify({
          keyword: suggestion.keyword,
          display_name: suggestion.display_name,
        }),
      });
      setStatus(`Saved ${suggestion.keyword} as ${suggestion.display_name}.`);
      await loadCleanupData();
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  function useAliasSuggestion(suggestion) {
    setAliasForm({
      keyword: suggestion.keyword,
      display_name: suggestion.display_name,
    });
    setStatus("Suggestion copied into the display name form.");
  }

  async function deleteRule(ruleId) {
    const confirmed = window.confirm("Delete this category rule?");

    if (!confirmed) {
      return;
    }

    setBusyAction(`rule-${ruleId}`);

    try {
      await fetchJson(`/api/category-rules/${ruleId}`, {
        method: "DELETE",
        headers: { "X-API-Key": apiKey },
      });
      await loadCleanupData();
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  async function deleteAlias(aliasId) {
    const confirmed = window.confirm("Delete this merchant display rule?");

    if (!confirmed) {
      return;
    }

    setBusyAction(`alias-${aliasId}`);

    try {
      await fetchJson(`/api/merchant-aliases/${aliasId}`, {
        method: "DELETE",
        headers: { "X-API-Key": apiKey },
      });
      await loadCleanupData();
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  async function deleteParserRule(ruleId) {
    const confirmed = window.confirm("Delete this learned SMS parser rule?");

    if (!confirmed) {
      return;
    }

    setBusyAction(`parser-${ruleId}`);

    try {
      await fetchJson(`/api/sms-parser-rules/${ruleId}`, {
        method: "DELETE",
        headers: { "X-API-Key": apiKey },
      });
      await loadCleanupData();
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  return (
    <section className="view-stack">
      {status && <section className="notice">{status}</section>}

      <article className="panel">
        <div className="panel-title">
          <div>
            <span>Merchant intelligence</span>
            <h2>Cleanup suggestions</h2>
          </div>
          {merchantIntel?.summary && (
            <strong>
              {merchantIntel.summary.display_groups} clean group
              {merchantIntel.summary.display_groups === 1 ? "" : "s"}
            </strong>
          )}
        </div>
        <p className="panel-note">
          The app scans your saved transactions, finds noisy bank merchant names,
          and suggests display names that make charts, recurring detection, and
          reports easier to read.
        </p>

        {loading ? (
          <EmptyState title="Loading merchant intelligence" detail="Checking saved transactions." />
        ) : merchantIntel?.suggestions?.length ? (
          <>
            <div className="merchant-intel-summary">
              <span>
                <strong>{merchantIntel.summary.unique_merchants}</strong>
                Raw merchants
              </span>
              <span>
                <strong>{merchantIntel.summary.aliased_merchants}</strong>
                Already cleaned
              </span>
              <span>
                <strong>{merchantIntel.summary.messy_merchants}</strong>
                Need review
              </span>
            </div>

            <ul className="merchant-suggestion-list">
              {merchantIntel.suggestions.map((suggestion) => (
                <li key={suggestion.keyword}>
                  <div>
                    <span>Suggested rule</span>
                    <strong>
                      {suggestion.keyword} → {suggestion.display_name}
                    </strong>
                    <small>
                      {suggestion.transaction_count} transaction
                      {suggestion.transaction_count === 1 ? "" : "s"} · BHD{" "}
                      {formatAmount(suggestion.total_amount)}
                    </small>
                    <code>{suggestion.examples.join(" / ")}</code>
                  </div>
                  <div className="row-actions">
                    <button
                      className="ghost-button"
                      type="button"
                      onClick={() => useAliasSuggestion(suggestion)}
                    >
                      Edit first
                    </button>
                    <button
                      className="primary-button"
                      disabled={busyAction === `suggestion-${suggestion.keyword}`}
                      type="button"
                      onClick={() => saveAliasSuggestion(suggestion)}
                    >
                      Save rule
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <EmptyState
            title="No cleanup suggestions"
            detail="Your current merchant names already look clean or aliases cover them."
          />
        )}
      </article>

      {merchantIntel?.groups?.length ? (
        <article className="panel">
          <div className="panel-title">
            <div>
              <span>Merchant groups</span>
              <h2>Clean report names</h2>
            </div>
          </div>
          <ul className="merchant-group-list">
            {merchantIntel.groups.slice(0, 8).map((group) => (
              <li key={group.display_name}>
                <div>
                  <strong>{group.display_name}</strong>
                  <span>
                    {group.raw_count} raw name{group.raw_count === 1 ? "" : "s"} ·{" "}
                    {group.transaction_count} transaction
                    {group.transaction_count === 1 ? "" : "s"}
                  </span>
                </div>
                <em>BHD {formatAmount(group.total_amount)}</em>
              </li>
            ))}
          </ul>
        </article>
      ) : null}

      <section className="dashboard-grid">
        <article className="panel">
          <div className="panel-title">
            <div>
              <h2>Category rules</h2>
            </div>
          </div>

          <form className="react-form compact-form" onSubmit={saveRule}>
            <label>
              Merchant keyword
              <input
                required
                type="text"
                value={ruleForm.keyword}
                placeholder="KEETA, TALABAT, OPENAI..."
                onChange={(event) =>
                  setRuleForm((current) => ({
                    ...current,
                    keyword: event.target.value,
                  }))
                }
              />
            </label>
            <label>
              Category
              <select
                value={ruleForm.category}
                onChange={(event) =>
                  setRuleForm((current) => ({
                    ...current,
                    category: event.target.value,
                  }))
                }
              >
                {categories
                  .filter((category) => category !== "Income")
                  .map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
              </select>
            </label>
            <button className="primary-button" disabled={busyAction === "rule"} type="submit">
              Save category rule
            </button>
          </form>

          {loading ? (
            <EmptyState title="Loading rules" detail="Reading saved category rules." />
          ) : rules.length ? (
            <ul className="cleanup-list">
              {rules.map((rule) => (
                <li key={rule.id}>
                  <div>
                    <strong>{rule.keyword}</strong>
                    <span>{rule.category}</span>
                  </div>
                  <button
                    className="danger-button"
                    disabled={busyAction === `rule-${rule.id}`}
                    type="button"
                    onClick={() => deleteRule(rule.id)}
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No category rules"
              detail="Rules will automatically categorize future SMS imports."
            />
          )}
        </article>

        <article className="panel">
          <div className="panel-title">
            <div>
              <span>Merchant cleanup</span>
              <h2>Display names</h2>
            </div>
          </div>

          <form className="react-form compact-form" onSubmit={saveAlias}>
            <label>
              Merchant keyword
              <input
                required
                type="text"
                value={aliasForm.keyword}
                placeholder="OPENAI *CHATGPT"
                onChange={(event) =>
                  setAliasForm((current) => ({
                    ...current,
                    keyword: event.target.value,
                  }))
                }
              />
            </label>
            <label>
              Display name
              <input
                required
                type="text"
                value={aliasForm.display_name}
                placeholder="OpenAI / ChatGPT"
                onChange={(event) =>
                  setAliasForm((current) => ({
                    ...current,
                    display_name: event.target.value,
                  }))
                }
              />
            </label>
            <button className="primary-button" disabled={busyAction === "alias"} type="submit">
              Save display name
            </button>
          </form>

          {loading ? (
            <EmptyState title="Loading aliases" detail="Reading display name rules." />
          ) : aliases.length ? (
            <ul className="cleanup-list">
              {aliases.map((alias) => (
                <li key={alias.id}>
                  <div>
                    <strong>{alias.keyword}</strong>
                    <span>{alias.display_name}</span>
                  </div>
                  <button
                    className="danger-button"
                    disabled={busyAction === `alias-${alias.id}`}
                    type="button"
                    onClick={() => deleteAlias(alias.id)}
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No display rules"
              detail="Aliases make messy bank merchant names easier to read."
            />
          )}
        </article>
      </section>

      <article className="panel">
        <div className="panel-title">
          <div>
            <span>SMS parser</span>
            <h2>Learned rules</h2>
          </div>
          <strong>{parserRules.length}</strong>
        </div>
        <p className="panel-note">
          These rules are created from AI parsing or manual repair, then reused
          so future similar bank messages can parse without AI.
        </p>

        {loading ? (
          <EmptyState title="Loading parser rules" detail="Reading learned SMS patterns." />
        ) : parserRules.length ? (
          <ul className="cleanup-list parser-rule-list">
            {parserRules.map((rule) => (
              <li key={rule.id}>
                <div>
                  <strong>{rule.name}</strong>
                  <span>
                    {rule.category} - used {rule.use_count || 0} time
                    {(rule.use_count || 0) === 1 ? "" : "s"}
                    {rule.last_used_at ? ` - last used ${rule.last_used_at}` : ""}
                  </span>
                  <code>{rule.example_message}</code>
                </div>
                <button
                  className="danger-button"
                  disabled={busyAction === `parser-${rule.id}`}
                  type="button"
                  onClick={() => deleteParserRule(rule.id)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No learned parser rules"
            detail="Use AI parse or repair an import, then teach the app from that SMS."
          />
        )}
      </article>
    </section>
  );
}

function BudgetsView({ apiKey, selectedMonth, dashboard, onSaved }) {
  const [budgetData, setBudgetData] = useState(null);
  const [form, setForm] = useState({
    monthly_budget_limit: "",
    category_budgets: {},
  });
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);

  async function loadBudgets() {
    setLoading(true);
    setStatus("");

    try {
      const data = await fetchJson("/api/budgets");
      setBudgetData(data);
      setForm({
        monthly_budget_limit: String(data.monthly_budget_limit || 0),
        category_budgets: Object.fromEntries(
          data.categories.map((category) => [
            category,
            String(data.category_budgets?.[category] || 0),
          ])
        ),
      });
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadBudgets();
  }, []);

  async function saveBudgets(event) {
    event.preventDefault();
    setSaving(true);
    setStatus("");

    try {
      await fetchJson("/api/budgets", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
        body: JSON.stringify({
          monthly_budget_limit: Number(form.monthly_budget_limit || 0),
          category_budgets: Object.fromEntries(
            Object.entries(form.category_budgets).map(([category, value]) => [
              category,
              Number(value || 0),
            ])
          ),
        }),
      });
      setStatus("Budgets saved.");
      await loadBudgets();
      onSaved();
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  function updateCategoryBudget(category, value) {
    setForm((current) => ({
      ...current,
      category_budgets: {
        ...current.category_budgets,
        [category]: value,
      },
    }));
  }

  const spendingByCategory = new Map(
    (dashboard?.spending_by_category || []).map((row) => [row.category, row.total])
  );
  const netSpent = Number(dashboard?.net_spent || 0);
  const monthlyLimit = Number(form.monthly_budget_limit || 0);
  const monthlyPercentRaw = monthlyLimit ? (netSpent / monthlyLimit) * 100 : 0;
  const monthlyPercentDisplay = Math.max(monthlyPercentRaw, 0);
  const monthlyPercent = Math.min(Math.max(monthlyPercentRaw, 0), 100);
  const monthlyBudgetTone =
    monthlyPercentRaw >= 100
      ? "over"
      : monthlyPercentRaw >= 80
        ? "warning"
        : "good";

  return (
    <section className="view-stack">
      {status && <section className="notice">{status}</section>}

      <article className="panel report-hero">
        <div>
          <h2>Budgets</h2>
          <p>
            Track your full monthly budget and category limits for{" "}
            {dashboard?.selected_month?.label || selectedMonth}.
          </p>
        </div>
      </article>

      {loading ? (
        <LoadingDashboard />
      ) : (
        <form className="view-stack" onSubmit={saveBudgets}>
          <article className="panel">
            <div className="panel-title">
              <div>
                <span>Monthly limit</span>
                <h2>Full budget</h2>
              </div>
            </div>

            <div className="budget-editor">
              <label>
                Monthly budget
                <input
                  min="0"
                  step="0.001"
                  type="number"
                  value={form.monthly_budget_limit}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      monthly_budget_limit: event.target.value,
                    }))
                  }
                />
              </label>
              <div className="budget-progress">
                <div>
                  <strong>{formatAmount(netSpent)}</strong>
                  <span>
                    {monthlyLimit
                      ? `${Math.round(monthlyPercentDisplay)}% of ${formatAmount(monthlyLimit)}`
                      : "Set a monthly budget"}
                  </span>
                </div>
                <div className="bar-track budget-total-track">
                  <div
                    className={`bar-fill budget-total-fill ${monthlyBudgetTone}`}
                    style={{ width: `${monthlyPercent}%` }}
                  />
                  <span className="bar-percent">
                    {monthlyLimit ? `${Math.round(monthlyPercentDisplay)}% used` : "No budget set"}
                  </span>
                </div>
              </div>
            </div>
          </article>

          <article className="panel">
            <div className="panel-title">
              <div>
                <span>Category limits</span>
                <h2>Per-category budgets</h2>
              </div>
            </div>

            <div className="budget-grid">
              {(budgetData?.categories || []).map((category) => {
                const spent = Number(spendingByCategory.get(category) || 0);
                const limit = Number(form.category_budgets[category] || 0);
                const percentRaw = limit ? (spent / limit) * 100 : 0;
                const percent = Math.min(percentRaw, 100);
                const budgetTone =
                  percentRaw >= 100 ? "over" : percentRaw >= 80 ? "warning" : "good";
                const warning =
                  limit && spent >= limit
                    ? "Over limit"
                    : limit && spent >= limit * 0.8
                      ? "Close to limit"
                      : "On track";

                return (
                  <div className="budget-row" key={category}>
                    <label>
                      {category}
                      <input
                        min="0"
                        step="0.001"
                        type="number"
                        value={form.category_budgets[category] || ""}
                        onChange={(event) =>
                          updateCategoryBudget(category, event.target.value)
                        }
                      />
                    </label>
                    <div className="budget-progress">
                      <div>
                        <strong>{formatAmount(spent)}</strong>
                        <span>
                          {limit
                            ? `${Math.round(percentRaw)}% of ${formatAmount(limit)} - ${warning}`
                            : `No limit - ${warning}`}
                        </span>
                      </div>
                      <div className="bar-track budget-total-track">
                        <div
                          className={`bar-fill budget-total-fill ${budgetTone}`}
                          style={{ width: `${percent}%` }}
                        />
                        <span className="bar-percent">
                          {limit ? `${Math.round(percentRaw)}% used` : "No limit set"}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            <button className="primary-button" disabled={saving} type="submit">
              {saving ? "Saving..." : "Save budgets"}
            </button>
          </article>
        </form>
      )}
    </section>
  );
}

function SettingsView({ apiKey, onApiKeyChanged, onShowShortcutGuide }) {
  const [health, setHealth] = useState(null);
  const [adminAccess, setAdminAccess] = useState(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [testBusy, setTestBusy] = useState(false);
  const [backupBusy, setBackupBusy] = useState(false);
  const [restoreFile, setRestoreFile] = useState(null);
  const [restoreConfirm, setRestoreConfirm] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [shortcutPublicUrl, setShortcutPublicUrl] = useState("");
  const [inviteForm, setInviteForm] = useState({ username: "", display_name: "" });
  const [latestInviteUrl, setLatestInviteUrl] = useState("");

  async function loadHealth() {
    setLoading(true);
    setStatus("");

    try {
      const healthData = await fetchJson("/api/settings/health");
      setHealth(healthData);

      if (healthData.multi_user?.current_user?.is_admin) {
        setAdminAccess(await fetchJson("/api/admin/invites"));
      } else {
        setAdminAccess(null);
      }
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadHealth();
  }, []);

  useEffect(() => {
    if (health) {
      setShortcutPublicUrl(health.shortcut_public_url || "");
    }
  }, [health]);

  async function regenerateKey() {
    const confirmed = window.confirm(
      "Regenerate the API key? You must update your iPhone Shortcut after this."
    );

    if (!confirmed) {
      return;
    }

    setBusy(true);
    setStatus("");

    try {
      const result = await fetchJson("/api/settings/regenerate-key", {
        method: "POST",
        headers: { "X-API-Key": apiKey },
      });
      onApiKeyChanged(result.api_key);
      await loadHealth();
      setStatus("API key regenerated. Update your iPhone Shortcut.");
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function copyText(label, value) {
    if (!navigator.clipboard) {
      setStatus(`${label}: ${value}`);
      return;
    }

    await navigator.clipboard.writeText(value);
    setStatus(`${label} copied.`);
  }

  async function sendTestImport() {
    setTestBusy(true);
    setStatus("");

    try {
      const result = await fetchJson("/api/settings/send-test-import", {
        method: "POST",
        headers: { "X-API-Key": apiKey },
      });
      setStatus(result.message);
      await loadHealth();
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setTestBusy(false);
    }
  }

  async function createBackup() {
    setBackupBusy(true);
    setStatus("");

    try {
      const result = await fetchJson("/api/backups/create", {
        method: "POST",
        headers: { "X-API-Key": apiKey },
      });
      setStatus(`Backup created: ${result.backup.filename}`);
      await loadHealth();
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setBackupBusy(false);
    }
  }

  async function saveShortcutPublicUrl(event) {
    event.preventDefault();
    setBusy(true);
    setStatus("");

    try {
      const result = await fetchJson("/api/settings/shortcut-public-url", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
        body: JSON.stringify({ shortcut_public_url: shortcutPublicUrl }),
      });
      setShortcutPublicUrl(result.shortcut_public_url || "");
      setStatus(
        result.shortcut_public_url
          ? "Shortcut public URL saved. Use this URL in your iPhone Shortcut."
          : "Shortcut public URL cleared."
      );
      await loadHealth();
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function restoreBackup(event) {
    event.preventDefault();
    setBackupBusy(true);
    setStatus("");

    try {
      if (!restoreFile) {
        throw new Error("Choose a backup file first.");
      }

      const formData = new FormData();
      formData.append("backup_file", restoreFile);
      formData.append("confirmation", restoreConfirm);
      const response = await fetch("/api/backups/restore", {
        method: "POST",
        headers: { "X-API-Key": apiKey },
        body: formData,
      });
      const result = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(result.error || "Restore failed.");
      }

      setStatus(`${result.message} Safety backup: ${result.safety_backup}`);
      setRestoreFile(null);
      setRestoreConfirm("");
      await loadHealth();
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setBackupBusy(false);
    }
  }

  async function createInvite(event) {
    event.preventDefault();
    setBusy(true);
    setStatus("");
    setLatestInviteUrl("");

    try {
      const result = await fetchJson("/api/admin/invites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(inviteForm),
      });
      setLatestInviteUrl(result.invite.invite_url);
      setInviteForm({ username: "", display_name: "" });
      setAdminAccess(await fetchJson("/api/admin/invites"));
      await loadHealth();
      setStatus("Invite created. Send the link to your friend.");
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    const result = await fetchJson("/api/logout", { method: "POST" });
    window.location.href = result.redirect_url || "/login";
  }

  const maskedApiKey = health?.api_key
    ? `${"*".repeat(Math.max(health.api_key.length - 6, 8))}${health.api_key.slice(-6)}`
    : "";
  const deploymentReadiness = health?.deployment_readiness || {
    level: "Waiting for backend update",
    score: 0,
    total: 0,
    checks: [],
  };
  const permissions = health?.permissions || {};
  const isAdmin = Boolean(permissions.is_admin);
  const canManageInvites = Boolean(permissions.can_manage_invites);
  const canManageBackups = Boolean(permissions.can_manage_backups);
  const canViewServerHealth = Boolean(permissions.can_view_server_health);

  return (
    <section className="view-stack">
      {status && <section className="notice">{status}</section>}

      <article className="panel report-hero">
        <div>
          <h2>Settings and Shortcut health</h2>
          <p>
            Manage your account, API key, iPhone Shortcut, and import health.
          </p>
        </div>
        <button className="secondary-button" type="button" onClick={loadHealth}>
          Refresh
        </button>
      </article>

      {loading ? (
        <LoadingDashboard />
      ) : health ? (
        <>
          <section className="metric-grid report-metrics">
            <article className="metric-card">
              <span>Last import</span>
              <strong>{health.automation_health.last_status}</strong>
              <small>{health.automation_health.last_time}</small>
            </article>
            <SummaryCard
              label="Today"
              value={health.automation_health.imports_today}
              detail="Imports received"
            />
            <SummaryCard
              label="Failed"
              value={health.automation_health.failed_today}
              detail="Parser issues today"
              tone="expense"
            />
            <SummaryCard
              label="Duplicates"
              value={health.automation_health.duplicates_today}
              detail="Ignored safely today"
            />
          </section>

          <section className="dashboard-grid">
            <article className="panel">
              <div className="panel-title">
                <div>
                  <span>Shortcut endpoint</span>
                  <h2>iPhone automation</h2>
                </div>
              </div>
              <div className="settings-list">
                <span>
                  Last merchant
                  <strong>{health.automation_health.last_merchant}</strong>
                </span>
                <span>
                  iPhone Shortcut URL
                  <code>{health.import_url}</code>
                </span>
                <span>
                  Local browser URL
                  <code>{health.local_import_url}</code>
                </span>
                <span>
                  Header
                  <code>X-API-Key</code>
                </span>
                <span>
                  URL status
                  <strong>{health.url_hint}</strong>
                </span>
                <span>
                  JSON body
                  <code>{health.shortcut_body_text}</code>
                </span>
              </div>
              <form className="shortcut-url-form" onSubmit={saveShortcutPublicUrl}>
                <label>
                  Shortcut public URL
                  <input
                    type="url"
                    value={shortcutPublicUrl}
                    placeholder="https://your-ngrok-url.ngrok-free.dev/import-message"
                    onChange={(event) => setShortcutPublicUrl(event.target.value)}
                  />
                </label>
                <button className="primary-button" disabled={busy} type="submit">
                  Save URL
                </button>
              </form>
              <p className="panel-note">
                Use this for ngrok or a future domain. If it is saved, the
                Shortcut guide and deployment checklist use it instead of
                localhost.
              </p>
              <div className="action-row">
                <button
                  className="primary-button"
                  disabled={testBusy}
                  type="button"
                  onClick={sendTestImport}
                >
                  {testBusy ? "Testing..." : "Send test import"}
                </button>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => copyText("Import URL", health.import_url)}
                >
                  Copy Shortcut URL
                </button>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => copyText("Shortcut JSON", health.shortcut_body_text)}
                >
                  Copy JSON
                </button>
              </div>
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <span>Security</span>
                  <h2>Account API key</h2>
                </div>
              </div>
              <div className="settings-list">
                <span>
                  Current API key
                  <code>{showApiKey ? health.api_key : maskedApiKey}</code>
                </span>
              </div>
              <div className="action-row">
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => setShowApiKey((current) => !current)}
                >
                  {showApiKey ? "Hide API key" : "Reveal API key"}
                </button>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => copyText("API key", health.api_key)}
                >
                  Copy API key
                </button>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={onShowShortcutGuide}
                >
                  Shortcut setup guide
                </button>
                <button
                  className="danger-button"
                  disabled={busy}
                  type="button"
                  onClick={regenerateKey}
                >
                  Regenerate API key
                </button>
                <button className="secondary-button" type="button" onClick={logout}>
                  Log out
                </button>
              </div>
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <span>Private access</span>
                  <h2>Multi-user foundation</h2>
                </div>
              </div>
              <div className="settings-list">
                <span>
                  Current user
                  <strong>
                    {health.multi_user?.current_user?.display_name || "Owner"}
                  </strong>
                </span>
                <span>
                  Username
                  <code>{health.multi_user?.current_user?.username || "owner"}</code>
                </span>
                {isAdmin ? (
                  <>
                    <span>
                      Active users
                      <strong>{health.multi_user?.active_user_count || 1}</strong>
                    </span>
                    <span>
                      Pending invites
                      <strong>{health.multi_user?.pending_invite_count || 0}</strong>
                    </span>
                  </>
                ) : null}
                <span>
                  Registration
                  <strong>
                    {health.multi_user?.public_registration
                      ? "Public sign-up enabled"
                      : "Manual users only"}
                  </strong>
                </span>
              </div>
              <p className="panel-note">
                The database now has user ownership fields. Public registration
                is still off until hosting, HTTPS, and backup safety are ready.
              </p>
            </article>

            {canManageInvites ? (
              <article className="panel">
                <div className="panel-title">
                  <div>
                    <span>Admin only</span>
                    <h2>Private invites</h2>
                  </div>
                </div>
                <form className="compact-form invite-form" onSubmit={createInvite}>
                  <label>
                    Username
                    <input
                      required
                      minLength="3"
                      type="text"
                      value={inviteForm.username}
                      placeholder="friend-name"
                      onChange={(event) =>
                        setInviteForm((current) => ({
                          ...current,
                          username: event.target.value,
                        }))
                      }
                    />
                  </label>
                  <label>
                    Display name
                    <input
                      type="text"
                      value={inviteForm.display_name}
                      placeholder="Friend Name"
                      onChange={(event) =>
                        setInviteForm((current) => ({
                          ...current,
                          display_name: event.target.value,
                        }))
                      }
                    />
                  </label>
                  <button className="primary-button" disabled={busy} type="submit">
                    {busy ? "Creating..." : "Create invite"}
                  </button>
                </form>

                {latestInviteUrl && (
                  <div className="invite-link-box">
                    <span>One-time invite link</span>
                    <code>{latestInviteUrl}</code>
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => copyText("Invite link", latestInviteUrl)}
                    >
                      Copy invite link
                    </button>
                  </div>
                )}

                <div className="settings-list">
                  <span>
                    Invite behavior
                    <strong>Expires after use</strong>
                  </span>
                  <span>
                    Public sign-up
                    <strong>Off</strong>
                  </span>
                </div>

                {adminAccess?.users?.length ? (
                  <ul className="backup-list invite-list">
                    {adminAccess.users.map((user) => (
                      <li key={user.id}>
                        <div>
                          <strong>
                            {user.display_name} {user.is_admin ? "(admin)" : ""}
                          </strong>
                          <span>
                            @{user.username} - API ends {user.api_key_last6 || "------"}
                          </span>
                        </div>
                        <em>{user.active ? "Active" : "Inactive"}</em>
                      </li>
                    ))}
                  </ul>
                ) : null}

                {adminAccess?.invites?.length ? (
                  <ul className="quality-list invite-history">
                    {adminAccess.invites.map((invite) => (
                      <li className={invite.status} key={invite.id}>
                        <strong>
                          {invite.display_name} / @{invite.username}
                        </strong>
                        <span>
                          {invite.status} - expires {invite.expires_at || "after use"}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="panel-note">
                    Create an invite when you are ready to let a friend set
                    their own password.
                  </p>
                )}
              </article>
            ) : null}
          </section>

          <section className="dashboard-grid">
            {canManageBackups ? (
              <article className="panel">
              <div className="panel-title">
                <div>
                  <span>Data safety</span>
                  <h2>Backup and restore</h2>
                </div>
              </div>
              <div className="action-row">
                <button
                  className="primary-button"
                  disabled={backupBusy}
                  type="button"
                  onClick={createBackup}
                >
                  {backupBusy ? "Working..." : "Create backup now"}
                </button>
                <a className="secondary-button" href={health.backup_download_url}>
                  Download current DB
                </a>
              </div>
              <form className="restore-form" onSubmit={restoreBackup}>
                <label>
                  Restore backup file
                  <input
                    accept=".db,.sqlite,.sqlite3"
                    type="file"
                    onChange={(event) => setRestoreFile(event.target.files?.[0] || null)}
                  />
                </label>
                <label>
                  Type RESTORE
                  <input
                    type="text"
                    value={restoreConfirm}
                    onChange={(event) => setRestoreConfirm(event.target.value)}
                  />
                </label>
                <button
                  className="danger-button"
                  disabled={backupBusy || restoreConfirm !== "RESTORE"}
                  type="submit"
                >
                  Restore backup
                </button>
              </form>

              {health.backup_history?.length ? (
                <ul className="backup-list">
                  {health.backup_history.map((backup) => (
                    <li key={backup.filename}>
                      <div>
                        <strong>{backup.filename}</strong>
                        <span>
                          {backup.created_at} - {(backup.size_bytes / 1024).toFixed(1)} KB
                        </span>
                      </div>
                      <a
                        className="secondary-button"
                        href={`/api/backups/${encodeURIComponent(
                          backup.filename
                        )}/download?api_key=${encodeURIComponent(apiKey)}`}
                      >
                        Download
                      </a>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  title="No saved backups"
                  detail="Create a backup before relying on automation."
                />
              )}
              </article>
            ) : null}

            <article className="panel">
              <div className="panel-title">
                <div>
                  <span>Trust checks</span>
                  <h2>Data quality alerts</h2>
                </div>
              </div>
              {health.data_quality_alerts.length ? (
                <ul className="quality-list">
                  {health.data_quality_alerts.map((alert) => (
                    <li className={alert.level} key={`${alert.title}-${alert.detail}`}>
                      <strong>{alert.title}</strong>
                      <span>{alert.detail}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  title="No data quality alerts"
                  detail="Imports, categories, duplicates, and backups look healthy."
                />
              )}
            </article>
          </section>

          {canViewServerHealth ? (
            <>
              <article className="panel">
                <div className="panel-title">
                  <div>
                    <span>Private deployment</span>
                    <h2>Reliable hosting checklist</h2>
                  </div>
                  <strong>
                    {deploymentReadiness.score}/{deploymentReadiness.total}
                  </strong>
                </div>
                <div className="settings-list">
                  <span>
                    Database
                    <code>{health.database_file}</code>
                  </span>
                </div>
                <p className="panel-note">
                  {deploymentReadiness.level}. This checks whether the app
                  is ready to run as a reliable private finance assistant instead
                  of only a local PC project.
                </p>
                {deploymentReadiness.checks.length ? (
                  <ul className="quality-list deployment-list">
                    {deploymentReadiness.checks.map((check) => (
                      <li className={check.status} key={check.key}>
                        <strong>{check.title}</strong>
                        <span>{check.detail}</span>
                        <em>{check.recommendation}</em>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState
                    title="Deployment checklist unavailable"
                    detail="Restart Flask so the latest backend can return these checks."
                  />
                )}
              </article>

              <article className="panel">
                <div className="panel-title">
                  <div>
                    <span>Future accounts</span>
                    <h2>Multi-user readiness</h2>
                  </div>
                  <strong>Planning only</strong>
                </div>
                <p className="panel-note">
                  Registration is intentionally not active yet. The app should stay
                  private until imports, backups, API keys, hosting, and HTTPS are
                  stable enough for another person's finance data.
                </p>
                <ul className="quality-list readiness-list">
                  <li className="info">
                    <strong>Import review queue</strong>
                    <span>Confirm real SMS imports are reviewed safely before auto-saving.</span>
                  </li>
                  <li className="info">
                    <strong>Backup and restore</strong>
                    <span>Test creating, downloading, and restoring a real backup.</span>
                  </li>
                  <li className="info">
                    <strong>API key protection</strong>
                    <span>Keep keys hidden by default and regenerate them when needed.</span>
                  </li>
                  <li className="info">
                    <strong>Real user demand</strong>
                    <span>Only add accounts after at least one friend will actually use it.</span>
                  </li>
                  <li className="info">
                    <strong>HTTPS hosting</strong>
                    <span>Use a stable domain, production server, and secure session cookies.</span>
                  </li>
                </ul>
                <div className="action-row">
                  <a className="secondary-button" href="/MULTI_USER_PLAN.md" target="_blank">
                    Open architecture plan
                  </a>
                </div>
              </article>
            </>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function ImportsView({ apiKey, onCreateRule }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [exchangeRates, setExchangeRates] = useState({});
  const [repairingId, setRepairingId] = useState(null);
  const [importFilter, setImportFilter] = useState("needs_review");
  const [repairForm, setRepairForm] = useState({
    amount: "",
    currency: "BHD",
    merchant: "",
    date: getToday(),
    date_text: "",
    category: "Other",
  });

  async function loadImports() {
    setLoading(true);
    setError("");

    try {
      setData(await fetchJson("/api/imports"));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadImports();
  }, []);

  async function deleteImport(importId) {
    const confirmed = window.confirm("Delete this import history row?");

    if (!confirmed) {
      return;
    }

    setBusyAction(`delete-${importId}`);
    setStatus("");

    try {
      await fetchJson(`/api/imports/${importId}`, {
        method: "DELETE",
        headers: { "X-API-Key": apiKey },
      });
      await loadImports();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  async function convertImport(importId) {
    const importItem = data?.imports?.find((item) => item.id === importId);
    const parsedCurrency = importItem?.parsed_currency || "USD";
    const defaultRate =
      data?.default_currency_to_bhd_rates?.[parsedCurrency] ||
      data?.default_usd_to_bhd_rate ||
      0;
    const exchangeRate = Number(exchangeRates[importId] || defaultRate);

    if (!exchangeRate || exchangeRate <= 0) {
      setError("Enter an exchange rate greater than 0.");
      return;
    }

    setBusyAction(`convert-${importId}`);
    setError("");
    setStatus("");

    try {
      await fetchJson(`/api/imports/${importId}/convert-currency`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
        body: JSON.stringify({ exchange_rate: exchangeRate }),
      });
      await loadImports();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  async function aiParseImport(importId) {
    setBusyAction(`ai-${importId}`);
    setError("");
    setStatus("");

    try {
      await fetchJson(`/api/imports/${importId}/ai-parse`, {
        method: "POST",
        headers: { "X-API-Key": apiKey },
      });
      await loadImports();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  async function saveBhdImport(importId) {
    setBusyAction(`save-${importId}`);
    setError("");
    setStatus("");

    try {
      await fetchJson(`/api/imports/${importId}/save-bhd`, {
        method: "POST",
        headers: { "X-API-Key": apiKey },
      });
      await loadImports();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  function startRepair(item) {
    setError("");
    setRepairingId(item.id);
    setRepairForm({
      amount: item.parsed_amount ? String(item.parsed_amount) : "",
      currency: item.parsed_currency || "BHD",
      merchant: item.parsed_merchant || "",
      date: item.parsed_date || getToday(),
      date_text: item.parsed_date_text || item.parsed_date || "",
      category: item.parsed_category || item.transaction_category || "Other",
    });
  }

  function updateRepairField(field, value) {
    setRepairForm((current) => ({ ...current, [field]: value }));
  }

  async function saveRepair(event, importId) {
    event.preventDefault();
    setBusyAction(`repair-${importId}`);
    setError("");
    setStatus("");

    try {
      await fetchJson(`/api/imports/${importId}/repair`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
        body: JSON.stringify(repairForm),
      });
      setRepairingId(null);
      await loadImports();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  async function learnRuleFromImport(importId) {
    setBusyAction(`learn-${importId}`);
    setError("");
    setStatus("");

    try {
      await fetchJson(`/api/imports/${importId}/learn-rule`, {
        method: "POST",
        headers: { "X-API-Key": apiKey },
      });
      setStatus("Learned parser rule saved. Similar future messages can parse without AI.");
      await loadImports();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  async function clearImports(type) {
    const label = type === "failed" ? "failed imports" : "duplicate imports";
    const confirmed = window.confirm(`Clear all ${label}?`);

    if (!confirmed) {
      return;
    }

    setBusyAction(type);
    setStatus("");

    try {
      await fetchJson("/api/imports/clear", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
        body: JSON.stringify({ type }),
      });
      await loadImports();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyAction("");
    }
  }

  const visibleImports = useMemo(() => {
    const imports = data?.imports || [];

    if (importFilter === "needs_review") {
      return imports.filter((item) =>
        ["Needs review", "AI parsed, review", "Parsed but not saved"].includes(
          item.status
        )
      );
    }

    if (importFilter === "failed") {
      return imports.filter((item) => item.status === "Failed to parse");
    }

    return imports;
  }, [data, importFilter]);

  return (
    <section className="view-stack">
      <article className="panel">
        <div className="panel-title">
          <div>
            <h2>Import review</h2>
          </div>
        </div>

        <div className="import-summary">
          <SummaryCard
            label="All imports"
            value={data?.counts?.all || 0}
            detail="History rows"
          />
          <SummaryCard
            label="Failed"
            value={data?.counts?.failed || 0}
            detail="Needs SMS/parser review"
            tone="expense"
          />
          <SummaryCard
            label="Duplicates"
            value={data?.counts?.duplicates || 0}
            detail="Ignored safely"
          />
          <SummaryCard
            label="Needs review"
            value={data?.counts?.needs_review || 0}
            detail="Waiting for confirmation"
            tone="expense"
          />
        </div>

        <div className="segmented-control import-filter" aria-label="Import filter">
          <button
            className={importFilter === "needs_review" ? "active" : ""}
            type="button"
            onClick={() => setImportFilter("needs_review")}
          >
            Review queue
          </button>
          <button
            className={importFilter === "failed" ? "active" : ""}
            type="button"
            onClick={() => setImportFilter("failed")}
          >
            Failed
          </button>
          <button
            className={importFilter === "all" ? "active" : ""}
            type="button"
            onClick={() => setImportFilter("all")}
          >
            All history
          </button>
        </div>

        <div className="action-row">
          <button
            className="secondary-button"
            disabled={busyAction === "failed"}
            type="button"
            onClick={() => clearImports("failed")}
          >
            Clear failed
          </button>
          <button
            className="secondary-button"
            disabled={busyAction === "duplicates"}
            type="button"
            onClick={() => clearImports("duplicates")}
          >
            Clear duplicates
          </button>
          <button className="secondary-button" type="button" onClick={loadImports}>
            Refresh
          </button>
        </div>
        <p className="panel-note">
          AI parse learns a reusable SMS parser rule, so similar future bank messages
          can be parsed without using AI again.
        </p>
      </article>

      <article className="panel">
        {status && <p className="form-status">{status}</p>}
        {error && <p className="form-status error-text">{error}</p>}
        {loading && <EmptyState title="Loading imports" detail="Reading SMS import history." />}
        {!loading && visibleImports.length ? (
          <ul className="import-list">
            {visibleImports.map((item) => (
              <li key={item.id}>
                <div className="import-list-header">
                  <div>
                    <strong>
                      {item.redacted_parsed_merchant ||
                        item.parsed_merchant ||
                        "Unknown merchant"}
                    </strong>
                    <span>{item.created_at}</span>
                  </div>
                  <em>{item.status}</em>
                </div>
                {item.review_reason || item.parser_confidence !== null ? (
                  <div className="review-reason-card">
                    <strong>
                      {Math.round(Number(item.parser_confidence || 0) * 100)}% confidence
                    </strong>
                    <span>{item.review_reason || "Review before saving."}</span>
                  </div>
                ) : null}
                <div className="import-meta-grid">
                  <span>
                    Amount
                    <strong>
                      {item.parsed_amount
                        ? `${item.parsed_currency} ${formatAmount(item.parsed_amount)}`
                        : "Not parsed"}
                    </strong>
                  </span>
                  <span>
                    Transaction
                    <strong>
                      {item.transaction_id
                        ? `${item.transaction_category} - ${formatAmount(
                            item.transaction_amount
                          )}`
                        : "Not created"}
                    </strong>
                  </span>
                  <span>
                    Date text
                    <strong>{item.parsed_date_text || "Not parsed"}</strong>
                  </span>
                  <span>
                    Category
                    <strong>{item.parsed_category || item.transaction_category || "Not parsed"}</strong>
                  </span>
                </div>
                {item.ai_parsed_at ? (
                  <div className="ai-parse-card">
                    <div>
                      <strong>AI parsed</strong>
                      <span>
                        Confidence{" "}
                        {Math.round(Number(item.ai_parse_confidence || 0) * 100)}%
                      </span>
                    </div>
                    <p>{item.ai_parse_reason || "Review before saving."}</p>
                  </div>
                ) : null}
                <details>
                  <summary>Raw SMS</summary>
                  <p>{item.redacted_raw_message}</p>
                </details>
                {repairingId === item.id ? (
                  <form
                    className="repair-form"
                    onSubmit={(event) => saveRepair(event, item.id)}
                  >
                    <label>
                      Amount
                      <input
                        required
                        min="0.001"
                        step="0.001"
                        type="number"
                        value={repairForm.amount}
                        onChange={(event) => updateRepairField("amount", event.target.value)}
                      />
                    </label>
                    <label>
                      Currency
                      <input
                        required
                        maxLength="3"
                        type="text"
                        value={repairForm.currency}
                        onChange={(event) =>
                          updateRepairField("currency", event.target.value.toUpperCase())
                        }
                      />
                    </label>
                    <label>
                      Merchant
                      <input
                        required
                        type="text"
                        value={repairForm.merchant}
                        onChange={(event) => updateRepairField("merchant", event.target.value)}
                      />
                    </label>
                    <label>
                      Date
                      <input
                        required
                        type="date"
                        value={repairForm.date}
                        onChange={(event) => updateRepairField("date", event.target.value)}
                      />
                    </label>
                    <label>
                      Date text in SMS
                      <input
                        type="text"
                        value={repairForm.date_text}
                        placeholder="JUN 06, 21:30 or 06/06/2026"
                        onChange={(event) => updateRepairField("date_text", event.target.value)}
                      />
                    </label>
                    <label>
                      Category
                      <select
                        value={repairForm.category}
                        onChange={(event) => updateRepairField("category", event.target.value)}
                      >
                        {(data?.categories || []).map((category) => (
                          <option key={category} value={category}>
                            {category}
                          </option>
                        ))}
                        <option value="Income">Income</option>
                      </select>
                    </label>
                    <div className="row-actions">
                      <button
                        className="primary-button"
                        disabled={busyAction === `repair-${item.id}`}
                        type="submit"
                      >
                        Save repair
                      </button>
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => setRepairingId(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : null}
                {item.parsed_amount &&
                item.parsed_currency !== "BHD" &&
                !item.transaction_id ? (
                  <div className="conversion-box">
                    <div>
                      <strong>Convert {item.parsed_currency} to BHD</strong>
                      <span>
                        {item.parsed_currency} {formatAmount(item.parsed_amount)} x rate
                      </span>
                    </div>
                    <label>
                      Exchange rate
                      <input
                        min="0.001"
                        step="0.001"
                        type="number"
                        value={
                          exchangeRates[item.id] ??
                          String(
                            data.default_currency_to_bhd_rates?.[item.parsed_currency] ||
                              data.default_usd_to_bhd_rate ||
                              ""
                          )
                        }
                        onChange={(event) =>
                          setExchangeRates((current) => ({
                            ...current,
                            [item.id]: event.target.value,
                          }))
                        }
                      />
                    </label>
                    <button
                      className="primary-button"
                      disabled={busyAction === `convert-${item.id}`}
                      type="button"
                      onClick={() => convertImport(item.id)}
                    >
                      Save as BHD
                    </button>
                  </div>
                ) : null}
                <div className="row-actions">
                  <button
                    className="secondary-button"
                    disabled={busyAction === `ai-${item.id}`}
                    type="button"
                    onClick={() => aiParseImport(item.id)}
                  >
                    {busyAction === `ai-${item.id}` ? "Parsing..." : "AI parse"}
                  </button>
                  {!item.transaction_id ? (
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => startRepair(item)}
                    >
                      Repair manually
                    </button>
                  ) : null}
                  {item.parsed_amount &&
                  item.parsed_currency &&
                  item.parsed_merchant ? (
                    <button
                      className="secondary-button"
                      disabled={busyAction === `learn-${item.id}`}
                      type="button"
                      onClick={() => learnRuleFromImport(item.id)}
                    >
                      Learn rule
                    </button>
                  ) : null}
                  {item.parsed_amount &&
                  item.parsed_currency === "BHD" &&
                  !item.transaction_id ? (
                    <button
                      className="primary-button"
                      disabled={busyAction === `save-${item.id}`}
                      type="button"
                      onClick={() => saveBhdImport(item.id)}
                    >
                      Save BHD
                    </button>
                  ) : null}
                  {item.status === "Needs category rule" && item.parsed_merchant ? (
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => onCreateRule(item.parsed_merchant)}
                    >
                      Create rule
                    </button>
                  ) : null}
                  <button
                    className="danger-button"
                    disabled={busyAction === `delete-${item.id}`}
                    type="button"
                    onClick={() => deleteImport(item.id)}
                  >
                    Delete import
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
        {!loading && data?.imports?.length && !visibleImports.length ? (
          <EmptyState
            title={
              importFilter === "needs_review"
                ? "Review queue is clear"
                : "No imports in this filter"
            }
            detail="Switch to all history to see older saved or duplicate imports."
          />
        ) : null}
        {!loading && !data?.imports?.length ? (
          <EmptyState
            title="No import history"
            detail="iPhone Shortcut SMS imports will appear here."
          />
        ) : null}
      </article>
    </section>
  );
}

function ShortcutGuideModal({ apiKey, importUrl, onClose }) {
  const [copied, setCopied] = useState("");
  const guideScreenshots = [
    {
      image: "/static/shortcut-guide-start/IMG_9874.jpeg",
      title: "Open Shortcuts",
      detail:
        "Search for Shortcuts on your iPhone and open the Shortcuts app.",
    },
    {
      image: "/static/shortcut-guide-start/IMG_9875.jpeg",
      title: "Open Automation",
      detail:
        "Go to the Automation tab and tap the plus button to create a personal automation.",
    },
    {
      image: "/static/shortcut-guide/IMG_9864.jpeg",
      title: "Choose the Message trigger",
      detail:
        "In Shortcuts, create a Personal Automation and choose Message as the trigger.",
    },
    {
      image: "/static/shortcut-guide/IMG_9865.jpeg",
      title: "Set the bank message condition",
      detail:
        "Choose your bank sender if you want, set Message Contains to BHD, and select Run Immediately.",
    },
    {
      image: "/static/shortcut-guide/IMG_9866.jpeg",
      title: "Create the action",
      detail:
        "After the trigger is created, tap Create New Shortcut or add an action below the received message input.",
    },
    {
      image: "/static/shortcut-guide/IMG_9870.jpeg",
      title: "Add Get Contents of URL",
      detail:
        "Search for Get Contents and choose Get Contents of URL.",
    },
    {
      image: "/static/shortcut-guide/IMG_9871.jpeg",
      title: "Fill the web request",
      detail:
        "Paste the Import URL, set Method to POST, add X-API-Key, set Request Body to JSON, and add raw_message.",
    },
    {
      image: "/static/shortcut-guide/IMG_9872.jpeg",
      title: "Use the real message variable",
      detail:
        "For raw_message, choose Shortcut Input or Received Message. Do not type the words manually.",
    },
    {
      image: "/static/shortcut-guide/IMG_9873.jpeg",
      title: "Final check",
      detail:
        "The finished action should show POST, X-API-Key, JSON, and raw_message set to Shortcut Input.",
    },
  ];

  async function copyText(label, value) {
    if (!navigator.clipboard) {
      setCopied(`${label}: ${value}`);
      return;
    }

    await navigator.clipboard.writeText(value);
    setCopied(`${label} copied`);
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="guide-modal" role="dialog" aria-modal="true" aria-labelledby="shortcut-guide-title">
        <div className="guide-header">
          <div>
            <span>First login guide</span>
            <h2 id="shortcut-guide-title">Set up iPhone SMS automation</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close guide">
            x
          </button>
        </div>

        <div className="guide-intro">
          <p>
            This connects your iPhone Shortcut to Flask. When a message from
            your bank contains BHD, the Shortcut sends the message text to this
            app.
          </p>
        </div>

        <div className="guide-copy-grid">
          <button type="button" onClick={() => copyText("Import URL", importUrl)}>
            <span>Import URL</span>
            <code>{importUrl}</code>
          </button>
          <button type="button" onClick={() => copyText("API key", apiKey)}>
            <span>API key</span>
            <code>{apiKey}</code>
          </button>
        </div>

        {copied && <div className="notice compact">{copied}</div>}

        <ol className="guide-steps">
          <li>
            <strong>Open Shortcuts</strong>
            <p>
              Search for <code>Shortcuts</code> on your iPhone and open the app.
            </p>
          </li>
          <li>
            <strong>Open the Automation tab</strong>
            <p>
              Tap Automation at the bottom, then tap the plus button to create a
              new personal automation.
            </p>
          </li>
          <li>
            <strong>Create the automation trigger</strong>
            <p>
              In Shortcuts, create a personal automation. Choose Message as the
              trigger, set your bank sender if needed, and set Message Contains
              to <code>BHD</code>.
            </p>
          </li>
          <li>
            <strong>Run it immediately</strong>
            <p>
              Choose Run Immediately so the Shortcut can send the SMS to the app
              without you opening the browser.
            </p>
          </li>
          <li>
            <strong>Add the correct Do action</strong>
            <p>
              Search for <code>Get Contents of URL</code>. Do not use Send
              Message.
            </p>
          </li>
          <li>
            <strong>Configure the request</strong>
            <p>
              Paste the Import URL, set Method to <code>POST</code>, add header
              <code>X-API-Key</code>, and set Request Body to <code>JSON</code>.
            </p>
          </li>
          <li>
            <strong>Add the message body</strong>
            <p>
              In JSON body, add key <code>raw_message</code>. For its value,
              choose <code>Shortcut Input</code> or the Received Message
              variable.
            </p>
          </li>
          <li>
            <strong>Test and review</strong>
            <p>
              Send a test BBK message or run the Shortcut manually. BHD imports
              should become transactions; USD imports should appear in Imports
              for exchange-rate review.
            </p>
          </li>
        </ol>

        <div className="guide-screenshot-grid">
          {guideScreenshots.map((step, index) => (
            <article className="guide-screenshot-card" key={step.image}>
              <div>
                <span>Step {index + 1}</span>
                <strong>{step.title}</strong>
                <p>{step.detail}</p>
              </div>
              <img src={step.image} alt={step.title} loading="lazy" />
            </article>
          ))}
        </div>

        <div className="guide-actions">
          <button className="primary-button" type="button" onClick={onClose}>
            I finished setup
          </button>
        </div>
      </section>
    </div>
  );
}

function AuthView({ route }) {
  const [sessionState, setSessionState] = useState(null);
  const [invite, setInvite] = useState(null);
  const [form, setForm] = useState({
    username: "owner",
    password: "",
    confirm_password: "",
  });
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const inviteToken = getInviteTokenFromPath(window.location.pathname);
  const isInviteRoute = route === "invite";

  useEffect(() => {
    let isCurrentRequest = true;

    async function loadAuthState() {
      setLoading(true);
      setStatus("");

      try {
        const [sessionData, inviteData] = await Promise.all([
          fetchJson("/api/session"),
          isInviteRoute ? fetchJson(`/api/invite/${encodeURIComponent(inviteToken)}`) : null,
        ]);

        if (!isCurrentRequest) {
          return;
        }

        setSessionState(sessionData);
        setInvite(inviteData?.invite || null);

        if (sessionData.authenticated && !isInviteRoute) {
          window.location.replace("/");
        }
      } catch (requestError) {
        if (isCurrentRequest) {
          setStatus(requestError.message);
        }
      } finally {
        if (isCurrentRequest) {
          setLoading(false);
        }
      }
    }

    loadAuthState();

    return () => {
      isCurrentRequest = false;
    };
  }, [inviteToken, isInviteRoute]);

  async function submitAuth(event) {
    event.preventDefault();
    setBusy(true);
    setStatus("");

    try {
      const nextUrl = new URLSearchParams(window.location.search).get("next") || "/";
      const result = await fetchJson(
        isInviteRoute ? `/api/invite/${encodeURIComponent(inviteToken)}/accept` : "/api/login",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...form,
            next_url: nextUrl,
          }),
        }
      );

      window.location.replace(result.redirect_url || "/");
    } catch (requestError) {
      setStatus(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  const setupRequired = Boolean(sessionState?.setup_required);
  const title = isInviteRoute
    ? `Join as ${invite?.display_name || "invited user"}`
    : setupRequired
      ? "Create your password"
      : "Log in";
  const detail = isInviteRoute
    ? "Create a password for your private expense tracker account."
    : setupRequired
      ? "This protects your local expense tracker before the dashboard opens."
      : "Enter your account password to open the dashboard.";

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="auth-brand">
          <span>ET</span>
          <strong>Smart Expense</strong>
        </div>
        <p className="eyebrow">Private app</p>
        <h1>{loading ? "Checking access" : title}</h1>
        <p className="auth-copy">{detail}</p>

        {status && <div className="notice error compact">{status}</div>}

        {!loading && (!isInviteRoute || invite) && (
          <form className="auth-form" onSubmit={submitAuth}>
            {!setupRequired && !isInviteRoute && (
              <label>
                Username
                <input
                  autoFocus
                  required
                  autoComplete="username"
                  type="text"
                  value={form.username}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, username: event.target.value }))
                  }
                />
              </label>
            )}

            {isInviteRoute && invite && (
              <div className="invite-summary">
                <span>Username</span>
                <strong>{invite.username}</strong>
              </div>
            )}

            <label>
              Password
              <input
                autoFocus={setupRequired || isInviteRoute}
                required
                minLength={8}
                autoComplete={setupRequired || isInviteRoute ? "new-password" : "current-password"}
                type="password"
                value={form.password}
                onChange={(event) =>
                  setForm((current) => ({ ...current, password: event.target.value }))
                }
              />
            </label>

            {(setupRequired || isInviteRoute) && (
              <label>
                Confirm password
                <input
                  required
                  minLength={8}
                  autoComplete="new-password"
                  type="password"
                  value={form.confirm_password}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      confirm_password: event.target.value,
                    }))
                  }
                />
              </label>
            )}

            <button className="primary-button" disabled={busy} type="submit">
              {busy
                ? "Working..."
                : isInviteRoute
                  ? "Create account"
                  : setupRequired
                    ? "Create password"
                    : "Log in"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}

export default function App() {
  const [selectedMonth, setSelectedMonth] = useState(getCurrentMonth());
  const [theme, setTheme] = useState(getPreferredTheme);
  const [route, setRoute] = useState(() => getRouteFromPath(window.location.pathname));
  const [selectedDay, setSelectedDay] = useState(() => getDayFromPath(window.location.pathname));
  const [chartType, setChartType] = useState("pie");
  const [dashboard, setDashboard] = useState(null);
  const [monthTransactions, setMonthTransactions] = useState([]);
  const [dashboardLoading, setDashboardLoading] = useState(true);
  const [appError, setAppError] = useState("");
  const [cleanupKeyword, setCleanupKeyword] = useState("");
  const [showShortcutGuide, setShowShortcutGuide] = useState(false);
  const [config, setConfig] = useState({
    categories: fallbackCategories,
    api_key: "",
    import_url: "",
  });

  const activeNav = route;
  const showMonthControls = monthBasedRoutes.has(route);
  const isAuthRoute = route === "login" || route === "invite";

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.body.dataset.theme = theme;

    return () => {
      delete document.documentElement.dataset.theme;
      delete document.body.dataset.theme;
    };
  }, [theme]);

  useEffect(() => {
    const mediaQuery = window.matchMedia?.("(prefers-color-scheme: dark)");

    if (!mediaQuery) {
      return undefined;
    }

    function handleSystemThemeChange(event) {
      if (window.localStorage?.getItem(themeStorageKey)) {
        return;
      }

      setTheme(event.matches ? "midnight" : "mint");
    }

    mediaQuery.addEventListener?.("change", handleSystemThemeChange);
    return () => mediaQuery.removeEventListener?.("change", handleSystemThemeChange);
  }, []);

  useEffect(() => {
    if (isAuthRoute) {
      return undefined;
    }

    async function loadConfig() {
      try {
        const data = await fetchJson("/api/config");
        setConfig({
          categories: data.categories || fallbackCategories,
          api_key: data.api_key || "",
          import_url: data.import_url || "/import-message",
        });
        if (data.default_dashboard_month) {
          setSelectedMonth((currentMonth) =>
            currentMonth === getCurrentMonth() &&
            data.default_dashboard_month !== currentMonth
              ? data.default_dashboard_month
              : currentMonth
          );
        }
        setShowShortcutGuide(Boolean(data.show_shortcut_guide));
      } catch (requestError) {
        setAppError(`Could not load app config. ${requestError.message}`);
      }
    }

    loadConfig();
  }, [isAuthRoute]);

  useEffect(() => {
    function handlePopState() {
      setRoute(getRouteFromPath(window.location.pathname));
      setSelectedDay(getDayFromPath(window.location.pathname));
    }

    window.addEventListener("popstate", handlePopState);

    return () => {
      window.removeEventListener("popstate", handlePopState);
    };
  }, []);

  async function loadDashboard() {
    if (isAuthRoute) {
      return;
    }

    setDashboardLoading(true);
    setAppError("");

    try {
      const [data, transactionData] = await Promise.all([
        fetchJson(`/api/dashboard?month=${selectedMonth}`),
        fetchJson(`/api/transactions?month=${selectedMonth}&sort=oldest`),
      ]);
      setDashboard(data);
      setMonthTransactions(transactionData.transactions || []);
    } catch (requestError) {
      setAppError(
        `Could not load dashboard data. Check that Flask is running on port 5000. ${requestError.message}`
      );
    } finally {
      setDashboardLoading(false);
    }
  }

  useEffect(() => {
    if (isAuthRoute) {
      setDashboardLoading(false);
      return undefined;
    }

    let isCurrentRequest = true;

    async function loadCurrentDashboard() {
      setDashboardLoading(true);
      setAppError("");

      try {
        const [data, transactionData] = await Promise.all([
          fetchJson(`/api/dashboard?month=${selectedMonth}`),
          fetchJson(`/api/transactions?month=${selectedMonth}&sort=oldest`),
        ]);

        if (isCurrentRequest) {
          setDashboard(data);
          setMonthTransactions(transactionData.transactions || []);
        }
      } catch (requestError) {
        if (isCurrentRequest) {
          setAppError(
            `Could not load dashboard data. Check that Flask is running on port 5000. ${requestError.message}`
          );
        }
      } finally {
        if (isCurrentRequest) {
          setDashboardLoading(false);
        }
      }
    }

    loadCurrentDashboard();

    return () => {
      isCurrentRequest = false;
    };
  }, [selectedMonth, isAuthRoute]);

  function navigate(nextRoute) {
    const item = navItems.find((navItem) => navItem.id === nextRoute);

    if (!item || item.external) {
      return;
    }

    window.history.pushState({}, "", item.path);
    setRoute(nextRoute);
    setSelectedDay("");
  }

  function navigateToDay(date) {
    window.history.pushState({}, "", `/day/${date}`);
    setSelectedDay(date);
    setSelectedMonth(date.slice(0, 7));
    setRoute("day");
  }

  function handleNavClick(event, item) {
    if (item.external) {
      return;
    }

    event.preventDefault();
    navigate(item.id);
  }

  function handleCreated(month) {
    setSelectedMonth(month);
  }

  function startRuleFromImport(keyword) {
    setCleanupKeyword(keyword);
    navigate("cleanup");
  }

  function updateApiKey(apiKey) {
    setConfig((current) => ({ ...current, api_key: apiKey }));
  }

  async function dismissShortcutGuide() {
    setShowShortcutGuide(false);

    try {
      await fetchJson("/api/onboarding/shortcut-guide/dismiss", {
        method: "POST",
      });
    } catch (requestError) {
      setAppError(`Could not save guide status. ${requestError.message}`);
    }
  }

  if (isAuthRoute) {
    return (
      <div className={`app-layout auth-layout theme-${theme}`}>
        <AuthView route={route} />
      </div>
    );
  }

  return (
    <div className={`app-layout theme-${theme}`}>
      {showShortcutGuide && (
        <ShortcutGuideModal
          apiKey={config.api_key}
          importUrl={config.import_url}
          onClose={dismissShortcutGuide}
        />
      )}
      <aside className="sidebar">
        <a className="brand" href="/" onClick={(event) => handleNavClick(event, navItems[0])}>
          <span>ET</span>
          <strong>Smart Expense</strong>
        </a>
        <nav className="side-nav" aria-label="Primary">
          {navItems.map((item) => (
            <a
              className={activeNav === item.id ? "active" : ""}
              href={item.path}
              key={item.id}
              onClick={(event) => handleNavClick(event, item)}
            >
              {item.label}
            </a>
          ))}
        </nav>
        <div className="theme-menu" aria-label="Visual style options">
          <span>Design</span>
          {themes.map((themeOption) => (
            <button
              className={theme === themeOption.id ? "active" : ""}
              key={themeOption.id}
              type="button"
              onClick={() => {
                window.localStorage?.setItem(themeStorageKey, themeOption.id);
                setTheme(themeOption.id);
              }}
            >
              {themeOption.name}
            </button>
          ))}
        </div>
      </aside>

      <main className="content-shell">
        <header className="topbar">
          <div className="title-block">
            <p className="eyebrow">Personal finance assistant</p>
            <h1>
              {route === "add"
                ? "Add Transaction"
                : route === "transactions"
                  ? "Transactions"
                  : route === "reports"
                    ? "Reports"
                    : route === "imports"
                      ? "Import Review"
                      : route === "cleanup"
                        ? "Cleanup"
                        : route === "budgets"
                          ? "Budgets"
                          : route === "settings"
                            ? "Settings"
                            : "Spending Overview"}
            </h1>
            {showMonthControls && (
              <p className="subhead">
                {dashboard?.selected_month?.label || "Loading selected month"}
              </p>
            )}
          </div>
          {showMonthControls && (
            <div className="toolbar">
              <label>
                Month
                <input
                  type="month"
                  value={selectedMonth}
                  onChange={(event) => setSelectedMonth(event.target.value)}
                />
              </label>
            </div>
          )}
        </header>

        {appError && <section className="notice error">{appError}</section>}

        {route === "dashboard" && (
          <DashboardView
            chartType={chartType}
            dashboard={dashboard}
            loading={dashboardLoading}
            monthTransactions={monthTransactions}
            onChartTypeChange={setChartType}
            onDaySelect={navigateToDay}
            onNavigate={navigate}
          />
        )}

        {route === "add" && (
          <AddTransactionView
            apiKey={config.api_key}
            categories={config.categories}
            onCreated={handleCreated}
            onNavigate={navigate}
          />
        )}

        {route === "transactions" && (
          <TransactionsView
            apiKey={config.api_key}
            categories={config.categories}
            selectedMonth={selectedMonth}
          />
        )}

        {route === "day" && (
          <TransactionsView
            apiKey={config.api_key}
            categories={config.categories}
            onBackToDashboard={() => navigate("dashboard")}
            selectedDate={selectedDay}
            selectedMonth={selectedDay ? selectedDay.slice(0, 7) : selectedMonth}
          />
        )}

        {route === "reports" && <ReportsView selectedMonth={selectedMonth} />}

        {route === "imports" && (
          <ImportsView apiKey={config.api_key} onCreateRule={startRuleFromImport} />
        )}

        {route === "budgets" && (
          <BudgetsView
            apiKey={config.api_key}
            dashboard={dashboard}
            onSaved={loadDashboard}
            selectedMonth={selectedMonth}
          />
        )}

        {route === "cleanup" && (
          <CleanupView
            apiKey={config.api_key}
            categories={config.categories}
            initialKeyword={cleanupKeyword}
            onInitialKeywordUsed={() => setCleanupKeyword("")}
          />
        )}

        {route === "settings" && (
          <SettingsView
            apiKey={config.api_key}
            onApiKeyChanged={updateApiKey}
            onShowShortcutGuide={() => setShowShortcutGuide(true)}
          />
        )}
      </main>
    </div>
  );
}
