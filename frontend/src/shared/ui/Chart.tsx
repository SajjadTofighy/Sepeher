import { BarChart, LineChart } from "echarts/charts";
import {
  AriaComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import { init, use, type EChartsCoreOption } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
use([
  LineChart,
  BarChart,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent,
  AriaComponent,
  SVGRenderer,
]);
export default function Chart({
  option,
  label,
}: {
  option: EChartsCoreOption;
  label: string;
}) {
  const element = useRef<HTMLDivElement>(null);
  const instance = useRef<ReturnType<typeof init> | null>(null);
  useEffect(() => {
    if (!element.current) return;
    const chart = init(element.current, undefined, { renderer: "svg" });
    instance.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(element.current);
    return () => {
      ro.disconnect();
      chart.dispose();
      instance.current = null;
    };
  }, []);
  useEffect(() => {
    instance.current?.setOption(option);
  }, [option]);
  return (
    <div
      className="chart-container"
      ref={element}
      role="img"
      aria-label={label}
    />
  );
}
