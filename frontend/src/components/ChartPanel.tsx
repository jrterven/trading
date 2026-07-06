import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  createSeriesMarkers,
  type SeriesMarker,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useEffect, useRef, useState } from 'react';

import type { Bar, Marker } from '../types';

interface Props {
  bars: Bar[];
  markers: Marker[];
  symbol: string;
  livePrice?: number | null;
}

function toChartTime(timestamp: string): UTCTimestamp {
  return Math.floor(new Date(timestamp).getTime() / 1000) as UTCTimestamp;
}

const INITIAL_VISIBLE_BARS = 140;

export function ChartPanel({ bars, markers, symbol, livePrice }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
  const [scrollState, setScrollState] = useState({
    disabled: true,
    maxStart: 0,
    start: 0,
    windowSize: 0,
  });
  const sources = Array.from(new Set(bars.map((bar) => bar.source).filter(Boolean)));
  const dataSource = sources.length > 1 ? 'mixed' : sources[0] ?? 'sin datos';

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#f8faf7' },
        textColor: '#24302f',
        fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
      },
      grid: {
        vertLines: { color: '#e2e8e2' },
        horzLines: { color: '#e2e8e2' },
      },
      rightPriceScale: {
        borderColor: '#ccd8d4',
      },
      timeScale: {
        borderColor: '#ccd8d4',
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        mode: 1,
      },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#0f9f6e',
      downColor: '#d64545',
      borderVisible: false,
      wickUpColor: '#0f9f6e',
      wickDownColor: '#d64545',
    });
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: '#8aa39b',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });

    candleSeries.setData(
      bars.map((bar) => ({
        time: toChartTime(bar.timestamp),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    );
    volumeSeries.setData(
      bars.map((bar) => ({
        time: toChartTime(bar.timestamp),
        value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(15, 159, 110, 0.32)' : 'rgba(214, 69, 69, 0.32)',
      })),
    );

    const seriesMarkers: SeriesMarker<UTCTimestamp>[] = markers.map((marker) => ({
      time: toChartTime(marker.timestamp),
      position: marker.marker_type === 'sell' ? 'aboveBar' : 'belowBar',
      shape:
        marker.marker_type === 'sell'
          ? 'arrowDown'
          : marker.marker_type === 'buy'
            ? 'arrowUp'
            : 'circle',
      color: marker.color,
      text: marker.label,
    }));
    createSeriesMarkers(candleSeries, seriesMarkers);

    const updateScrollState = () => {
      const range = chart.timeScale().getVisibleLogicalRange();
      if (!range || bars.length <= 1) {
        setScrollState({ disabled: true, maxStart: 0, start: 0, windowSize: bars.length });
        return;
      }

      const rawWindowSize = Math.max(1, Math.round(range.to - range.from));
      const windowSize = Math.min(bars.length, rawWindowSize);
      const maxStart = Math.max(0, bars.length - windowSize);
      const start = Math.min(maxStart, Math.max(0, Math.round(range.from)));

      setScrollState({
        disabled: maxStart <= 0,
        maxStart,
        start,
        windowSize,
      });
    };

    const visibleBars = Math.min(bars.length, INITIAL_VISIBLE_BARS);
    if (bars.length > visibleBars) {
      chart.timeScale().setVisibleLogicalRange({
        from: bars.length - visibleBars,
        to: bars.length - 1,
      });
    } else {
      chart.timeScale().fitContent();
    }
    updateScrollState();
    chart.timeScale().subscribeVisibleLogicalRangeChange(updateScrollState);

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(updateScrollState);
      chartRef.current = null;
      chart.remove();
    };
  }, [bars, markers]);

  const handleScroll = (value: number) => {
    if (!chartRef.current || scrollState.disabled) return;
    chartRef.current.timeScale().setVisibleLogicalRange({
      from: value,
      to: value + scrollState.windowSize,
    });
  };

  return (
    <section className="chart-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Mercado</p>
          <h1>{symbol}</h1>
        </div>
        <div className="price-readout">
          <span>Ultimo</span>
          <strong>{livePrice ? `$${livePrice.toFixed(2)}` : '--'}</strong>
          <small className={dataSource === 'sample' || dataSource === 'mixed' ? 'source-badge sample' : 'source-badge'}>
            {dataSource === 'sample' ? 'SAMPLE DATA' : dataSource === 'mixed' ? 'MIXED DATA' : dataSource.toUpperCase()}
          </small>
        </div>
      </div>
      <div className="chart-viewport">
        <div ref={containerRef} className="chart-canvas" />
      </div>
      <div className="chart-scrollbar">
        <input
          aria-label="Desplazar grafica horizontalmente"
          type="range"
          min="0"
          max={scrollState.maxStart}
          step="1"
          value={scrollState.start}
          disabled={scrollState.disabled}
          onChange={(event) => handleScroll(Number(event.target.value))}
        />
      </div>
    </section>
  );
}
