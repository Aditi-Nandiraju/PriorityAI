// Runtime smoke test without a browser: server-render every page inside a
// MemoryRouter + AuthProvider and assert nothing throws during render.
// Catches bad hook usage, undefined imports, context misuse, JSX typos.
import React from "react";
import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";

import { AuthProvider } from "../src/context/AuthContext.jsx";
import { BoardDataProvider } from "../src/context/BoardDataContext.jsx";
import Login from "../src/pages/Login.jsx";
import Ingest from "../src/pages/Ingest.jsx";
import Board from "../src/pages/Board.jsx";
import IncidentDetail from "../src/pages/IncidentDetail.jsx";
import Resources from "../src/pages/Resources.jsx";
import ActivityLog from "../src/pages/ActivityLog.jsx";
import Settings from "../src/pages/Settings.jsx";
import Layout from "../src/components/Layout.jsx";
import { NAV } from "../src/nav.js";

function tryRender(name, el, route = "/") {
  try {
    const html = renderToString(
      React.createElement(
        MemoryRouter,
        { initialEntries: [route] },
        React.createElement(AuthProvider, null, el)
      )
    );
    console.log(`  ok   ${name}  (${html.length} bytes)`);
    return true;
  } catch (e) {
    console.log(`  FAIL ${name}: ${e.message}`);
    return false;
  }
}

let ok = true;
console.log("SSR render smoke:");
ok &= tryRender("Login", React.createElement(Login), "/login");
// Layout and Board read from BoardDataContext (incidents/resources/demo mode
// now live above the routed pages so they survive navigation - see
// context/BoardDataContext.jsx), so both need the provider in the tree.
ok &= tryRender(
  "Layout shell",
  React.createElement(BoardDataProvider, null, React.createElement(Layout))
);
ok &= tryRender("Ingest", React.createElement(Ingest));
ok &= tryRender(
  "Board",
  React.createElement(BoardDataProvider, null, React.createElement(Board))
);
ok &= tryRender("IncidentDetail", React.createElement(IncidentDetail), "/incident/abc");
ok &= tryRender("Resources", React.createElement(Resources));
ok &= tryRender("ActivityLog", React.createElement(ActivityLog));
ok &= tryRender(
  "Settings",
  React.createElement(BoardDataProvider, null, React.createElement(Settings))
);

console.log("\nRole-based tab visibility (nav.js):");
for (const role of ["admin", "operator"]) {
  const visible = NAV.filter((t) => t.roles.includes(role)).map((t) => t.label);
  console.log(`  ${role.padEnd(9)} -> ${visible.join(", ")}`);
}
const operatorSeesActivity = NAV.find((t) => t.to === "/activity").roles.includes("operator");
const operatorSeesSettings = NAV.find((t) => t.to === "/settings").roles.includes("operator");
console.log(`  operator sees Activity Log? ${operatorSeesActivity} (expected false)`);
console.log(`  operator sees Settings?     ${operatorSeesSettings} (expected false)`);
ok &= !operatorSeesActivity && !operatorSeesSettings;

process.exit(ok ? 0 : 1);
