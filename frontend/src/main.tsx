import "@fontsource/vazirmatn/400.css";
import "@fontsource/vazirmatn/500.css";
import "@fontsource/vazirmatn/600.css";
import "@fontsource/vazirmatn/700.css";
import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import AuthGate from "./shared/auth/AuthGate";
import { SessionProvider } from "./shared/auth/session";
import ErrorBoundary from "./app/ErrorBoundary";
import { queryClient } from "./app/queryClient";
import "./soc.css";
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <AuthGate>
            <App />
          </AuthGate>
        </SessionProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
