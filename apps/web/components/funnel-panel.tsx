"use client";

import type { Funnel } from "@/lib/api";
import {
  Bar,
  BarChart,
  LabelList,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

export function FunnelPanel({ funnel }: { funnel: Funnel }) {
  const data = [
    { name: "Indexed", value: funnel.indexed },
    { name: "Semantic", value: funnel.semantic_matches },
    { name: "Filtered", value: funnel.passed_base_filters },
    { name: "Researched", value: funnel.researched },
    { name: "Qualified", value: funnel.fully_qualified },
  ];
  return (
    <div className="h-40 w-full">
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 32 }}>
          <XAxis type="number" hide domain={[0, funnel.indexed]} />
          <YAxis
            type="category"
            dataKey="name"
            width={78}
            tickLine={false}
            axisLine={false}
            tick={{ fontSize: 12 }}
          />
          <Bar dataKey="value" fill="var(--chart-2)" radius={3} barSize={16} isAnimationActive={false}>
            <LabelList dataKey="value" position="right" style={{ fontSize: 12 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
