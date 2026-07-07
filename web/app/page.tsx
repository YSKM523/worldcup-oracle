"use client";

import { useEffect, useState } from "react";
import { Dashboard } from "@/components/Dashboard";
import type { Data } from "@/lib/types";
import { useLive } from "@/lib/useLive";
import { usePolymarket } from "@/lib/usePolymarket";
import { useWeather } from "@/lib/useWeather";

export default function Home() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState(false);
  const live = useLive();
  const poly = usePolymarket(data?.matches ?? []);
  const weather = useWeather();

  useEffect(() => {
    fetch(`/data.json?v=${Math.floor(Date.now() / 3600e3)}`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => setError(true));
  }, []);

  return <Dashboard data={data} live={live} poly={poly} weather={weather} error={error} />;
}
