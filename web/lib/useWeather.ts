"use client";

import { useEffect, useState } from "react";
import type { WeatherData } from "@/lib/types";

/** 加载 weather.json（天气研究 + 每场天气 + 实验性修正）。失败时静默返回 null。 */
export function useWeather(): WeatherData | null {
  const [wx, setWx] = useState<WeatherData | null>(null);
  useEffect(() => {
    fetch(`/weather.json?v=${Math.floor(Date.now() / 3600e3)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setWx)
      .catch(() => setWx(null));
  }, []);
  return wx;
}
