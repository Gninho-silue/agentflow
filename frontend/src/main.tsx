import React from "react";
import ReactDOM from "react-dom/client";
import { Analytics } from "@vercel/analytics/react";
import { SpeedInsights } from "@vercel/speed-insights/react";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
    {/* Vercel Web Analytics and Speed Insights: no-ops outside Vercel. */}
    <Analytics />
    <SpeedInsights />
  </React.StrictMode>,
);
