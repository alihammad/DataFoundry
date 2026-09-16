// Roles + assignments UI (feature 007, T043).
// Create roles scoped to platform/dataset/column, assign users; users see
// exactly the scoped capabilities (FR-013, FR-014, US6-AC1).

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "../../app/auth";

export function Roles() {
  const { api } = useAuth();
  const [name, setName] = useState("");
  const [scope, setScope] = useState("dataset");
  const [assignUser, setAssignUser] = useState("");
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => api.listRoles() });
  const createRole = useMutation({
    mutationFn: () => api.createRole({ name, scope, permissions: ["dataset.read"] }),
  });
  const assign = useMutation({
    mutationFn: (roleId: string) => api.assignRole(roleId, { user_identity: assignUser }),
  });

  return (
    <div className="panel">
      <h2>Roles</h2>
      <div>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Role name" />
        <select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="platform">Platform</option>
          <option value="dataset">Dataset</option>
          <option value="column">Column</option>
        </select>
        <button className="primary" onClick={() => createRole.mutate()}>
          Create role
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Scope</th>
            <th>Assign user</th>
          </tr>
        </thead>
        <tbody>
          {(roles.data?.items ?? []).map((r) => (
            <tr key={r.role_id}>
              <td>{r.name}</td>
              <td>{r.scope}</td>
              <td>
                <input value={assignUser} onChange={(e) => setAssignUser(e.target.value)} placeholder="user@example.com" />
                <button onClick={() => assign.mutate(r.role_id)}>Assign</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {(createRole.error || assign.error) && <p className="error">{(createRole.error || assign.error)?.message}</p>}
    </div>
  );
}