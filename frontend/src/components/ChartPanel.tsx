import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  createSeriesMarkers,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useEffect, useRef, useState } from 'react';

import type { Bar, Marker, NewsChartMarker } from '../types';

interface Props {
  bars: Bar[];
  markers: Marker[];
  newsMarkers: NewsChartMarker[];
  selectedNewsId?: string | null;
  focusNewsRequest?: { articleId: string; nonce: number } | null;
  symbol: string;
  timeframe: string;
  livePrice?: number | null;
  onNewsMarkerClick?: (articleId: string) => void;
}

function toChartTime(timestamp: string, timeframe: string): Time {
  if (timeframe === '1Day') {
    return dateKey(timestamp);
  }
  return Math.floor(new Date(timestamp).getTime() / 1000) as UTCTimestamp;
}

function chartTimeKey(time: Time | undefined) {
  if (time === undefined) return '';
  if (typeof time === 'string' || typeof time === 'number') return String(time);
  const month = String(time.month).padStart(2, '0');
  const day = String(time.day).padStart(2, '0');
  return `${time.year}-${month}-${day}`;
}

const INITIAL_VISIBLE_BARS = 140;

function newsMarkerColor(sentiment: NewsChartMarker['sentiment']) {
  if (sentiment === 'positive') return '#0f766e';
  if (sentiment === 'negative') return '#d64545';
  return '#b88900';
}

function dateKey(timestamp: string) {
  return new Date(timestamp).toISOString().slice(0, 10);
}

function dayStartMs(timestamp: string) {
  return Date.parse(`${dateKey(timestamp)}T00:00:00.000Z`);
}

function medianBarIntervalMs(bars: Bar[]) {
  if (bars.length < 2) return 24 * 60 * 60 * 1000;
  const intervals = bars
    .slice(1)
    .map((bar, index) => new Date(bar.timestamp).getTime() - new Date(bars[index].timestamp).getTime())
    .filter((value) => value > 0)
    .sort((a, b) => a - b);
  return intervals[Math.floor(intervals.length / 2)] || 24 * 60 * 60 * 1000;
}

function resolveNewsBarTimestamp(bars: Bar[], timestamp: string, timeframe: string) {
  if (!bars.length) return null;
  if (timeframe === '1Day') {
    const targetDay = dayStartMs(timestamp);
    const firstDay = dayStartMs(bars[0].timestamp);
    const lastDay = dayStartMs(bars[bars.length - 1].timestamp);
    if (targetDay < firstDay || targetDay > lastDay) return null;

    const sameDay = bars.find((bar) => dayStartMs(bar.timestamp) === targetDay);
    if (sameDay) return sameDay.timestamp;

    const nextTradingBar = bars.find((bar) => dayStartMs(bar.timestamp) > targetDay);
    if (!nextTradingBar) return null;
    const dayGap = dayStartMs(nextTradingBar.timestamp) - targetDay;
    return dayGap <= 4 * 24 * 60 * 60 * 1000 ? nextTradingBar.timestamp : null;
  }

  const target = new Date(timestamp).getTime();
  const interval = medianBarIntervalMs(bars);
  const tolerance = Math.max(interval * 1.5, 15 * 60 * 1000);
  let nearest: string | null = null;
  let nearestDistance = Number.POSITIVE_INFINITY;
  for (const bar of bars) {
    const distance = Math.abs(new Date(bar.timestamp).getTime() - target);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearest = bar.timestamp;
    }
  }
  return nearest && nearestDistance <= tolerance ? nearest : null;
}

export function ChartPanel({
  bars,
  markers,
  newsMarkers,
  selectedNewsId,
  focusNewsRequest,
  symbol,
  timeframe,
  livePrice,
  onNewsMarkerClick,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
  const markerApiRef = useRef<{ setMarkers: (markers: SeriesMarker<Time>[]) => void } | null>(null);
  const onNewsMarkerClickRef = useRef(onNewsMarkerClick);
  const [scrollState, setScrollState] = useState({
    disabled: true,
    maxStart: 0,
    start: 0,
    windowSize: 0,
  });
  const [hoveredBar, setHoveredBar] = useState<Bar | null>(null);
  const sources = Array.from(new Set(bars.map((bar) => bar.source).filter(Boolean)));
  const dataSource = sources.length > 1 ? 'mixed' : sources[0] ?? 'no data';

  useEffect(() => {
    onNewsMarkerClickRef.current = onNewsMarkerClick;
  }, [onNewsMarkerClick]);

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
        timeVisible: timeframe !== '1Day',
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
        time: toChartTime(bar.timestamp, timeframe),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    );
    volumeSeries.setData(
      bars.map((bar) => ({
        time: toChartTime(bar.timestamp, timeframe),
        value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(15, 159, 110, 0.32)' : 'rgba(214, 69, 69, 0.32)',
      })),
    );

    markerApiRef.current = createSeriesMarkers(candleSeries, []);
    const barsByTime = new Map(bars.map((bar) => [String(toChartTime(bar.timestamp, timeframe)), bar]));

    const handleChartClick = (param: MouseEventParams) => {
      const objectId = param.hoveredInfo?.objectId ?? param.hoveredObjectId;
      if (typeof objectId !== 'string' || !objectId.startsWith('news:')) return;
      onNewsMarkerClickRef.current?.(objectId.slice('news:'.length));
    };
    const handleCrosshairMove = (param: MouseEventParams) => {
      setHoveredBar(barsByTime.get(chartTimeKey(param.time)) ?? null);
    };

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
    chart.subscribeClick(handleChartClick);
    chart.subscribeCrosshairMove(handleCrosshairMove);

    return () => {
      chart.unsubscribeClick(handleChartClick);
      chart.unsubscribeCrosshairMove(handleCrosshairMove);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(updateScrollState);
      markerApiRef.current = null;
      chartRef.current = null;
      chart.remove();
    };
  }, [bars, timeframe]);

  useEffect(() => {
    const resolvedNewsMarkers = newsMarkers
      .map((marker) => ({
        marker,
        barTimestamp: resolveNewsBarTimestamp(bars, marker.timestamp, timeframe),
      }))
      .filter((item): item is { marker: NewsChartMarker; barTimestamp: string } => item.barTimestamp !== null);
    const seriesMarkers: SeriesMarker<Time>[] = [
      ...markers.map((marker) => ({
        time: toChartTime(marker.timestamp, timeframe),
        position: marker.marker_type === 'sell' ? 'aboveBar' : 'belowBar',
        shape:
          marker.marker_type === 'sell'
            ? 'arrowDown'
            : marker.marker_type === 'buy'
              ? 'arrowUp'
              : 'circle',
        color: marker.color,
        text: marker.label,
      }) satisfies SeriesMarker<Time>),
      ...resolvedNewsMarkers.map(({ marker, barTimestamp }) => ({
        id: `news:${marker.article_id}`,
        time: toChartTime(barTimestamp, timeframe),
        position: marker.sentiment === 'negative' ? 'belowBar' : 'aboveBar',
        shape: 'square',
        color: marker.article_id === selectedNewsId ? '#153f3a' : newsMarkerColor(marker.sentiment),
        text: marker.article_id === selectedNewsId ? 'N*' : 'N',
        size: marker.article_id === selectedNewsId ? 1.45 : 1.15,
      }) satisfies SeriesMarker<Time>),
    ];
    markerApiRef.current?.setMarkers(seriesMarkers);
  }, [bars, markers, newsMarkers, selectedNewsId, timeframe]);

  useEffect(() => {
    if (!chartRef.current || !focusNewsRequest || bars.length === 0) return;
    const marker = newsMarkers.find((item) => item.article_id === focusNewsRequest.articleId);
    if (!marker) return;
    const resolvedTimestamp = resolveNewsBarTimestamp(bars, marker.timestamp, timeframe);
    if (!resolvedTimestamp) return;
    const markerTime = new Date(resolvedTimestamp).getTime();
    let nearestIndex = 0;
    let nearestDistance = Number.POSITIVE_INFINITY;
    bars.forEach((bar, index) => {
      const distance = Math.abs(new Date(bar.timestamp).getTime() - markerTime);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = index;
      }
    });
    const range = chartRef.current.timeScale().getVisibleLogicalRange();
    const currentWindowSize = range ? Math.max(1, Math.round(range.to - range.from)) : 80;
    const windowSize = Math.min(Math.max(currentWindowSize, 1), bars.length);
    const maxFrom = Math.max(0, bars.length - windowSize);
    const from = Math.min(maxFrom, Math.max(0, nearestIndex - Math.floor(windowSize / 2)));
    const to = from + windowSize;
    chartRef.current.timeScale().setVisibleLogicalRange({ from, to });
  }, [bars, focusNewsRequest, newsMarkers, timeframe]);

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
          <p className="eyebrow">Market</p>
          <h1>{symbol}</h1>
        </div>
        {hoveredBar && (
          <div className="ohlc-readout">
            <span>{timeframe === '1Day' ? dateKey(hoveredBar.timestamp) : new Date(hoveredBar.timestamp).toLocaleString('es-MX')}</span>
            <strong>O {hoveredBar.open.toFixed(2)}</strong>
            <strong>H {hoveredBar.high.toFixed(2)}</strong>
            <strong>L {hoveredBar.low.toFixed(2)}</strong>
            <strong>C {hoveredBar.close.toFixed(2)}</strong>
          </div>
        )}
        <div className="price-readout">
          <span>Last</span>
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
          aria-label="Scroll chart horizontally"
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
