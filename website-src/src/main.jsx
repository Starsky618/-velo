import React from "react";
import { hydrateRoot } from "react-dom/client";
import { App } from "./App.jsx";
import "./styles.css";
import "./refinement.css";

hydrateRoot(document.getElementById("root"),
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

import "./typography.css";
