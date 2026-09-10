// Role-based tab visibility.
//
// NOTE: CMS_SPEC.md section 5 was referenced for this but isn't in the repo, so
// this matrix is inferred and matches the backend's own guards:
//   - GET /audit is admin-only  -> Activity Log is admin-only
//   - PUT/POST /resources is admin-only -> Resources is view-all / edit-admin
//   - everything else needs any authenticated user
// Roles in the system: "admin", "operator" ("viewer" is also role "operator").
export const NAV = [
  { to: "/ingest", label: "Ingest / Manual Entry", roles: ["operator", "admin"] },
  { to: "/board", label: "Incident Board", roles: ["operator", "admin"] },
  { to: "/resources", label: "Resource Inventory", roles: ["operator", "admin"] },
  { to: "/activity", label: "Activity Log", roles: ["admin"] },
];
