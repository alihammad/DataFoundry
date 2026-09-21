// Notification channels UI (feature 007, T045).
// Per-platform channel configuration (FR-014); config never displayed
// (FR-022, SC-006).

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "../../app/auth";

export function Notifications() {
  const { api } = useAuth();
  const [platformId, setPlatformId] = useState("");
  const [name, setName] = useState("");
  const [channelType, setChannelType] = useState("email");
  const channels = useQuery({
    queryKey: ["notifications", platformId],
    queryFn: () => api.client.get(`/ui/notifications${platformId ? `?platform_id=${platformId}` : ""}`),
  });
  const create = useMutation({
    mutationFn: () =>
      api.client.post("/ui/notifications", {
        platform_id: platformId,
        channel_type: channelType,
        name,
        config: { recipients: [] },
        event_types: ["gate.failed"],
      }),
  });

  return (
    <div className="panel">
      <h2>Notification Channels</h2>
      <div>
        <input value={platformId} onChange={(e) => setPlatformId(e.target.value)} placeholder="Platform ID" />
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Channel name" />
        <select value={channelType} onChange={(e) => setChannelType(e.target.value)}>
          <option value="email">Email</option>
          <option value="webhook">Webhook</option>
          <option value="slack">Slack</option>
        </select>
        <button className="primary" onClick={() => create.mutate()}>
          Add channel
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Events</th>
            <th>Enabled</th>
          </tr>
        </thead>
        <tbody>
          {((channels.data as { items?: Array<{ channel_id: string; name: string; channel_type: string; event_types: string[]; enabled: boolean }> } | undefined)?.items ?? []).map((c) => (
            <tr key={c.channel_id}>
              <td>{c.name}</td>
              <td>{c.channel_type}</td>
              <td>{c.event_types.join(", ")}</td>
              <td>{c.enabled ? "Yes" : "No"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {create.error && <p className="error">{create.error.message}</p>}
    </div>
  );
}