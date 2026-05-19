import { createFileRoute } from "@tanstack/react-router";
import { ActivityIcon, BarChart3Icon, FileIcon, FolderOpenIcon, PieChartIcon, RowsIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, Cell, Pie, PieChart } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "#/components/ui/card";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "#/components/ui/chart";
import { Skeleton } from "#/components/ui/skeleton";
import { type DashboardStats, getDashboardStats } from "#/lib/server";
import { PageHeader } from "#/routes/(platform)/-components/page-header";
import { StatCard } from "#/routes/(platform)/dashboard/-components/stat-card";

const CHART_COLORS = ["#F9F618", "#F4F4F4", "#9A9A9A", "#404040", "#D9D9D9", "#6B6B6B", "#C8C8C8", "#141414"];

const processStatusChartConfig = {
  queued: { label: "Queued", color: CHART_COLORS[0] },
  processing: { label: "Processing", color: CHART_COLORS[1] },
  completed: { label: "Completed", color: CHART_COLORS[2] },
  failed: { label: "Failed", color: CHART_COLORS[3] },
} satisfies import("#/components/ui/chart").ChartConfig;

const formatDistributionChartConfig = {
  json_lines: { label: "JSON Lines", color: CHART_COLORS[0] },
  csv: { label: "CSV", color: CHART_COLORS[1] },
  syslog: { label: "Syslog", color: CHART_COLORS[2] },
  apache_access: { label: "Apache Access", color: CHART_COLORS[3] },
  nginx_access: { label: "Nginx Access", color: CHART_COLORS[4] },
  logfmt: { label: "Logfmt", color: CHART_COLORS[5] },
  key_value: { label: "Key Value", color: CHART_COLORS[6] },
  unified: { label: "Unified", color: CHART_COLORS[7] },
} satisfies import("#/components/ui/chart").ChartConfig;

export const Route = createFileRoute("/(platform)/dashboard/")({
  component: DashboardPage,
});

function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      setLoading(true);
      try {
        const data = await getDashboardStats();
        setStats(data);
      } catch {
        setStats(null);
      } finally {
        setLoading(false);
      }
    };

    void fetchStats();
  }, []);

  const processingCount = useMemo(() => {
    return (stats?.processes.queued ?? 0) + (stats?.processes.processing ?? 0);
  }, [stats]);

  const processStatusData = useMemo(() => {
    if (!stats) return [];
    return [
      { status: "queued", value: stats.processes.queued },
      { status: "processing", value: stats.processes.processing },
      { status: "completed", value: stats.processes.completed },
      { status: "failed", value: stats.processes.failed },
    ];
  }, [stats]);

  const formatDistributionData = useMemo(() => {
    if (!stats) return [];
    return stats.format_distribution.map((item) => ({
      format: item.format,
      value: item.count,
    }));
  }, [stats]);

  return (
    <>
      <PageHeader breadcrumbs={[{ label: "Dashboard" }]} />
      <div className={"flex flex-1 flex-col gap-6 p-6"}>
        <div className={"grid gap-4 md:grid-cols-2 lg:grid-cols-4"}>
          <StatCard
            description={"Total log groups created"}
            icon={FolderOpenIcon}
            loading={loading}
            title={"Log Groups"}
            value={stats?.log_group_count ?? 0}
          />
          <StatCard
            description={"Files uploaded across all groups"}
            icon={FileIcon}
            loading={loading}
            title={"Total Files"}
            value={stats?.total_files ?? 0}
          />
          <StatCard
            description={"Rows inferred from process results"}
            icon={RowsIcon}
            loading={loading}
            title={"Total Rows"}
            value={stats?.total_rows ?? 0}
          />
          <StatCard
            description={`${stats?.processes.completed ?? 0} completed, ${stats?.processes.failed ?? 0} failed`}
            icon={ActivityIcon}
            loading={loading}
            title={"Processing"}
            value={processingCount}
          />
        </div>

        <div className={"grid gap-4 md:grid-cols-2"}>
          <Card>
            <CardHeader className={"pb-2"}>
              <CardTitle className={"flex items-center gap-2 font-medium text-sm"}>
                <BarChart3Icon className={"size-4 text-muted-foreground"} />
                Process Status
              </CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <Skeleton className={"h-[200px] w-full"} />
              ) : processStatusData.length === 0 || processStatusData.every((d) => d.value === 0) ? (
                <p className={"text-muted-foreground py-8 text-center text-sm"}>No process data yet.</p>
              ) : (
                <ChartContainer className={"h-[200px] w-full"} config={processStatusChartConfig}>
                  <BarChart data={processStatusData}>
                    <ChartTooltip content={<ChartTooltipContent nameKey="status" />} />
                    <ChartLegend content={<ChartLegendContent nameKey="status" />} />
                    <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                      {processStatusData.map((entry, index) => (
                        <Cell fill={CHART_COLORS[index % CHART_COLORS.length]} key={`cell-${entry.status}`} />
                      ))}
                    </Bar>
                  </BarChart>
                </ChartContainer>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className={"pb-2"}>
              <CardTitle className={"flex items-center gap-2 font-medium text-sm"}>
                <PieChartIcon className={"size-4 text-muted-foreground"} />
                Format Distribution
              </CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <Skeleton className={"h-[200px] w-full"} />
              ) : formatDistributionData.length === 0 ? (
                <p className={"text-muted-foreground py-8 text-center text-sm"}>No format data yet.</p>
              ) : (
                <ChartContainer className={"h-[200px] w-full"} config={formatDistributionChartConfig}>
                  <PieChart>
                    <Pie
                      cx="50%"
                      cy="50%"
                      data={formatDistributionData}
                      dataKey="value"
                      nameKey="format"
                      outerRadius={80}
                      paddingAngle={2}
                    >
                      {formatDistributionData.map((entry, index) => (
                        <Cell fill={CHART_COLORS[index % CHART_COLORS.length]} key={`cell-${entry.format}`} />
                      ))}
                    </Pie>
                    <ChartTooltip content={<ChartTooltipContent nameKey="format" />} />
                    <ChartLegend content={<ChartLegendContent nameKey="format" />} />
                  </PieChart>
                </ChartContainer>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
