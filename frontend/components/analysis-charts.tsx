"use client";

import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { format, parseISO } from "date-fns";
import { useState } from "react";
import { Info } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { HELP, type HelpKey } from "@/lib/analysis-help";
import { INK } from "@/lib/analysis";
import { cn } from "@/lib/utils";

const axis = {
  stroke: INK.axis,
  tick: { fill: INK.muted, fontSize: 11 },
  tickLine: false,
} as const;

export function InfoButton({ topic, label }: { topic: HelpKey; label: string }) {
  const h = HELP[topic];
  return (
    <Popover>
      <PopoverTrigger
        aria-label={`How to read: ${label}`}
        className="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground hover:text-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <Info className="h-3.5 w-3.5" />
      </PopoverTrigger>
      <PopoverContent className="w-[380px] max-w-[calc(100vw-32px)] p-4 text-xs leading-relaxed space-y-3 max-h-[70vh] overflow-y-auto">
        <div>
          <p className="font-medium text-foreground mb-1">What it shows</p>
          <p className="text-muted-foreground">{h.shows}</p>
        </div>
        <div>
          <p className="font-medium text-foreground mb-1">What to look for</p>
          <ul className="list-disc pl-4 space-y-1 text-muted-foreground">
            {h.lookFor.map((t) => <li key={t}>{t}</li>)}
          </ul>
        </div>
        {"caveats" in h && h.caveats && (
          <div>
            <p className="font-medium text-foreground mb-1">Caveats</p>
            <ul className="list-disc pl-4 space-y-1 text-muted-foreground">
              {h.caveats.map((t) => <li key={t}>{t}</li>)}
            </ul>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

export function ChartCard({
  title,
  hint,
  info,
  right,
  children,
  className,
}: {
  title: string;
  hint?: React.ReactNode;
  info?: HelpKey;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("min-w-0", className)}>
      <CardHeader className="pb-2 flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle className="text-base flex items-center gap-1.5">
            {title}
            {info && <InfoButton topic={info} label={title} />}
          </CardTitle>
          {hint && <p className="text-xs text-muted-foreground mt-1 max-w-prose">{hint}</p>}
        </div>
        {right}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export function TipBox({ title, rows }: { title: string; rows: [string, string, string?][] }) {
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
      <p className="font-medium mb-1 text-foreground">{title}</p>
      {rows.map(([k, v, color]) => (
        <p key={k} className="flex items-center gap-2 text-muted-foreground">
          {color && <span className="h-2 w-2 rounded-full" style={{ background: color }} />}
          <span>{k}</span>
          <span className="ml-auto pl-4 tabular-nums text-foreground">{v}</span>
        </p>
      ))}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string; hollow?: boolean }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {items.map((i) => (
        <span key={i.label} className="flex items-center gap-1.5">
          <span
            className="h-2.5 w-2.5 rounded-sm"
            style={i.hollow ? { border: `1.5px solid ${i.color}` } : { background: i.color }}
          />
          {i.label}
        </span>
      ))}
    </div>
  );
}

// ------------------------------------------------------------- stacked bars

export type StackSeries = { key: string; label: string; color: string };

export function StackedBars({
  data,
  series,
  unit,
  percent,
  reference,
  height = 240,
}: {
  data: Record<string, any>[];
  series: StackSeries[];
  unit: string;
  percent?: boolean;
  reference?: { y: number; label: string };
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} stackOffset={percent ? "expand" : "none"} barCategoryGap="20%">
        <CartesianGrid vertical={false} stroke={INK.grid} />
        <XAxis dataKey="label" {...axis} interval="preserveStartEnd" minTickGap={16} />
        <YAxis
          {...axis}
          width={44}
          axisLine={false}
          tickFormatter={(v) => (percent ? `${Math.round(v * 100)}%` : `${v}`)}
        />
        <Tooltip
          cursor={{ fill: "rgba(255,255,255,0.04)" }}
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            const total = series.reduce((s, x) => s + (payload[0].payload[x.key] ?? 0), 0);
            return (
              <TipBox
                title={String(label)}
                rows={[...series]
                  .reverse()
                  .filter((x) => payload[0].payload[x.key])
                  .map((x) => {
                    const v = payload[0].payload[x.key] as number;
                    return [
                      x.label,
                      percent ? `${Math.round((v / total) * 100)}%` : `${v.toFixed(1)} ${unit}`,
                      x.color,
                    ];
                  })}
              />
            );
          }}
        />
        {reference && (
          <ReferenceLine
            y={reference.y}
            stroke={INK.text}
            strokeDasharray="4 4"
            label={{ value: reference.label, fill: INK.text, fontSize: 11, position: "insideTopRight" }}
          />
        )}
        {series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            stackId="a"
            fill={s.color}
            stroke="hsl(240 6% 10%)"
            strokeWidth={1}
            radius={i === series.length - 1 ? [4, 4, 0, 0] : 0}
            isAnimationActive={false}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

// ------------------------------------------------------------- trend scatter

export type TrendPoint = {
  x: number; // epoch ms
  y: number;
  ghost: boolean;
  color: string;
  id: number;
  tip: [string, string][];
  title: string;
  hollow?: boolean;
};

const dateTick = (v: number) => format(new Date(v), "d MMM yy");

export function TrendScatter({
  points,
  trend,
  domain,
  yFormat,
  yReversed,
  bands,
  refLines,
  onSelect,
  height = 260,
}: {
  points: TrendPoint[];
  trend: { x: number; y: number }[];
  domain: [number, number];
  yFormat: (v: number) => string;
  yReversed?: boolean;
  bands?: { y1: number; y2: number; color: string }[];
  refLines?: { y: number; label: string }[];
  onSelect?: (id: number) => void;
  height?: number;
}) {
  const real = points.filter((p) => !p.ghost);
  const ghosts = points.filter((p) => p.ghost);
  // Hover is driven by the dots themselves, not Recharts' Tooltip: its
  // index matching mixes up separate scatter series. Rings never react.
  const [hover, setHover] = useState<{ p: TrendPoint; cx: number; cy: number } | null>(null);
  const shape = (props: any) => {
    const p: TrendPoint = props.payload;
    if (p.ghost)
      return (
        <circle
          cx={props.cx}
          cy={props.cy}
          r={3.5}
          fill="none"
          stroke={INK.muted}
          strokeOpacity={0.5}
          style={{ pointerEvents: "none" }}
        />
      );
    const on = hover?.p.id === p.id;
    return (
      <g
        onMouseEnter={() => setHover({ p, cx: props.cx, cy: props.cy })}
        onMouseLeave={() => setHover((h) => (h?.p.id === p.id ? null : h))}
        onClick={() => onSelect?.(p.id)}
        style={{ cursor: onSelect ? "pointer" : undefined }}
      >
        {/* invisible hit target, bigger than the mark */}
        <circle cx={props.cx} cy={props.cy} r={10} fill="transparent" />
        <circle
          cx={props.cx}
          cy={props.cy}
          r={on ? 6.5 : 5}
          fill={p.hollow ? "hsl(240 6% 10%)" : p.color}
          stroke={p.hollow ? p.color : on ? "#f0efec" : "hsl(240 6% 10%)"}
          strokeWidth={2}
        />
      </g>
    );
  };
  return (
    <div className="relative" onMouseLeave={() => setHover(null)}>
    {hover && (
      <div
        className="pointer-events-none absolute z-10"
        style={{
          left: hover.cx,
          top: hover.cy,
          // Open away from the nearest edges so the box stays inside the card.
          transform: `translate(${hover.cx > 260 ? "calc(-100% - 14px)" : "14px"}, ${
            hover.cy > height / 2 ? "calc(-100% + 16px)" : "-16px"
          })`,
        }}
      >
        <TipBox title={hover.p.title} rows={hover.p.tip} />
      </div>
    )}
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={INK.grid} vertical={false} />
        <XAxis
          type="number"
          dataKey="x"
          domain={domain}
          scale="time"
          tickFormatter={dateTick}
          {...axis}
          minTickGap={24}
          allowDuplicatedCategory={false}
        />
        <YAxis
          type="number"
          dataKey="y"
          domain={["auto", "auto"]}
          reversed={yReversed}
          tickFormatter={yFormat}
          {...axis}
          axisLine={false}
          width={52}
        />
        {bands?.map((b) => (
          <ReferenceArea key={`${b.y1}-${b.y2}`} y1={b.y1} y2={b.y2} fill={b.color} fillOpacity={0.08} stroke="none" />
        ))}
        {refLines?.map((r) => (
          <ReferenceLine
            key={r.label}
            y={r.y}
            stroke={INK.text}
            strokeDasharray="4 4"
            label={{ value: r.label, fill: INK.text, fontSize: 11, position: "insideTopLeft" }}
          />
        ))}
        <Scatter data={ghosts} shape={shape} isAnimationActive={false} />
        <Line
          data={trend}
          dataKey="y"
          type="linear"
          stroke={INK.text}
          strokeWidth={2}
          dot={false}
          activeDot={false}
          isAnimationActive={false}
          tooltipType="none"
        />
        <Scatter
          data={real}
          shape={shape}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
    </div>
  );
}

// -------------------------------------------------------------- line series

export function SeriesChart({
  data,
  lines,
  band,
  yFormat = (v) => `${Math.round(v)}`,
  height = 220,
  zeroLine,
}: {
  data: Record<string, any>[];
  lines: { key: string; label: string; color: string; dashed?: boolean }[];
  band?: { key: string; label: string; color: string };
  yFormat?: (v: number) => string;
  height?: number;
  zeroLine?: boolean;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={INK.grid} vertical={false} />
        <XAxis
          dataKey="date"
          {...axis}
          tickFormatter={(d) => format(parseISO(d), "d MMM")}
          minTickGap={32}
        />
        <YAxis {...axis} axisLine={false} width={44} domain={["auto", "auto"]} tickFormatter={yFormat} />
        {zeroLine && <ReferenceLine y={0} stroke={INK.axis} />}
        <Tooltip
          cursor={{ stroke: INK.axis }}
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            const row = payload[0].payload;
            const rows: [string, string, string?][] = lines
              .filter((l) => row[l.key] != null)
              .map((l) => [l.label, yFormat(row[l.key]), l.color]);
            if (band && row[band.key]) rows.push([band.label, row[band.key].map(yFormat).join("–")]);
            return <TipBox title={format(parseISO(String(label)), "EEE d MMM yyyy")} rows={rows} />;
          }}
        />
        {band && (
          <Area
            dataKey={band.key}
            stroke="none"
            fill={band.color}
            fillOpacity={0.15}
            isAnimationActive={false}
            connectNulls
          />
        )}
        {lines.map((l) => (
          <Line
            key={l.key}
            dataKey={l.key}
            stroke={l.color}
            strokeWidth={2}
            strokeDasharray={l.dashed ? "4 4" : undefined}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// ------------------------------------------------------------ calendar heat

export function CalendarHeat({
  days,
  onPick,
}: {
  days: { date: string; load: number; label: string }[];
  onPick?: (date: string) => void;
}) {
  const max = Math.max(1, ...days.map((d) => d.load));
  // Sequential blue on dark: near-zero recedes into the surface, heavy days glow.
  const steps = ["#1e293b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#b7d3f6"];
  const color = (v: number) => (v <= 0 ? steps[0] : steps[Math.min(5, 1 + Math.floor((v / max) * 4.999))]);
  const first = days.length ? (parseISO(days[0].date).getDay() + 6) % 7 : 0;
  const cells: ({ date: string; load: number; label: string } | null)[] = [
    ...Array(first).fill(null),
    ...days,
  ];
  const weeks: (typeof cells)[] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return (
    <div className="overflow-x-auto">
      <div className="flex gap-[3px] w-max">
        <div className="flex flex-col gap-[3px] mr-1 text-[10px] text-muted-foreground">
          {["M", "", "W", "", "F", "", "S"].map((d, i) => (
            <span key={i} className="h-3 leading-3">{d}</span>
          ))}
        </div>
        {weeks.map((w, i) => (
          <div key={i} className="flex flex-col gap-[3px]">
            {w.map((d, j) =>
              d ? (
                <button
                  key={d.date}
                  type="button"
                  title={d.label}
                  aria-label={d.label}
                  onClick={() => onPick?.(d.date)}
                  className="h-3 w-3 rounded-[3px] hover:ring-1 hover:ring-foreground"
                  style={{ background: color(d.load) }}
                />
              ) : (
                <span key={j} className="h-3 w-3" />
              ),
            )}
          </div>
        ))}
      </div>
      <div className="flex items-center gap-1 mt-2 text-[10px] text-muted-foreground">
        less {steps.map((c) => <span key={c} className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} />)} more load
      </div>
    </div>
  );
}

// ----------------------------------------------------------- stream panels

export function StreamPanel({
  data,
  dataKey,
  label,
  color,
  yFormat = (v) => `${Math.round(v)}`,
  reversed,
  markers,
  syncId,
}: {
  data: Record<string, any>[];
  dataKey: string;
  label: string;
  color: string;
  yFormat?: (v: number) => string;
  reversed?: boolean;
  markers?: { x: number; label: string }[];
  syncId: string;
}) {
  return (
    <div>
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <ResponsiveContainer width="100%" height={110}>
        <LineChart data={data} syncId={syncId} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={INK.grid} vertical={false} />
          <XAxis dataKey="minute" type="number" domain={["dataMin", "dataMax"]} {...axis} tickFormatter={(v) => `${Math.round(v)}′`} />
          <YAxis {...axis} axisLine={false} width={44} domain={["auto", "auto"]} reversed={reversed} tickFormatter={yFormat} />
          {markers?.map((m) => (
            <ReferenceLine
              key={m.label}
              x={m.x}
              stroke={INK.text}
              strokeDasharray="4 4"
              label={{ value: m.label, fill: INK.text, fontSize: 10, position: "insideTopRight" }}
            />
          ))}
          <Tooltip
            cursor={{ stroke: INK.axis }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0].payload;
              return <TipBox title={`${row.minute.toFixed(1)} min`} rows={[[label, row[dataKey] == null ? "—" : yFormat(row[dataKey]), color]]} />;
            }}
          />
          <Line dataKey={dataKey} stroke={color} strokeWidth={1.5} dot={false} connectNulls isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
