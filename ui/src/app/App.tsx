// App shell + routing (feature 007, T011/T018).
// Persistent sidebar (platform context switcher, nav sections), top bar, and
// content area. Selected-platform state scopes all views (FR-020).

import { useMemo, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "./auth";
import { Dashboard } from "../features/dashboard/Dashboard";
import { Pipelines } from "../features/pipelines/Pipelines";
import { Catalog } from "../features/catalog/Catalog";
import { Quality } from "../features/quality/Quality";
import { Admin } from "../features/admin/Admin";
import { Config } from "../features/config/Config";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/config", label: "Configure" },
  { to: "/pipelines", label: "Pipelines" },
  { to: "/catalog", label: "Catalog" },
  { to: "/quality", label: "Quality" },
  { to: "/admin", label: "Admin" },
];

function Shell() {
  const { api, auth } = useAuth();
  const [platformId, setPlatformId] = useState<string>("");

  const platforms = useQuery({
    queryKey: ["platforms"],
    queryFn: () => api.listPlatforms(),
  });

  const platformOptions = useMemo(() => platforms.data?.items ?? [], [platforms.data]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">DataFoundry</div>
        <div className="platform-switcher">
          <label htmlFor="platform">Platform</label>
          <select
            id="platform"
            value={platformId}
            onChange={(e) => setPlatformId(e.target.value)}
          >
            <option value="">All platforms</option>
            {platformOptions.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="topbar-identity">{auth.token ? auth.token.slice(0, 12) : "dev"}</span>
        </header>
        <main className="content">
          <Routes>
            <Route path="/" element={<Dashboard platformId={platformId} />} />
            <Route path="/config" element={<Config platformId={platformId} />} />
            <Route path="/pipelines" element={<Pipelines platformId={platformId} />} />
            <Route path="/catalog" element={<Catalog />} />
            <Route path="/quality" element={<Quality />} />
            <Route path="/admin" element={<Admin />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  );
}