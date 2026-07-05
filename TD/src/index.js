import React from "react";
import ReactDOM from "react-dom/client";
import "./styles.css";
import TrashDataDashboard from "./components/TrashDataDashboard";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <TrashDataDashboard />
  </React.StrictMode>
);
